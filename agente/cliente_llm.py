"""Inicialización del cliente de Gemini. Es lo único que habla con la API."""

import logging
import time
from typing import Callable, Protocol

from google import genai
from google.genai import errors, types

from .config import Config
from .herramientas import TOOLS
from .prompts import SYSTEM_PROMPT

log = logging.getLogger("sistema")

# 429: cuota por minuto (el free tier permite pocas solicitudes); 5xx: sobrecarga temporal.
CODIGOS_REINTENTABLES = {429, 500, 503, 504}
MAX_ESPERA_S = 60.0


class ModeloLLM(Protocol):
    def generar(self, historial: list[types.Content]) -> types.GenerateContentResponse: ...


def _segundos_sugeridos(error: errors.APIError) -> float | None:
    """Lee el RetryInfo.retryDelay (p. ej. "27s") que Google adjunta a los 429."""
    detalles = (error.details or {}).get("error", {}).get("details", []) if isinstance(error.details, dict) else []
    for detalle in detalles:
        retraso = detalle.get("retryDelay") if isinstance(detalle, dict) else None
        if isinstance(retraso, str) and retraso.endswith("s"):
            try:
                return float(retraso[:-1])
            except ValueError:
                return None
    return None


class GeminiLLM:
    def __init__(self, config: Config, max_intentos: int = 4, dormir: Callable[[float], None] = time.sleep):
        self._client = genai.Client(
            api_key=config.api_key,
            http_options=types.HttpOptions(timeout=config.timeout_ms),
        )
        self._modelo = config.modelo
        self._max_intentos = max_intentos
        self._dormir = dormir
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=TOOLS,
            # Las tools se ejecutan en nuestro loop (validación + log), no automáticamente en el SDK.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.AUTO)
            ),
        )

    def generar(self, historial: list[types.Content]) -> types.GenerateContentResponse:
        for intento in range(1, self._max_intentos + 1):
            try:
                return self._client.models.generate_content(
                    model=self._modelo,
                    contents=historial,
                    config=self._config,
                )
            except errors.APIError as e:
                if e.code not in CODIGOS_REINTENTABLES or intento == self._max_intentos:
                    raise
                espera = min(_segundos_sugeridos(e) or 2.0**intento, MAX_ESPERA_S)
                log.info("Gemini respondió %s (%s); reintento %d en %.0fs", e.code, e.status, intento, espera)
                self._dormir(espera)
        raise AssertionError("inalcanzable")
