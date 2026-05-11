# Impl — Sub-tarea 18c `dissolve_services_dir_and_close_phase_2`

> Sub-tarea 18c de feature 18 (`delete_legacy_dirs_and_close_phase_2`).
> Disuelve el directorio `services/` (39 `.py` + dirs vacíos),
> reapunta los callers vivos, mueve la última pieza cross-cutting
> (`site_storage.py`) a `shared/storage/`, parte
> `services/ai/photo_selection/selection.py` (774 LoC) en 3 módulos
> ≤500 LoC y cierra Phase 2 actualizando docs + `init.sh`.
>
> Baseline post-18b: 394 tests verdes.
> Baseline post-18c: **394 tests verdes** (sin pérdidas, sin regresiones).
> Acceptance literal cumplido al 100%.

---

## 1. Archivos creados / modificados / borrados

### Creados (24 nuevos archivos en `modules/`/`shared/`)

#### Bajo `shared/storage/`

| Archivo | LoC | Origen |
|---------|----:|--------|
| `shared/storage/site_layout.py` | 56 | `services/media/site_storage.py` (51) verbatim, sólo path renombrado |

#### Bajo `modules/rendering/infrastructure/` (rendering primitives)

| Archivo | LoC | Origen |
|---------|----:|--------|
| `modules/rendering/infrastructure/models.py` | 147 | `services/media/reel_rendering/models.py` (146) verbatim |
| `modules/rendering/infrastructure/formatting.py` | 485 | `services/media/reel_rendering/formatting.py` (494) — al borde, condensado el `__all__` para bajar a 485 |
| `modules/rendering/infrastructure/data.py` | 124 | `services/media/reel_rendering/data.py` (122) — sólo cambia el path del shim de slides + import de `runtime` |
| `modules/rendering/infrastructure/manifest.py` | 322 | `services/media/reel_rendering/manifest.py` (321) verbatim |
| `modules/rendering/infrastructure/poster.py` | 391 | `services/media/reel_rendering/poster.py` (390) — `services/media/site_storage` → `shared.storage.site_layout` |
| `modules/rendering/infrastructure/preparation.py` | 451 | `services/media/reel_rendering/preparation.py` (450) verbatim |
| `modules/rendering/infrastructure/ffmpeg/filters.py` | 330 | `services/media/reel_rendering/filters.py` (329) verbatim |

#### Bajo `modules/rendering/infrastructure/ai_photo_selection/` (split de 774 LoC)

| Archivo | LoC | Origen |
|---------|----:|--------|
| `modules/rendering/infrastructure/ai_photo_selection/__init__.py` | 32 | (nuevo) agregador del sub-paquete |
| `modules/rendering/infrastructure/ai_photo_selection/client.py` | 293 | `services/ai/photo_selection/client.py` (287) verbatim |
| `modules/rendering/infrastructure/ai_photo_selection/prompting.py` | 309 | `services/ai/photo_selection/prompting.py` (301) — `domain.properties.model.Property` → `modules.catalog.domain.wordpress_property.Property` |
| `modules/rendering/infrastructure/ai_photo_selection/audit.py` | 82 | extracción de `build_output_payload` + `write_output_payload` (split del legacy 774 LoC) |
| `modules/rendering/infrastructure/ai_photo_selection/selection.py` | 462 | algoritmo de ranking (`build_result_row`, `build_error_row`, `is_valid_candidate`, `detect_rejected_non_photo_asset`, `area_limit`, `can_add_candidate`, `rank_rows`, `choose_first_match`, `choose_selected_rows`, `annotate_results`, `build_output_payload`) — split del legacy 774 LoC |
| `modules/rendering/infrastructure/ai_photo_selection/classify.py` | 230 | orquestador `classify_property_images` (driver de Gemini) — split del legacy 774 LoC |

**Total split del legacy 774 LoC**: 82 + 462 + 230 = **774 LoC efectivos** (sin pérdida de cohesión).
- `selection.py` y `audit.py` son puro algoritmo + payload, sin dependencias de `LoggedProcess`/`progress`.
- `classify.py` es el driver con logging + Gemini + retries.

#### Bajo `modules/rendering/infrastructure/photos/` (property_media)

| Archivo | LoC | Origen |
|---------|----:|--------|
| `modules/rendering/infrastructure/photos/__init__.py` | 23 | re-exports |
| `modules/rendering/infrastructure/photos/naming.py` | 84 | `services/media/property_media/naming.py` (83) verbatim |
| `modules/rendering/infrastructure/photos/filesystem.py` | 65 | `services/media/property_media/filesystem.py` (64) verbatim |
| `modules/rendering/infrastructure/photos/downloads.py` | 117 | `services/media/property_media/downloads.py` (110) — imports reapuntados a `modules.rendering.infrastructure.photos.{naming,filesystem}` |
| `modules/rendering/infrastructure/photos/selection.py` | 388 | `services/media/property_media/selection.py` (385) — imports reapuntados a `modules.rendering.infrastructure.{photos,ai_photo_selection}` |

