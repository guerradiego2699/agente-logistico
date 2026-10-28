"""Tests del loop del agente con un modelo guionizado (sin llamar a la API).

Las respuestas son objetos reales del SDK (`types.GenerateContentResponse`), así que
se ejercita el mismo camino de código que con Gemini.
"""

from google.genai import errors, types

from agente.agente import AgenteLogistico
from agente.herramientas import EjecutorHerramientas
from agente.inventario import InventarioMock


def texto(t):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=t)]))]
    )


def llamada(nombre, id_="c1", **args):
    parte = types.Part(function_call=types.FunctionCall(id=id_, name=nombre, args=args))
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[parte]))]
    )


class ModeloGuionizado:
    """Devuelve respuestas en orden. Cada paso puede ser una respuesta o una función
    que recibe el historial y decide (útil para "razonar" sobre lo que devolvió una tool)."""

    def __init__(self, pasos):
        self._pasos = list(pasos)
        self.historiales_vistos = []

    def generar(self, historial):
        self.historiales_vistos.append(list(historial))
        paso = self._pasos.pop(0)
        if isinstance(paso, Exception):
            raise paso
        return paso(historial) if callable(paso) else paso


def ultima_respuesta_tool(historial):
    return historial[-1].parts[0].function_response.response


def crear_agente(pasos, stock=3, **kwargs):
    inventario = InventarioMock(stock_min=stock, stock_max=stock)
    modelo = ModeloGuionizado(pasos)
    agente = AgenteLogistico(modelo, EjecutorHerramientas(inventario), **kwargs)
    return agente, modelo, inventario


def test_escenario_10_laptops():
    def propone_por_deficit(historial):
        stock = ultima_respuesta_tool(historial)["stock"]
        return texto(f"Hay {stock} laptops. Faltan {10 - stock}. ¿Emito orden por {10 - stock}?")

    def confirma_orden(historial):
        r = ultima_respuesta_tool(historial)
        return texto(f"Listo: orden {r['orden_id']} por {r['cantidad']} {r['producto']}.")

    agente, modelo, inventario = crear_agente(
        [
            llamada("consultar_stock", producto="laptops"),
            propone_por_deficit,
            llamada("emitir_orden_compra", id_="c2", producto="laptops", cantidad=7),
            confirma_orden,
        ],
        stock=3,
    )

    r1 = agente.enviar("Necesitamos equipar a 10 nuevos empleados con laptops")
    assert r1 == "Hay 3 laptops. Faltan 7. ¿Emito orden por 7?"
    assert inventario.ordenes == []  # todavía no se compra nada

    r2 = agente.enviar("Sí, dale")
    assert r2 == "Listo: orden OC-0001 por 7 laptops."
    assert [(o.producto, o.cantidad) for o in inventario.ordenes] == [("laptops", 7)]

    # Memoria: en el segundo turno el modelo recibió todo lo anterior.
    historial_turno_2 = modelo.historiales_vistos[2]
    textos = [p.text for c in historial_turno_2 for p in c.parts if p.text]
    assert "Necesitamos equipar a 10 nuevos empleados con laptops" in textos
    assert "Hay 3 laptops. Faltan 7. ¿Emito orden por 7?" in textos
    assert textos[-1] == "Sí, dale"


def test_function_response_conserva_id_y_nombre():
    agente, modelo, _ = crear_agente(
        [llamada("consultar_stock", id_="abc", producto="monitores"), texto("Hay 3.")]
    )
    agente.enviar("¿Cuántos monitores hay?")
    respuesta_tool = modelo.historiales_vistos[1][-1].parts[0].function_response
    assert respuesta_tool.id == "abc"
    assert respuesta_tool.name == "consultar_stock"
    assert respuesta_tool.response == {"producto": "monitores", "stock": 3}


def test_cantidad_negativa_llega_como_error_al_modelo():
    agente, modelo, inventario = crear_agente(
        [
            llamada("emitir_orden_compra", producto="laptops", cantidad=-5),
            lambda h: texto("No puedo: " + ultima_respuesta_tool(h)["error"]),
        ]
    )
    respuesta = agente.enviar("Compra -5 laptops")
    assert "mayor que cero" in respuesta
    assert inventario.ordenes == []


def test_varias_llamadas_en_paralelo():
    llamadas = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(function_call=types.FunctionCall(id="a", name="consultar_stock", args={"producto": "teclados"})),
                        types.Part(function_call=types.FunctionCall(id="b", name="consultar_stock", args={"producto": "mouses"})),
                    ],
                )
            )
        ]
    )
    agente, modelo, _ = crear_agente([llamadas, texto("ok")])
    agente.enviar("Stock de teclados y mouses")
    respuestas = modelo.historiales_vistos[1][-1].parts
    assert [p.function_response.id for p in respuestas] == ["a", "b"]


def test_error_de_api_sin_efectos_descarta_el_turno():
    agente, _, _ = crear_agente([errors.APIError(503, {"error": {"message": "overloaded"}}), texto("Hola")])
    respuesta = agente.enviar("¿Stock de sillas?")
    assert "503" in respuesta
    assert agente.historial == []  # el usuario puede reintentar sin basura en el contexto

    assert agente.enviar("¿Stock de sillas?") == "Hola"
    assert len(agente.historial) == 2


def test_error_de_api_tras_emitir_orden_conserva_el_registro():
    agente, _, inventario = crear_agente(
        [
            llamada("emitir_orden_compra", producto="sillas", cantidad=2),
            errors.APIError(500, {"error": {"message": "boom"}}),
        ]
    )
    agente.enviar("Confirmo, compra 2 sillas")
    assert len(inventario.ordenes) == 1
    roles = [c.role for c in agente.historial]
    assert roles == ["user", "model", "user", "model"]  # la orden queda en memoria y la alternancia se mantiene


def test_limite_de_rondas_corta_loops_del_modelo():
    agente, _, _ = crear_agente(
        [llamada("consultar_stock", id_=str(i), producto="laptops") for i in range(3)],
        max_rondas_tools=3,
    )
    respuesta = agente.enviar("loop")
    assert "demasiados pasos" in respuesta
    assert agente.historial[-1].role == "model"


def test_respuesta_vacia_del_modelo():
    vacia = types.GenerateContentResponse(candidates=[])
    agente, _, _ = crear_agente([vacia])
    assert "reformular" in agente.enviar("hola")
    assert agente.historial == []


def test_recorte_de_historial_no_separa_call_de_response():
    pasos = []
    for i in range(4):
        pasos += [llamada("consultar_stock", id_=str(i), producto="laptops"), texto(f"r{i}")]
    agente, modelo, _ = crear_agente(pasos, max_turnos_historial=2)

    for i in range(4):
        agente.enviar(f"pregunta {i}")

    primero = agente.historial[0]
    assert primero.role == "user" and primero.parts[0].text == "pregunta 2"
    for vistos in modelo.historiales_vistos:
        assert vistos[0].parts[0].text is not None  # nunca arranca con una function_response huérfana
