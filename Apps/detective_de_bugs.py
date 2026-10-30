import asyncio
import json
import re

import flet as ft
import httpx
from flet_audio_recorder import AudioEncoder, AudioRecorder, AudioRecorderConfiguration

from ia import ia
from multimedia import ia_media, pcm_a_wav


class ErrorDiagnosticoInvalido(ValueError):
    """Indica que la IA no devolvió los tres pasos del diagnóstico."""


PATRONES_DATOS_SENSIBLES = (
    (
        "posible número de DUI",
        re.compile(r"(?<!\d)(?:\d{8}-\d|\d{9})(?!\d)"),
    ),
    (
        "posible número de teléfono",
        re.compile(
            r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})"
            r"[\s.-]\d{3,4}[\s.-]\d{4}(?!\w)|(?<!\d)\d{10,15}(?!\d)"
            r"|\b\d{4}[-.\s]\d{4}\b"
            r"|\b(?:tel[eé]fono|telefono|celular|phone|llamar)\b"
            r"[^\d\n]{0,16}(?:\+?503[\s.-]?)?\d{8}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "posible contraseña",
        re.compile(
            r"\b(?:contraseña|contrasena|password|passwd|pwd)\b"
            r"\s*(?:[:=]\s*|\b(?:is|es)\b\s+)\S+",
            re.IGNORECASE,
        ),
    ),
)


