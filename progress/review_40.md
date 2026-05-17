# Review — feature 40 (manual_reel_regenerate_endpoint)

**Veredicto:** APPROVED

Revisor: Claude (rol reviewer lanzado por leader). Fecha: 2026-05-16.

Cubre `progress/impl_40.md`. Re-verificación local sobre la rama del implementer.

---

## 1. Resumen ejecutivo

Implementación correcta. Cumple cada decisión del leader (HTTP contract literal,
modo opt-in `manual_only`, 2 excepciones nuevas mapeadas a 409, conflict
pre-check vía `find_active_job_for_property`, sin schema). El default
`mode='approve_and_regenerate'` preserva el contrato de feature 25 y la
regresión-guard así lo demuestra. Tests verdes (1050 passed = baseline
1042 + 8 nuevos; mismos 3 fallos pre-existentes en
`test_http_surface_contract.py` y `test_http_transport.py`). Readiness
checks API + worker en exit 0.

Sobre el open item del 409 body-shape: divergencia confirmada
respecto a feature 35, pero el frontend está cableado precisamente
contra la shape literal pedida por el leader (`{error: CODE, ...}`),
así que **no bloquea**. La unificación a `json_error` queda como
follow-up opcional (no-blocking nit, ver §3).

---

## 2. Auditoría por decisión del leader (file:line)

| Decisión del leader | Estado | Evidencia |
|---|---|---|
| **HTTP contract** `POST /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/regenerate` | OK | `modules/reels/transport/http/admin_reels_router.py:447-448` (`@router.post(".../regenerate")`). |
| Body `{ "reason": "optional string" }` o `{}`, Pydantic `extra='forbid'`, `reason: str \| None` | OK | `modules/reels/transport/payloads/admin_reels.py:120-142`: `class ReelManualRegeneratePayload` con `model_config = ConfigDict(extra="forbid")` y `reason: str \| None = Field(default=None, max_length=500, ...)`. El router parsea manualmente (`admin_reels_router.py:486-502`) para permitir cuerpo vacío sin que FastAPI lo marque como required. |
| **200** retorna `{render_status:"pending", job_id:"<uuid>", queued_at:"<ISO>"}` (nombres exactos) | OK | `admin_reels_router.py:565-572`. Test que comprueba las 3 claves: `tests/integration/reels/test_regenerate_reel_manual.py:160-164`. |
| `RegenerateReelUseCase.execute` gana `mode: Literal['approve_and_regenerate','manual_only'] = 'approve_and_regenerate'` | OK | `modules/reels/application/use_cases/regenerate_reel.py:55` (`RegenerateMode = Literal[...]`), `:192` (`mode: RegenerateMode = "approve_and_regenerate"`). Default preserva los callers. |
| Default preserva callers existentes (feature 25 approve flow sin pasar `mode`) | OK | El approve handler invoca el use case sin `mode` en `admin_reels_router.py:406-411`. Regresión guard del comportamiento idempotente: `tests/integration/reels/test_regenerate_reel_manual.py:522-574` (`test_approve_handler_still_replays_queued_job_after_mode_extension`), passed. |
| `mode='manual_only'` NO mute workflow_state ni publish_status | OK | El `if mode == "approve_and_regenerate":` envuelve TODO el bloque `update_workflow_state` + `update_publish_status` (`regenerate_reel.py:255-269`). Test que comprueba antes/después: `test_regenerate_reel_manual.py:142-174`. |
| 2 excepciones nuevas `RegeneratePublishedForbidden` y `RegenerateAlreadyInFlight`, subclase de `ApplicationError`, mapean a 409 | OK | `regenerate_reel.py:58-88` (`RegeneratePublishedForbidden(ApplicationError)`) y `:91-122` (`RegenerateAlreadyInFlight(ApplicationError)`). Router las captura por separado y emite 409 (`admin_reels_router.py:516-537`). Tests: `test_regenerate_reel_manual.py:254-296` y `:304-373` (más `:375-418` con `queued`). |
| Pre-check usa `find_active_job_for_property` (sin SQL ad-hoc) | OK | `regenerate_reel.py:242-253`: `uow.delivery.jobs.find_active_job_for_property(external_source_id=..., property_id=..., kind="reel_publish")`. Helper pre-existente verificado en `modules/delivery/infrastructure/job_repository.py:186`. Cero SQL nuevo. |
| Sin nuevo schema (no alembic, no ORM changes) | OK | `ls alembic/versions/` no muestra archivo nuevo: head sigue siendo `20260515_0005_reels_manifest_override.py`. `grep -r 'class.*ORM' shared/db/orm.py` no muestra columnas nuevas para `reels`. |
| Pre-check `publish_status == 'published'` → 409 `REGENERATE_PUBLISHED_FORBIDDEN` | OK | `regenerate_reel.py:234-241`. El pre-check normaliza con `.strip().lower()` antes de comparar. Test: `:254-296`. |
| Pre-check active job `queued`/`processing` → 409 `REGENERATE_ALREADY_IN_FLIGHT` | OK | `regenerate_reel.py:242-253`. El método `find_active_job_for_property` (en `job_repository.py:186`) filtra por `status IN ('queued', 'processing')`. Tests: `:304-373` (`processing`) y `:375-418` (`queued`). |
| `manual_reason` viaja en `publish_context_json` | OK | `regenerate_reel.py:405-415`. Test: `:185-187` confirma `context.get("manual_reason") == "Frontend manual button"` y `context.get("regenerate_mode") == "manual_only"`. |

