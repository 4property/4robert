# Implementer Report — Feature 23: `wire_render_to_agency_music_tracks` (BACK)

> Status: NOT marked `done` (waiting on reviewer).
> Baseline preserved (3 pre-existing test failures untouched).
> Alembic head after this feature: `20260514_0005`.

## Decisiones §6 del explore (con justificación de 1 línea)

1. **Qué archivos NCS entran al seed**: `Silence`, `NCS Default` (= `ncs-music.mp3`), `Apart`, `Underrated` — los 4 NCS-released en `assets/music/`; `New Light.wav` queda fuera porque no es NCS y pesa 43 MB.
2. **Filtrado por `is_default`**: hecho en el use case (`resolve_agency_background_audio_candidates`), no en el repo — `MusicTracksRepository.list_for_agency` queda intacto para no romper consumers ajenos.
3. **Convención de filename para blobs seed**: prefijo plano `_seed_ncs_*.mp3` — el downgrade hace `LIKE 'agencies/%/music/_seed_ncs_%'` y los uploads del usuario nunca colisionan porque pasan por hash sha1 en el upload router.
4. **Migración monolítica vs script aparte**: opción A (la migración copia los blobs + ffprobe la duración) — el seed es one-shot, mantiene atomicidad y permite que `temporary_postgres_schema` siga corriendo sin fixtures extra.
5. **Punto de inyección en `RegisterAgencyUseCase`**: leer `workspace_dir` desde `uow.base_dir` — `app_factory` ya lo pasa al construir el UoW factory, no rompe la firma `RegisterAgencyUseCase()` que el test unit_of_work_factory usa con `SimpleNamespace`.
6. **Fallback en readiness**: mantener el scan legacy de `assets/music/` (`music_tracks=None`) — readiness no consulta BBDD por diseño actual y el `--check` debe seguir funcionando sin postgres.
7. **Comportamiento si pool vacío**: `resolve_agency_background_audio_candidates` raise `PropertyReelError(code="MUSIC_NO_TRACKS", stage="prepare")` antes de gastar ffmpeg; cuando configuration namespace falta (unit-test UoWs minimal), retorna `()` y el runtime usa el scan legacy.
8. **`REEL_BACKGROUND_AUDIO_FILENAME` legacy**: queda como semilla del scan legacy en `resolve_background_audio_paths` (solo se usa cuando `music_tracks=None`). No se borra para preservar el camino feliz de readiness/dev sin BBDD.

## Archivos modificados/añadidos (por capa)

### Domain (modules/configuration/domain)
- **Añadido** `modules/configuration/domain/default_music_tracks.py` — `DEFAULT_NCS_MUSIC_TRACK_SEEDS`, `DefaultMusicTrackSeed`, `SEED_FILENAME_PREFIX`.
- **Modificado** `modules/configuration/domain/__init__.py` — exporta las nuevas constantes.

### Application (modules/configuration/application)
- **Añadido** `modules/configuration/application/use_cases/seed_default_music_tracks.py` — `seed_default_music_tracks_for_agency(uow, agency_id, workspace_dir, source_music_dir=None)`. Idempotente; ffprobe best-effort.

### Application (modules/reels/application)
- **Añadido** `modules/reels/application/use_cases/_resolve_agency_music_pool.py` — `resolve_agency_background_audio_candidates(*, uow, agency_id, workspace_dir)`. Aplica la regla default-first.
- **Modificado** `modules/reels/application/use_cases/ingest_property_into_reel.py` — importa el helper, lo invoca antes de construir el `PropertyContext`, inyecta el tuple en `PropertyContext.background_audio_candidates`.

### Application (modules/rendering/application)
- **Modificado** `modules/rendering/application/frame_composition.py` — `DefaultMediaRenderer._render_reel` lee `context.background_audio_candidates`, decide `None` vs tuple, y lo pasa a `prepare_reel_render_assets(music_tracks=...)`.

### Infrastructure (modules/rendering/infrastructure)
- **Modificado** `modules/rendering/infrastructure/runtime/assets.py` —
  - `resolve_background_audio_paths` ahora acepta kwarg `music_tracks: tuple[Path, ...] | None = None`; comportamiento legacy cuando es `None`/vacío.
  - **Añadido** `resolve_agency_music_local_paths(*, workspace_dir, music_tracks)` — traduce `MusicTrack.object_key` → `Path` y raise `ResourceNotFoundError(code="MUSIC_BLOB_MISSING")` ante blob ausente o `object_key` malformado/con esquema `://`.
