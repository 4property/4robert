# Implementer report — Unrestricted intro/outro uploads

Date: 2026-05-20
Scope: Eliminar todas las restricciones de tamaño (50 MB) y duración
(`[1, 10]` s) que el backend aplicaba a los uploads de intro/outro de
agencia (features 33 y 34, ambas `done`). Mantener validación de MIME
y "body no vacío". Mantener la derivación de duración vía `ffprobe` y
su persistencia en `agency_intro_outro_assets.duration_seconds` —
ahora es solo informativa.

Sin cambios de schema → sin migración Alembic.

## Decisión

**Opción A** (recomendada por el leader): borrado completo de
constantes, funciones y parámetros obsoletos. Las funciones
`validate_*_duration` desaparecen; el parámetro `max_upload_bytes`
desaparece de los use cases y los routers; los códigos HTTP
`*_FILE_TOO_LARGE` y `*_INVALID_DURATION` ya no se emiten.

No quedaba ningún call-site externo (todos los consumidores estaban en
tests del propio repo), así que la limpieza dura es segura.

## Archivos modificados

### Producción

- `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/upload_outro_video.py`
  - Borradas constantes `OUTRO_MAX_UPLOAD_BYTES`,
    `OUTRO_MIN_DURATION_SECONDS`, `OUTRO_MAX_DURATION_SECONDS`.
  - Borrada función `validate_outro_duration`.
  - Eliminada la rama `len(body) > max_upload_bytes` de
    `validate_outro_upload`; eliminado el parámetro `max_upload_bytes`.
  - Eliminado `max_upload_bytes` del constructor de
    `UploadOutroVideoUseCase`.
  - Eliminada la llamada a `validate_outro_duration(duration)` en
    `execute()` (junto con el bloque `try/except` que limpiaba el blob
    huérfano en caso de duración fuera de rango).
  - `__all__` y docstring del módulo actualizados.
- `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/upload_intro_video.py`
  - Espejo simétrico: mismas borraduras (`INTRO_MAX_UPLOAD_BYTES`,
    `INTRO_MIN_DURATION_SECONDS`, `INTRO_MAX_DURATION_SECONDS`,
    `validate_intro_duration`), mismo cleanup en
    `UploadIntroVideoUseCase`.
- `/opt/projects/4Reels-Backend/modules/configuration/transport/http/outro_router.py`
  - Eliminado import de `OUTRO_MAX_UPLOAD_BYTES`.
  - Eliminado parámetro `max_upload_bytes` de `create_outro_router`.
  - Eliminado el guard de tamaño `if len(body) > max_upload_bytes`
    (early 413).
  - El handler de `ValidationError` ya no necesita ramificar a 413; se
    devuelve siempre 422 (las únicas `ValidationError` que puede emitir
    el use case son ahora 422).
  - Docstring/`summary`/`description` del endpoint actualizados — sin
    mencionar 50 MB ni 1-10s.
- `/opt/projects/4Reels-Backend/modules/configuration/transport/http/intro_router.py`
  - Espejo simétrico.

### Tests

- `/opt/projects/4Reels-Backend/tests/unit/configuration/test_outro_validator.py`
  - Eliminados los tests `test_validator_rejects_payload_over_50mb`,
    `test_validate_duration_accepts_range_extremes`,
    `test_validate_duration_rejects_zero_seconds`,
    `test_validate_duration_rejects_above_max`,
    `test_validate_duration_rejects_negative_value`.
  - Añadido `test_validator_accepts_payload_well_over_50mb` (60 MB de
    bytes pasan la validación).
  - Docstring del módulo actualizado.
- `/opt/projects/4Reels-Backend/tests/unit/configuration/test_intro_validator.py`
  - Espejo simétrico.
- `/opt/projects/4Reels-Backend/tests/integration/configuration/test_outro_router.py`
  - `test_outro_upload_rejects_payload_over_50mb_with_413` →
    reemplazado por `test_outro_upload_accepts_payload_over_50mb`
    (50 MB + 16 B con un `ffprobe_runner` stubbeado que devuelve 60s;
    inyecta el use case vía el parámetro `upload_outro_video` del
    router para no depender del comportamiento de ffprobe sobre bytes
    sintéticos).
  - `test_outro_upload_rejects_duration_above_10_seconds` →
    reemplazado por `test_outro_upload_accepts_duration_above_10_seconds`
    (usa el fixture real `long_outro_15s.mp4` y asserta 200 +
    `outro_duration_seconds == 15` + blob persistido).
  - Docstring del módulo actualizado.
- `/opt/projects/4Reels-Backend/tests/integration/configuration/test_intro_router.py`
  - Espejo simétrico (incluye el flip de `test_intro_upload_rejects_*`
    a `_accepts_*`).

### Documentación