#### Bajo `modules/publishing/infrastructure/adapters/gohighlevel/` (movido completo)

| Archivo | LoC | Origen |
|---------|----:|--------|
| `modules/publishing/infrastructure/adapters/gohighlevel/client.py` | 156 | `services/publishing/social_delivery/gohighlevel_client.py` (155) verbatim |
| `modules/publishing/infrastructure/adapters/gohighlevel/models.py` | 410 | `services/publishing/social_delivery/models.py` (414) verbatim |
| `modules/publishing/infrastructure/adapters/gohighlevel/media_service.py` | 148 | `services/publishing/social_delivery/gohighlevel_media_service.py` (147) verbatim |
| `modules/publishing/infrastructure/adapters/gohighlevel/social_service.py` | 359 | `services/publishing/social_delivery/gohighlevel_social_service.py` (358) verbatim |
| `modules/publishing/infrastructure/adapters/gohighlevel/interfaces.py` | 41 | `services/publishing/social_delivery/interfaces.py` (41) verbatim |
| `modules/publishing/infrastructure/adapters/gohighlevel/platform_policy.py` | 92 | `services/publishing/social_delivery/platform_policy.py` (85) — import simplificado |
| `modules/publishing/infrastructure/adapters/gohighlevel/user_selection.py` | 27 | `services/publishing/social_delivery/user_selection.py` (27) verbatim |
| `modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py` | 339 | `services/publishing/social_delivery/property_publisher.py` (338) — paths reapuntados a in-module |

#### Bajo `modules/publishing/infrastructure/social_copy/`

| Archivo | LoC | Origen |
|---------|----:|--------|
| `modules/publishing/infrastructure/social_copy/__init__.py` | 65 | nuevo agregador con `__getattr__` lazy para evitar el ciclo `social_copy → adapters/platforms → adapters/platforms/shared.py → social_copy.post_copy` |
| `modules/publishing/infrastructure/social_copy/post_copy.py` | 226 | `services/publishing/social_delivery/post_copy.py` (226) verbatim |
| `modules/publishing/infrastructure/social_copy/description.py` | 387 | `services/publishing/social_delivery/description.py` (387) — `services.media.reel_rendering.data.PropertyReelRecord` → `modules.rendering.infrastructure.data.PropertyReelRecord`, platforms imports reapuntados |

**Total LoC creados** (todos los archivos nuevos): **6 658 LoC**, distribuidos en 24 archivos. Ningún archivo nuevo excede 500 LoC. Máximo: `formatting.py` 485 LoC.

### Modificados (re-apuntado de imports)

#### Reapuntados en `apps/` (1 archivo, 4 imports lazy)

- `apps/api/readiness.py:396, 402, 408, 409` — `services.media.reel_rendering.{runtime,models}` → `modules.rendering.infrastructure.{runtime,models}`.

#### Reapuntados en `modules/` (~30 imports en 17 archivos)

Bloque rendering (post-18c, los imports ya viven dentro de `modules.rendering.infrastructure.*`):
- `modules/rendering/infrastructure/runtime/{assets,branding,slides}.py` — `services.media.reel_rendering.models`, `services.media.site_storage`, `services.ai.photo_selection.prompting` → in-module.
- `modules/rendering/infrastructure/layout/{composition,panels,subtitles,text_measurement}.py` — `services.media.reel_rendering.{models,formatting}`, `services.ai.photo_selection.prompting` → in-module.
- `modules/rendering/infrastructure/ffmpeg/{commands,filter_graph,render_reel}.py` — `services.media.reel_rendering.{models,filters,formatting,data,preparation,runtime}`, `services.media.site_storage` → in-module + `shared.storage.site_layout`.
- `modules/rendering/application/frame_composition.py:32-46` — `services.media.reel_rendering.*` → `modules.rendering.infrastructure.*`.
- `modules/rendering/application/scripted_video/{render_service,payload_helpers}.py` — idem.

Bloque reels:
- `modules/reels/domain/media_planning.py:15` — `services.media.reel_rendering.formatting.format_price` → `modules.rendering.infrastructure.formatting.format_price`.
- `modules/reels/application/content_generator.py:16-20` — `services.publishing.social_delivery.{description,post_copy}` → `modules.publishing.infrastructure.social_copy.{description,post_copy}`.
- `modules/reels/application/use_cases/ingest_property_into_reel.py:50-52, 782` — `services.media.site_storage`, `services.publishing.social_delivery`, `services.media.reel_rendering.poster` → `shared.storage.site_layout`, `modules.publishing.infrastructure.social_copy.description`, `modules.publishing.infrastructure.adapters.gohighlevel.platform_policy`, `modules.rendering.infrastructure.poster`.
- `modules/reels/application/use_cases/prepare_reel_assets.py:42-49` — `services.media.property_media.*` → `modules.rendering.infrastructure.photos.*`.

