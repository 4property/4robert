# Reviewer Report — Feature 23: `wire_render_to_agency_music_tracks` (BACK)

> Status: APPROVED. Listo para que el leader cierre cross-repo y desbloquee 24/25.
> Reviewer: Claude Opus 4.7 (1M).
> Fecha: 2026-05-14.
> Baseline preservada (3 fallos pre-existentes intactos).
> Alembic head: `20260514_0005`.

## Veredicto

**APPROVED** — todos los acceptance criteria del feature 23 (1-9) verificados.
La feature está bien implementada, idempotente, con buena separación por
capas, tests robustos (20 nuevos del feature, 17 de los cuales 100% del
feature), y la migración se comporta correctamente en upgrade/downgrade
y replay. La única anomalía es operacional (no de código) y se documenta
abajo.

## Acceptance criteria — verificación

### AC1: `alembic upgrade head` ejecuta el seed (N filas + N blobs) — VERDE

- `head=20260514_0005`. `down_revision=20260514_0004` enlaza bien.
- Estado real en `miapp_test`: 3 agencias × 4 tracks = **12 filas**
  `agency_music_tracks` con `is_default=TRUE` y `object_key` con marker
  `_seed_ncs_`.
- Blobs en disco: 12 archivos bajo `generated_media/_agency_music/<agency>/_seed_ncs_*.mp3`
  con bytes idénticos a los originales en `assets/music/`.

### AC2: `alembic downgrade -1` limpia solo lo seedeado — VERDE

- Test `tests/integration/configuration/test_seed_existing_agencies_music.py::test_seed_migration_downgrade_only_removes_seeded_rows`
  PASSED.
- Verificación manual cycle `upgrade → downgrade -1 → upgrade head`
  completo sin errores.
- `WHERE object_key LIKE 'agencies/%/music/_seed_ncs_%'` es exclusivo
  porque feature 22 usa hashes `sha1[:12]` sin marker.

### AC3: Default pool → library → raise — VERDE

- `tests/unit/reels/test_resolve_agency_music_pool.py` (5 tests) cubren los
  3 caminos: default-first, library fallback, vacío total → `MUSIC_NO_TRACKS`.

### AC4: Filter graph referencia Path bajo `resolve_agency_music_destination` — VERDE

- `tests/integration/rendering/test_render_uses_agency_music_pool.py::test_renderer_forwards_agency_music_paths_to_preparation`
  PASSED. El test arma paths via `resolve_agency_music_destination`,
  los inyecta por `PropertyContext.background_audio_candidates`, y
  asserta que `prepare_reel_render_assets` recibe paths con
  `_agency_music` en el str y SIN `assets/music`.

### AC5: Crear agencia nueva via use case dispara seed — VERDE

- `tests/integration/tenancy/test_admin_agencies_router.py::test_create_agency_seeds_default_music_tracks`
  PASSED.
- Anomalía operacional: el smoke manual contra `:8001` devolvió `count: 0`
  porque la **API process es pre-feature-23** (PID 2295779, ELAPSED 01h09m,
  arrancada antes de que el implementer cerrara). Una vez reinicie la API,
  el camino del use case funcionará (los tests integration lo verifican).
  Esto es operativo, NO un defecto del código.

### AC6: `resolve_background_audio_paths` con firma nueva en lockstep — VERDE

- Los 3 call sites pasan `music_tracks=...` explícito:
  - `modules/rendering/infrastructure/preparation.py:187-192` → `music_tracks=music_tracks`
    (parámetro nuevo de `prepare_reel_render_assets`).
  - `modules/rendering/infrastructure/manifest.py:180-186` → `music_tracks=None`
    (preview/dry-run, fallback legacy intencionado).
  - `apps/api/readiness.py:412-417` → `music_tracks=None` (sin BBDD en
    readiness, fallback legacy intencionado).

### AC7: `pytest -q` verde — VERDE