- **Modificado** `modules/rendering/infrastructure/runtime/__init__.py` — exporta el nuevo helper.
- **Modificado** `modules/rendering/infrastructure/preparation.py` — `prepare_reel_render_assets` acepta `music_tracks` y lo forwarda a `resolve_background_audio_paths`.
- **Modificado** `modules/rendering/infrastructure/manifest.py` — call-site actualizado con `music_tracks=None` explícito (preview/dry-run usa el scan legacy igual que antes).

### Domain (modules/reels/domain)
- **Modificado** `modules/reels/domain/types.py` — `PropertyContext` ahora tiene campo `background_audio_candidates: tuple[Path, ...] = field(default_factory=tuple)`.

### Tenancy (modules/tenancy/application)
- **Modificado** `modules/tenancy/application/use_cases/register_agency.py` — tras el seed de social_templates ya existente, añade hook al seed de music tracks usando `uow.base_dir` como workspace_dir; best-effort con try/except + logger.

### Transport / API
- **Modificado** `apps/api/readiness.py` — `_resolve_background_audio_paths` ahora pasa `music_tracks=None` explícito a la nueva firma.

### Storage
- **Sin cambios** en `shared/storage/site_layout.py` — feature 22 ya provee `resolve_agency_music_destination` y `resolve_agency_music_local_path`.

### Migration
- **Añadido** `alembic/versions/20260514_0005_seed_existing_agencies_with_ncs_music_tracks.py` — `revision="20260514_0005"`, `down_revision="20260514_0004"`. Upgrade itera agencias, copia 4 .mp3 + inserta filas; downgrade borra filas con marker `_seed_ncs_` + sus blobs.

### Tests añadidos
- `tests/unit/rendering/test_resolve_agency_music_local_paths.py` (5 tests) — happy path, blob ausente, object_key vacío, esquema `://`, input vacío.
- `tests/unit/rendering/test_resolve_background_audio_paths.py` (5 tests) — happy path con tracks, skip parcial de tracks ausentes, todos ausentes → raise, None falls back a legacy, tupla vacía falls back a legacy.
- `tests/unit/reels/test_resolve_agency_music_pool.py` (5 tests) — default-first, library fallback, empty pool raise `MUSIC_NO_TRACKS`, configuration ausente → `()`, blob missing propaga `MUSIC_BLOB_MISSING`.
- `tests/integration/rendering/test_render_uses_agency_music_pool.py` (2 tests) — `DefaultMediaRenderer` forwardea las paths a `prepare_reel_render_assets`; pool vacío → renderer pasa `music_tracks=None`.
- `tests/integration/tenancy/test_admin_agencies_router.py::test_create_agency_seeds_default_music_tracks` — crear agencia via POST → 4 filas + 4 blobs bajo `_agency_music/<agency>/`.
- `tests/integration/configuration/test_seed_existing_agencies_music.py` (3 tests) — backfill de agencia existente, downgrade limpia solo lo seedeado (uploads sobreviven), idempotencia ante agencias pre-seedeadas.

### Tests existentes tocados (mínimo)
- `tests/unit/rendering/test_frame_composition.py` — el fake `_fake_prepare` acepta el nuevo kwarg `music_tracks` y lo captura para assert.
- `tests/integration/rendering/test_side_banner_render.py` — idem.
- `tests/support/postgres.py::seed_tenant` — nuevo param `seed_default_music=True` (default) + `workspace_dir` opcional; siembra `agency_music_tracks` con marker + escribe stub blob para que e2e renderer no rompa.
- `tests/integration/reels/test_*_flow.py` (4 archivos) — call sites de `seed_tenant` actualizados para pasar `workspace_dir`.
- `tests/integration/delivery/test_worker_dispatcher_flow.py`, `tests/integration/ingestion/test_wordpress_webhook_flow.py` — idem (1 call site cada uno).
- `tests/integration/configuration/test_music_router.py::test_music_list_returns_seeded_track`, `tests/integration/configuration/test_reel_profile_router.py::test_get_returns_null_for_a_fresh_agency` — pasan `seed_default_music=False` porque su semántica "agencia fresca sin tracks" colisionaba con el nuevo default.

## Shape del render context (para features 24/25)

El job ahora viaja del use case al renderer así:

