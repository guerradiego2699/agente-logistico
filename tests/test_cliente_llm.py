import pytest
from google.genai import errors

from agente.cliente_llm import GeminiLLM
from agente.config import Config

ERROR_429 = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "message": "quota",
        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "27s"}],
    }
}


class ModelsFalso:
    def __init__(self, resultados):
        self._resultados = list(resultados)
        self.llamadas = 0

    def generate_content(self, **_):
        self.llamadas += 1
        r = self._resultados.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def crear_llm(resultados, **kwargs):
    esperas = []
    llm = GeminiLLM(Config(api_key="x", modelo="m"), dormir=esperas.append, **kwargs)
    models = ModelsFalso(resultados)
    llm._client = type("ClienteFalso", (), {"models": models})()
    return llm, models, esperas


def test_reintenta_429_respetando_retry_delay():
    llm, models, esperas = crear_llm([errors.APIError(429, ERROR_429), "respuesta"])
    assert llm.generar([]) == "respuesta"
    assert models.llamadas == 2
    assert esperas == [27.0]


def test_backoff_exponencial_sin_retry_delay():
    err = errors.APIError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "x"}})
    llm, _, esperas = crear_llm([err, err, "ok"])
    assert llm.generar([]) == "ok"
    assert esperas == [2.0, 4.0]


def test_se_rinde_tras_max_intentos():
    err = errors.APIError(429, ERROR_429)
    llm, models, _ = crear_llm([err, err], max_intentos=2)
    with pytest.raises(errors.APIError):
        llm.generar([])
    assert models.llamadas == 2


def test_no_reintenta_errores_del_cliente():
    err = errors.APIError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "x"}})
    llm, models, _ = crear_llm([err])
    with pytest.raises(errors.APIError):
        llm.generar([])
    assert models.llamadas == 1
