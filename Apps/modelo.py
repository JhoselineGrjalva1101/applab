import asyncio

import flet as ft

from ia import ia


def vista() -> ft.Control:
    entrada = ft.TextField(
        label="¿Qué pasó?",
        hint_text="Cuéntanos qué necesitas explicar...",
        multiline=True,
        min_lines=3,
        max_lines=5,
        expand=True,
    )
    mensaje = ft.Text()
    resultados = ft.Column(spacing=8)
    boton = ft.Button("Generar excusas")

    async def generar(e: ft.ControlEvent) -> None:
        texto = (entrada.value or "").strip()
        if not texto:
            mensaje.value = "Escribe qué pasó antes de generar las excusas."
            e.page.update()
            return

        boton.disabled = True
        mensaje.value = "Pensando excusas..."
        resultados.controls.clear()
        e.page.update()

        instruccion = (
            "Devuelve únicamente un objeto JSON con las claves "
            '"creible", "epica" y "absurda". Cada valor debe ser una excusa '
            "de una sola frase, en español, basada en lo que pasó. "
            "La excusa creíble debe sonar realista, la épica grandiosa y "
            "la absurda disparatada."
        )

        try:
            # La llamada síncrona a la IA no debe bloquear la interfaz.
            respuesta = await asyncio.to_thread(ia, instruccion, texto, True)
            if not isinstance(respuesta, dict):
                raise ValueError("La respuesta no tiene el formato esperado.")

            etiquetas = (
                ("creible", "Creíble"),
                ("epica", "Épica"),
                ("absurda", "Absurda"),
            )
            excusas = []
            for clave, etiqueta in etiquetas:
                excusa = respuesta.get(clave)
                if not isinstance(excusa, str) or not excusa.strip():
                    raise ValueError("La respuesta no incluye las tres excusas.")
                excusas.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(etiqueta, weight=ft.FontWeight.BOLD),
                                ft.Text(excusa.strip()),
                            ],
                            spacing=4,
                        ),
                        padding=12,
                        border=ft.border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                    )
                )

            resultados.controls.extend(excusas)
            mensaje.value = ""
        except Exception as error:
            mensaje.value = (
                "No pudimos generar las excusas. Inténtalo de nuevo. "
                f"Detalle: {error}"
            )
        finally:
            boton.disabled = False
            e.page.update()

    boton.on_click = generar

    return ft.Column(
        [
            ft.Text("Excusas", size=24, weight=ft.FontWeight.BOLD),
            entrada,
            boton,
            mensaje,
            resultados,
        ],
        spacing=12,
        expand=True,
    )