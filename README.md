# Agente Logístico (CLI) — Gemini + Function Calling

Asistente de consola de logística e inventario. Usa el SDK oficial `google-genai` con
**Function Calling nativo** (`types.Tool` / `FunctionDeclaration`): el modelo decide solo
cuándo consultar stock o emitir una orden de compra; no hay menús ni parseo de JSON con regex.

## Cómo correrlo

Requisitos: Python 3.10+.

1. Consigue una API key gratuita en <https://aistudio.google.com/apikey>.
2. Instala dependencias:
   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Configura la key: copia `.env.example` a `.env` y reemplaza el valor de `GEMINI_API_KEY`
   (o exporta la variable de entorno `GEMINI_API_KEY`).
4. Ejecuta:
   ```bash
   python main.py            # --seed 7 para stock reproducible, --debug para ver cada tool call
   ```
5. Tests (no requieren API key; usan un modelo guionizado):
   ```bash
   pytest
   ```

Escenario de prueba: escribe `Necesitamos equipar a 10 nuevos empleados con laptops`. El agente
consulta `consultar_stock("laptops")`, calcula el déficit, propone una orden solo por el faltante
y, si respondes que sí, llama a `emitir_orden_compra` (verás el log `[SISTEMA] Orden de compra ...`).

## Arquitectura

| Archivo | Responsabilidad |
|---|---|
| `agente/cliente_llm.py` | Inicialización del cliente Gemini: system prompt, tools y config. Único punto que toca la API. |
| `agente/inventario.py` | Funciones de negocio mock (`consultar_stock`, `emitir_orden_compra`) y sus reglas. No saben nada del LLM. |
| `agente/herramientas.py` | Declaraciones de las tools y validación de lo que envía el modelo antes de tocar el negocio. |
| `agente/agente.py` | Loop de ejecución: historial, rondas de function calling, manejo de errores. |
| `main.py` | CLI. |

## Estrategia de historial

El agente guarda la conversación como una lista de `types.Content` que se envía completa en cada
llamada a `generate_content`. Cada turno agrega el mensaje del usuario, el contenido **íntegro** que
devuelve el modelo (incluidas las `function_call` y las *thought signatures* de Gemini 3, que el
modelo necesita para continuar su razonamiento) y las `function_response` con el mismo `id` de cada
llamada. Así el modelo "recuerda" el stock que consultó y la cantidad que propuso cuando el usuario
responde "sí" en el turno siguiente. El function calling automático del SDK está desactivado: el
loop es nuestro, lo que permite validar argumentos, loguear y limitar las rondas por turno (5).

Para que el contexto no crezca sin límite se usa una ventana de los últimos 20 turnos, cortando
siempre justo antes de un mensaje de texto del usuario, nunca entre una `function_call` y su
respuesta. Si la API falla y en ese turno no se ejecutó ninguna tool, el turno se descarta para
que el usuario reintente limpio; si ya se ejecutó alguna (p. ej. una orden), se conserva en el
historial con un mensaje de cierre, para que el modelo no la repita.

## Edge cases cubiertos

- **Cantidades inválidas** (negativas, cero, > 500, fracciones, texto, booleanos): se rechazan en
  código y el error vuelve al modelo como `function_response` para que lo explique. El schema
  también declara `minimum`/`maximum`.
- **Alucinaciones del modelo**: función inexistente, parámetros extra o faltantes, producto fuera del
  catálogo → `{"error": ...}` en vez de excepción. Los sinónimos (`laptop`, `portátil`) se normalizan.
- **Loops de tools**: máximo 5 rondas por turno.
- **Cuota y sobrecarga de Gemini** (429 / 5xx): reintentos automáticos que respetan el `retryDelay`
  que envía Google (o backoff exponencial), con timeout de 60 s por solicitud. Nota: el free tier
  permite pocas solicitudes por minuto, así que algunas respuestas pueden tardar en llegar.
- **Errores de API / red / respuesta vacía**: mensaje claro al usuario sin romper el historial.
- **Fuera de dominio** (clima, código, chistes): el system prompt obliga a negarse y redirigir.
- El stock aleatorio (1–5) se fija por producto durante la sesión, para que dos consultas no se contradigan.