- 752 passed, 3 failed (los **3 baseline pre-existentes**, idénticos al
  baseline pre-implementer):
  - `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
  - `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state`
  - `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads`
- Focus run (`tests/integration/rendering/`, `tests/unit/rendering/`,
  `tests/integration/reels/`, `tests/integration/configuration/`,
  `tests/integration/tenancy/`, `tests/unit/tenancy/`): **272 passed**.

### AC8: `apps.api --check` y `apps.worker --check` exit 0 — VERDE

- Ambos vuelven `EXIT=0`. Imprimen el `DATABASE` y `FFMPEG` esperados.

### AC9: Bloquea-resuelto: features 24/25 pueden arrancar — VERDE

- El shape del context (`PropertyContext.background_audio_candidates`)
  y el helper `resolve_agency_background_audio_candidates(*, uow,
  agency_id, workspace_dir)` están listos para extender con la regla
  configurable de feature 24 y el override per-reel de feature 25 sin
  romper callers.

## Inspección de decisiones notables del implementer

### 1. Migración `20260514_0005` — VERDE

- **Path destino consistente con feature 22**: la migración no importa
  `shared.storage.site_layout` (a propósito, para autocontención
  alembic). Su `_resolve_destination` (líneas 107-118) reproduce el
  layout `workspace/generated_media/_agency_music/<safe_agency>/<filename>`
  y el `object_key` `agencies/<safe_agency>/music/<filename>` con
  byte-for-byte fidelity al helper público. La UI/render servirán los
  blobs vía el endpoint del feature 22 sin problema.
- **Idempotencia upgrade**: skip si `COUNT(*) FROM agency_music_tracks
  WHERE agency_id = ?` > 0 (líneas 163-171). Verificado replay-safe en
  el cycle real.
- **Downgrade selectivo**: `LIKE 'agencies/%/music/_seed_ncs_%'` (líneas
  226-238). Los uploads de feature 22 nunca llevan el marker, así que
  sobreviven.

### 2. Hook en `RegisterAgencyUseCase` — VERDE (con nota)

- Orden correcto: `agencies.create → get_by_id → social_templates.replace_all
  → music seed` (líneas 56-114). El hook corre DESPUÉS de `get_by_id`,
  así que el agency ya está flushed en la sesión cuando se invoca el seed
  (commit final ocurre al salir del UoW).
- `try/except Exception: logger.exception(...)` defensivo (líneas 109-113):
  si la copia falla, el agency NO se aborta. El implementer documenta esto
  como TODO consciente; lo apruebo: las consecuencias de abortar la
  creación de la agencia son peores que arrastrar un seed parcial que
  se puede reintentar via `/music/upload` o re-running la migración.
- `getattr(uow, "base_dir", None)` resuelve bien para UoWs reales
  (`apps/api/app_factory.py:165-168` lo pasa explícitamente). Tests con
  `SimpleNamespace` sin `base_dir` skipean silenciosamente. Validado.

### 3. `PropertyContext.background_audio_candidates` — VERDE

- Campo nuevo: `background_audio_candidates: tuple[Path, ...] = field(default_factory=tuple)`
  en `modules/reels/domain/types.py:367`.
- **NO viaja por cola**: revisado `modules/delivery/`, `shared/`, `apps/`
  con `grep -rn 'background_audio_candidates'` — solo aparece en rendering
  application/infrastructure y en los tests del feature. `PropertyContext`
  no tiene `to_dict/from_dict` (a diferencia de `SocialPublishContext`).
- El resolve se hace en cada worker run dentro del use case
  `IngestPropertyIntoReelUseCase._execute_with_uow` (línea 160), justo
  antes de construir el `PropertyContext` (línea 412). Esto es correcto:
  un worker que recoja un job tras un upload pickeará la nueva pista
  sin necesidad de re-encolar el job.

### 4. Helper `resolve_agency_music_local_paths` con `MUSIC_BLOB_MISSING` — VERDE

- `modules/rendering/infrastructure/runtime/assets.py:178-233`. Documentado
  con docstring que explica el contrato S3-future-proofing y por qué se
  raise en vez de skip silencioso. Tres caminos de error
  (`MUSIC_BLOB_MISSING`):
  - `object_key` vacío/whitespace.
  - `resolve_agency_music_local_path` retorna `None` (file ausente,
    esquema `://`, traversal `..`, prefijo distinto a `agencies/<x>/music/`).
- Cubierto por 5 unit tests en
  `tests/unit/rendering/test_resolve_agency_music_local_paths.py`.

### 5. Use case `_resolve_agency_music_pool` — capas correctas — VERDE

- Vive en `modules/reels/application/use_cases/_resolve_agency_music_pool.py`
  (la query SQL queda en reels application, no en rendering).
- `grep -rn 'from modules.configuration' modules/rendering/` arroja
  **solo 2 imports**, ambos de `modules.configuration.domain` (`MusicTrack`,
  `RenderTemplate`). NINGÚN import de application/infrastructure de
  configuration. Layer rules respetadas.
- `grep -rn 'from modules.rendering' modules/configuration/` arroja
  **0 imports** — sentido inverso también limpio.
- El use case helper sí importa
  `modules.rendering.infrastructure.runtime.assets.resolve_agency_music_local_paths`,
  lo cual es válido (reels/application → rendering/infrastructure es un
  cruce esperado al ser una utility runtime).

### 6. Firma `resolve_background_audio_paths(*, music_tracks=None)` — VERDE

- Kwarg-only, default `None`. Cuando es `None` o tupla vacía, ejecuta
  el scan legacy de `workspace/<assets>/music/`. Esto preserva readiness
  (sin BBDD) y dev workflows.
- Los 3 call sites están en lockstep (ver AC6).

### 7. `seed_tenant(seed_default_music=True)` — VERDE

- `tests/support/postgres.py:228,258` siembra UNA pista sintética con
  marker `_seed_ncs_test.mp3` + escribe stub blob bajo
  `workspace/generated_media/_agency_music/<agency>/`.
