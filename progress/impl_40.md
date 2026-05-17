# impl_40 — manual_reel_regenerate_endpoint

**Feature 40** — `POST /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/regenerate`.

Implementer: Claude (rol implementer lanzado por leader).
Inicio: 2026-05-16. Estado en `feature_list.json`: `in_progress` (NO marcado `done`; pendiente review).

---

## 1. Use case `mode` parameter design + new exception classes

`RegenerateReelUseCase.execute` ahora acepta dos kwargs nuevos con defaults retrocompatibles:

```python
def execute(
    self,
    *,
    uow: DatabaseUnitOfWork,
    agency_id: str,
    site_id: str,
    source_property_id: int,
    mode: RegenerateMode = "approve_and_regenerate",   # NEW
    manual_reason: str | None = None,                  # NEW
) -> RegenerateReelResult: ...
```

- `RegenerateMode = Literal["approve_and_regenerate", "manual_only"]`.
- **Default `"approve_and_regenerate"`** preserva los callers existentes (approve handler en `admin_reels_router.py:~378-440` sigue sin pasar `mode`, y se comporta exactamente igual). Cero cambios de contrato en feature 25 / 35 / 36 / 37.

**Comportamiento por modo:**

| Paso del flujo | `approve_and_regenerate` | `manual_only` |
|---|---|---|
| Pre-check `publish_status=='published'` | no se evalúa | **raise `RegeneratePublishedForbidden`** |
| Pre-check `find_active_job_for_property` | no se evalúa (lo evalúa la rama idempotent-replay más abajo) | **raise `RegenerateAlreadyInFlight`** |
| `update_workflow_state('approved')` | sí | **NO** |
| `update_publish_status('pending_publish')` | sí | **NO** |
| Prereq missing branch (no GHL / no raw payload) | 200 con `publish_enqueued=False, reason='PUBLISH_PREREQUISITES_MISSING'` | idem |
| Idempotent-replay branch (active job) | sí (replay con `idempotent_replay=True`) | nunca se ejecuta (ya raised arriba) |
| Enqueue nuevo job | sí | sí |
| `publish_context_json.regenerate_mode` | ausente | `"manual_only"` |
| `publish_context_json.manual_reason` | ausente | `reason` (string) o `null` |
| `result.queued_at` | nuevo: `now.isoformat()` (poblado siempre que se enqueua) | idem |

**Dos clases de error nuevas en `modules/reels/application/use_cases/regenerate_reel.py`:**

```python
class RegeneratePublishedForbidden(ApplicationError):
    code = "REGENERATE_PUBLISHED_FORBIDDEN"
    # context: agency_id, site_id, source_property_id, publish_status

class RegenerateAlreadyInFlight(ApplicationError):
    code = "REGENERATE_ALREADY_IN_FLIGHT"
    # context: agency_id, site_id, source_property_id, job_id
```

Patrón calcado de `ReelPhotosOverrideLockedError` (feature 35): `ApplicationError` subclase con `self.code` asignado en `__init__`, mensaje natural en el body de `super().__init__`. Las excepciones NO heredan de `PipelineError` (no necesitan `stage` / `retryable` / `external_trace_id`) — el router las mapea a 409 directamente, sin pasar por `_application_error_response`.

**Decisión clave — conflict pre-check dentro del use case, no en el router**: el leader lo pidió explícitamente para que la lógica viva en el lugar que también ejecutarían futuros callers. Se reúsa `uow.delivery.jobs.find_active_job_for_property(kind="reel_publish")` (ya existente, lo usaba la rama de idempotent-replay del approve). No hay SQL duplicado.

---

## 2. HTTP contract implementado

### Endpoint

`POST /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/regenerate`

**Body** (opcional — `{}` y body vacío se aceptan):
```json
{ "reason": "optional string up to 500 chars" }
```

`ReelManualRegeneratePayload` (`modules/reels/transport/payloads/admin_reels.py`):
- `extra='forbid'`.
- `reason: str | None = None`, `max_length=500`.

### Responses

**200 OK — happy path**:
```json
{
  "render_status": "pending",
  "job_id": "<uuid>",
  "queued_at": "2026-05-16T22:00:00.000000+00:00"
}
```

**200 OK — prerequisites missing** (no GHL connection / no raw payload, paralelo al approve flow):
```json
{
  "render_status": "pending",
  "job_id": null,
  "queued_at": null,
  "publish_enqueued": false,
  "reason": "PUBLISH_PREREQUISITES_MISSING",
  "hint": "..."
}
```

