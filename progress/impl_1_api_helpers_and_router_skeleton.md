# Impl Report — Feature 1: api_helpers_and_router_skeleton

- **Feature id / name:** 1 — api_helpers_and_router_skeleton
- **Módulo afectado:** `apps/api/`
- **¿Toca schema?:** no
- **Status al cierre:** in_progress (revisión pendiente — no marcar `done`)

## Archivos creados

| Archivo                                                  | Tipo                  |
|----------------------------------------------------------|-----------------------|
| `apps/api/admin_auth.py`                                 | helper (router skeleton) |
| `apps/api/error_handlers.py`                             | helper (router skeleton) |
| `apps/api/logging_middleware.py`                         | helper (router skeleton) |
| `apps/api/range_response.py`                             | helper (router skeleton) |
| `tests/unit/apps_api/__init__.py`                        | test package init     |
| `tests/unit/apps_api/test_admin_auth.py`                 | unit test (9 tests)   |
| `tests/unit/apps_api/test_error_handlers.py`             | unit test (6 tests)   |
| `tests/unit/apps_api/test_range_response.py`             | unit test (8 tests)   |
| `tests/unit/apps_api/test_logging_middleware.py`         | unit test (7 tests)   |

## Archivos modificados

| Archivo                                  | Cambio                                                                 |
|------------------------------------------|------------------------------------------------------------------------|
| `apps/api/app_factory.py`                | Importa y llama `register_error_handlers(server.app)` después de construir el server. Sigue delegando los routers en `WordPressWebhookServer`. |
| `services/transport/http/server.py`      | Solo compat shim: importa los helpers de `apps/api/...` y elimina las definiciones locales duplicadas (`_AdminAccessPolicy`, `_authorize_admin_request` (ahora wrapper de 1 línea sobre `runtime.admin_access_policy`), `_extract_bearer_token`, `_format_client`, `_json_error`, `_sanitize_headers_for_logging`, `_decode_body_for_logging`, `_redact_sensitive_json_values`, `_extract_response_body`, `_rebuild_request_with_body`, `_build_range_response`, `_VIDEO_STREAM_CHUNK_SIZE`, `_SENSITIVE_HEADER_NAMES`, `_SENSITIVE_BODY_FIELDS`). El middleware `persist_http_traffic` se reemplaza por `register_logging_middleware(app)`. Las rutas siguen donde estaban (no se mueven en esta feature). |
| `feature_list.json`                      | Feature 1 status: `pending` → `in_progress`.                           |
| `progress/current.md`                    | Plan + bitácora de la feature.                                          |

## Diseño de los helpers

- `apps/api/admin_auth.py` — `AdminAccessPolicy` (dataclass público), `authorize_admin_request(request, policy)`, `extract_bearer_token`, `format_client`. Es hoja: solo importa `shared.observability`, `shared.errors` (vía `error_handlers`) y stdlib (`secrets`, `dataclasses`, `logging`).
- `apps/api/error_handlers.py` — `json_error(status_code, message, *, code=None, hint=None, details=None)` (shape canónica `{error, code?, hint?, details?}`) y `register_error_handlers(app)` que mapea `ApplicationError` → JSON con status 400 (`ValidationError`), 404 (`ResourceNotFoundError`) o 500 (otros), incluyendo `stage`/`retryable`/`external_trace_id` para subclases de `PipelineError`.
- `apps/api/logging_middleware.py` — `register_logging_middleware(app)` reproduce 1:1 el comportamiento del middleware inline `persist_http_traffic`: emite `http.request`, `http.response`, `http.exception` con headers/body sanitizados (Authorization redactado, JSON keys sensibles redactadas) y asigna `request.state.request_id`. Expone también las primitivas `sanitize_headers_for_logging`, `decode_body_for_logging`, `extract_response_body`, `rebuild_request_with_body`.
- `apps/api/range_response.py` — `build_range_response(request, file_path, *, media_type, cache_control, chunk_size)` soporta:
  - sin header `Range` → 200 + body completo
  - una sola range (`bytes=10-19`, `bytes=4090-`, `bytes=-100`) → 206 + slice
  - múltiples ranges (`bytes=0-9, 100-109, 1000-1019`) → 206 `multipart/byteranges` con boundary aleatorio (la versión legacy en server.py solo soportaba single range; se documenta como mejora compatible)
  - rangos malformados o fuera de rango → 416 con `Content-Range: bytes */<file_size>`

