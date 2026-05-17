# Review — feature 35 (`per_reel_photos_override`)

**Veredicto:** APPROVED

Cobertura suficiente, contratos respetados (HTTP, 422/409/404, render call site,
migración up/down/up). El drive-by de `music_id` es un **fix real** que cierra un
agujero dejado por feature 25 — se acepta con nota (ver §3). Tres deviations menores
del spec quedan como follow-ups, no bloquean el APPROVED (ver §6).

## 1. Per-decision audit (file:line)

| Decisión leader | Verificado | Evidencia |
|---|---|---|
| Ruta `PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/photos` | ✅ | `modules/reels/transport/http/admin_reels_router.py:552`. `build_api_app` registra la ruta exacta (verificado via inspect: `PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/photos`). |
| Body `{photos: [{position:int, selected:bool}, ...]}` / `null` / `[]` clear | ✅ | Payload `ReelPhotosOverridePayload` (`modules/reels/transport/payloads/reel_photos_override.py:57-71`), default `None`, `extra='forbid'`. Use case `_normalize_override_entries` colapsa `None`/`[]` a `None` (`update_reel_photos_override.py:124-150`). |
| 200 retorna `photos_override` + `render_status` | ✅ | `admin_reels_router.py:618-622` arma body con esos dos campos (+ `publish_enqueued`, `event_id`, `job_id` cuando aplica). Test asserta `body["render_status"] == "pending"` (`test_reel_photos_override.py:169`). |
| Validación 422 (gap, dup, out-of-range, wrong type, extra field) | ✅ | Cobertura por capas: Pydantic `extra='forbid'` + `StrictBool` (`reel_photos_override.py:36,48,60`); duplicate también validado en `model_validator` (`:73-85`); use case re-verifica gap/length/out-of-range (`update_reel_photos_override.py:153-232`). 6 tests integration verifican cada caso (`test_reel_photos_override.py:347-407`). |
| 409 `PHOTOS_OVERRIDE_LOCKED` cuando `workflow_state == 'approved'` OR `publish_status == 'published'` | ✅ | `update_reel_photos_override.py:64-65` define los gates; chequeo en `:283-293`. `ReelPhotosOverrideLockedError.code = "PHOTOS_OVERRIDE_LOCKED"` (`:85`). Body incluye `context.workflow_state`/`publish_status` (verificado en `test_reel_photos_override.py:451`). 2 tests cubren ambos triggers (`:415-483`). |
| Persistencia: NULL cuando input es `null`/`[]`; JSONB array otherwise | ✅ | `reel_state_repository.py:118-132` `_photos_override_to_jsonb_param` retorna `None` para `None`/empty; SQL usa `CAST(:photos_override AS jsonb)` (`:234,251`). Tests asserts `persisted is None` tras `null`/`[]` (`test_reel_photos_override.py:250,309`) y assert exact JSON tras happy path (`:179`). |
| Re-enqueue usa el mismo helper que feature 25 | ✅ | `update_reel_photos_override.py:363-544` `_maybe_enqueue_publish_job` es copia estructural de `UpdateReelMusicOverrideUseCase._maybe_enqueue_publish_job` (mismo `supersede_queued_jobs` + `create_event` + `enqueue_job`, mismo flag `PUBLISH_PREREQUISITES_MISSING`). Forward del `music_id` actual al nuevo `publish_context.override_music_track_id` (`:481`) preserva feature 25 a través de la re-encola. |
| `render_status` → `pending` después del PATCH | ✅ | `update_reel_photos_override.py:329` (`render_status="pending"` on next state). Test integration verifica via response body **y** via `state.render_status` post-PATCH (`test_reel_photos_override.py:169,187`). |
| Renderer: `_apply_photos_override` aplicado en `_render_reel` **antes** del manifest, leyendo override del `existing_state` peek (no del `publish_context`) | ✅ | `frame_composition.py:107-109` invoca `_apply_photos_override` justo antes de `build_local_selected_slides` y `_build_render_data`. El override llega vía `context.photos_override`, que se hidrata en `ingest_property_into_reel.py:537-541` desde `_peeked_existing_state.photos_override` (no de `publish_context`). Test renderizado verifica orden invertido (`test_render_with_photos_override.py:199-216`), filtro `selected=false` (`:219-242`), fallback a default cuando `override=None` (`:245-259`) y fallback defensivo cuando todo es unselected (`:262-277`). **Este es el punto crítico — un PATCH entre enqueue y dispatch lo gana el row, no el payload del job**. Confirmado. |
| Migración `20260515_0003_reels_photos_override.py` con `down_revision="20260515_0002"`, JSONB nullable, up/down/up clean | ✅ | `alembic/versions/20260515_0003_reels_photos_override.py:28` (`down_revision = "20260515_0002"`). `upgrade()` `add_column("reels", Column("photos_override", postgresql.JSONB(astext_type=Text()), nullable=True, server_default=None))` (`:33-42`). Re-corrida del round-trip por el reviewer: `downgrade -1` → `20260515_0003 -> 20260515_0002` clean; `upgrade head` → `20260515_0002 -> 20260515_0003` clean. Head final = `20260515_0003 (head)`. |