def vista(page: ft.Page | None = None) -> ft.Control:
    cian = ft.Colors.CYAN
    entrada = ft.TextField(
        label="Error de Python",
        hint_text="Pega aquí el mensaje de error y, si puedes, el fragmento relacionado...",
        multiline=True,
        min_lines=5,
        max_lines=10,
        expand=True,
        border_color=cian,
        focused_border_color=cian,
        cursor_color=cian,
    )
    nivel_programador = ft.Dropdown(
        label="Nivel del programador",
        value="Principiante",
        options=[
            ft.DropdownOption(key="Principiante", text="Principiante"),
            ft.DropdownOption(key="Intermedio", text="Intermedio"),
            ft.DropdownOption(key="Avanzado", text="Avanzado"),
        ],
        border_color=cian,
        focused_border_color=cian,
    )
    estado = ft.Text()
    resultados = ft.Column(spacing=10)
    historial_visual = ft.Column(spacing=6)
    resumen_votos = ft.Text("👍 Útiles: 0   ·   👎 No me sirvió: 0", size=14)
    ultima_solucion: str | None = None
    boton = ft.Button(
        "Investigar error",
        color=ft.Colors.BLACK,
        bgcolor=cian,
    )
    boton_copiar = ft.Button(
        "Copiar solución",
        icon=ft.Icons.COPY,
        disabled=True,
    )
    boton_escuchar = ft.Button(
        "Escuchar solución",
        icon=ft.Icons.VOLUME_UP,
        disabled=True,
    )
    boton_limpiar = ft.Button(
        "Limpiar pantalla",
        icon=ft.Icons.CLEAR_ALL,
    )
    boton_audio = ft.Button(
        "Grabar descripción",
        icon=ft.Icons.MIC,
        icon_color=ft.Colors.BLACK,
        color=ft.Colors.BLACK,
        bgcolor=cian,
    )
    boton_imagen = ft.Button(
        "Subir foto del error",
        icon=ft.Icons.IMAGE,
        icon_color=ft.Colors.BLACK,
        color=ft.Colors.BLACK,
        bgcolor=cian,
    )
    boton_multimodal = ft.Button(
        "Diagnóstico con foto + voz",
        icon=ft.Icons.MERGE_TYPE,
        icon_color=ft.Colors.BLACK,
        color=ft.Colors.BLACK,
        bgcolor=cian,
    )
    boton_archivo = ft.Button(
        "Subir archivo .py o .txt",
        icon=ft.Icons.UPLOAD_FILE,
        icon_color=ft.Colors.BLACK,
        color=ft.Colors.BLACK,
        bgcolor=cian,
    )
    selector_imagen = ft.FilePicker()
    archivo_info = ft.Text()
    progreso = ft.ProgressRing(visible=False, color=cian, stroke_width=3)
    fragmentos_audio: list[bytes] = []
    grabando = False
    transcribiendo = False
    temporizador = None
    modo_multimodal = False
    temporizador_multimodal = None
    imagen_multimodal: tuple[bytes, str, str] | None = None
    pagina = None

    def recibir_audio(e):
        fragmentos_audio.append(e.chunk)

    grabadora = AudioRecorder(
        configuration=AudioRecorderConfiguration(
            encoder=AudioEncoder.PCM16BITS,
            channels=1,
            sample_rate=16000,
        ),
        on_stream=recibir_audio,
    )

    def transcribir_audio(audio_pcm: bytes) -> str:
        audio_wav = pcm_a_wav(audio_pcm, tasa=16000, canales=1)
        texto = ia_media(
            "Transcribe fielmente el audio en español. Devuelve únicamente "
            "el texto hablado, sin etiquetas, explicaciones ni comillas.",
            audio_wav,
            "audio/wav",
        )
        if not isinstance(texto, str) or not texto.strip():
            raise ValueError("No se reconoció texto en la grabación.")
        return texto.strip()

    def validar_imagen(archivo) -> tuple[bytes, str]:
        imagen = archivo.bytes
        if not isinstance(imagen, bytes) or not imagen:
            raise ValueError("El archivo seleccionado está vacío o no se pudo leer.")

        # Comprueba la extensión y la firma para evitar enviar archivos no compatibles.
        formatos = {
            ".jpg": ("image/jpeg", lambda datos: datos.startswith(b"\xff\xd8\xff")),
            ".jpeg": ("image/jpeg", lambda datos: datos.startswith(b"\xff\xd8\xff")),
            ".png": ("image/png", lambda datos: datos.startswith(b"\x89PNG\r\n\x1a\n")),
            ".webp": (
                "image/webp",
                lambda datos: (
                    len(datos) >= 12
                    and datos.startswith(b"RIFF")
                    and datos[8:12] == b"WEBP"
                ),
            ),
        }
        extension = "." + archivo.name.rsplit(".", 1)[-1].lower()
        formato = formatos.get(extension)
        if formato is None or not formato[1](imagen):
            raise ValueError(
                "El archivo no parece una imagen JPEG, PNG o WEBP válida."
            )
        return imagen, formato[0]

    pasos = (
        ("que_paso", "Qué pasó"),
        ("por_que_ocurrio", "Por qué ocurrió"),
        ("como_solucionarlo", "Cómo solucionarlo"),
    )

    def detectar_datos_sensibles(texto: str) -> list[str]:
        # Solo devuelve categorías; nunca copia los valores sensibles al aviso.
        return [
            categoria
            for categoria, patron in PATRONES_DATOS_SENSIBLES
            if patron.search(texto)
        ]

    def bloquear_datos_sensibles(
        pagina_actual: ft.Page, texto: str
    ) -> bool:
        categorias = detectar_datos_sensibles(texto)
        if not categorias:
            return False

        tipos = ", ".join(categorias)
        mensaje = (
            f"Por seguridad, no enviaré este texto porque parece incluir {tipos}. "
            "Elimina esos datos y vuelve a intentarlo."
        )
        estado.value = mensaje
        estado.color = ft.Colors.ORANGE
        pagina_actual.show_dialog(
            ft.SnackBar(
                content=mensaje,
                duration=8000,
                bgcolor=ft.Colors.ORANGE,
            )
        )
        pagina_actual.update()
        return True

    def mensaje_error_amigable(error: Exception) -> str:
        if isinstance(error, (json.JSONDecodeError, ErrorDiagnosticoInvalido)):
            return (
                "La IA devolvió una respuesta incompleta. "
                "Inténtalo de nuevo en unos segundos."
            )
        if isinstance(error, httpx.TimeoutException):
            return (
                "La conexión tardó demasiado. Comprueba tu internet "
                "e inténtalo de nuevo."
            )
        if isinstance(error, httpx.RequestError):
            return (
                "No pude conectar con la IA. Revisa tu conexión "
                "e inténtalo de nuevo."
            )
        if isinstance(error, (KeyError, IndexError, TypeError)):
            return (
                "La IA no envió una respuesta completa. "
                "Inténtalo de nuevo en unos segundos."
            )
        if isinstance(error, RuntimeError):
            detalle = str(error).lower()
            if any(
                referencia in detalle
                for referencia in (
                    "429",
                    "cuota",
                    "quota",
                    "rate limit",
                    "resource exhausted",
                )
            ):
                return "La IA está descansando un momento. Espera 10 segundos e inténtalo de nuevo."
            if "15 mb" in detalle or "muy grande" in detalle:
                return "El archivo es demasiado grande. Prueba con uno más pequeño."
            if any(
                referencia in detalle
                for referencia in ("gemini_api_key", "400/403", "401", "403")
            ):
                return (
                    "No se pudo acceder a la IA. Revisa la configuración "
                    "del servicio e inténtalo más tarde."
                )
            return "La IA no pudo completar la solicitud. Inténtalo de nuevo más tarde."
        if isinstance(error, ValueError):
            detalle = str(error).lower()
            if "grabación" in detalle or "audio" in detalle:
                return (
                    "No pude reconocer el audio. Intenta grabarlo de nuevo "
                    "con más claridad."
                )
            return "No pude procesar la respuesta. Inténtalo de nuevo."
        return "Ocurrió un problema al procesar tu solicitud. Inténtalo de nuevo."

    def notificar_error(pagina_actual: ft.Page, error: Exception) -> None:
        mensaje = mensaje_error_amigable(error)
        estado.value = mensaje
        estado.color = ft.Colors.RED
        pagina_actual.show_dialog(
            ft.SnackBar(
                content=mensaje,
                duration=6000,
                bgcolor=ft.Colors.RED,
            )
        )

    async def copiar_solucion(e):
        if not ultima_solucion:
            return

        try:
            portapapeles = ft.Clipboard()
            if portapapeles not in e.page.services:
                e.page.services.append(portapapeles)
            await portapapeles.set(ultima_solucion)
            e.page.show_dialog(
                ft.SnackBar(
                    content="¡Copiado al portapapeles!",
                    duration=2200,
                    bgcolor=cian,
                )
            )
        except Exception:
            # Avisa si el sistema no permite acceder al portapapeles.
            estado.value = "No pude copiar la solución al portapapeles."
            estado.color = ft.Colors.RED
            e.page.update()

    def escuchar_solucion(e):
        if not ultima_solucion:
            return

        # Flet 1.0 no ofrece una API pública de síntesis de voz para el navegador.
        e.page.show_dialog(
            ft.SnackBar(
                content=(
                    "La lectura en voz alta no está disponible aquí. "
                    "Puedes usar la función de lectura de tu navegador o dispositivo."
                ),
                duration=5000,
            )
        )

    def limpiar_pantalla(e):
        nonlocal ultima_solucion
        entrada.value = ""
        archivo_info.value = ""
        estado.value = ""
        resultados.controls.clear()
        ultima_solucion = None
        boton_copiar.disabled = True
        boton_escuchar.disabled = True
        # El historial queda disponible; solo se limpia el diagnóstico actual.
        e.page.update()

    def adaptar_instruccion(instruccion: str) -> str:
        nivel = nivel_programador.value or "Principiante"
        tonos = {
            "Principiante": (
                "Usa un tono didáctico y paciente, define los términos técnicos "
                "y explica los pasos como para alguien que está aprendiendo."
            ),
            "Intermedio": (
                "Usa un tono claro y práctico, explica la causa y ofrece una "
                "solución concreta sin extenderte en conceptos básicos."
            ),
            "Avanzado": (
                "Usa un tono técnico y conciso, incluye detalles relevantes de "
                "implementación y evita explicaciones introductorias."
            ),
        }
        tono = tonos.get(nivel, tonos["Principiante"])
        return f"{instruccion}\n\nNivel del programador: {nivel}. {tono}"

    def obtener_historial(pagina_actual: ft.Page) -> list[str]:
        datos_sesion = pagina_actual.data
        if datos_sesion is None:
            datos_sesion = {}
            pagina_actual.data = datos_sesion
        if not isinstance(datos_sesion, dict):
            raise TypeError("Los datos de sesión de la página deben ser un diccionario.")

        historial = datos_sesion.get("detective_de_bugs_historial")
        if not isinstance(historial, list) or any(
            not isinstance(error, str) for error in historial
        ):
            historial = []
            datos_sesion["detective_de_bugs_historial"] = historial
        return historial

    def actualizar_historial(historial: list[str]) -> None:
        historial_visual.controls.clear()
        for error in reversed(historial):
            vista_previa = " ".join(error.split())
            if len(vista_previa) > 180:
                vista_previa = vista_previa[:180] + "..."
            historial_visual.controls.append(
                ft.Container(
                    content=ft.Text(vista_previa, size=13),
                    padding=10,
                    bgcolor=ft.Colors.with_opacity(0.05, cian),
                    border=ft.Border.all(1, ft.Colors.OUTLINE),
                    border_radius=8,
                )
            )

    def obtener_votos(pagina_actual: ft.Page) -> dict[str, int]:
        obtener_historial(pagina_actual)
        votos = pagina_actual.data.get("detective_de_bugs_votos")
        if not isinstance(votos, dict) or any(
            type(votos.get(tipo)) is not int or votos[tipo] < 0
            for tipo in ("util", "no_util")
        ):
            votos = {"util": 0, "no_util": 0}
            pagina_actual.data["detective_de_bugs_votos"] = votos
        return votos

    def actualizar_resumen_votos(
        pagina_actual: ft.Page, actualizar_control: bool = True
    ) -> None:
        votos = obtener_votos(pagina_actual)
        resumen_votos.value = (
            f"👍 Útiles: {votos['util']}   ·   👎 No me sirvió: {votos['no_util']}"
        )
        if actualizar_control:
            resumen_votos.update()

    def registrar_error(error: str, historial: list[str]) -> None:
        historial.append(error)
        del historial[:-5]
        actualizar_historial(historial)

    def incluir_historial(error_actual: str, historial: list[str]) -> str:
        if not historial:
            return error_actual

        anteriores = "\n".join(
            f"{numero}. {error}"
            for numero, error in enumerate(historial, start=1)
        )
        return (
            "Errores consultados anteriormente (úsalos como contexto):\n"
            f"{anteriores}\n\nNuevo error a analizar:\n{error_actual}"
        )

    def mostrar_diagnostico(respuesta):
        nonlocal ultima_solucion
        if not isinstance(respuesta, dict) or any(
            not isinstance(respuesta.get(clave), str)
            or not respuesta[clave].strip()
            for clave, _ in pasos
        ):
            raise ErrorDiagnosticoInvalido(
                "La respuesta no contiene los tres pasos esperados."
            )

        ultima_solucion = respuesta["como_solucionarlo"].strip()
        boton_copiar.disabled = False
        boton_escuchar.disabled = False
        resultados.controls.clear()
        for numero, (clave, titulo) in enumerate(pasos, start=1):
            boton_util = ft.Button("👍 Útil")
            boton_no_util = ft.Button("👎 No me sirvió")
            estado_voto = ft.Text(
                size=12,
                color=ft.Colors.with_opacity(0.7, cian),
            )

            def crear_manejadores_voto(
                boton_util: ft.Button,
                boton_no_util: ft.Button,
                estado_voto: ft.Text,
            ):
                voto_actual: str | None = None

                def crear_manejador_voto(valor: str):
                    def registrar_voto(e):
                        nonlocal voto_actual
                        if voto_actual == valor:
                            return

                        votos = obtener_votos(e.page)
                        if voto_actual is not None:
                            # Cambiar la valoración ajusta el total sin duplicar votos.
                            votos[voto_actual] -= 1
                        votos[valor] += 1
                        voto_actual = valor

                        boton_util.bgcolor = cian if valor == "util" else None
                        boton_util.color = (
                            ft.Colors.BLACK if valor == "util" else None
                        )
                        boton_no_util.bgcolor = cian if valor == "no_util" else None
                        boton_no_util.color = (
                            ft.Colors.BLACK if valor == "no_util" else None
                        )
                        estado_voto.value = "Gracias por tu opinión."
                        boton_util.update()
                        boton_no_util.update()
                        estado_voto.update()
                        actualizar_resumen_votos(e.page)

                    return registrar_voto

                return (
                    crear_manejador_voto("util"),
                    crear_manejador_voto("no_util"),
                )

            boton_util.on_click, boton_no_util.on_click = crear_manejadores_voto(
                boton_util, boton_no_util, estado_voto
            )
            resultados.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Container(
                                        content=ft.Text(
                                            str(numero),
                                            color=ft.Colors.BLACK,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        bgcolor=cian,
                                        width=32,
                                        height=32,
                                        alignment=ft.Alignment.CENTER,
                                        border_radius=16,
                                    ),
                                    ft.Column(
                                        [
                                            ft.Text(
                                                titulo,
                                                color=cian,
                                                weight=ft.FontWeight.BOLD,
                                            ),
                                            ft.Text(respuesta[clave].strip()),
                                        ],
                                        spacing=4,
                                        expand=True,
                                    ),
                                ],
                                spacing=12,
                                vertical_alignment=ft.CrossAxisAlignment.START,
                            ),
                            ft.Row(
                                [boton_util, boton_no_util, estado_voto],
                                spacing=8,
                                wrap=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=12,
                    ),
                    padding=14,
                    bgcolor=ft.Colors.with_opacity(0.08, cian),
                    border=ft.Border.all(1, cian),
                    border_radius=10,
                )
            )

    async def analizar_archivo(e):
        if grabando or transcribiendo or modo_multimodal:
            return

        historial = obtener_historial(e.page)
        actualizar_historial(historial)
        boton_archivo.disabled = True
        boton_imagen.disabled = True
        boton_audio.disabled = True
        boton_multimodal.disabled = True
        boton.disabled = True
        estado.value = "Selecciona un archivo de código..."
        estado.color = cian
        progreso.visible = True
        e.page.update()

        try:
            if selector_imagen not in e.page.services:
                e.page.services.append(selector_imagen)

            archivos = await selector_imagen.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["txt", "py"],
                with_data=True,
            )
            if not archivos:
                estado.value = "No seleccionaste ningún archivo."
                estado.color = ft.Colors.ORANGE
                return

            archivo = archivos[0]
            if not archivo.name.lower().endswith((".py", ".txt")):
                raise ValueError("Selecciona un archivo con extensión .py o .txt.")
            if not isinstance(archivo.bytes, bytes) or not archivo.bytes:
                raise ValueError("El archivo está vacío o no se pudo leer.")

            try:
                codigo = archivo.bytes.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise ValueError(
                    "No pude leer el archivo. Guárdalo como texto UTF-8 e inténtalo de nuevo."
                ) from error
            if not codigo.strip():
                raise ValueError("El archivo no contiene texto.")

            prompt = incluir_historial(codigo, historial)
            if bloquear_datos_sensibles(e.page, prompt):
                return

            lineas = len(codigo.splitlines())
            palabras = len(codigo.split())
            entrada.value = codigo
            archivo_info.value = (
                f"{archivo.name} · {lineas} líneas · {palabras} palabras"
            )
            estado.value = "Analizando el archivo..."
            e.page.update()

            instruccion = (
                "Analiza el código fuente de Python y detecta el error o bug "
                "más relevante. Devuelve únicamente un objeto JSON con las "
                'claves "que_paso", "por_que_ocurrio" y "como_solucionarlo". '
                "Cada valor "
                "debe ser una explicación breve y clara en español. Si el "
                "archivo no contiene un error evidente, indícalo en la respuesta."
            )
            instruccion = adaptar_instruccion(instruccion)
            registrar_error(f"{archivo.name}: {codigo}", historial)
            respuesta = await asyncio.to_thread(ia, instruccion, prompt, True)
            mostrar_diagnostico(respuesta)
            estado.value = ""
        except ErrorDiagnosticoInvalido as error:
            notificar_error(e.page, error)
        except json.JSONDecodeError as error:
            notificar_error(e.page, error)
        except ValueError as error:
            estado.value = str(error)
            estado.color = ft.Colors.ORANGE
        except Exception as error:
            notificar_error(e.page, error)
        finally:
            progreso.visible = False
            boton_archivo.disabled = False
            boton_imagen.disabled = False
            boton_audio.disabled = False
            boton_multimodal.disabled = False
            boton.disabled = False
            e.page.update()

    async def analizar_imagen(e):
        if grabando or transcribiendo or modo_multimodal:
            return

        historial = obtener_historial(e.page)
        actualizar_historial(historial)
        boton_imagen.disabled = True
        boton_archivo.disabled = True
        boton_audio.disabled = True
        boton_multimodal.disabled = True
        boton.disabled = True
        estado.value = "Selecciona una imagen del error..."
        estado.color = cian
        progreso.visible = True
        e.page.update()

        try:
            if selector_imagen not in e.page.services:
                e.page.services.append(selector_imagen)

            archivos = await selector_imagen.pick_files(
                file_type=ft.FilePickerFileType.IMAGE,
                with_data=True,
            )
            if not archivos:
                estado.value = "No se seleccionó ninguna imagen."
                estado.color = ft.Colors.ORANGE
                return

            archivo = archivos[0]
            imagen, mime = validar_imagen(archivo)

            estado.value = "Analizando la imagen..."
            e.page.update()
            instruccion = (
                "Lee el mensaje de error de Python visible en la imagen y "
                "analízalo. Devuelve únicamente un objeto JSON con las claves "
                '"que_paso", "por_que_ocurrio" y "como_solucionarlo". Cada valor '
                "debe ser "
                "una explicación breve y clara en español. Si no hay un error "
                "legible, indícalo en la clave \"que_paso\" y aclara las demás."
            )
            instruccion = adaptar_instruccion(instruccion)
            contexto = incluir_historial(
                f"Analiza el error visible en la imagen {archivo.name}.",
                historial,
            )
            if bloquear_datos_sensibles(e.page, contexto):
                return

            respuesta = await asyncio.to_thread(
                ia_media,
                instruccion,
                imagen,
                mime,
                contexto,
                True,
            )
            mostrar_diagnostico(respuesta)
            registrar_error(f"Imagen {archivo.name}: {respuesta['que_paso'].strip()}", historial)
            estado.value = ""
        except ErrorDiagnosticoInvalido as error:
            notificar_error(e.page, error)
        except json.JSONDecodeError as error:
            notificar_error(e.page, error)
        except ValueError as error:
            estado.value = str(error)
            estado.color = ft.Colors.ORANGE
        except Exception as error:
            notificar_error(e.page, error)
        finally:
            progreso.visible = False
            boton_imagen.disabled = False
            boton_archivo.disabled = False
            boton_audio.disabled = False
            boton_multimodal.disabled = False
            boton.disabled = False
            e.page.update()

    async def detener_multimodal_y_analizar():
        nonlocal modo_multimodal, temporizador_multimodal, imagen_multimodal
        nonlocal transcribiendo
        if not modo_multimodal or transcribiendo:
            return

        modo_multimodal = False
        transcribiendo = True
        tarea_actual = asyncio.current_task()
        if (
            temporizador_multimodal is not None
            and temporizador_multimodal is not tarea_actual
        ):
            temporizador_multimodal.cancel()
        temporizador_multimodal = None
        boton_multimodal.disabled = True
        boton_audio.disabled = True
        boton_imagen.disabled = True
        boton_archivo.disabled = True
        boton.disabled = True
        boton_multimodal.content = "Analizando foto + voz..."
        estado.value = "Preparando audio y analizando ambos recursos..."
        estado.color = cian
        progreso.visible = True
        if pagina is not None:
            pagina.update()

        try:
            await grabadora.stop_recording()
            audio_pcm = b"".join(fragmentos_audio)
            if not audio_pcm:
                raise ValueError("La grabación no contiene audio.")
            if imagen_multimodal is None:
                raise ValueError("No se encontró la captura seleccionada.")

            imagen, mime, nombre_imagen = imagen_multimodal
            audio_wav = await asyncio.to_thread(
                pcm_a_wav, audio_pcm, tasa=16000, canales=1
            )
            if not audio_wav:
                raise ValueError("No se pudo preparar el audio grabado.")

            historial = obtener_historial(pagina)
            contexto = incluir_historial(
                "La captura muestra el error. El audio describe lo que hacía "
                f"el usuario cuando ocurrió. Archivo: {nombre_imagen}.",
                historial,
            )
            if bloquear_datos_sensibles(pagina, contexto):
                return

            instruccion = (
                "Analiza conjuntamente la captura de pantalla y el audio "
                "adjunto. Extrae de la imagen el error o código visible y "
                "usa la explicación oral como contexto de lo que hacía el "
                "usuario. Compara ambas fuentes y no inventes detalles que "
                "no estén respaldados por ellas. Devuelve únicamente un "
                "objeto JSON con las claves \"que_paso\", \"por_que_ocurrio\" "
                "y \"como_solucionarlo\", cada una con una explicación breve "
                "en español. Si una fuente no es legible, indícalo claramente."
            )
            instruccion = adaptar_instruccion(instruccion)
            respuesta = await asyncio.to_thread(
                ia_media,
                instruccion,
                imagen,
                mime,
                contexto,
                True,
                adjuntos=[(audio_wav, "audio/wav")],
            )
            mostrar_diagnostico(respuesta)
            registrar_error(
                f"Foto + voz ({nombre_imagen}): "
                f"{respuesta['que_paso'].strip()}",
                historial,
            )
            estado.value = ""
        except ErrorDiagnosticoInvalido as error:
            notificar_error(pagina, error)
        except json.JSONDecodeError as error:
            notificar_error(pagina, error)
        except ValueError as error:
            estado.value = str(error)
            estado.color = ft.Colors.ORANGE
        except Exception as error:
            notificar_error(pagina, error)
        finally:
            transcribiendo = False
            progreso.visible = False
            boton_multimodal.disabled = False
            boton_audio.disabled = False
            boton_imagen.disabled = False
            boton_archivo.disabled = False
            boton.disabled = False
            boton_multimodal.content = "Diagnóstico con foto + voz"
            imagen_multimodal = None
            if pagina is not None:
                pagina.update()

    async def detener_multimodal_por_limite():
        await asyncio.sleep(30)
        if modo_multimodal:
            await detener_multimodal_y_analizar()

    async def analizar_multimodal(e):
        nonlocal modo_multimodal, temporizador_multimodal, imagen_multimodal, pagina
        if grabando or transcribiendo:
            return
        if modo_multimodal:
            await detener_multimodal_y_analizar()
            return

        pagina = e.page
        boton_multimodal.disabled = True
        boton_audio.disabled = True
        boton_imagen.disabled = True
        boton_archivo.disabled = True
        boton.disabled = True
        estado.value = "Selecciona la captura del error..."
        estado.color = cian
        progreso.visible = True
        e.page.update()

        try:
            if selector_imagen not in e.page.services:
                e.page.services.append(selector_imagen)

            archivos = await selector_imagen.pick_files(
                file_type=ft.FilePickerFileType.IMAGE,
                with_data=True,
            )
            if not archivos:
                estado.value = "No seleccionaste una captura."
                estado.color = ft.Colors.ORANGE
                return

            archivo = archivos[0]
            imagen, mime = validar_imagen(archivo)
            if not await grabadora.has_permission():
                estado.value = "No se concedió permiso para usar el micrófono."
                estado.color = ft.Colors.ORANGE
                return

            fragmentos_audio.clear()
            iniciada = await grabadora.start_recording()
            if not iniciada:
                estado.value = "No se pudo iniciar la grabación. Inténtalo de nuevo."
                estado.color = ft.Colors.RED
                return

            imagen_multimodal = (imagen, mime, archivo.name)
            modo_multimodal = True
            boton_multimodal.content = "Detener voz y analizar"
            boton_multimodal.icon = ft.Icons.STOP
            boton_multimodal.disabled = False
            archivo_info.value = f"Captura seleccionada: {archivo.name}"
            estado.value = (
                "Grabando contexto... Describe qué hacías; se detendrá "
                "automáticamente a los 30 segundos."
            )
            estado.color = cian
            progreso.visible = False
            temporizador_multimodal = asyncio.create_task(
                detener_multimodal_por_limite()
            )
        except Exception as error:
            notificar_error(e.page, error)
        finally:
            if not modo_multimodal:
                boton_multimodal.disabled = False
                boton_audio.disabled = False
                boton_imagen.disabled = False
                boton_archivo.disabled = False
                boton.disabled = False
                progreso.visible = False
                boton_multimodal.content = "Diagnóstico con foto + voz"
                boton_multimodal.icon = ft.Icons.MERGE_TYPE
            e.page.update()

    async def detener_y_transcribir():
        nonlocal grabando, transcribiendo, temporizador, ultima_solucion
        if not grabando or transcribiendo:
            return

        grabando = False
        transcribiendo = True
        tarea_actual = asyncio.current_task()
        if temporizador is not None and temporizador is not tarea_actual:
            temporizador.cancel()
        temporizador = None
        boton_audio.disabled = True
        boton_imagen.disabled = True
        boton_archivo.disabled = True
        boton_multimodal.disabled = True
        boton.disabled = True
        boton_audio.content = "Transcribiendo..."
        boton_audio.icon = ft.Icons.MIC
        estado.value = "Transcribiendo..."
        estado.color = cian
        progreso.visible = True
        if pagina is not None:
            pagina.update()

        try:
            await grabadora.stop_recording()
            audio_pcm = b"".join(fragmentos_audio)
            if not audio_pcm:
                raise ValueError("La grabación no contiene audio.")
            transcripcion = await asyncio.to_thread(transcribir_audio, audio_pcm)
            entrada.value = transcripcion
            resultados.controls.clear()
            ultima_solucion = None
            boton_copiar.disabled = True
            boton_escuchar.disabled = True
            estado.value = "Transcripción lista. Ya puedes investigar el error."
            estado.color = cian
        except Exception as error:
            notificar_error(pagina, error)
        finally:
            transcribiendo = False
            progreso.visible = False
            boton_audio.disabled = False
            boton_imagen.disabled = False
            boton_archivo.disabled = False
            boton_multimodal.disabled = False
            boton_audio.content = "Grabar descripción"
            boton_audio.icon = ft.Icons.MIC
            boton.disabled = False
            if pagina is not None:
                pagina.update()

    async def detener_por_limite():
        await asyncio.sleep(30)
        if grabando:
            await detener_y_transcribir()

    async def dictar(e):
        nonlocal grabando, pagina, temporizador
        if transcribiendo or modo_multimodal:
            return
        if grabando:
            await detener_y_transcribir()
            return

        pagina = e.page
        boton_audio.disabled = True
        boton_imagen.disabled = True
        boton_archivo.disabled = True
        boton_multimodal.disabled = True
        boton.disabled = True
        estado.value = "Solicitando permiso del micrófono..."
        estado.color = cian
        progreso.visible = True
        e.page.update()

        try:
            if not await grabadora.has_permission():
                estado.value = "No se concedió permiso para usar el micrófono."
                estado.color = ft.Colors.ORANGE
                return

            fragmentos_audio.clear()
            iniciada = await grabadora.start_recording()
            if not iniciada:
                estado.value = "No se pudo iniciar la grabación. Inténtalo de nuevo."
                estado.color = ft.Colors.RED
                return

            grabando = True
            boton_audio.content = "Detener y transcribir"
            boton_audio.icon = ft.Icons.STOP
            boton_audio.disabled = False
            estado.value = "Grabando... Se detendrá automáticamente a los 30 segundos."
            estado.color = cian
            # El temporizador limita la grabación aunque el usuario no la detenga.
            temporizador = asyncio.create_task(detener_por_limite())
        except Exception:
            estado.value = "No pude iniciar la grabación. Revisa el permiso del micrófono."
            estado.color = ft.Colors.RED
        finally:
            if not grabando:
                boton_audio.disabled = False
                boton_imagen.disabled = False
                boton_archivo.disabled = False
                boton_multimodal.disabled = False
                boton.disabled = False
                progreso.visible = False
            e.page.update()

    async def investigar(e):
        nonlocal ultima_solucion
        historial = obtener_historial(e.page)
        actualizar_historial(historial)
        error_python = (entrada.value or "").strip()
        resultados.controls.clear()
        ultima_solucion = None
        boton_copiar.disabled = True
        boton_escuchar.disabled = True

        if not error_python:
            estado.value = "Pega un error de Python para poder investigarlo."
            estado.color = ft.Colors.ORANGE
            e.page.update()
            return

        if len(error_python) > 500:
            estado.value = "El texto no puede superar los 500 caracteres."
            estado.color = ft.Colors.ORANGE
            e.page.update()
            return

        prompt = incluir_historial(error_python, historial)
        if bloquear_datos_sensibles(e.page, prompt):
            return

        boton.disabled = True
        progreso.visible = True
        estado.value = "Analizando el error..."
        estado.color = cian
        e.page.update()

        instruccion = (
            "Analiza el error de Python proporcionado. Devuelve únicamente "
            "un objeto JSON con las claves \"que_paso\", \"por_que_ocurrio\" "
            "y \"como_solucionarlo\". Cada valor debe ser una explicación breve "
            "y clara en español. No incluyas números ni numeración: la "
            "aplicación presentará la respuesta en tres pasos."
        )
        instruccion = adaptar_instruccion(instruccion)

        try:
            registrar_error(error_python, historial)
            respuesta = await asyncio.to_thread(ia, instruccion, prompt, True)
            mostrar_diagnostico(respuesta)
            estado.value = ""
        except Exception as error:
            notificar_error(e.page, error)
        finally:
            progreso.visible = False
            boton.disabled = False
            e.page.update()

    boton.on_click = investigar
    boton_copiar.on_click = copiar_solucion
    boton_escuchar.on_click = escuchar_solucion
    boton_limpiar.on_click = limpiar_pantalla
    boton_audio.on_click = dictar
    boton_imagen.on_click = analizar_imagen
    boton_multimodal.on_click = analizar_multimodal
    boton_archivo.on_click = analizar_archivo

    if page is not None:
        actualizar_historial(obtener_historial(page))
        actualizar_resumen_votos(page, actualizar_control=False)

    return ft.Container(
        content=ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Text("🔍🐛", size=28),
                                width=56,
                                height=56,
                                alignment=ft.Alignment.CENTER,
                                bgcolor=ft.Colors.with_opacity(0.16, cian),
                                border_radius=14,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "Detective de bugs",
                                        size=24,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.WHITE,
                                    ),
                                    ft.Text(
                                        "Tu compañero para entender errores de Python",
                                        size=13,
                                        color=ft.Colors.with_opacity(0.8, ft.Colors.WHITE),
                                    ),
                                ],
                                spacing=3,
                                expand=True,
                            ),
                        ],
                        spacing=14,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=16,
                    bgcolor=ft.Colors.with_opacity(0.12, cian),
                    border=ft.Border.all(1, cian),
                    border_radius=14,
                ),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "¿Qué puedes hacer?",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=cian,
                            ),
                            ft.Text(
                                "Analiza errores de Python y recibe un diagnóstico en tres pasos.\n"
                                "Pega texto, dicta el error o carga una captura o archivo .py/.txt.\n"
                                "La IA puede equivocarse; el filtro revisa texto y código, no fotos ni audio.",
                                size=14,
                                color=ft.Colors.WHITE,
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=16,
                    bgcolor=ft.Colors.with_opacity(0.06, cian),
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.35, cian)),
                    border_radius=12,
                ),
                entrada,
                nivel_programador,
                boton_audio,
                boton_imagen,
                boton_multimodal,
                boton_archivo,
                archivo_info,
                grabadora,
                ft.Row([progreso, estado], spacing=8),
                boton,
                ft.Row(
                    [boton_copiar, boton_escuchar, boton_limpiar],
                    spacing=8,
                    wrap=True,
                ),
                resultados,
                ft.Text("Errores consultados recientemente", size=18, color=cian),
                historial_visual,
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "Satisfacción de la sesión",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=cian,
                            ),
                            resumen_votos,
                        ],
                        spacing=6,
                    ),
                    padding=14,
                    bgcolor=ft.Colors.with_opacity(0.06, cian),
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.35, cian)),
                    border_radius=12,
                ),
            ],
            spacing=12,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
        padding=16,
        border=ft.Border.all(1, cian),
        border_radius=12,
        expand=True,
    )