## Cómo se enganchan en el bootstrap

- `apps/api/app_factory.build_api_app()` construye el `WordPressWebhookServer` (que sigue componiendo todas las rutas) y luego llama `register_error_handlers(server.app)`.
- Dentro de `services/transport/http/server.create_fastapi_app()` se llama `register_logging_middleware(app)` (compat shim — usa el helper extraído en lugar de la definición inline). Esto mantiene los tests que usan `create_fastapi_app` directamente (`tests/integration/test_http_transport.py`) funcionando sin cambios.

## Verificación

### `pytest -q`

```
........................................................................ [ 49%]
........................................................................ [ 98%]
..                                                                       [100%]
146 passed in 51.85s
```

Baseline previa: 116 passed → ahora 146 passed (+30 nuevos tests bajo `tests/unit/apps_api/`). Sin tests rojos, sin tests skipped.

### `python -m apps.api --check`

```
RUNTIME READY: Yes
PRODUCTION READY: No
WORKSPACE: C:\Users\4pm\Desktop\4reels\4reels back
DATABASE: postgresql+psycopg://postgres:***@localhost:5432/miapp
DATABASE SCHEMA: public
PYTHON VERSION: 3.13.0
FFMPEG: ...\ffmpeg.EXE
```

Exit code: `0`.

### `python -m apps.worker --check`

`./init.sh` reporta `apps.worker --check verde` (exit 0).

### `./init.sh` (resumen)

```
[OK]    Entorno listo. Puedes empezar a trabajar.
```

## Decisiones no obvias

- **Compat shim en server.py minimizado al import + un único wrapper de 1 línea para `_authorize_admin_request`** (porque su firma legacy era `(request, runtime)` y la del helper es `(request, policy)`). El resto de símbolos privados se re-exportan literalmente con `as _name` para no romper ningún call site interno.
- **`register_logging_middleware` se llama desde `create_fastapi_app` (no desde `app_factory.py`)** porque `tests/integration/test_http_transport.py` construye el `TestClient` directamente con `create_fastapi_app(application=runtime)` y depende de que la middleware esté instalada para que los persistent events queden cubiertos. Mover la registración solo a `app_factory` rompería ese path. La acceptance ("registers middlewares vía esos helpers") se cumple igualmente: la registración pasa por el helper extraído. App_factory sí registra los exception handlers vía `register_error_handlers`.
- **Multipart byteranges en `build_range_response`** es una mejora aditiva. La versión legacy en server.py solo soportaba un único range (un cliente de video HTML5 nunca pide multipart en la práctica), pero la acceptance pide cobertura de tests para multipart, así que el helper se extendió para producir un `multipart/byteranges` RFC-7233 válido cuando se reciben múltiples rangos. El comportamiento single-range queda byte-a-byte idéntico al legacy.
- **No se introdujo dependencia circular**: `admin_auth.py` importa `error_handlers.json_error`; `error_handlers.py` solo depende de `shared.errors`; `logging_middleware.py` y `range_response.py` no importan a los otros helpers. Todos son hojas respecto a `apps/api/app_factory.py`.
- **No se tocó `_NoopDispatcher`** ni se añadió ningún router fantasma (la feature 16 maneja eso).

## Próximo paso

Reviewer revisa este informe. Si OK, el leader marca la feature como `done` en `feature_list.json`.