```text
IngestPropertyIntoReelUseCase
  ↓ resolve_agency_background_audio_candidates(uow, agency_id, workspace_dir)
  ↓ → tuple[Path, ...]  (default-tracks-first, library fallback, raise on empty)
PropertyContext
  .background_audio_candidates: tuple[Path, ...]   # NEW field, default ()
  ↓
DefaultMediaRenderer._render_reel
  ↓ music_tracks = context.background_audio_candidates or None
prepare_reel_render_assets(..., music_tracks=music_tracks)
  ↓ music_tracks forwarded to:
resolve_background_audio_paths(workspace, settings, music_tracks=..., shuffle_candidates=True)
  ↓ when music_tracks is non-empty: shuffle + return as-is (no legacy scan)
  ↓ when music_tracks is None/empty: legacy scan of workspace/assets/music/
PreparedReelAssets
  .background_audio_path: Path                  # first picked
  .background_audio_candidates: tuple[Path, ...] # full pool for mux_audio_candidates
```

**Para feature 24** (configurabilidad de fallback): el helper
`resolve_agency_background_audio_candidates` recibe `uow` y agency_id;
basta extender la regla con un AgencyMusicPolicy leído de
`agency_reel_defaults` o de una columna nueva en `agency_brand_settings`.
**Para feature 25** (selector manual de track): añadir un parámetro
`override_music_id: str | None` al helper; cuando es no-nulo, el helper
filtra `all_tracks` por ese music_id y propaga al `PropertyContext`.

## Comportamiento del seed

**Agencias nuevas** (`RegisterAgencyUseCase`): después de crear la fila
en `agencies` y de seedear `agency_social_templates`, el use case
invoca `seed_default_music_tracks_for_agency` con
`workspace_dir=uow.base_dir`. Comportamiento idempotente: si la
agencia ya tiene tracks, skip; si no, copia los 4 .mp3 y crea las
filas. Best-effort: errores de I/O o de copia se logean (logger
`modules.tenancy.application.use_cases.register_agency`) pero NO
abortan la creación de la agencia (que ya está commitada).

**Agencias existentes** (alembic upgrade `20260514_0005`): itera
`SELECT id FROM agencies`; para cada una, mismo flujo idempotente
que el use case. ffprobe se invoca best-effort por blob (timeouts
30s, falla silenciosa → duration=0). Workspace resuelto via
`os.environ.get("REELS_WORKSPACE_DIR")` con fallback al repo root
(consistente con `apps.api.app_factory`).

**Downgrade**: borra filas con `object_key LIKE 'agencies/%/music/_seed_ncs_%'`
y best-effort `unlink(missing_ok=True)` de los blobs. Los uploads
del usuario (hash sha1 sin marker) sobreviven.

## Resultados de verificación

```text
$ .venv/bin/python -m alembic heads
20260514_0005 (head)

$ .venv/bin/python -m alembic upgrade head   # OK; 3 agencias preexistentes → 12 filas + 12 blobs
$ .venv/bin/python -m alembic downgrade -1   # OK; 0 filas, blobs eliminados
$ .venv/bin/python -m alembic upgrade head   # OK; idempotente

$ .venv/bin/python -m pytest -q
752 passed, 3 failed, 14 warnings in 315.97s

  baseline pre-feature:    731 passed, 3 failed
  delta:                   +21 passed, 0 nuevos fallos (3 baseline preserved)

failures (todos del baseline, no tocados):
  tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
  tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
  tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads

$ .venv/bin/python -m apps.api --check       # exit 0
$ .venv/bin/python -m apps.worker --check    # exit 0
```

## Riesgos abiertos / TODO para reviewer

- El hook seed en `RegisterAgencyUseCase` corre **dentro** del UoW; si
  la copia de blobs falla, el log queda pero el commit del agency va
  igualmente (best-effort). El reviewer puede decidir si esto debería
  abortar la creación de la agencia, o si el log + repair-on-next-render
  es suficiente.
- `resolve_background_audio_paths` ya no escanea `assets/music/` en
  el path real del render — solo readiness/manifest. Si alguna test
  E2E aún espera ver pisos bajo `assets/music/` debería usar el fake
  apropiado.
- `ffprobe` ausente al correr la migración solo guarda `duration_seconds=0`;
  esto NO impide reproducir audio pero el frontend puede mostrar `0s` en
  el listado. Mitigable subiendo cualquier track via `/music/upload`
  (que sí lo probará).