**404 — reel no encontrado**: serializado por `_resource_not_found_response` (shape canónica del project).

**409 REGENERATE_PUBLISHED_FORBIDDEN**:
```json
{
  "error": "REGENERATE_PUBLISHED_FORBIDDEN",
  "detail": "Cannot re-render a reel that has already been published."
}
```

**409 REGENERATE_ALREADY_IN_FLIGHT**:
```json
{
  "error": "REGENERATE_ALREADY_IN_FLIGHT",
  "detail": "A render is already in progress for this reel. Wait for it to finish."
}
```

**Nota de divergencia respecto a la convención del project:** la shape de error pedida por el leader (`{error: CODE, detail: ...}`) no coincide con la canónica `json_error` del repo (`{error: message, code: CODE, hint, details}`). El router emite el body literal pedido por el leader, vía `JSONResponse(status_code=409, content=...)` directo, sin pasar por `json_error`. Esto se mantuvo deliberadamente por instrucción explícita del leader.

**Body inválido (extra field, reason >500 chars):** 422 `INVALID_REGENERATE_PAYLOAD` por la shape canónica `json_error` (no es uno de los códigos explícitos del leader, lo dejo como código del project para shapes mal formadas; alternativa habría sido convertir cada `ValidationError` de Pydantic en 422 separado, pero el leader no especificó comportamiento para body malformado).

**Autorización:** `authorize_admin_request(...)` como primera línea (patrón canónico de `docs/conventions.md §Auth en /v1/admin/*`).

---

## 3. Archivos tocados

### Producción

| Archivo | Tipo | Cambio |
|---|---|---|
| `modules/reels/application/use_cases/regenerate_reel.py` | use case | + parámetros `mode` / `manual_reason`, + 2 excepciones (`RegeneratePublishedForbidden`, `RegenerateAlreadyInFlight`), + `RegenerateMode` Literal, + campo `queued_at` en `RegenerateReelResult`, + `regenerate_mode` y `manual_reason` en `publish_context` cuando `mode='manual_only'`. Default del kwarg preserva todos los callers. |
| `modules/reels/transport/payloads/admin_reels.py` | payload | + clase `ReelManualRegeneratePayload(reason: str \| None, extra='forbid', max_length=500)`. + entrada en `__all__`. |
| `modules/reels/transport/http/admin_reels_router.py` | router | + import de las 2 excepciones nuevas + import de `ReelManualRegeneratePayload`. + handler `regenerate_admin_agency_reel` (POST `.../regenerate`). |

### Tests

| Archivo | Tipo | Cambio |
|---|---|---|
| `tests/integration/reels/test_regenerate_reel_manual.py` | integration test (nuevo) | 8 tests (ver §4). |

### NO se tocó

- Schema (sin alembic).
- `apps/api/app_factory.py` (la firma de `create_admin_reels_router` no cambió).
- `modules/reels/application/use_cases/update_reel_photos_override.py` ni los otros override use cases (features 35/36/37 intactas).
- `modules/delivery/infrastructure/job_repository.py` (se reúsa `find_active_job_for_property` ya existente).
- `docs/API.md`, `docs/http_surface.md`, `docs/openapi.json` (follow-up doc-debt heredado de features 33/34; no es parte del scope obligatorio del leader y la convención post-feature-37 ha sido regenerar bajo demanda).

---

## 4. Tests añadidos

Archivo: `tests/integration/reels/test_regenerate_reel_manual.py` — **8 tests, todos PASSED**.