---

## 3. Evaluación del 409 body-shape (open item del leader)

### Hechos verificados

- **Feature 40 emite** (`admin_reels_router.py:517-537`):
  ```json
  {"error": "REGENERATE_PUBLISHED_FORBIDDEN", "detail": "Cannot re-render a reel that has already been published."}
  ```
  Mismo patrón para `REGENERATE_ALREADY_IN_FLIGHT`. `JSONResponse(status_code=409, content=...)` directo, sin pasar por `json_error`.

- **Feature 35 emite** (`admin_reels_router.py:760-767` para `PHOTOS_OVERRIDE_LOCKED`):
  Usa `json_error(409, str(error), code=error.code, hint=..., details={"context": ...})`.
  Helper en `apps/api/error_handlers.py:21-37` produce:
  ```json
  {"error": "<message>", "code": "PHOTOS_OVERRIDE_LOCKED", "hint": "...", "details": {...}}
  ```

- **Divergencia real**: en feature 35 `error` es el mensaje y `code` es la discriminator; en feature 40 `error` es la discriminator y `detail` es el mensaje. **NO coinciden**.

### Compatibilidad frontend

Verificado leyendo `/opt/projects/4Reels-Frontend/src/features/reels/editor/RegenerateReelButton.jsx:58-67`:

```js
const status = err?.status;
const code = err?.body?.error || err?.body?.code || '';
if (status === 409 && code === 'REGENERATE_PUBLISHED_FORBIDDEN') { ... }
if (status === 409 && code === 'REGENERATE_ALREADY_IN_FLIGHT') { ... }
```

El front lee `body.error` PRIMERO (que en la shape de feature 40 ES el code). Si el back hubiera emitido la shape canónica de feature 35 (`{error: "Cannot re-render…", code: "REGENERATE_PUBLISHED_FORBIDDEN", ...}`) entonces `code = body.error = "Cannot re-render…"` y la rama `if (code === 'REGENERATE_PUBLISHED_FORBIDDEN')` jamás dispararía.

→ **El FE depende explícitamente de la shape de feature 40, no de la canónica.** El toast de error a mostrar está hardcoded en el FE (no se lee `body.detail` ni `body.message`), así que la divergencia `detail` vs `message` es invisible.

El mock backend del frontend (`/opt/projects/4Reels-Frontend/tests/support/mock-backend.js:299-320`) emite `{error: 'REGENERATE_PUBLISHED_FORBIDDEN', message: '...'}` — usa `error` para el code (compatible con feature 40) pero `message` en vez de `detail`. La key del mensaje es irrelevante en el flujo del FE porque el `RegenerateReelButton` no lo consume.

### Veredicto sobre el body-shape

- **Diverge** respecto a feature 35.
- **Front-compatible**: el FE está cableado contra la shape literal pedida por el leader (`{error: CODE, ...}`). No hay riesgo de regresión en el FE; el mock del FE también honra `{error: CODE}` como discriminator.
- **Decisión**: APROBADO. La divergencia es consciente y compatible con el FE actual. Se documenta como follow-up no bloqueante:

> **Follow-up opcional (no bloqueante):** considerar unificar las shapes 409 del repo a la canónica `json_error` (`{error: message, code: CODE}`). Si se acomete, requerirá un cambio coordinado FE (RegenerateReelButton lee `body.code` como fallback) + mock + back en una sola feature. El gasto/beneficio es marginal hoy.

---

## 4. Checkpoints

- **C1** El arnés está completo — `[x]`
  - Archivos base presentes (`AGENTS.md`, `CLAUDE.md`, `feature_list.json`, `progress/current.md`, `docs/architecture.md`, `docs/conventions.md`, `docs/verification.md`, `CHECKPOINTS.md`). `./init.sh` exit 0.
- **C2** El estado es coherente — `[x]`
  - Solo feature 40 está `in_progress`. `progress/current.md` describe la sesión activa (bloque feature 40 al final).
- **C3** El código respeta la arquitectura — `[x]`
  - Imports en `regenerate_reel.py` solo de `shared/`, `modules/configuration/.../use_cases/compute_next_publish_slot` (pre-existente, no introducido aquí) y `modules/delivery/domain`. No hay cross-module a `application/` o `infrastructure/` nuevo.
  - `modules/reels/domain/` libre de SQLAlchemy (no se tocó).
  - Repos no llaman `commit()` (grep confirmado en `modules/reels/` y `modules/delivery/`).
  - Sin código nuevo en `services/`, `application/`, `repositories/`, `core/`, `domain/` legacy.
- **C4** La verificación es real — `[x]`
  - 8 tests integration nuevos en `tests/integration/reels/test_regenerate_reel_manual.py` cubren happy + 404 + 409×2 + body vacío + override-survives + regression guard de feature 25.
  - Usan `tests/support/postgres.py` (`seed_tenant`, `seed_provider_connection`, `temporary_postgres_schema`, `temporary_workspace`). No mockean Postgres.
  - `pytest -q` → 1050 passed (+8 vs baseline 1042). `apps.api --check` + `apps.worker --check` exit 0.
- **C5** Schema y migraciones coherentes — `[x] (N/A)`
  - Sin tocar schema. Sin nueva migración. Head sigue en `20260515_0005`.
- **C6** La sesión se cerró bien — `[x] (pendiente de cierre por leader)`
  - Sin `print()` de debug visibles en los archivos tocados. Sin TODOs nuevos. Tras este APPROVED, el leader marca feature 40 → `done` en `feature_list.json` y archiva el bloque WIP de `progress/current.md`.

---

## 5. Acceptance checklist del leader

- [x] **HTTP contract** literal verificado (`{render_status, job_id, queued_at}` exact names) — `admin_reels_router.py:565-572`, test `:160-164`.
- [x] **`mode='approve_and_regenerate'`** default preserva feature 25 — regresión guard `test_approve_handler_still_replays_queued_job_after_mode_extension`, passed.
- [x] **`mode='manual_only'`** no muta workflow_state/publish_status — test `test_regenerate_manual_enqueues_job_without_touching_workflow_state` antes/después invariantes.
- [x] **2 excepciones** subclase de `ApplicationError`, ambas → 409 — `regenerate_reel.py:58-122`, router `:516-537`.
- [x] **Conflict pre-check** vía `find_active_job_for_property` — `regenerate_reel.py:242-253`, helper pre-existente en `job_repository.py:186`.
- [x] **No nuevo schema** — verificado por inspección de `alembic/versions/` y `shared/db/orm.py`.
- [x] **No `session.commit()`** en repos nuevos — N/A (no se tocaron repos).
- [x] **No legacy imports** — `./init.sh` step 4 (`0 imports legacy en apps|modules|shared|tests`).
- [x] **Inter-module rule respetado** — imports cross-module en use case son solo a `modules/configuration/.../compute_next_publish_slot` (pre-existente, también usado por `ingest_property_into_reel.py:41-42` y `update_reel_music_override.py:43-44`; no introducido por esta feature) y `modules/delivery/domain`. La composición sigue en `apps/api/app_factory.py`.
- [x] **Composición** solo en `apps/api/app_factory.py` — no se tocó `app_factory.py`; la firma de `create_admin_reels_router` no cambió.
- [x] **No test deleted / weakened** — solo se añade el archivo nuevo; tests pre-existentes intactos.

---