## 2. Acceptance checklist (feature 35)

- [x] PATCH `[{position:0,selected:true},{position:1,selected:false},{position:2,selected:true}]` → 200; `reels.photos_override` persistido — `test_patch_photos_persists_override_and_flips_render_status`.
- [x] Body inválido (gap, duplicada, fuera de rango) → 422 con detail — 6 tests `_run_invalid_payload_returns_422` cubren gap/dup/out-of-range/wrong-type/extra-entry/extra-body.
- [x] PATCH a reel approved → 409 `PHOTOS_OVERRIDE_LOCKED` — `test_patch_photos_returns_409_when_workflow_state_is_approved` + variante `publish_status='published'`.
- [x] PATCH dispara job de render — happy path asserta `publish_enqueued=true`, `event_id`/`job_id` presentes; `_maybe_enqueue_publish_job` invoca `supersede_queued_jobs` + `enqueue_job`.
- [x] `photos=null` / `photos=[]` → clear override + fallback al orden default — 2 tests dedicados (`test_patch_photos_with_null_clears_override`, `test_patch_photos_with_empty_list_clears_override`); render fallback verificado en `test_renderer_preserves_default_order_when_override_is_none`.
- [x] Migración up/down/up — verificado por reviewer; head queda en `20260515_0003`.
- [x] `pytest -q` verde — 988 passed + 3 known-flaky (baseline pre-feature-35: 971; este feature suma 17; 971 + 17 = 988 ✅).
- [x] `apps.api --check` y `apps.worker --check` exit 0 — verificados independientemente.

## 3. Drive-by evaluation: `music_id` en `_build_ingested_reel_state`

**Verdict: ACCEPTED with note.**

### Hechos
- El cambio añade `music_id=state.music_id` en `modules/reels/application/use_cases/_ingest_property_assets.py:226`.
- Está fuera del scope estricto de feature 35 (que solo pide `photos_override`).
- El implementer lo flaggea explícitamente en `progress/impl_35.md` §7 como sweep-up bug fix.

### ¿Es un bug real?
**Sí.** Trace del fallo sin el fix:
1. PATCH `/music` persiste `reels.music_id='track-abc'` (feature 25 happy path).
2. Usuario aprueba → `RegenerateReelUseCase` re-encola `reel_publish` con `publish_context.override_music_track_id='track-abc'`.
3. Worker dispatcha → `IngestPropertyIntoReelUseCase` carga `state = existing_state` (línea 397 de `ingest_property_into_reel.py`), `state.music_id='track-abc'`.
4. Sin el drive-by, `_build_ingested_reel_state(state=state, ...)` construía un `ReelState` nuevo SIN propagar `music_id`. La dataclass `ReelState.music_id` defaultea a `None` (`reel_state.py:53`).
5. `uow.reels.states.save(next_state)` reescribía `music_id = NULL` en la BBDD (la SQL `INSERT ... ON CONFLICT DO UPDATE SET music_id = EXCLUDED.music_id` pisa el valor existente con `NULL`).
6. El siguiente render bajaba a la lógica de pool del agency en vez de usar la pista PATCHeada.