- `/opt/projects/4Reels-Backend/docs/API.md`
  - Secciones "Outro video (feature 33)" e "Intro video (feature 34)"
    actualizadas: el campo "Maximum payload size" pasa a
    "unrestricted" y se documenta que la duración deja de validarse
    (`ffprobe` sigue invocándose). Las tablas de error reference
    pierden las filas `*_FILE_TOO_LARGE` (413) y `*_INVALID_DURATION`
    (422), y ganan `*_FILE_EMPTY` (422).
- `/opt/projects/4Reels-Backend/docs/openapi.json` y
  `/opt/projects/4Reels-Backend/docs/http_surface.md` — regenerados
  con `scripts/generate_http_surface.py --write`; los strings
  "1-10s", "<=50MB", "FILE_TOO_LARGE" y "INVALID_DURATION" ya no
  aparecen.

## Verificación

### Pytest del módulo configuración

```
.venv/bin/python -m pytest -q tests/unit/configuration tests/integration/configuration --no-header
```

Resultado: **273 passed in 205.38s**. Cero fallos. Incluye los nuevos
tests `test_*_upload_accepts_duration_above_10_seconds`,
`test_*_upload_accepts_payload_over_50mb` (unit + integration intro/outro).

### Subset de validadores (rápido)

```
.venv/bin/python -m pytest -q tests/unit/configuration/test_outro_validator.py tests/unit/configuration/test_intro_validator.py --no-header
```

Resultado: **12 passed in 0.86s**.

### Smoke checks

```
.venv/bin/python -m apps.api --check     # OK
.venv/bin/python -m apps.worker --check  # OK
```

### Pytest completo del repo

```
.venv/bin/python -m pytest -q --no-header
```

Resultado: **1117 passed, 3 failed, 1 deselected** en 600.46 s. Los 3
fallos son **pre-existentes y no relacionados con esta tarea**:

- `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
  — env var `FRONTEND_REPO_ROOT` no configurada en este host; el path
  por defecto sigue siendo el de Windows (`C:/Users/4pm/...`). No hay
  forma de que esto dependa de intro/outro.
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_*` (2)
  — los tests asertan el shape antiguo del payload de `/health`
  (`{status, dispatcher_accepting_jobs}`), mientras que
  `apps/api/health_router.py:125` ya añade un tercer campo
  `configured_worker_count`. Hay otro test (`tests/integration/apps_api/test_health_router.py:39-72`)
  que sí incluye `configured_worker_count: 3`, así que la incoherencia
  es entre dos baterías de tests del propio repo. No tocada por esta
  tarea.

Estos tres fallos eran rojos antes de aplicar los cambios.

## Verificación manual de los call-sites borrados

```
grep -rn -E "OUTRO_MAX_UPLOAD_BYTES|INTRO_MAX_UPLOAD_BYTES|OUTRO_MAX_DURATION_SECONDS|OUTRO_MIN_DURATION_SECONDS|INTRO_MAX_DURATION_SECONDS|INTRO_MIN_DURATION_SECONDS|validate_outro_duration|validate_intro_duration|OUTRO_INVALID_DURATION|OUTRO_FILE_TOO_LARGE|INTRO_INVALID_DURATION|INTRO_FILE_TOO_LARGE" --include="*.py"
```

Resultado: ninguna coincidencia en código fuente ni tests. Los únicos
hits residuales viven en `feature_list.json` y `progress/*.md`, que son
**registros históricos** de las features 33/34 cuando se cerraron y
que el protocolo manda no reescribir.

## Notas para el reviewer

- `*_FILE_EMPTY` (422) se mantiene como guardia mínima para detectar
  multipart fields vacíos. Es la única validación de "tamaño" que
  queda viva en el use case.
- La duración sigue persistiéndose en
  `agency_intro_outro_assets.duration_seconds` y aparece en
  `*_duration_seconds` del payload de respuesta y de
  `GET /defaults`. El frontend puede seguir mostrándola.
- `ffprobe` sigue siendo bloqueante: si la binaria no está disponible o
  no consigue parsear el upload, se devuelve 422
  `OUTRO_PROBE_UNAVAILABLE`/`OUTRO_PROBE_FAILED` (o las simétricas
  intro). Esto se conserva tal cual estaba — el orphan blob se borra
  en esos paths.
- El router sigue garantizando `_safe_unlink(destination)` en los dos
  paths de error de ffprobe; al haber desaparecido el path de
  duración inválida, el bloque `try/except ValidationError` que
  envolvía a `validate_*_duration` también se borra (ya no hay nada
  que limpiar a ese nivel).
- No se ha tocado `feature_list.json` — ninguna feature se marca como
  `done`, según las reglas del protocolo.

## Resultado

Cambio listo para revisión por el reviewer. El admin SaaS puede ahora
subir intros/outros de cualquier duración y cualquier peso; el
backend solo rechaza payloads vacíos o con MIME distinto de
`video/mp4`/`video/quicktime`.