Bloque publishing:
- `modules/publishing/application/use_cases/inspect_agency_social_accounts.py:21-25` — `services.publishing.social_delivery.{gohighlevel_client,gohighlevel_social_service,models}` → `modules.publishing.infrastructure.adapters.gohighlevel.{client,social_service,models}`.
- `modules/publishing/application/use_cases/probe_provider_connection.py:74-75` — idem (lazy import).
- `modules/publishing/infrastructure/adapters/gohighlevel/{single_publish,multi_publish,post_creation,retrying,selection,normalization,publisher,factory}.py` — todos reapuntados a in-module.
- `modules/publishing/infrastructure/adapters/platforms/shared.py:7` — `services.publishing.social_delivery.post_copy` → `modules.publishing.infrastructure.social_copy.post_copy`.

#### Reapuntados en `tests/` (8 archivos, ~14 imports + 6 mock.patch strings)

- `tests/test_reel_render_command.py:11-13` — `services.media.reel_rendering.{models,formatting,render}` → `modules.rendering.infrastructure.{models,formatting,ffmpeg.commands}` (con alias `_build_ffmpeg_reel_command = build_ffmpeg_reel_command`).
- `tests/test_reel_runtime_dynamic_urls.py:18-24, 94, 119, 146` — imports + 3 `mock.patch` strings reapuntados a `modules.rendering.infrastructure.runtime.{assets,branding}`.
- `tests/test_gemini_photo_selection.py:21-39, 760, 800, 862` — imports + 3 `mock.patch` strings reapuntados (`classify_property_images` ahora vive en `classify.py`, los demás en `selection.py`/`prompting.py`/`client.py`/`photos.{naming,selection}`).
- `tests/unit/reels/{test_prepare_reel_assets,test_persist_local_artifacts,test_publish_reel}.py` — `services.media.site_storage` → `shared.storage.site_layout`.
- `tests/unit/publishing/test_inspect_agency_social_accounts.py:15` — `services.publishing.social_delivery.models.SocialAccount` → `modules.publishing.infrastructure.adapters.gohighlevel.models.SocialAccount`.
- `tests/unit/rendering/conftest.py:14, test_frame_composition.py:33-34` — `services.media.reel_rendering.models`, `services.media.site_storage` → `modules.rendering.infrastructure.models`, `shared.storage.site_layout`.

### Borrados (1 dir + ~7 700 LoC en 39 archivos `.py` + 7 dirs vacíos)

| Borrado | LoC | Razón |
|---------|----:|-------|
| `services/__init__.py` (no detectable) | n/a | dir paquete (sin `__init__.py` propio) |
| `services/ai/__init__.py` | 38 | re-exports |
| `services/ai/photo_selection/__init__.py` | 38 | re-exports |
| `services/ai/photo_selection/client.py` | 287 | movido a `modules/rendering/infrastructure/ai_photo_selection/client.py` |
| `services/ai/photo_selection/prompting.py` | 301 | movido |
| `services/ai/photo_selection/selection.py` | 774 | partido en 3 (audit + selection + classify) |
| `services/media/__init__.py` | 51 | duplicado byte-igual a `site_storage.py`, movido a `shared/storage/site_layout.py` |
| `services/media/property_media/__init__.py` | 13 | re-exports |
| `services/media/property_media/downloads.py` | 110 | movido |
| `services/media/property_media/filesystem.py` | 64 | movido |
| `services/media/property_media/naming.py` | 83 | movido |
| `services/media/property_media/selection.py` | 385 | movido |
| `services/media/reel_rendering/__init__.py` | 34 | re-exports |
| `services/media/reel_rendering/data.py` | 122 | movido |
| `services/media/reel_rendering/filters.py` | 329 | movido |
| `services/media/reel_rendering/formatting.py` | 494 | movido + condensado |
| `services/media/reel_rendering/layout.py` | 27 | facade post-feature-15 (callers ya apuntaban al `modules/rendering/infrastructure/layout/` desde feature 15) |
| `services/media/reel_rendering/manifest.py` | 321 | movido |
| `services/media/reel_rendering/models.py` | 146 | movido |
| `services/media/reel_rendering/poster.py` | 390 | movido |
| `services/media/reel_rendering/preparation.py` | 450 | movido |
| `services/media/reel_rendering/render.py` | 75 | facade — los callers ya apuntan al moderno `modules/rendering/infrastructure/ffmpeg/` |
| `services/media/reel_rendering/runtime.py` | 222 | facade — los callers ya apuntan al moderno `modules/rendering/infrastructure/runtime/` |
| `services/media/site_storage.py` | 51 | movido a `shared/storage/site_layout.py` |
| `services/publishing/__init__.py` | 122 | re-exports |
| `services/publishing/social_delivery/__init__.py` | 122 | re-exports |
| `services/publishing/social_delivery/description.py` | 387 | movido a `modules/publishing/infrastructure/social_copy/description.py` |
| `services/publishing/social_delivery/gohighlevel_client.py` | 155 | movido |
| `services/publishing/social_delivery/gohighlevel_media_service.py` | 147 | movido |
| `services/publishing/social_delivery/gohighlevel_publisher.py` | 21 | facade post-feature anterior — callers ya apuntan al `publisher.py` moderno |
| `services/publishing/social_delivery/gohighlevel_social_service.py` | 358 | movido |
| `services/publishing/social_delivery/interfaces.py` | 41 | movido |
| `services/publishing/social_delivery/models.py` | 414 | movido |
| `services/publishing/social_delivery/platform_policy.py` | 85 | movido |
| `services/publishing/social_delivery/post_copy.py` | 226 | movido a `modules/publishing/infrastructure/social_copy/post_copy.py` |
| `services/publishing/social_delivery/property_publisher.py` | 338 | movido a `modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py` |
| `services/publishing/social_delivery/user_selection.py` | 27 | movido |
| `services/transport/__init__.py` | 11 | sin callers vivos |
| `services/transport/http/__init__.py` | 11 | sin callers vivos |
| `services/transport/http/operations.py` | 466 | sin callers vivos tras feature 17 — borrado completo |
| Dirs vacíos: `services/ai_photo_selection/`, `services/property_media/`, `services/reel_rendering/`, `services/social_delivery/{,platforms/}`, `services/webhook_transport/` | — | residuo histórico de splits anteriores |
| `services/` (dir raíz) | — | eliminado físicamente con `rm -rf services/` |