| Test | Cubre |
|---|---|
| `test_regenerate_manual_enqueues_job_without_touching_workflow_state` | Happy path completa: 200, body con `render_status='pending', job_id, queued_at`; nuevo job `status='queued', kind='reel_publish'`; `workflow_state` y `publish_status` **invariantes antes/después**; `publish_context_json.regenerate_mode='manual_only'` y `manual_reason='Frontend manual button'` persisten en el job. |
| `test_regenerate_manual_accepts_empty_body` | POST con `{}` retorna 200 (body opcional). |
| `test_regenerate_manual_returns_404_for_unknown_reel` | `(site_id, 9999)` inexistente → 404 (vía `_resource_not_found_response`). |
| `test_regenerate_manual_returns_409_when_already_published` | reel con `publish_status='published'` → 409 con body literal `{"error": "REGENERATE_PUBLISHED_FORBIDDEN", "detail": "..."}`. |
| `test_regenerate_manual_returns_409_when_active_job_already_exists` | job en `status='processing'` para la misma property → 409 `REGENERATE_ALREADY_IN_FLIGHT`; sanity-check de que el job pre-existente sigue intacto. |
| `test_regenerate_manual_returns_409_when_queued_job_already_exists` | job en `status='queued'` también gatilla 409 (mismo path; espejo del comportamiento idempotente de approve). |
| `test_regenerate_manual_preserves_photos_override_on_reel` | reel con `photos_override` JSONB no-null pre-seedeado → tras POST, el override sigue en BBDD y el use case lo ve por `uow.reels.states.get(...)` (donde lo lee el ingest para hidratar `PropertyContext.photos_override` en feature 35). |
| `test_approve_handler_still_replays_queued_job_after_mode_extension` | **regresión guard de feature 25**: el approve handler con job `queued` pre-existente debe devolver `publish_enqueued=True, idempotent_replay=true, job_id == old_job_id, event_id == old_event_id` — pese a que el use case ganó el parámetro `mode`. |

No se añadieron unit tests del conflict-pre-check helper porque el leader habilitó la opción de extraerlo o no ("Unit tests for the conflict pre-check helper if extracted as a pure function"); mantuve el pre-check inline en el use case (es trivial: dos llamadas al UoW + raise) y dejé que los tests integration cubran ambas ramas extremo-a-extremo. Si el reviewer quiere unit tests puros, sería trivial extraer `_check_manual_regenerate_preconditions(uow, ...)`.

---

## 5. Verificación

### `bash ./init.sh` (1050 passed = 1042 baseline + 8 nuevos, mismos 3 known-flaky)

```
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
...
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 1050 passed, 14 warnings in 573.50s (0:09:33)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Los 3 fallos son la baseline pre-existente flagueada en `progress/current.md` (features 33-39 los han venido reportando: `test_http_surface_contract.py` por mismatch con el front, 2 en `test_http_transport.py` por el state del dispatcher).

### Subset del leader

```
$ .venv/bin/python -m pytest \
    tests/integration/reels/test_regenerate_reel_manual.py \
    tests/integration/reels/test_reel_photos_override.py \
    tests/integration/reels/test_reel_subtitles_override.py \
    tests/integration/reels/test_admin_reels_music_override.py -q -v