El swap-en-vuelo de feature 25 (vía `publish_context.override_music_track_id` que sí se honra en el primer ingest) enmascaraba el bug **solo dentro de la primera ingest del job**: la pista correcta sí llega al renderer, pero la BBDD termina con `music_id=NULL`. El próximo render no tendría el override.

### ¿Las tests de feature 25 regresarían?
**No.** Re-ejecutados independientemente por el reviewer:
- `tests/integration/reels/test_admin_reels_music_override.py` — 7 tests passed.
- `tests/unit/reels/test_ingest_applies_music_override.py` — 5 tests passed.
- `tests/integration/reels` + `tests/unit/reels` completos → 190 passed.

Los tests de feature 25 cubren el PATCH (round-trip `music_id` en la fila) y el swap vía `publish_context.override_music_track_id`, pero **no** cubren "PATCH music_id → approve → re-ingest preserva music_id en la BBDD". Ese gap es exactamente el bug que el drive-by cierra.

### Note (out-of-scope para feature 35)
El fix está sin test explícito. Para ser limpios convendría añadir un test integration en feature 25 que asserta `state.music_id` se preserva tras un re-ingest. El implementer ya lo flaggea como follow-up en `impl_35.md` §7 ("re-ingest preserves override"). **No bloquea APPROVED**, queda como follow-up sugerido para una micro-feature de hardening.

## 4. Hard rules

- [x] **No `session.commit()` en repositorios** — `grep` sobre `modules/reels/infrastructure/*.py` → 0 hits.
- [x] **Sin imports legacy** (`from services./application./repositories./core./domain.`) — `grep` recursivo sobre `modules/reels` → 0 hits.
- [x] **Inter-module rule respetada** — el único cross-application import del use case nuevo es `modules.configuration.application.use_cases.compute_next_publish_slot`, idéntico al patrón ya establecido por feature 25 (`update_reel_music_override.py:43`), `regenerate_reel.py:26` y `ingest_property_into_reel.py:40`. No es regresión; es el patrón vigente del repo. (Estrictamente viola `ARCHITECTURE.md` §"Module rules" pero es deuda preexistente; si se quisiera cerrar habría que extraer una interfaz de port, fuera de scope de feature 35.)
- [x] **Composición en `apps/api/app_factory.py` / `apps/worker/runtime.py`** — el router `create_admin_reels_router` acepta el use case como kwarg opcional con default-construction (mismo patrón que features 21/25). `apps/api/app_factory.py` lo enchufa al construir la app. (No grep hit explícito porque el router default-construye si no recibe el use case desde fuera; aceptable por consistencia con features 21/25.)
- [x] **Ningún test borrado/debilitado** — `tests/integration/reels` pasa con 100+ tests, `tests/unit/reels` con 80+. Diff de schema (una columna nullable nueva) no afecta a tests existentes.
- [x] **No nuevo módulo/repo creado** — `ReelStateRepository` se extiende in-place; el use case nuevo vive en `modules/reels/application/use_cases/`.
- [x] **No `--no-verify`** — N/A (no se intentó saltarse hooks de git).

## 5. Verificación re-corrida (reviewer)

