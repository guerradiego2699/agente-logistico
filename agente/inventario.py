"""Funciones de negocio simuladas (mocks). No saben nada del LLM."""

import logging
import random
import unicodedata
from dataclasses import dataclass

log = logging.getLogger("sistema")

MAX_UNIDADES_POR_ORDEN = 500

# Nombre canónico -> sinónimos que puede usar el usuario (o el modelo).
CATALOGO: dict[str, set[str]] = {
    "laptops": {"laptop", "portatil", "portatiles", "notebook", "notebooks", "computador portatil"},
    "monitores": {"monitor", "pantalla", "pantallas"},
    "teclados": {"teclado"},
    "mouses": {"mouse", "raton", "ratones"},
    "headsets": {"headset", "audifonos", "auriculares", "diadema", "diademas"},
    "sillas": {"silla", "silla ergonomica", "sillas ergonomicas"},
}


class ErrorDeNegocio(ValueError):
    """Error de validación que se le devuelve al agente para que lo explique."""


class ProductoNoEncontrado(ErrorDeNegocio):
    pass


class CantidadInvalida(ErrorDeNegocio):
    pass


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


_ALIAS = {
    _normalizar(alias): canonico
    for canonico, sinonimos in CATALOGO.items()
    for alias in sinonimos | {canonico}
}


def resolver_producto(producto: str) -> str:
    canonico = _ALIAS.get(_normalizar(producto))
    if canonico is None:
        raise ProductoNoEncontrado(
            f"'{producto}' no existe en el catálogo. Productos disponibles: {', '.join(CATALOGO)}."
        )
    return canonico


@dataclass(frozen=True)
class OrdenCompra:
    id: str
    producto: str
    cantidad: int


class InventarioMock:
    """Simula la base de datos de inventario de una sesión.

    El stock se genera al azar la primera vez que se consulta un producto y se mantiene
    durante la sesión, para que el agente no vea cifras distintas en cada consulta.
    """

    def __init__(self, seed: int | None = None, stock_min: int = 1, stock_max: int = 5):
        self._rng = random.Random(seed)
        self._stock_min = stock_min
        self._stock_max = stock_max
        self._stock: dict[str, int] = {}
        self.ordenes: list[OrdenCompra] = []

    def consultar_stock(self, producto: str) -> int:
        canonico = resolver_producto(producto)
        if canonico not in self._stock:
            self._stock[canonico] = self._rng.randint(self._stock_min, self._stock_max)
        return self._stock[canonico]

    def emitir_orden_compra(self, producto: str, cantidad: int) -> str:
        canonico = resolver_producto(producto)
        if isinstance(cantidad, bool) or not isinstance(cantidad, int):
            raise CantidadInvalida(f"La cantidad debe ser un entero; se recibió {cantidad!r}.")
        if cantidad <= 0:
            raise CantidadInvalida(f"La cantidad debe ser mayor que cero; se recibió {cantidad}.")
        if cantidad > MAX_UNIDADES_POR_ORDEN:
            raise CantidadInvalida(
                f"Máximo {MAX_UNIDADES_POR_ORDEN} unidades por orden; se pidieron {cantidad}."
            )

        orden = OrdenCompra(id=f"OC-{len(self.ordenes) + 1:04d}", producto=canonico, cantidad=cantidad)
        self.ordenes.append(orden)
        log.info("Orden de compra %s emitida: %d x %s", orden.id, orden.cantidad, orden.producto)
        return "OK"
