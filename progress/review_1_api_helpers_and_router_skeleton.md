# Review — feature 1 (api_helpers_and_router_skeleton)

**Veredicto:** APPROVED

## Resumen

El implementer extrae los cuatro helpers transversales (`admin_auth`,
`error_handlers`, `logging_middleware`, `range_response`) de
`services/transport/http/server.py` a `apps/api/*.py` y deja un compat shim
puro en server.py: solo imports + un wrapper de 1 línea para
`_authorize_admin_request`. `apps/api/app_factory.py` registra los handlers
de error vía el helper extraído. Ningún router se mueve (es scope de las
features 2-8). 146 tests verdes (baseline 116 + 30 nuevos).

## Foco específico de esta review

### 1. No hay cambio de comportamiento observable

- `services/transport/http/server.py:4197-4201` — `_authorize_admin_request`
  ahora es un wrapper de 1 línea sobre
  `apps/api/admin_auth.authorize_admin_request(request, runtime.admin_access_policy)`.
  La firma legacy `(request, runtime)` se conserva intacta, y todos los call
  sites (líneas 1669, 1702, 1765, …, 3465) siguen pasando `runtime`. La
  política es exactamente el mismo dataclass que se construía inline.
- `services/transport/http/server.py:712-717` — `WordPressWebhookApplication`
  sigue construyendo `_AdminAccessPolicy(...)` con los mismos campos
  (`enabled`, `base_path`, `bearer_token`, `disable_auth_for_testing`).
- `services/transport/http/server.py:1438` — la middleware ahora se monta
  vía `register_logging_middleware(app)` y reproduce 1:1 el comportamiento
  legacy: tres eventos persistentes (`http.request`, `http.response`,
  `http.exception`), `request.state.request_id`, redacción de Authorization
  + JSON keys sensibles. Verificado en
  `tests/unit/apps_api/test_logging_middleware.py:75-127`.
- `apps/api/app_factory.py:101` — añade `register_error_handlers(server.app)`
  tras construir el server. El handler mapea `ValidationError → 400`,
  `ResourceNotFoundError → 404`, resto `ApplicationError → 500` con la
  forma canónica `{error, code?, hint?, details?}`. Antes server.py no
  registraba un exception handler explícito para `ApplicationError`, así
  que esto endurece el contrato pero **no rompe** ninguna ruta (las que ya
  capturaban manualmente siguen devolviendo `_json_error(...)` directamente).
  Comprobado: integration test `tests/integration/test_http_transport.py`
  (que construye via `create_fastapi_app`) sigue verde.

### 2. Helpers en `apps/api/*.py` son hojas

Verificado con `Grep` sobre los 4 archivos:

- `apps/api/admin_auth.py:5-18` — stdlib (`logging`, `secrets`,
  `dataclasses`), `fastapi`, `shared.observability`, y `apps.api.error_handlers`
  (otro helper hoja). Sin imports de `services/`, `application/`,
  `repositories/`, `core/`, `domain/`, `modules/`.
- `apps/api/error_handlers.py:5-16` — stdlib + `fastapi` + `shared.errors`.
- `apps/api/logging_middleware.py:5-13` — stdlib + `fastapi` +
  `shared.observability`.
- `apps/api/range_response.py:5-10` — stdlib + `fastapi` solamente.

Cumple la regla: helpers de transport sin lógica de negocio embebida.

### 3. `services/transport/http/server.py` no contiene código duplicado

Verificado con `Grep`:
- No queda `def _format_client`, `def _extract_bearer_token`,
  `def _sanitize_headers_for_logging`, `def _decode_body_for_logging`,
  `def _redact_sensitive_json_values`, `def _extract_response_body`,
  `def _rebuild_request_with_body`, `def _build_range_response`,
  `class _AdminAccessPolicy`, `_VIDEO_STREAM_CHUNK_SIZE = `,
  `_SENSITIVE_HEADER_NAMES = `, `_SENSITIVE_BODY_FIELDS = `,
  `def _json_error`, ni `async def persist_http_traffic` en server.py.
- Todos esos símbolos llegan vía
  `services/transport/http/server.py:87-103` (imports `from apps.api.*`).
- Detalle menor: `register_error_handlers` se importa en server.py:93 pero
  no se usa allí (solo en `app_factory.py:101`). Es un import muerto, pero
  no afecta el comportamiento ni la corrección. No bloquea aprobación.

### 4. Tests añadidos, no quitados

