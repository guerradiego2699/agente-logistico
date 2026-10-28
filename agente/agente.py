"""Orquestación: historial de la conversación y loop de Function Calling."""

import logging

from google.genai import errors, types

from .cliente_llm import ModeloLLM, es_cuota_diaria
from .herramientas import EjecutorHerramientas

log = logging.getLogger("sistema")

RESPUESTA_VACIA = "No obtuve una respuesta válida del modelo. ¿Puedes reformular tu solicitud de inventario?"


class AgenteLogistico:
    def __init__(
        self,
        llm: ModeloLLM,
        herramientas: EjecutorHerramientas,
        max_rondas_tools: int = 5,
        max_turnos_historial: int = 20,
    ):
        self._llm = llm
        self._herramientas = herramientas
        self._max_rondas_tools = max_rondas_tools
        self._max_turnos_historial = max_turnos_historial
        self.historial: list[types.Content] = []

    def enviar(self, mensaje: str) -> str:
        """Procesa un mensaje del usuario y devuelve la respuesta final en texto.

        Un turno puede requerir varias rondas: el modelo pide tools, las ejecutamos,
        le devolvemos el resultado y repetimos hasta que conteste con texto.
        """
        inicio_turno = len(self.historial)
        self.historial.append(types.Content(role="user", parts=[types.Part(text=mensaje)]))
        hubo_efectos = False  # True si en este turno ya se ejecutó alguna tool

        try:
            for _ in range(self._max_rondas_tools):
                self._recortar_historial()
                respuesta = self._llm.generar(self.historial)
                contenido = respuesta.candidates[0].content if respuesta.candidates else None
                if contenido is None or not contenido.parts:
                    return self._cerrar_turno_fallido(inicio_turno, hubo_efectos, RESPUESTA_VACIA)

                # Se guarda el contenido completo del modelo (incluye thought signatures de
                # Gemini 3, necesarias para que el razonamiento continúe entre rondas).
                self.historial.append(contenido)

                llamadas = respuesta.function_calls
                if not llamadas:
                    return respuesta.text or RESPUESTA_VACIA

                partes = []
                for llamada in llamadas:
                    resultado = self._herramientas.ejecutar(llamada.name, llamada.args)
                    hubo_efectos = True
                    partes.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=llamada.id, name=llamada.name, response=resultado
                            )
                        )
                    )
                self.historial.append(types.Content(role="user", parts=partes))

            log.warning("Se alcanzó el límite de %d rondas de tools en un turno", self._max_rondas_tools)
            return self._cerrar_turno_fallido(
                inicio_turno,
                hubo_efectos,
                "La solicitud requirió demasiados pasos y la detuve. ¿Puedes dividirla en partes?",
            )
        except errors.APIError as e:
            log.error("Error de la API de Gemini: %s %s", e.code, e.status)
            aviso = (
                "Se agotó la cuota diaria gratuita de Gemini para este modelo; se renueva mañana. "
                "Puedes cambiar GEMINI_MODEL en .env (p. ej. gemini-3.5-flash-lite)."
                if es_cuota_diaria(e)
                else f"No pude contactar al modelo ({e.code}). Intenta de nuevo."
            )
            return self._cerrar_turno_fallido(inicio_turno, hubo_efectos, aviso)
        except Exception:  # p. ej. caída de red (httpx) o respuesta inesperada del SDK
            log.exception("Fallo inesperado durante el turno")
            return self._cerrar_turno_fallido(
                inicio_turno, hubo_efectos, "Ocurrió un error inesperado. Intenta de nuevo."
            )

    def _cerrar_turno_fallido(self, inicio_turno: int, hubo_efectos: bool, aviso: str) -> str:
        if not hubo_efectos:
            # Nada ocurrió en el mundo: se descarta el turno para que el usuario pueda reintentar limpio.
            del self.historial[inicio_turno:]
            return aviso
        # Ya se ejecutaron tools (p. ej. una orden): se conserva el registro para que el modelo no
        # las repita, y se cierra el turno con un mensaje del modelo para mantener la alternancia.
        if self.historial[-1].role != "model" or self._tiene_llamadas(self.historial[-1]):
            self.historial.append(types.Content(role="model", parts=[types.Part(text=aviso)]))
        return aviso

    def _recortar_historial(self) -> None:
        """Ventana deslizante de los últimos N turnos del usuario.

        Solo se corta justo antes de un mensaje de texto del usuario, nunca entre una
        function_call y su function_response, para no dejar llamadas huérfanas.
        """
        inicios = [i for i, c in enumerate(self.historial) if self._es_mensaje_usuario(c)]
        if len(inicios) > self._max_turnos_historial:
            del self.historial[: inicios[-self._max_turnos_historial]]

    @staticmethod
    def _es_mensaje_usuario(contenido: types.Content) -> bool:
        return contenido.role == "user" and any(p.text for p in contenido.parts or [])

    @staticmethod
    def _tiene_llamadas(contenido: types.Content) -> bool:
        return any(p.function_call for p in contenido.parts or [])
