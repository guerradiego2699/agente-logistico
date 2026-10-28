"""Puente entre el Function Calling de Gemini y las funciones de negocio.

Aquí viven las declaraciones que ve el modelo y la validación de lo que el modelo
envía: el LLM puede alucinar nombres de función, argumentos o tipos, así que nada
llega al inventario sin pasar por `EjecutorHerramientas.ejecutar`.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable

from google.genai import types

from .inventario import (
    CATALOGO,
    MAX_UNIDADES_POR_ORDEN,
    ErrorDeNegocio,
    InventarioMock,
    resolver_producto,
)

log = logging.getLogger("sistema")

_PRODUCTO = {
    "type": "string",
    "description": f"Producto del catálogo, tal como lo nombra el usuario. Catálogo: {', '.join(CATALOGO)}.",
}

DECLARACIONES = [
    types.FunctionDeclaration(
        name="consultar_stock",
        description="Devuelve las unidades disponibles hoy en el inventario para un producto.",
        parameters_json_schema={
            "type": "object",
            "properties": {"producto": _PRODUCTO},
            "required": ["producto"],
        },
    ),
    types.FunctionDeclaration(
        name="emitir_orden_compra",
        description=(
            "Emite una orden de compra real. Solo debe llamarse después de que el usuario "
            "confirme explícitamente el producto y la cantidad."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "producto": _PRODUCTO,
                "cantidad": {
                    "type": "integer",
                    "description": "Unidades a comprar (entero positivo).",
                    "minimum": 1,
                    "maximum": MAX_UNIDADES_POR_ORDEN,
                },
            },
            "required": ["producto", "cantidad"],
        },
    ),
]

TOOLS = [types.Tool(function_declarations=DECLARACIONES)]


class ArgumentoInvalido(ValueError):
    pass


def _texto(valor: Any, nombre: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ArgumentoInvalido(f"'{nombre}' debe ser un texto no vacío; se recibió {valor!r}.")
    return valor.strip()


def _entero(valor: Any, nombre: str) -> int:
    # Los argumentos llegan como JSON: un 7 puede venir como 7.0. Se acepta si es entero exacto.
    if isinstance(valor, bool):
        raise ArgumentoInvalido(f"'{nombre}' debe ser un entero; se recibió {valor!r}.")
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    if not isinstance(valor, int):
        raise ArgumentoInvalido(f"'{nombre}' debe ser un entero; se recibió {valor!r}.")
    return valor


@dataclass(frozen=True)
class _Herramienta:
    funcion: Callable[..., Any]
    parametros: dict[str, Callable[[Any, str], Any]]


class EjecutorHerramientas:
    def __init__(self, inventario: InventarioMock):
        self._inventario = inventario
        self._herramientas = {
            "consultar_stock": _Herramienta(
                funcion=inventario.consultar_stock,
                parametros={"producto": _texto},
            ),
            "emitir_orden_compra": _Herramienta(
                funcion=inventario.emitir_orden_compra,
                parametros={"producto": _texto, "cantidad": _entero},
            ),
        }

    def ejecutar(self, nombre: str, args: dict[str, Any] | None) -> dict[str, Any]:
        """Ejecuta una llamada del modelo y devuelve siempre un dict serializable.

        Nunca lanza: cualquier problema se devuelve como {"error": ...} para que el
        modelo lo explique al usuario o corrija la llamada.
        """
        args = dict(args or {})
        log.debug("Tool call: %s(%s)", nombre, args)
        try:
            herramienta = self._herramientas.get(nombre)
            if herramienta is None:
                raise ArgumentoInvalido(
                    f"La función '{nombre}' no existe. Disponibles: {', '.join(self._herramientas)}."
                )
            kwargs = self._validar(herramienta, args)
            resultado = herramienta.funcion(**kwargs)
        except (ArgumentoInvalido, ErrorDeNegocio) as e:
            log.warning("Tool %s rechazada: %s", nombre, e)
            return {"error": str(e)}
        except Exception:
            log.exception("Fallo inesperado ejecutando %s", nombre)
            return {"error": "Fallo interno del sistema de inventario. Intenta de nuevo más tarde."}

        if nombre == "consultar_stock":
            return {"producto": resolver_producto(kwargs["producto"]), "stock": resultado}
        orden = self._inventario.ordenes[-1]
        return {"status": resultado, "orden_id": orden.id, "producto": orden.producto, "cantidad": orden.cantidad}

    @staticmethod
    def _validar(herramienta: _Herramienta, args: dict[str, Any]) -> dict[str, Any]:
        sobrantes = set(args) - set(herramienta.parametros)
        if sobrantes:
            raise ArgumentoInvalido(
                f"Parámetros no soportados: {', '.join(sorted(sobrantes))}. "
                f"Usa solo: {', '.join(herramienta.parametros)}."
            )
        faltantes = [p for p in herramienta.parametros if p not in args]
        if faltantes:
            raise ArgumentoInvalido(f"Faltan parámetros obligatorios: {', '.join(faltantes)}.")
        return {p: validar(args[p], p) for p, validar in herramienta.parametros.items()}