## 6. Re-run de verificación

### `bash ./init.sh`

```
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 1050 passed, 14 warnings in 581.79s (0:09:41)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Los 3 fallos son la baseline pre-existente flaggeada en `progress/current.md` (features 33–39 los han venido reportando). 1050 = 1042 baseline + 8 nuevos (test_regenerate_reel_manual.py).

### Subset del leader

```
$ .venv/bin/python -m pytest \
    tests/integration/reels/test_regenerate_reel_manual.py \
    tests/integration/reels/test_admin_reels_music_override.py \
    tests/integration/reels/test_reel_photos_override.py \
    tests/integration/reels/test_reel_subtitles_override.py -q
47 passed in 75.50s (0:01:15)
```

### Readiness checks

- `.venv/bin/python -m apps.api --check` → `RUNTIME READY: Yes`, exit 0.
- `.venv/bin/python -m apps.worker --check` → `Worker --check OK`, exit 0.

---

## 7. Issues encontrados

Ninguno bloqueante. Solo los siguientes follow-ups menores (no-blocking):

1. **409 body-shape divergente** respecto a la canónica `json_error` del repo. Ver §3. Decisión: aceptada por instrucción literal del leader y por compatibilidad con el FE actual. Follow-up opcional sin urgencia.

2. **No unit test puro del pre-check helper**. El leader marcó como opcional ("if extracted as a pure function"). El pre-check está inline (4 líneas en `regenerate_reel.py:234-253`); los tests integration cubren ambas ramas extremo-a-extremo. Aceptable.

3. **`docs/API.md` + `docs/http_surface.md` + `docs/openapi.json` no regenerados**. El implementer lo dejó para follow-up; ver §8.

---

## 8. Decisión sobre el doc-debt (`docs/API.md`, `docs/http_surface.md`, `docs/openapi.json`)

El implementer flaggeó el doc-debt en `impl_40.md §6.5` y lo defirió a "una pasada post-review".

**Decisión del reviewer**: **aceptable diferirlo a un follow-up dedicado**, NO bloqueante para esta PR. Razones:

- El contrato HTTP ya está documentado en la docstring del handler (`admin_reels_router.py:449-470`) y en el payload (`admin_reels.py:121-142`).
- El FE ya consume el endpoint contra el contrato correcto (verificado en §3).
- El test guard `test_frontend_api_requests_target_existing_backend_routes` ya está en rojo pre-existente desde feature 33 (es la flaky del baseline). Regenerar `docs/http_surface.md` lo haría pasar al verde para esta ruta, pero el test depende del path del FE en `FRONTEND_REPO_ROOT` y el rojo crónico no es atribuible a feature 40.
- Recomendación operativa: ejecutar `scripts/generate_http_surface.py --write` en una pasada de doc-debt que incluya también las rutas pendientes de features 33/34 (intro/outro). Mejor consolidarlo que hacer N pasadas parciales.

→ El leader marca feature 40 → `done` y abre (o anota como pendiente en `progress/current.md`) el item "doc-debt sweep" para una pasada futura.

---

## 9. Open items para el leader

1. **Decisión doc-debt**: confirmar diferimiento a follow-up (recomendado por §8). Si el leader prefiere bloquear hasta regenerar `docs/*`, hacerlo lanzando el implementer con scope "regenerate http_surface + add API.md section for feature 40 + (opcional) sweep 33/34" — sin necesidad de reabrir feature 40.

2. **Unificación de shape 409 a futuro** (opcional): si se decide, requiere PR coordinada FE/back. Sin urgencia.

3. **Sin unit test puro del pre-check helper**: aceptado tal cual (cubierto por integration). Si en el futuro el helper se extrae, añadir un unit test sería trivial.

---

## 10. Recomendación final

**APPROVED**. La implementación cumple cada decisión del leader, los tests son sólidos (especialmente el regression guard de feature 25), y la divergencia del 409 body-shape es compatible con el FE actual. El doc-debt y la unificación de shapes quedan como follow-ups no bloqueantes.

Acciones para el leader:

1. `feature_list.json` → `id: 40` → `status: "done"`.
2. Cierre del bloque feature 40 en `progress/current.md` (mover a `history.md` el resumen, o añadir línea de cierre).
3. (Opcional) abrir un follow-up para el doc-debt sweep si quiere mantener traza.