47 passed in 73.69s (0:01:13)
```

(8 nuevos + 13 photos override + 17 subtitles override + 9 music override.)

### Readiness checks

- `.venv/bin/python -m apps.api --check` → `RUNTIME READY: Yes`, exit 0.
- `.venv/bin/python -m apps.worker --check` → `Worker --check OK`, exit 0.

### Tests adyacentes (regresión local)

```
$ .venv/bin/python -m pytest tests/integration/reels/ tests/unit/reels/ -q
234 passed in 209.59s (0:03:29)
```

---

## 6. Open items para el reviewer

1. **Conflict-detection SQL — ¿reusa repo o one-off?** **Reusa el repo.** El pre-check llama
   `uow.delivery.jobs.find_active_job_for_property(external_source_id, property_id, kind="reel_publish")`,
   que es exactamente el método que la rama idempotent-replay del approve flow ya usaba (`regenerate_reel.py:~321` antes del cambio, ahora `~414` post-edit). Cero SQL nuevo. Cero queries duplicadas. Si el reviewer prefiere una variante separada (p. ej. `count_active_jobs_for_property`) lo dice y la extraigo, pero la actual reúsa el contrato existente y devuelve los datos suficientes para construir el contexto del 409 (`job_id`).

2. **Shape del 409 (`{error, detail}`) vs canónica del project (`{error, code, hint, details}`)**: la implementación honra LITERALMENTE el contrato del leader (`Body: {"error": "REGENERATE_PUBLISHED_FORBIDDEN", "detail": "..."}`). Es una divergencia consciente respecto al resto del repo, que sí responde con `{error: message, code: CODE, ...}`. Si el reviewer quiere homogeneizar, el cambio es de 2 líneas en el router; en ese caso también los tests cambiarían a `body["code"]`. Pendiente decisión de homogeneización vs literal-contract.

3. **`POST .../regenerate` con body Pydantic-mal-formado** (extra field, reason >500): hoy devuelve 422 `INVALID_REGENERATE_PAYLOAD` (código inventado por mí — el leader sólo nombró los 2 códigos 409). Si el reviewer prefiere otro código (`VALIDATION_ERROR`, `INVALID_PAYLOAD`, etc.) lo cambio.

4. **`scheduled_at` en la respuesta**: el leader pidió `{render_status, job_id, queued_at}` — NO incluí `scheduled_at` aunque el use case lo computa. La razón: para un `manual_only` re-render la noción de "ventana de publicación" sigue computándose internamente (porque el `publish_context.scheduled_at` se persiste y será respetado por el worker), pero el endpoint manual no lo expone en la response porque el leader no lo listó. Si el reviewer quiere exponerlo, basta añadir `"scheduled_at": result.scheduled_at` al body.

5. **`docs/API.md` + `docs/http_surface.md` + `docs/openapi.json`**: NO se regeneraron. Es follow-up doc-debt acumulado de las últimas features (33/34 también lo dejaron pendiente; 37 sí los regeneró). Si el reviewer lo exige, se ejecuta `.venv/bin/python scripts/generate_http_surface.py --write` y se añade sección en `docs/API.md` siguiendo el patrón de feature 37. Recomendación: hacerlo todo junto en una pasada post-review (incluyendo el doc-debt acumulado).

6. **Sin unit test puro del pre-check helper**: el leader lo marcó como "if extracted as a pure function". Mantuve el pre-check inline (4 líneas dentro del `execute`). Si el reviewer prefiere extracción + unit test, sería trivial:

   ```python
   def _check_manual_preconditions(uow, *, agency_id, site_id, property_id, state):
       if state.publish_status == "published": raise ...
       active = uow.delivery.jobs.find_active_job_for_property(...)
       if active is not None: raise ...
   ```

---

## 7. Sample curl contra `:8001`

> Asumiendo: agency con id `<AGENCY_ID>`, site `<SITE>` (lowercase), property con `source_property_id=42`, BBDD seedeada con un reel completed+needs-approval.

### Happy path

```bash
curl -X POST \
  "http://127.0.0.1:8001/v1/admin/agencies/<AGENCY_ID>/reels/<SITE>/42/regenerate" \
  -H "Authorization: Bearer <ADMIN_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"reason": "FE manual button — debug investigation"}'
```

Respuesta esperada (200):
```json
{
  "render_status": "pending",
  "job_id": "ab12-...-cd34",
  "queued_at": "2026-05-16T22:30:00.123456+00:00"
}
```

### Body vacío (también válido)

```bash
curl -X POST \
  "http://127.0.0.1:8001/v1/admin/agencies/<AGENCY_ID>/reels/<SITE>/42/regenerate" \
  -H "Authorization: Bearer <ADMIN_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 409 — publish_status='published'

```bash
# Si el reel ya está publicado:
curl -X POST \
  "http://127.0.0.1:8001/v1/admin/agencies/<AGENCY_ID>/reels/<SITE>/42/regenerate" \
  -H "Authorization: Bearer <ADMIN_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'
# → HTTP 409
# {"error":"REGENERATE_PUBLISHED_FORBIDDEN","detail":"Cannot re-render a reel that has already been published."}
```

### 409 — job en flight

```bash
# Justo después de un POST /approve (worker aún no claimed el job):
curl -X POST \
  "http://127.0.0.1:8001/v1/admin/agencies/<AGENCY_ID>/reels/<SITE>/42/regenerate" \
  -H "Authorization: Bearer <ADMIN_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'
# → HTTP 409
# {"error":"REGENERATE_ALREADY_IN_FLIGHT","detail":"A render is already in progress for this reel. Wait for it to finish."}
```

### Verificación post-POST contra la BBDD :8001

```sql
-- workflow_state / publish_status invariantes
SELECT workflow_state, publish_status FROM reels
WHERE external_source_id = '<SITE>' AND source_property_id = 42;

-- nuevo job encolado con discriminador manual_only
SELECT job_id, status, kind,
       publish_context_json->>'regenerate_mode' AS mode,
       publish_context_json->>'manual_reason'   AS reason
FROM jobs
WHERE external_source_id = '<SITE>' AND property_id = 42
ORDER BY created_at DESC
LIMIT 1;
```
