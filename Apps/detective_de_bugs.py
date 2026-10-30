import asyncio

import flet as ft
from flet_audio_recorder import AudioEncoder, AudioRecorder, AudioRecorderConfiguration

from ia import ia
from multimedia import ia_media, pcm_a_wav


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

    pasos = (
        ("que_paso", "Qué pasó"),
        ("por_que_ocurrio", "Por qué ocurrió"),
        ("como_solucionarlo", "Cómo solucionarlo"),
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

    def limpiar_pantalla(e):
        nonlocal ultima_solucion
        entrada.value = ""
        archivo_info.value = ""
        estado.value = ""
        resultados.controls.clear()
        ultima_solucion = None
        boton_copiar.disabled = True
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
            raise ValueError("La respuesta no contiene los tres pasos esperados.")

        ultima_solucion = respuesta["como_solucionarlo"].strip()
        boton_copiar.disabled = False
        resultados.controls.clear()
        for numero, (clave, titulo) in enumerate(pasos, start=1):
            resultados.controls.append(
                ft.Container(
                    content=ft.Row(
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
                    padding=14,
                    bgcolor=ft.Colors.with_opacity(0.08, cian),
                    border=ft.Border.all(1, cian),
                    border_radius=10,
                )
            )

    async def analizar_archivo(e):
        if grabando or transcribiendo:
            return

        historial = obtener_historial(e.page)
        actualizar_historial(historial)
        boton_archivo.disabled = True
        boton_imagen.disabled = True
        boton_audio.disabled = True
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
            prompt = incluir_historial(codigo, historial)
            registrar_error(f"{archivo.name}: {codigo}", historial)
            respuesta = await asyncio.to_thread(ia, instruccion, prompt, True)
            mostrar_diagnostico(respuesta)
            estado.value = ""
        except ValueError as error:
            estado.value = str(error)
            estado.color = ft.Colors.ORANGE
        except Exception:
            # Explica el fallo de lectura o análisis sin interrumpir la app.
            estado.value = "No pude leer o analizar el archivo. Inténtalo de nuevo."
            estado.color = ft.Colors.RED
        finally:
            progreso.visible = False
            boton_archivo.disabled = False
            boton_imagen.disabled = False
            boton_audio.disabled = False
            boton.disabled = False
            e.page.update()

    async def analizar_imagen(e):
        if grabando or transcribiendo:
            return

        historial = obtener_historial(e.page)
        actualizar_historial(historial)
        boton_imagen.disabled = True
        boton_archivo.disabled = True
        boton_audio.disabled = True
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
            mime = formato[0]

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
            respuesta = await asyncio.to_thread(
                ia_media,
                instruccion,
                imagen,
                mime,
                incluir_historial(
                    f"Analiza el error visible en la imagen {archivo.name}.",
                    historial,
                ),
                True,
            )
            mostrar_diagnostico(respuesta)
            registrar_error(f"Imagen {archivo.name}: {respuesta['que_paso'].strip()}", historial)
            estado.value = ""
        except ValueError as error:
            estado.value = str(error)
            estado.color = ft.Colors.ORANGE
        except Exception:
            # Avisa de forma amable si no se puede leer o analizar la imagen.
            estado.value = "No pude analizar la imagen. Inténtalo de nuevo."
            estado.color = ft.Colors.RED
        finally:
            progreso.visible = False
            boton_imagen.disabled = False
            boton_archivo.disabled = False
            boton_audio.disabled = False
            boton.disabled = False
            e.page.update()

    async def detener_y_transcribir():
        nonlocal grabando, transcribiendo, temporizador
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
            estado.value = "Transcripción lista. Ya puedes investigar el error."
            estado.color = cian
        except Exception:
            # Informa del fallo sin detener la app ni ocultar la opción de reintentar.
            estado.value = "No pude transcribir el audio. Inténtalo de nuevo."
            estado.color = ft.Colors.RED
        finally:
            transcribiendo = False
            progreso.visible = False
            boton_audio.disabled = False
            boton_imagen.disabled = False
            boton_archivo.disabled = False
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
        if transcribiendo:
            return
        if grabando:
            await detener_y_transcribir()
            return

        pagina = e.page
        boton_audio.disabled = True
        boton_imagen.disabled = True
        boton_archivo.disabled = True
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
                boton.disabled = False
                progreso.visible = False
            e.page.update()

    async def investigar(e):
        historial = obtener_historial(e.page)
        actualizar_historial(historial)
        error_python = (entrada.value or "").strip()
        resultados.controls.clear()

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

        nonlocal ultima_solucion
        ultima_solucion = None
        boton_copiar.disabled = True
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
            prompt = incluir_historial(error_python, historial)
            registrar_error(error_python, historial)
            respuesta = await asyncio.to_thread(ia, instruccion, prompt, True)
            mostrar_diagnostico(respuesta)
            estado.value = ""
        except Exception:
            # Mantiene la app disponible y muestra un mensaje claro si falla el análisis.
            estado.value = "No pude analizar el error. Inténtalo de nuevo."
            estado.color = ft.Colors.RED
        finally:
            progreso.visible = False
            boton.disabled = False
            e.page.update()

    boton.on_click = investigar
    boton_copiar.on_click = copiar_solucion
    boton_limpiar.on_click = limpiar_pantalla
    boton_audio.on_click = dictar
    boton_imagen.on_click = analizar_imagen
    boton_archivo.on_click = analizar_archivo

    if page is not None:
        actualizar_historial(obtener_historial(page))

    return ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    "Detective de bugs",
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=cian,
                ),
                ft.Text("Pega un error de Python y descubre cómo resolverlo."),
                entrada,
                nivel_programador,
                boton_audio,
                boton_imagen,
                boton_archivo,
                archivo_info,
                grabadora,
                ft.Row([progreso, estado], spacing=8),
                boton,
                ft.Row([boton_copiar, boton_limpiar], spacing=8),
                resultados,
                ft.Text("Errores consultados recientemente", size=18, color=cian),
                historial_visual,
            ],
            spacing=12,
            expand=True,
        ),
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
        padding=16,
        border=ft.Border.all(1, cian),
        border_radius=12,
        expand=True,
    )