- Default `True` para mantener compat con los flows E2E que asumen una
  pista disponible. Tests que necesitan semántica "agencia fresca sin
  música" pasan `seed_default_music=False` (cambio explícito en 2
  archivos: `test_music_router.py::test_music_list_returns_seeded_track`
  y `test_reel_profile_router.py::test_get_returns_null_for_a_fresh_agency`).
- 0 nuevos fallos en `pytest -q`: confirma compat opt-in.

### 8. Error `MUSIC_NO_TRACKS` — VERDE

- `PropertyReelError(code="MUSIC_NO_TRACKS", stage="prepare", ...)` raise
  en `_resolve_agency_music_pool.py:70-80`. Se levanta ANTES de gastar
  ffmpeg (en el use case, no en el renderer).
- El job se marca failed con ese código vía el manejador estándar de
  `PropertyReelError` en el ingest use case (no es nuevo de feature 23;
  reusa el mismo error-handling que `MEDIA_MISSING` o similares).

## Riesgos / TODOs del implementer revisados

1. **Hook seed dentro del UoW con best-effort log**: aprobado. La
   alternativa (abortar la creación) es peor para el UX del admin.
2. **`assets/music/` ya no se escanea en producción**: aprobado. Sigue
   sirviendo a readiness/dev. Los tests E2E que necesitaban la pista
   ahora pasan `seed_default_music=True` (default).
3. **ffprobe ausente en la migración → `duration_seconds=0`**: aceptable.
   El upload via `/music/upload` lo reparará. Frontend puede mostrar 0s
   como display fallback.

## Anomalías encontradas (no bloqueantes)

### A1. API server en `:8001` está corriendo código pre-feature-23

- PID 2295779, ELAPSED ~1h10min en el momento del review. El proceso se
  arrancó antes del cierre del implementer.
- Síntoma: smoke manual `POST /v1/admin/agencies` → la nueva agencia
  queda con `count: 0` tracks (el hook no se ejecuta porque el código
  cargado no lo tiene).
- **Acción recomendada al leader**: reiniciar el servicio `:8001` antes
  de cerrar el feature cross-repo, para que el manual smoke pase. El
  código en disco está correcto y los tests integration lo demuestran.

### A2. Restos de smoke previo de feature 22 en el FS

- En `generated_media/_agency_music/f86148f7-.../` quedó un `tiny.mp3`
  (4510 bytes) de un upload manual previo de feature 22. NO tiene fila
  en `agency_music_tracks` (cleanup parcial del smoke previo). No
  impacta feature 23 (la migración hace skip si la agencia tiene rows,
  pero esta agencia ya tenía las 4 seedeadas; `tiny.mp3` es un orfanato
  inocuo).

## Comandos de verificación ejecutados

```text
bash ./init.sh                                          # exit 0
.venv/bin/python -m alembic heads                       # 20260514_0005 (head)
.venv/bin/python -m alembic upgrade head                # OK
.venv/bin/python -m alembic downgrade -1                # OK
.venv/bin/python -m alembic upgrade head                # OK (idempotent)
.venv/bin/python -m apps.api --check                    # exit 0
.venv/bin/python -m apps.worker --check                 # exit 0
.venv/bin/python -m pytest tests/integration/rendering/ \
  tests/unit/rendering/ tests/integration/reels/ \
  tests/integration/configuration/ tests/integration/tenancy/ \
  tests/unit/tenancy/ -q                                # 272 passed
.venv/bin/python -m pytest -q                           # 752 passed, 3 failed (baseline)
.venv/bin/python -m pytest \
  tests/integration/rendering/test_render_uses_agency_music_pool.py \
  tests/unit/reels/test_resolve_agency_music_pool.py \
  tests/unit/rendering/test_resolve_agency_music_local_paths.py \
  tests/unit/rendering/test_resolve_background_audio_paths.py \
  tests/integration/configuration/test_seed_existing_agencies_music.py \
  tests/integration/tenancy/test_admin_agencies_router.py::test_create_agency_seeds_default_music_tracks \
                                                        # 21 passed
```

Manual contra :8001 ejecutado (con la anomalía A1 documentada arriba),
estado de DB verificado con SQL directa: **3 agencias × 4 tracks
`is_default=true`** con marker `_seed_ncs_` + 12 blobs físicos en disco.

## Recomendación al leader

Aprobar y proceder con el cierre cross-repo. Antes de marcar la feature
como done:

1. Reiniciar el servicio `:8001` para que el manual smoke vea el código
   nuevo (anomalía A1).
2. Marcar feature 23 como `done` en `feature_list.json` (ambos repos —
   el frontend es no-op).
3. Desbloquear 24 (`agency_music_selection_rules`) y 25
   (`per_reel_music_override`), que dependen del shape ya estable.

No hay defectos de código que rectificar.
