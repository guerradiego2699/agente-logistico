import pytest

from agente.herramientas import EjecutorHerramientas
from agente.inventario import InventarioMock


@pytest.fixture
def inventario():
    return InventarioMock(seed=42)


@pytest.fixture
def ejecutor(inventario):
    return EjecutorHerramientas(inventario)


def test_stock_en_rango_y_estable_en_la_sesion(inventario):
    primero = inventario.consultar_stock("laptops")
    assert 1 <= primero <= 5
    assert inventario.consultar_stock("Laptop") == primero
    assert inventario.consultar_stock("  PORTÁTILES ") == primero


def test_consultar_stock_devuelve_nombre_canonico(ejecutor):
    resultado = ejecutor.ejecutar("consultar_stock", {"producto": "portátil"})
    assert resultado["producto"] == "laptops"
    assert 1 <= resultado["stock"] <= 5


def test_producto_inexistente(ejecutor):
    resultado = ejecutor.ejecutar("consultar_stock", {"producto": "unicornios"})
    assert "no existe en el catálogo" in resultado["error"]


def test_orden_valida_loguea_y_devuelve_ok(ejecutor, inventario, caplog):
    with caplog.at_level("INFO", logger="sistema"):
        resultado = ejecutor.ejecutar("emitir_orden_compra", {"producto": "laptops", "cantidad": 7})
    assert resultado == {"status": "OK", "orden_id": "OC-0001", "producto": "laptops", "cantidad": 7}
    assert len(inventario.ordenes) == 1
    assert "OC-0001" in caplog.text and "7 x laptops" in caplog.text


@pytest.mark.parametrize("cantidad", [-3, 0, 501])
def test_cantidades_fuera_de_rango(ejecutor, inventario, cantidad):
    resultado = ejecutor.ejecutar("emitir_orden_compra", {"producto": "laptops", "cantidad": cantidad})
    assert "error" in resultado
    assert inventario.ordenes == []


@pytest.mark.parametrize("cantidad", [2.5, "5", True, None])
def test_cantidades_con_tipo_alucinado(ejecutor, inventario, cantidad):
    resultado = ejecutor.ejecutar("emitir_orden_compra", {"producto": "laptops", "cantidad": cantidad})
    assert "entero" in resultado["error"]
    assert inventario.ordenes == []


def test_float_entero_se_acepta(ejecutor):
    # JSON no distingue 7 de 7.0; el SDK puede entregar cualquiera de los dos.
    resultado = ejecutor.ejecutar("emitir_orden_compra", {"producto": "laptops", "cantidad": 7.0})
    assert resultado["cantidad"] == 7


def test_funcion_alucinada(ejecutor):
    resultado = ejecutor.ejecutar("borrar_inventario", {})
    assert "no existe" in resultado["error"]


def test_parametro_alucinado(ejecutor, inventario):
    resultado = ejecutor.ejecutar(
        "emitir_orden_compra", {"producto": "laptops", "cantidad": 2, "descuento": 50}
    )
    assert "descuento" in resultado["error"]
    assert inventario.ordenes == []


def test_parametro_faltante(ejecutor):
    resultado = ejecutor.ejecutar("emitir_orden_compra", {"producto": "laptops"})
    assert "cantidad" in resultado["error"]


def test_args_none(ejecutor):
    resultado = ejecutor.ejecutar("consultar_stock", None)
    assert "producto" in resultado["error"]


def test_fallo_interno_no_rompe_el_agente(inventario):
    def explota(producto):
        raise RuntimeError("DB caída")

    inventario.consultar_stock = explota
    ejecutor = EjecutorHerramientas(inventario)
    resultado = ejecutor.ejecutar("consultar_stock", {"producto": "laptops"})
    assert "Fallo interno" in resultado["error"]