- Baseline previa: 116 tests.
- Nueva cuenta: 146 tests (`./init.sh` paso 6: `146 passed in 52.77s`).
- Delta: +30 tests, todos en `tests/unit/apps_api/`.

### 5. `tests/unit/apps_api/` cubre los casos pedidos

- `tests/unit/apps_api/test_admin_auth.py` (9 tests):
  - feliz path (línea 46-59), sin auth (línea 61-74),
    token inválido (línea 76-89), API deshabilitada → 404
    (línea 91-104), no configurada → 503 (línea 106-119),
    bypass para testing (línea 121-131),
    constant-time prefix-match (línea 133-150).
- `tests/unit/apps_api/test_error_handlers.py` (6 tests):
  - `json_error` shape mínima y completa (línea 60-81),
    `ValidationError → 400` (línea 85-96),
    `ResourceNotFoundError → 404` (línea 98-105),
    `PipelineError → 500` con stage/retryable/external_trace_id
    (línea 107-116), `ApplicationError` plano → 500
    (línea 118-125).
- `tests/unit/apps_api/test_range_response.py` (8 tests):
  - sin Range → 200 (línea 34-40), single range 206 (línea 42-52),
    open-ended `bytes=4090-` (línea 54-58),
    suffix `bytes=-100` (línea 60-68),
    rango fuera de rango → 416 (línea 70-77),
    rango malformado → 416 (línea 79-82),
    multipart con tres ranges (línea 84-114),
    Content-Length consistente con body multipart (línea 116-126).
- `tests/unit/apps_api/test_logging_middleware.py` (7 tests):
  - `sanitize_headers_for_logging` redacta Authorization (línea 19-29),
    `decode_body_for_logging` redacta JSON secret keys (línea 32-47),
    middleware asigna `request_id` (línea 76-81),
    eventos `http.request` y `http.response` con campos esperados
    + Authorization redactado + body redactado (línea 83-127).

### 6. Sin print/TODO/_NoopDispatcher nuevo/router fantasma

- `Grep print(` sobre `apps/api/`: única ocurrencia es
  `apps/api/main.py:92` (`--check` CLI output, pre-existente, no debug).
- `Grep TODO|FIXME|XXX` sobre `apps/api/` y `tests/unit/apps_api/`:
  cero matches.
- `_NoopDispatcher` sigue donde estaba (`apps/api/app_factory.py:37-57`),
  no se introduce uno nuevo. La feature 16 lo eliminará.
- No se añade ningún router: solo `register_error_handlers(server.app)` en
  app_factory tras construir `WordPressWebhookServer`.

### 7. `./init.sh` verde (ejecutado por el reviewer)

```
[OK]    apps.api --check verde
[OK]    apps.worker --check verde
146 passed in 52.77s
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Único warning: paso 4 reporta 29 archivos legacy modificados en 24h —
mayoría son `__pycache__/`; los cambios reales en `services/...` son los
del compat shim de feature 1 (consistente con lo descrito en el informe).

## Checkpoints

- C1: [x] — `./init.sh` exit 0; archivos del arnés presentes.
- C2: [x] — feature 1 sigue `in_progress` en `feature_list.json:35`,
  `progress/current.md` describe la sesión activa.
- C3: [x] — Helpers en `apps/api/` solo importan de stdlib/shared/fastapi
  o de otro helper hoja (`error_handlers` desde `admin_auth`). Ningún
  módulo nuevo en `modules/`. No hay nuevas dependencias prohibidas.
  Compat shim en server.py es el único cambio en directorio legacy y solo
  re-exporta — no añade lógica nueva.
- C4: [x] — `tests/unit/apps_api/` cubre los 4 helpers con 30 tests.
  146 passed total. `apps.api --check` y `apps.worker --check` exit 0.
- C5: [x] — No se modificó `shared/db/orm.py` ni se añadió migración
  (la feature no toca schema; es scaffolding HTTP).
- C6: [x] — Sin archivos sospechosos sin trackear, sin `print()` de debug,
  sin TODOs sin contexto. `feature_list.json` refleja el estado correcto
  (in_progress; el leader marca `done` tras esta review).

## Cambios requeridos

Ninguno bloqueante. Observación menor (no requerida para approval, pero
útil tenerla en cuenta cuando se haga la feature 9
`retire_wordpress_webhook_server`):

- `services/transport/http/server.py:93` importa
  `register_error_handlers` pero no lo usa allí (solo
  `app_factory.py:101` lo invoca). Se puede limpiar al borrar server.py
  en feature 9.