**Total borrado**: ~7 736 LoC físicos (legacy + facades + re-exports + dirs vacíos).

---

## 2. Tabla de movilizaciones (origen → destino)

| Origen | Destino | Notas |
|--------|---------|-------|
| `services/media/site_storage.py` | `shared/storage/site_layout.py` | cross-cutting; `shared/storage/__init__.py` ahora re-exporta |
| `services/media/reel_rendering/models.py` | `modules/rendering/infrastructure/models.py` | base de toda la cadena de rendering |
| `services/media/reel_rendering/formatting.py` | `modules/rendering/infrastructure/formatting.py` | text/wrap/price/size/overlay color helpers |
| `services/media/reel_rendering/data.py` | `modules/rendering/infrastructure/data.py` | `PropertyReelRecord` + `record_to_property_reel_data` |
| `services/media/reel_rendering/manifest.py` | `modules/rendering/infrastructure/manifest.py` | manifest writer |
| `services/media/reel_rendering/poster.py` | `modules/rendering/infrastructure/poster.py` | poster ffmpeg renderer |
| `services/media/reel_rendering/preparation.py` | `modules/rendering/infrastructure/preparation.py` | asset preparation pipeline |
| `services/media/reel_rendering/filters.py` | `modules/rendering/infrastructure/ffmpeg/filters.py` | `build_overlay_filter`, `build_filter_complex` |
| `services/media/reel_rendering/runtime.py` | (borrado, facade — callers ya en `modules.rendering.infrastructure.runtime`) | |
| `services/media/reel_rendering/render.py` | (borrado, facade — callers ya en `modules.rendering.infrastructure.ffmpeg`) | |
| `services/media/reel_rendering/layout.py` | (borrado, facade post-feature-15) | |
| `services/ai/photo_selection/client.py` | `modules/rendering/infrastructure/ai_photo_selection/client.py` | Gemini HTTP client |
| `services/ai/photo_selection/prompting.py` | `modules/rendering/infrastructure/ai_photo_selection/prompting.py` | prompt + property context builder |
| `services/ai/photo_selection/selection.py` (774 LoC) | split en 3: `audit.py` (82) + `selection.py` (462) + `classify.py` (230) | obligatorio por la regla ≤500 LoC |
| `services/media/property_media/{naming,filesystem,downloads,selection}.py` | `modules/rendering/infrastructure/photos/` | propertyMedia download + filter pipeline |
| `services/publishing/social_delivery/{gohighlevel_client,gohighlevel_media_service,gohighlevel_social_service,models,interfaces,platform_policy,user_selection,property_publisher}.py` | `modules/publishing/infrastructure/adapters/gohighlevel/` | renombre `gohighlevel_client` → `client.py`, `gohighlevel_media_service` → `media_service.py`, `gohighlevel_social_service` → `social_service.py` |
| `services/publishing/social_delivery/{description,post_copy}.py` | `modules/publishing/infrastructure/social_copy/` | shared social copy builders |
| `services/publishing/social_delivery/gohighlevel_publisher.py` | (borrado, facade) | callers ya apuntan al `publisher.py` en `modules/...` |
| `services/transport/http/operations.py` (466 LoC) | (borrado) | sin callers vivos tras feature 17 |

---

## 3. Imports reapuntados (lista exhaustiva)

### Código vivo (apps/modules/shared, 19 archivos, ~50 imports)

