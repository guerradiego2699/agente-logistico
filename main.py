"""CLI del Asistente de Logística e Inventario.

Uso:  python main.py [--seed N] [--debug]
"""

import argparse
import logging
import sys

from agente.agente import AgenteLogistico
from agente.cliente_llm import GeminiLLM
from agente.config import ConfigError, cargar_config
from agente.herramientas import EjecutorHerramientas
from agente.inventario import InventarioMock

COMANDOS_SALIDA = {"salir", "exit", "quit"}


def configurar_logs(debug: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [SISTEMA] %(message)s"))
    logger = logging.getLogger("sistema")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False


def construir_agente(seed: int | None) -> AgenteLogistico:
    config = cargar_config()
    return AgenteLogistico(
        llm=GeminiLLM(config),
        herramientas=EjecutorHerramientas(InventarioMock(seed=seed)),
        max_rondas_tools=config.max_rondas_tools,
        max_turnos_historial=config.max_turnos_historial,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Asistente de Logística e Inventario (Gemini)")
    parser.add_argument("--seed", type=int, help="Semilla para que el stock simulado sea reproducible")
    parser.add_argument("--debug", action="store_true", help="Muestra cada llamada a herramientas")
    args = parser.parse_args()

    configurar_logs(args.debug)
    try:
        agente = construir_agente(args.seed)
    except ConfigError as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 1

    print("Asistente de Logística e Inventario. Escribe 'salir' para terminar.\n")
    while True:
        try:
            mensaje = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not mensaje:
            continue
        if mensaje.lower() in COMANDOS_SALIDA:
            break
        try:
            print(f"Agente: {agente.enviar(mensaje)}\n")
        except KeyboardInterrupt:
            print("\n(Turno cancelado)\n")

    print("Hasta luego.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
