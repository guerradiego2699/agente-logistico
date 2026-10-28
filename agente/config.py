"""Configuración leída del entorno (o de un archivo .env en la raíz)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Flash estable; se puede cambiar con GEMINI_MODEL (p. ej. "gemini-flash-latest").
MODELO_POR_DEFECTO = "gemini-3.6-flash"


class ConfigError(RuntimeError):
    """Falta configuración obligatoria para arrancar."""


@dataclass(frozen=True)
class Config:
    api_key: str
    modelo: str
    max_rondas_tools: int = 5
    max_turnos_historial: int = 20
    timeout_ms: int = 60_000


def cargar_config() -> Config:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ConfigError(
            "No se encontró GEMINI_API_KEY. Copia .env.example a .env y pega tu API key "
            "(https://aistudio.google.com/apikey)."
        )
    return Config(
        api_key=api_key,
        modelo=os.getenv("GEMINI_MODEL", MODELO_POR_DEFECTO),
    )