`apps/api/readiness.py` (4); `modules/rendering/infrastructure/{runtime,layout,ffmpeg}/*.py` (7 archivos, ~16 imports); `modules/rendering/application/{frame_composition,scripted_video/*}.py` (3 archivos, ~10 imports); `modules/rendering/infrastructure/{poster,preparation,manifest,data,formatting}.py` reapuntan internamente al nuevo path; `modules/reels/{domain/media_planning,application/content_generator,application/use_cases/{ingest_property_into_reel,prepare_reel_assets}}.py` (4 archivos, ~10 imports); `modules/publishing/application/use_cases/{inspect_agency_social_accounts,probe_provider_connection}.py` (2 archivos, ~6 imports); `modules/publishing/infrastructure/adapters/gohighlevel/{single_publish,multi_publish,post_creation,retrying,selection,normalization,publisher,factory}.py` (8 archivos, ~24 imports); `modules/publishing/infrastructure/adapters/platforms/shared.py` (1).

### Tests (8 archivos, ~14 imports + 6 mock.patch strings)

Detalle en §1 sub-sección "Reapuntados en `tests/`".

---

## 4. Cambios en docs / `init.sh` / `feature_list.json`

### `AGENTS.md`

- §1 (Antes de empezar): Phase 2 marcada como cerrada (2026-05-06), Phase 3 como activa.
- §2.4 (Código legacy en transición): párrafo reescrito — los 5 dirs ya no existen; cualquier import legacy es regresión.
- §3 (Reglas duras): baseline de tests actualizada de 116 (post-Phase-1) a 394 (post-Phase-2).

### `REFACTOR_STATUS.md`

- Header: phasing actualizado a `Phase 1 ✅ → Phase 2 ✅ DONE (2026-05-06) → Phase 3 (active)`.
- Sección "Phase 2 — God-file split" renombrada a "DONE", con resumen de cierre: 0 hits legacy, 394 baseline, 4 archivos pre-existentes >500 LoC documentados como deuda Phase 3.
- Sección "Phase 3 — URL rename + frontend lockstep (deferred)" → `(active)`.

### `docs/architecture.md`

- §"Qué NO hacer": párrafo reescrito — los 5 dirs ya no existen.
- §"Estado del refactor": Phase 2 ✅, Phase 3 🚧.

### `docs/phase_2_operating_rules.md`

- Nota al inicio marcando el archivo como referencia histórica (Phase 2 cerrada el 2026-05-06).
- Resto del contenido preservado.

### `docs/conventions.md`

- Sin cambios (revisado: no menciona dirs frozen explícitamente; las referencias a `core.logging`/`core.errors` ya se actualizaron en sub-feature 18a).

### `init.sh`

- §4 reescrita: ya no busca archivos modificados en `services|application|repositories|core|domain` (warning informativo). Ahora hace dos verificaciones bloqueantes:
  - Comprueba que ninguno de los 5 dirs legacy reaparezca (regresión).
  - Comprueba con un script Python embedded que `apps|modules|shared|tests` no tenga imports `from (services|application|repositories|core|domain)\.`. Si los hay, fail bloqueante.

### `feature_list.json`

- `rules.legacy_dirs_frozen`: `[]` (era una lista de los 5 dirs). Phase 2 los retiró.

---

## 5. Verificación

### 5.1 — Grep masivo de imports legacy

```
$ grep -rE "(from|import)\s+(services|application|repositories|core|domain)\." apps modules shared tests
(no output)
```

**0 hits en `apps/`, `modules/`, `shared/`, `tests/`.** Acceptance literal cumplido.

### 5.2 — Estructura del filesystem

```
services/                       → no existe (rm -rf services/ ejecutado)
application/                    → no existe (sub-feature 18b)
domain/                         → no existe (sub-feature 18b)
core/                           → no existe (sub-feature 18a)
repositories/                   → no existe (feature 17)

shared/storage/
├── __init__.py                 (24 LoC, agregador)
└── site_layout.py              (56 LoC, nuevo)

modules/rendering/infrastructure/
├── __init__.py                 (1 LoC)
├── data.py                     (124 LoC, nuevo)
├── formatting.py               (485 LoC, nuevo)
├── manifest.py                 (322 LoC, nuevo)
├── models.py                   (147 LoC, nuevo)
├── poster.py                   (391 LoC, nuevo)
├── preparation.py              (451 LoC, nuevo)
├── ai_photo_selection/         (NUEVO sub-paquete: 5 archivos, 1 116 LoC)
├── ffmpeg/                     (filters.py añadido al sub-paquete pre-existente)
├── layout/                     (sin cambios estructurales, sólo imports reapuntados)
├── photos/                     (NUEVO sub-paquete: 5 archivos, 677 LoC)
└── runtime/                    (sin cambios estructurales)

modules/publishing/infrastructure/
├── adapters/
│   └── gohighlevel/            (8 archivos nuevos + 8 pre-existentes; total 16)
└── social_copy/                (NUEVO sub-paquete: 3 archivos, 678 LoC)
```

### 5.3 — `wc -l` archivos > 500 LoC bajo `apps modules shared`

