import asyncio

import flet as ft

from ia import ia


def vista() -> ft.Control:
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
    estado = ft.Text()
    resultados = ft.Column(spacing=10)
    boton = ft.Button(
        "Investigar error",
        color=ft.Colors.BLACK,
        bgcolor=cian,
    )

    async def investigar(e):
        error_python = (entrada.value or "").strip()
        resultados.controls.clear()

        if not error_python:
            estado.value = "Pega un error de Python para poder investigarlo."
            estado.color = ft.Colors.ORANGE
            e.page.update()
            return

        boton.disabled = True
        estado.value = "Analizando el error..."
        estado.color = cian
        e.page.update()

        instruccion = (
            "Analiza el error de Python proporcionado. Devuelve únicamente "
            "un objeto JSON con las claves \"que_paso\", \"por_que\" y "
            "\"como_se_arregla\". Cada valor debe ser una explicación breve "
            "y clara en español. No incluyas números ni numeración: la "
            "aplicación presentará la respuesta en tres pasos."
        )

        try:
            respuesta = await asyncio.to_thread(ia, instruccion, error_python, True)
            pasos = (
                ("que_paso", "Qué pasó"),
                ("por_que", "Por qué"),
                ("como_se_arregla", "Cómo se arregla"),
            )
            if not isinstance(respuesta, dict) or any(
                not isinstance(respuesta.get(clave), str)
                or not respuesta[clave].strip()
                for clave, _ in pasos
            ):
                raise ValueError("La respuesta no contiene los tres pasos esperados.")

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
                        border=ft.border.all(1, cian),
                        border_radius=10,
                    )
                )
            estado.value = ""
        except Exception:
            # Mantiene la app disponible y muestra un mensaje claro si falla el análisis.
            estado.value = "No pude analizar el error. Inténtalo de nuevo."
            estado.color = ft.Colors.RED
        finally:
            boton.disabled = False
            e.page.update()

    boton.on_click = investigar

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
                boton,
                estado,
                resultados,
            ],
            spacing=12,
            expand=True,
        ),
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
        padding=16,
        border=ft.border.all(1, cian),
        border_radius=12,
        expand=True,
    )