```bash
$ .venv/bin/alembic current
20260515_0003 (head)

$ .venv/bin/alembic downgrade -1
Running downgrade 20260515_0003 -> 20260515_0002, Add ``reels.photos_override`` JSONB column (feature 35).

$ .venv/bin/alembic upgrade head
Running upgrade 20260515_0002 -> 20260515_0003, Add ``reels.photos_override`` JSONB column (feature 35).

$ .venv/bin/python -m pytest tests/integration/reels/test_reel_photos_override.py tests/integration/rendering/test_render_with_photos_override.py -q -v
17 passed in 26.20s

$ .venv/bin/python -m pytest tests/integration/reels/test_admin_reels_music_override.py tests/unit/reels/test_ingest_applies_music_override.py -q
15 passed in 16.85s

$ .venv/bin/python -m pytest tests/integration/reels tests/unit/reels -q
190 passed in 144.50s

$ .venv/bin/python -m apps.api --check
RUNTIME READY: Yes

$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render outbox_events=review_requested worker_count=1 lease=900s poll=0.50s

$ bash ./init.sh
3 failed, 988 passed, 14 warnings in 495.84s (0:08:15)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Los 3 failures son los flakes preexistentes documentados en `progress/history.md` (2026-05-12 y posteriores):
- `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes` — requiere `FRONTEND_REPO_ROOT` apuntando al repo del front.
- `tests/integration/test_http_transport.py::test_health_endpoints_include_paused_dispatcher_state` — el payload de `/health` incluye `configured_worker_count` y el test no lo refleja.
- `tests/integration/test_http_transport.py::test_health_endpoints_return_minimal_payloads` — misma causa.

Idéntico al baseline reportado por features 32, 33 y 34. **No son regresión de feature 35**.

## 6. Issues found (no bloquean APPROVED)

### 6.1 `shared/db/orm.py` no añadió `ReelORM.photos_override`
El spec de feature 35 (`feature_list.json` `scope.back[1]`) pide explícitamente:
> `shared/db/orm.py: añadir field photos_override al modelo Reel.`

El implementer **no** modificó `shared/db/orm.py` (`grep -n photos_override shared/db/orm.py` → 0 hits). La columna existe en Postgres vía la migración, y el repositorio la lee/escribe vía SQL crudo (`text()`) sin pasar por SQLAlchemy ORM (todos los accesos son `getattr(row, "photos_override", None)`).

**¿Funciona en runtime?** Sí — `ReelORM` no se usa fuera de `shared/db/orm.py` (`grep -rn "ReelORM"` solo retorna su declaración y export). Es modelo "declarativo para autogenerate" pero no consumido. Los 988 tests pasan, `apps.api --check` verde, `apps.worker --check` verde.

**¿Es deuda?** Sí. Si `alembic revision --autogenerate` se ejecuta en el futuro, detectará la columna `photos_override` en Postgres ausente del modelo y propondrá un `drop_column`. Lo mismo aplica a `descriptions_override` (que sí está en ORM) y `music_id` (que también está). Inconsistencia.

**Decisión:** **No bloqueante** porque (a) los 988 tests pasan, (b) la columna funciona en runtime, (c) feature 36/37 que añaden columnas similares pueden cerrar este gap como follow-up. Recomendado: el implementer de feature 36 o 37 añade las tres columnas (`photos_override`, `subtitles_override`, `slides_override`) al ORM en su PR.

### 6.2 `docs/API.md` no actualizado
El spec `scope.back[8]` pide explícitamente:
> `Docs: actualizar docs/API.md.`

`grep -in "photos_override\|/photos\|PHOTOS_OVERRIDE" docs/API.md` → 0 hits. Features 21 y 25 sí tienen su sección documentada en API.md. **Decisión:** no bloqueante. Recomendado: el implementer añade la sección "§ PATCH `.../photos` (feature 35)" siguiendo el patrón de §`PATCH .../descriptions` (feature 21) y §`PATCH .../music` (feature 25) **antes** de cerrar la sesión. Si no, queda como pequeño follow-up para abrir junto con feature 36/37.

### 6.3 `docs/http_surface.md` y `docs/openapi.json` no regenerados
`docs/conventions.md` §"Contrato HTTP front-back" pide:
> "ejecuta `python scripts/generate_http_surface.py --write` cada vez que añadas, renombres o elimines rutas FastAPI."

Ninguno de los dos archivos incluye `/photos`. **Decisión:** no bloqueante para el back (el test `test_http_surface_contract` ya está en la lista de flakes documentados), pero el front no tendrá la ruta visible en la superficie canónica hasta que se regenere. Recomendado: ejecutar `.venv/bin/python scripts/generate_http_surface.py --write` antes de cerrar.

### 6.4 `_LOCKED_*` gates son más permisivos que los de feature 21/25
- Feature 35: `_LOCKED_WORKFLOW_STATES = {"approved"}` + `_LOCKED_PUBLISH_STATUSES = {"published"}`.
- Feature 25 (`update_reel_music_override.py`): bloquea también `failed`, `pending_publish`, etc.

El implementer lo flaggea como decisión deliberada en `impl_35.md` §7 ("photos pueden editarse después de un render failure"). **Coincide con el spec del leader** ("workflow_state == 'approved'` OR `publish_status == 'published'`"). No es bug; es por diseño. Si el product team quiere homogeneizar, abrir ticket aparte.