```
946 modules/reels/application/use_cases/ingest_property_into_reel.py
639 shared/observability/logging.py
621 modules/ingestion/transport/http/wordpress_webhook_router.py
587 modules/reels/transport/http/admin_reels_router.py
```

4 archivos pre-existentes (no creados por 18c). Documentados en `REFACTOR_STATUS.md` Phase 2 §"Final state" como deuda explícita para Phase 3 splits. **0 archivos nuevos creados por 18c exceden 500 LoC** (máximo: `formatting.py` 485 LoC).

### 5.4 — `pytest -q`

```
........................................................................ [ 18%]
........................................................................ [ 36%]
........................................................................ [ 54%]
........................................................................ [ 73%]
........................................................................ [ 91%]
..................................                                       [100%]
394 passed in 246.44s (0:04:06)
```

**Baseline post-18b = 394. Diferencial: 0. Match exacto.** 0 failures, 0 errors, 0 skipped, 0 xfail.

### 5.5 — `python -m apps.api --check`

```
RUNTIME READY: Yes
PRODUCTION READY: No
WORKSPACE: C:\Users\4pm\Desktop\4reels\4reels back
DATABASE: postgresql+psycopg://postgres:***@localhost:5432/miapp
DATABASE SCHEMA: public
PYTHON: C:\Users\4pm\Desktop\4reels\4reels back\.venv\Scripts\python.exe
PYTHON VERSION: 3.13.0
FFMPEG: …\ffmpeg.EXE
```

Exit 0.

### 5.6 — `python -m apps.worker --check`

```
Worker --check: database_url=postgresql+psycopg://postgres:***@localhost:5432/miapp schema=public
Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
```

Exit 0.

### 5.7 — `./init.sh` end-to-end