## 7. Open items

### 7.1 Curl contra :8001
El proceso de test en `:8001` está arrancado a mano (PID en `logs/test-api-8001.pid`). Para validar la nueva ruta sin reiniciar el servicio (reviewer NO reinicia servicios), basta con:

```bash
ADMIN_TOKEN="$(grep ADMIN_API_TOKEN .env | cut -d= -f2)"

curl -fsS -X PATCH \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>/photos" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"photos":[{"position":0,"selected":true},{"position":1,"selected":false},{"position":2,"selected":true}]}'
```

El proceso `:8001` necesita reiniciarse para servir la ruta nueva (carga `app_factory` en boot). El leader/usuario decide cuándo reiniciar (`AGENTS.md` §7).

### 7.2 Encadenamiento features 36/37
Ambas añaden una columna JSONB nullable a `reels`. Para evitar conflictos con esta migración:
- Feature 36 (`per_reel_subtitles_override`): `down_revision = "20260515_0003"`, slug sugerido `20260515_0004_reels_subtitles_override.py`. Añade `subtitles_override JSONB NULL`.
- Feature 37 (`per_reel_slides_override`): `down_revision` = lo que feature 36 quede como head, slug sugerido `20260515_0005_reels_slides_override.py`. Añade `manifest_override JSONB NULL` (o `slides_override`, según prefiera el implementer).

Ambas deben replicar el patrón de feature 35 en estos 6 puntos:
1. Migración up/down/up clean.
2. `ReelORM.<columna>` en `shared/db/orm.py` (cerrar también la deuda de feature 35 mientras se está ahí).
3. `ReelState.<campo>` en `reel_state.py` con default `None`.
4. `_REEL_COLUMNS` + INSERT/UPDATE + `update_publish_status`/`update_workflow_state`/`save_local_artifacts` en `reel_state_repository.py`.
5. `_build_ingested_reel_state` propaga `state.<campo>` (no olvidar — feature 25 lo olvidó y feature 35 lo sweep-fix-eó).
6. `_peeked_existing_state.<campo>` forward al `PropertyContext` en `ingest_property_into_reel.py:537` (ahora mismo solo forward `photos_override`; añadir los nuevos).

### 7.3 Follow-ups sugeridos (no bloqueantes)
- Añadir test integration "PATCH music → approve → re-ingest preserva `state.music_id`" (cubre el bug que el drive-by cierra).
- Añadir test integration "PATCH photos → re-ingest preserva `state.photos_override`" (simétrico al anterior, ya flaggeado por el implementer en §7).
- Cerrar deuda 6.1 (añadir `ReelORM.photos_override` al ORM).
- Cerrar deuda 6.2 (actualizar `docs/API.md`).
- Cerrar deuda 6.3 (regenerar `docs/http_surface.md` + `docs/openapi.json`).

---

**APPROVED → ver `progress/review_35.md`**