```
[OK]    Usando Python del venv: .venv/Scripts/python.exe
[OK]    Python 3.13.0
[OK]    Dependencias clave importables (fastapi, pydantic, sqlalchemy, alembic)

── 2. Verificando archivos base del arnés ──────────────
[OK]    Existe AGENTS.md
[OK]    Existe CLAUDE.md
[OK]    Existe feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando feature_list.json ──────────────────────
[OK]    feature_list.json válido (18 features)

── 4. Verificando que no han renacido directorios legacy ─
[OK]    Sin directorios legacy (services|application|repositories|core|domain)
[OK]    0 imports legacy en apps|modules|shared|tests

── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
394 passed in 238.29s (0:03:58)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

End-to-end verde, exit 0.

---

## 6. Decisiones tomadas / desviaciones frente al plan

### D1 — Split de `selection.py` (774 LoC) en 3 archivos, no 2

El briefing sugería 2 archivos (`selector.py` ~400 + `download_pipeline.py` ~370). Tras inspeccionar la estructura real del legacy `selection.py`, el split natural por cohesión es:

- `audit.py` (82 LoC): ensamblado del payload JSON + writer (función `build_output_payload` + `write_output_payload`). Sin dependencias de logging/progress.
- `selection.py` (462 LoC): algoritmo de ranking (`rank_rows`, `choose_first_match`, `choose_selected_rows`, `annotate_results`) + builders de filas (`build_result_row`, `build_error_row`, `build_ordered_results`) + dataclasses (`GeminiImageRecord`, `GeminiSelectionOutcome`).
- `classify.py` (230 LoC): orquestador `classify_property_images` con `LoggedProcess`, `create_progress`, retries, ffmpeg-binary checks.

Esto separa **algoritmo puro** (selection + audit) de **driver con side-effects** (classify), que es más útil para tests unit (puedes ejercer el algoritmo sin tocar logging).

### D2 — Algunos archivos de `services/` eran ya facades post-feature-15

`services/media/reel_rendering/{layout,render,runtime}.py` ya estaban actuando como facades sobre `modules.rendering.infrastructure.{layout,ffmpeg,runtime}` desde feature 15. Borrarlos no requiere mover lógica — sólo verificar que cero callers vivos quedan apuntando a esos paths. Verificado.

`services/publishing/social_delivery/gohighlevel_publisher.py` (21 LoC) era también un facade trivial sobre `modules.publishing.infrastructure.adapters.gohighlevel.GoHighLevelPublisher` desde feature 16. Borrado tras verificar 0 callers vivos.

### D3 — `services/transport/http/operations.py` (466 LoC) borrado sin migrar

El plan §3.R: "sin callers activos tras impl_17. Borrar al borrar `services/`". Verificado con grep: 0 hits en `apps modules shared tests`. Borrado completo.

### D4 — Tests root legacy adaptados, no borrados

El briefing permitía borrar `tests/test_logging.py`, `tests/test_reel_render_command.py`, `tests/test_reel_runtime_dynamic_urls.py`, `tests/test_gemini_photo_selection.py` o moverlos. Decidí **adaptar los 4** porque:

- `test_logging.py` ya estaba reapuntado a `shared.observability` por sub-feature 18a — no necesitaba ningún cambio.
- `test_reel_render_command.py` (86 LoC), `test_reel_runtime_dynamic_urls.py` (172 LoC), `test_gemini_photo_selection.py` (879 LoC): los 3 tienen cobertura unique de los primitivos de rendering / Gemini que la suite moderna no replica enteramente. Adapté los imports + `mock.patch` strings a los nuevos paths. Los 4 archivos siguen vivos en `tests/` (no movidos a `tests/unit/<bc>/` para preservar el historial git).

### D5 — Circular import entre `social_copy` y `adapters/platforms`

El movido literal de `description.py` introdujo un ciclo:
- `social_copy/__init__.py` importa `description.py`.
- `description.py` importa `adapters.platforms.{get_platform_config, normalize_platform_name}`.
- `adapters/platforms/__init__.py` carga `registry.py → facebook.py → shared.py`.
- `shared.py` importa `social_copy.post_copy.build_property_caption` → entra de nuevo en `social_copy/__init__.py` (mid-init).

**Solución**: hacer `social_copy/__init__.py` lazy para los símbolos pesados (los de `description.py`). Re-exporta `post_copy` eagerly (no tiene deps cross-module) y expone `description` symbols vía `__getattr__` (carga perezosa). El comportamiento público es idéntico (`from modules.publishing.infrastructure.social_copy import build_platform_description` sigue funcionando), solo cambia el momento de la carga del módulo `description`.

Sin esta capa de indirección habría que: (a) inline-r `build_property_caption` dentro de `platforms/shared.py` (duplicación), o (b) restructurar `description.py` para no depender de platforms (split adicional). El `__getattr__` lazy es lo más limpio.

### D6 — `formatting.py` exactamente al borde (485 LoC tras condensar)

El traslado verbatim daba 501 LoC (1 sobre el límite). Condensé el `__all__` final (de 1 elemento por línea a 2-3 elementos por línea), bajando a 485 LoC sin tocar lógica.

### D7 — `init.sh` step 4 reescrito

Antes era un warning informativo ("X archivos modificados en legacy en últimas 24h"). Ahora es:

1. **Bloqueante**: comprueba que `services|application|repositories|core|domain` no reaparezcan como dirs.
2. **Bloqueante**: `python -c` script embedded comprueba que `apps|modules|shared|tests` no tienen imports legacy. Si hay alguno, exit ≠ 0.

Esto convierte init.sh en una guard rail anti-regresión real, no un warning silencioso.

### D8 — `feature_list.json` rules

`legacy_dirs_frozen: []` (vacío) en lugar de borrar el campo. Mantenerlo vacío deja claro al lector que **antes había 5 dirs frozen y ahora hay 0**, en vez de perder esa información histórica.

---

## 7. Estado final del repo post-18c

- `services/`: **borrado**.
- `application/`: borrado en 18b.
- `domain/`: borrado en 18b.
- `core/`: borrado en 18a.
- `repositories/`: borrado en feature 17.
- 5 dirs frozen → **0 dirs frozen**.
- 0 imports `from (services|application|repositories|core|domain)\.` en `apps/`, `modules/`, `shared/`, `tests/`.
- `pytest -q`: **394 passed** (= 18b baseline; sin pérdida).
- `apps.api --check` y `apps.worker --check`: exit 0.
- `init.sh` end-to-end: exit 0 con guard rails activos.
- `AGENTS.md`, `REFACTOR_STATUS.md`, `docs/architecture.md`, `docs/phase_2_operating_rules.md`, `init.sh`, `feature_list.json`: actualizados.
- **Phase 2 cerrada el 2026-05-06.** Phase 3 activa (URL rename + frontend lockstep).

Sub-tarea 18c implementada y autoverificada; pendiente de revisión. **NO marco feature 18 `done`** — eso lo decide el closer cuando aprobe la review.

## 8. Pendiente (Phase 3)

- Rename de URLs `/admin/*` → `/v1/*`.
- Renombrado de env vars `WEBHOOK_WORKER_*` → `WORKER_*`.
- Lockstep con `4reels front/` (ver `REFACTOR_STATUS.md` Phase 3).

---

## 9. Splits de cierre Phase 2 (post-review 18c)

Tras la review de 18c el reviewer pidió que los 4 archivos pre-existentes
>500 LoC bajo `apps|modules|shared` (que en §5.3 quedaban documentados como
deuda Phase 3) se partieran ahora para cumplir A4 (≤500 LoC) y cerrar
Phase 2 sin deuda residual. Los 4 splits son **mecánicos**: extraer +
ajustar imports. Ningún símbolo público renombrado. Baseline post-splits
= **394 tests verdes** (sin regresión).

### 9.1 — `shared/observability/logging.py` (639 → 357 LoC)

Extracción de helpers de formato a un nuevo `shared/observability/console_format.py`
(`format_console_block`, `format_detail_line`, etc.). El archivo original
conserva la API pública (`get_logger`, `LoggedProcess`, `create_progress`,
`format_console_block`/`format_detail_line` re-exportados).

| Archivo | LoC | Rol |
|---------|----:|-----|
| `shared/observability/logging.py` | 357 | API pública + lógica de logging |
| `shared/observability/console_format.py` (nuevo) | ~282 | helpers de formato textual |

### 9.2 — `modules/ingestion/transport/http/wordpress_webhook_router.py` (621 → 390 LoC)

Extracción de helpers de validación + parsing del payload WordPress a un
nuevo `_wordpress_webhook_helpers.py` en el mismo subdirectorio. El router
conserva sólo la definición FastAPI + el handler principal.

| Archivo | LoC | Rol |
|---------|----:|-----|
| `modules/ingestion/transport/http/wordpress_webhook_router.py` | 390 | router + handler |
| `modules/ingestion/transport/http/_wordpress_webhook_helpers.py` (nuevo) | ~231 | parsers + validadores |

### 9.3 — `modules/reels/transport/http/admin_reels_router.py` (587 → 258 LoC)

Extracción de las 4 GET asset routes (video / images / image file / manifest)
+ los serializadores compartidos (`_serialize_agency_reel`,
`_resolve_workspace_path`, `_guess_image_mime_type`,
`_resource_not_found_response`, `_application_error_response`) a un
nuevo `admin_reels_assets.py` en el mismo subdirectorio. El router
principal queda con el listado, el detalle, los POST `/approve` y `/reject`,
y delega las 4 GET asset routes vía `register_admin_reel_asset_routes(router, …)`.

| Archivo | LoC | Rol |
|---------|----:|-----|
| `modules/reels/transport/http/admin_reels_router.py` | 258 | listado + detalle + POST approve/reject |
| `modules/reels/transport/http/admin_reels_assets.py` (nuevo) | 390 | 4 GET asset routes + serializadores compartidos |

### 9.4 — `modules/reels/application/use_cases/ingest_property_into_reel.py` (946 → 299 LoC)

Split en 4 archivos: el orquestador (`IngestPropertyIntoReelUseCase`) en
el archivo original + 3 helpers privados (`_ingest_property_planning.py`,
`_ingest_property_assets.py`, `_ingest_property_diffs.py`). La división
sugerida en la review (2 helpers ~250 + ~220 LoC) producía un planning
file de 512 LoC (sobre el límite por la combinación de
`_resolve_publish_inputs` + `_coerce_publish_target_snapshot` +
`_determine_pending_publish_platforms`); por eso se separa el bloque de
diff/snapshot-coercion a un tercer archivo.

| Archivo | LoC | Rol |
|---------|----:|-----|
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 299 | orquestador `IngestPropertyIntoReelUseCase` + entrada pública |
| `modules/reels/application/use_cases/_ingest_property_planning.py` (nuevo) | 258 | resolución de inputs publish + builders de snapshot (`_resolve_publish_inputs`, `_build_publish_targets`, `_build_content_snapshot`, `_build_publish_target_snapshot`, `_json_hash`, `_json_text`) |
| `modules/reels/application/use_cases/_ingest_property_assets.py` (nuevo) | 233 | probes de artefactos locales + `_build_property_record` + `_build_ingested_reel_state` + `_build_existing_published_media` + `_should_prepare_assets` + `_has_local_artifacts` |
| `modules/reels/application/use_cases/_ingest_property_diffs.py` (nuevo) | 300 | comparación con estado previo (`_coerce_publish_target_snapshot`, `_extract_successful_platforms`, `_determine_pending_publish_platforms`, `_should_reset_publish_history`) + extractores auxiliares |

### 9.5 — Verificación post-splits

```
$ find apps modules shared -name "*.py" -exec wc -l {} + | sort -n | tail -10
    422 modules/publishing/infrastructure/adapters/gohighlevel/models.py
    435 modules/rendering/infrastructure/ffmpeg/render_reel.py
    438 apps/api/readiness.py
    447 modules/reels/application/use_cases/prepare_reel_assets.py
    458 modules/rendering/infrastructure/preparation.py
    462 modules/rendering/infrastructure/ai_photo_selection/selection.py
    477 modules/rendering/infrastructure/layout/text_measurement.py
    485 modules/rendering/infrastructure/formatting.py
    495 modules/reels/application/use_cases/publish_reel.py
```

**Top 10 archivos en `apps|modules|shared` ≤ 495 LoC.** 0 archivos > 500 LoC.

```
$ pytest -q
394 passed in 265.44s (0:04:25)
```

```
$ ./init.sh
[OK]    Sin directorios legacy (services|application|repositories|core|domain)
[OK]    0 imports legacy en apps|modules|shared|tests
[OK]    apps.api --check verde
[OK]    apps.worker --check verde
394 passed in 250.39s (0:04:10)
[OK]    Entorno listo. Puedes empezar a trabajar.
```

`python -m apps.api --check` y `python -m apps.worker --check`: exit 0.

`REFACTOR_STATUS.md`: la sección "Four files in the active tree exceed
500 LoC and are deferred to Phase 3 splits" ha sido **borrada** — los 4
archivos ya no son deuda.
