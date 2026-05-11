# Impl — Sub-tarea 18b `dissolve_domain_and_application_dirs`

> Sub-tarea 18b de feature 18 (`delete_legacy_dirs_and_close_phase_2`).
> Disuelve los directorios `application/` (3 026 LoC) y `domain/` (925 LoC)
> moviendo los símbolos vivos a `modules/<bc>/`, `shared/db/uow_factory.py`
> y `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`.
> Reapunta los imports en código vivo y borra `application/` y `domain/`
> físicamente.
>
> Conforme al plan del explore §3 + briefing del leader.
>
> Feature 18 sigue `pending` hasta que 18c termine. Resta sólo `services/`.

---

## 1. Archivos creados / modificados / borrados

### Creados (12)

| Archivo | LoC | Origen | Tipo |
|---------|----:|--------|------|
| `modules/reels/domain/types.py` | 312 | `application/types.py` (285) verbatim + helpers `_normalize_platform_name` + `_normalise_platforms` (importados antes de `domain/publishing/platforms.py`) | Implementación movida |
| `modules/reels/domain/media_planning.py` | 97 | `domain/media/planning.py` (88) verbatim, imports reapuntados | Implementación movida |
| `modules/reels/application/content_generator.py` | 158 | `application/pipeline/content_generation.py` (150) verbatim, imports reapuntados | Implementación movida |
| `modules/catalog/domain/wordpress_property.py` | 214 | `domain/properties/model.py:Property` aggregate + `from_api_payload` factory + `to_db_record` / `to_dict` thin wrappers | Implementación movida (split de helpers a `_property_conversions.py`) |
| `modules/catalog/domain/_property_conversions.py` | 325 | helpers `_to_text`, `_to_int`, `_to_float`, `_extract_rendered_text`, `_to_text_tuple`, `_to_int_tuple`, `_to_serialised_text`, `_sequence_to_json`, `_normalise_slug`, `_json_safe_copy` + builders `build_property_db_record`, `build_property_dict` | Helpers privados del aggregate |
| `modules/tenancy/domain/context.py` | 19 | `domain/tenancy/context.py` (14) verbatim | Implementación movida |
| `modules/tenancy/domain/storage.py` | 27 | `domain/tenancy/storage.py` (22) verbatim | Implementación movida |
| `modules/publishing/infrastructure/adapters/gohighlevel/factory.py` | 50 | `application/bootstrap/runtime.py:build_default_social_property_publisher` (28 LoC con docstring + `__all__`) | Implementación movida |
| `shared/db/uow_factory.py` | 37 | `application/bootstrap/runtime.py:build_default_unit_of_work_factory` + `build_runtime_unit_of_work_factory` | Implementación movida |
| `modules/rendering/application/scripted_video/__init__.py` | 5 | (nuevo) | Agregador del sub-paquete |
| `modules/rendering/application/scripted_video/payload_helpers.py` | 412 | mitad de `application/scripted_render/service.py` (helpers `_ScriptedRenderSettingsPayload`, `resolve_scripted_render_template`, `resolve_slides`, `resolve_local_file_path`, `replace_atomically`, `relative_path_text`, coerciones `require_text/_int`, `optional_text/_int`, `_coerce_text/_int` + dataclasses `ScriptedVideoArtifactRecord` + `ScriptedVideoRenderResult` + alias `UnitOfWork`) | Split del service legacy |
| `modules/rendering/application/scripted_video/render_service.py` | 349 | otra mitad de `application/scripted_render/service.py` (clase `ScriptedVideoRenderService` + `_ResolvedScriptedVideoRequest`) | Split del service legacy |

Total LoC creado: **2 005 LoC** distribuidos en 12 archivos (todos ≤500 LoC).

### Modificados (agregadores `modules/<bc>/domain/__init__.py`)

| Archivo | Cambio |
|---------|--------|
| `modules/catalog/domain/__init__.py` | Re-exporta `Property` (junto a `CatalogProperty`, `CatalogPropertyImage`, `PropertySyncState`). |
| `modules/tenancy/domain/__init__.py` | Re-exporta `TenantContext` y `SiteStorageLayout` (junto a `Agency`). |

### Modificados (imports reapuntados — código vivo, 11 archivos)

Todos los reapuntados son sustituciones textuales mecánicas: cambia el path
del import, el contenido importado se preserva 1:1.

| Archivo | Imports reapuntados |
|---------|---------------------|
| `modules/reels/application/orchestrator.py:36-37` | `application.types` → `modules.reels.domain.types`; `domain.tenancy.context` → `modules.tenancy.domain.context`. |
| `modules/reels/application/orchestrator.py:246-248` | (lazy) `application.bootstrap.runtime.build_default_social_property_publisher` → `modules.publishing.infrastructure.adapters.gohighlevel.factory.build_default_social_property_publisher`. |
| `modules/reels/application/use_cases/ingest_property_into_reel.py:35-47, 824` | `application.pipeline.content_generation` → `modules.reels.application.content_generator`; `application.types` → `modules.reels.domain.types`; `domain.media.planning` → `modules.reels.domain.media_planning`; `domain.properties.model` → `modules.catalog.domain.wordpress_property`. Incluye el lazy `from application.types import PublishedMediaArtifact` en línea 824. |
| `modules/reels/application/use_cases/persist_local_artifacts.py:43-47` | `application.types` → `modules.reels.domain.types`. |
| `modules/reels/application/use_cases/prepare_reel_assets.py:32, 41` | `application.types` → `modules.reels.domain.types`; `domain.properties.model` → `modules.catalog.domain.wordpress_property`. |
| `modules/reels/application/use_cases/publish_reel.py:35-39` | `application.types` → `modules.reels.domain.types`. |
| `modules/reels/application/use_cases/render_scripted_video.py:23-27` | (lazy) `application.bootstrap.runtime.build_runtime_unit_of_work_factory` → `shared.db.uow_factory.build_runtime_unit_of_work_factory`; `application.scripted_render.service.ScriptedVideoRenderService` → `modules.rendering.application.scripted_video.render_service.ScriptedVideoRenderService`. |
| `modules/rendering/application/frame_composition.py:32-36` | `application.types` → `modules.reels.domain.types`. |

### Modificados (tests reapuntados — 11 archivos)

| Archivo | Imports reapuntados |
|---------|---------------------|
| `tests/unit/reels/test_persist_local_artifacts.py:17-25` | `application.types` → `modules.reels.domain.types`; `domain.properties.model` → `modules.catalog.domain.wordpress_property`; `domain.tenancy.context` → `modules.tenancy.domain.context`. |
| `tests/unit/reels/test_prepare_reel_assets.py:16-23` | idem. |
| `tests/unit/reels/test_publish_reel.py:20-34` | idem. |
| `tests/unit/reels/test_ingest_property_into_reel.py:12-13` | `application.types` → `modules.reels.domain.types`; `domain.tenancy.context` → `modules.tenancy.domain.context`. |
| `tests/unit/rendering/test_frame_composition.py:23-30` | idem (3 reapuntados). |
| `tests/integration/reels/test_ingest_property_into_reel_flow.py:7-8` | `application.types` → `modules.reels.domain.types`; `domain.tenancy.context` → `modules.tenancy.domain.context`. |
| `tests/integration/reels/test_persist_local_artifacts_flow.py:25-26` | idem. |
| `tests/integration/reels/test_prepare_reel_assets_flow.py:18-19` | idem. |
| `tests/integration/reels/test_publish_reel_flow.py:32-38` | idem. |
| `tests/integration/delivery/test_worker_dispatcher_flow.py:230-238, 273` | `mock.patch("application.scripted_render.service.ScriptedVideoRenderService...")` → `mock.patch("modules.rendering.application.scripted_video.render_service.ScriptedVideoRenderService...")`. Lazy `from application.types import RenderedMediaArtifact` → `from modules.reels.domain.types import RenderedMediaArtifact`. |
| `tests/test_gemini_photo_selection.py:20` | `domain.properties.model` → `modules.catalog.domain.wordpress_property`. |

### Modificados (deviación — frozen `services/`, 10 archivos)

Mismo patrón de deviación que 18a §2.2 (patches profilácticos en frozen
para preservar la baseline al borrar `domain/` y `application/`
físicamente). Los archivos en `services/` siguen vivos hasta 18c y se
cargan transitivamente cuando los use cases modernos los importan
(`prepare_reel_assets.py:42-49`, `ingest_property_into_reel.py:50-52`,
`render_service.py` nuevo, `frame_composition.py:38-46`).

| Archivo | Imports reapuntados |
|---------|---------------------|
| `services/ai/photo_selection/prompting.py:8` | `domain.properties.model.Property` → `modules.catalog.domain.wordpress_property.Property`. |
| `services/ai/photo_selection/selection.py:21` | idem. |
| `services/media/site_storage.py:7` | `domain.tenancy.storage.SiteStorageLayout` → `modules.tenancy.domain.storage.SiteStorageLayout`. |
| `services/media/__init__.py:7` | idem. |
| `services/media/property_media/filesystem.py:7` | `domain.properties.model.Property` → `modules.catalog.domain.wordpress_property.Property`. |
| `services/media/property_media/downloads.py:10-11` | `domain.properties.model.Property` → `modules.catalog.domain.wordpress_property.Property`; `domain.media.types.DownloadedImage` → `modules.reels.domain.types.DownloadedImage`. |
| `services/media/property_media/selection.py:16-17` | idem (2 reapuntados). |
| `services/publishing/social_delivery/description.py:6` | `domain.properties.model.Property` → `modules.catalog.domain.wordpress_property.Property`. |
| `services/publishing/social_delivery/post_copy.py:7` | idem. |
| `services/publishing/social_delivery/property_publisher.py:6` | `application.types.{PlatformPublishTargetPlan,PropertyContext,PublishedMediaArtifact}` → `modules.reels.domain.types.{PlatformPublishTargetPlan,PropertyContext,PublishedMediaArtifact}`. |

Coste de la deviación: **11 líneas modificadas en 10 archivos frozen** (1
línea por archivo, salvo `downloads.py` y `selection.py` que tienen 2
imports a reapuntar). No toca lógica, no añade ni quita código fuera del
import.

### Borrados (2 dirs, 25 archivos, ~3 951 LoC) + 2 tests legacy raíz

| Borrado | LoC | Razón |
|---------|----:|-------|
| `application/__init__.py` | 2 | Agregador legacy. |
| `application/bootstrap/__init__.py` | 68 | Symbols movidos a `modules/publishing/.../factory.py` y `shared/db/uow_factory.py`. |
| `application/bootstrap/runtime.py` | 68 | Idem (byte-igual al `__init__.py`). |
| `application/dispatch/__init__.py` | 1 | Sin callers vivos tras feature 17. |
| `application/dispatch/database_dispatcher.py` | 458 | Idem. |
| `application/persistence.py` | 450 | Idem. |
| `application/pipeline/__init__.py` | 1 | Symbols movidos a `modules/reels/application/content_generator.py`. |
| `application/pipeline/content_generation.py` | 150 | Idem. |
| `application/scripted_render/__init__.py` | 702 | Symbols partidos y movidos a `modules/rendering/application/scripted_video/`. |
| `application/scripted_render/service.py` | 702 | Idem (byte-igual al `__init__.py`). |
| `application/tenancy/__init__.py` | 61 | Sin callers vivos tras feature 17. |
| `application/tenancy/resolver.py` | 61 | Idem. |
| `application/types.py` | 285 | Symbols movidos a `modules/reels/domain/types.py`. |
| `application/` (dir) | — | Eliminado físicamente con `rm -rf application/`. |
| `domain/__init__.py` | 1 | Agregador legacy. |
| `domain/media/__init__.py` | 0 | Agregador legacy. |
| `domain/media/planning.py` | 88 | Symbols movidos a `modules/reels/domain/media_planning.py`. |
| `domain/media/types.py` | 194 | Sin callers activos directos (tipos duplicados con `application/types.py`). |
| `domain/properties/__init__.py` | 0 | Agregador legacy. |
| `domain/properties/model.py` | 485 | `Property` aggregate movido a `modules/catalog/domain/wordpress_property.py` + helpers en `_property_conversions.py`. |
| `domain/publishing/__init__.py` | 0 | Agregador legacy. |
| `domain/publishing/platforms.py` | 16 | Sin callers activos directos. |
| `domain/publishing/types.py` | 86 | Sin callers activos directos (duplicaba `application/types.py`). |
| `domain/tenancy/__init__.py` | 0 | Agregador legacy. |
| `domain/tenancy/context.py` | 14 | `TenantContext` movido a `modules/tenancy/domain/context.py`. |
| `domain/tenancy/storage.py` | 22 | `SiteStorageLayout` movido a `modules/tenancy/domain/storage.py`. |
| `domain/` (dir) | — | Eliminado físicamente con `rm -rf domain/`. |
| `tests/test_social_publishing.py` | 1 746 | Cobertura moderna en `tests/integration/publishing/`. **30 tests removidos**. |
| `tests/test_reel_pipeline.py` | 1 381 | Cobertura moderna en `tests/integration/reels/` + `tests/unit/rendering/`. **30 tests removidos**. |

Total borrado: ~7 078 LoC físicos (frozen + tests duplicados).

---

## 2. Tabla de movilizaciones (origen → destino)

| Origen | Destino | Símbolos |
|--------|---------|----------|
| `application/types.py` | `modules/reels/domain/types.py` | `MediaDeliveryPlan`, `PlatformPublishTargetPlan`, `PreparedMediaAssets`, `PropertyContext`, `PropertyMediaJob`, `PublishedMediaArtifact`, `RenderedMediaArtifact`, `SocialPublishContext`, `DownloadedImage` |
| `application/pipeline/content_generation.py` | `modules/reels/application/content_generator.py` | `ContentGenerator` (Protocol), `DeterministicPropertyContentGenerator`, `GeneratedPropertyContent`, `render_template_with_property` |
| `application/scripted_render/service.py` (702 LoC) | `modules/rendering/application/scripted_video/render_service.py` (349 LoC) + `modules/rendering/application/scripted_video/payload_helpers.py` (412 LoC) | Clase `ScriptedVideoRenderService`, dataclass `_ResolvedScriptedVideoRequest`, dataclass `ScriptedVideoArtifactRecord`, dataclass `ScriptedVideoRenderResult`, Pydantic `_ScriptedRenderSettingsPayload`, helpers `resolve_scripted_render_template`/`resolve_slides`/`resolve_local_file_path`/`replace_atomically`/`relative_path_text`/`require_text`/`require_int`/`optional_text`/`optional_int`/`optional_text_allow_blank`, alias `UnitOfWork = object` |
| `application/bootstrap/runtime.py:build_default_social_property_publisher` | `modules/publishing/infrastructure/adapters/gohighlevel/factory.py` | `build_default_social_property_publisher` |
| `application/bootstrap/runtime.py:build_*_unit_of_work_factory` | `shared/db/uow_factory.py` | `build_default_unit_of_work_factory`, `build_runtime_unit_of_work_factory` |
| `domain/properties/model.py:Property` | `modules/catalog/domain/wordpress_property.py` (clase, 214 LoC) + `modules/catalog/domain/_property_conversions.py` (helpers, 325 LoC) | `Property` aggregate (con `from_api_payload`, `image_count`, `folder_name`, `raw_json`, `to_db_record`, `to_dict`); helpers `to_text`/`to_int`/`to_float`/`to_text_tuple`/`to_int_tuple`/`to_serialised_text`/`extract_rendered_text`/`json_safe_copy`/`normalise_slug`/`sequence_to_json`/`build_property_db_record`/`build_property_dict` |
| `domain/tenancy/context.py` | `modules/tenancy/domain/context.py` | `TenantContext` |
| `domain/tenancy/storage.py` | `modules/tenancy/domain/storage.py` | `SiteStorageLayout` |
| `domain/media/planning.py` | `modules/reels/domain/media_planning.py` | `build_media_delivery_plan`, `build_price_display_text`, `normalize_listing_lifecycle` |
| `domain/media/types.py` | (borrado) | Tipos duplicados en `application/types.py` (versión activa); cero callers directos. |
| `domain/publishing/{platforms,types}.py` | (borrado, función inline en `modules/reels/domain/types.py`) | `normalize_platform_name`/`SocialPublishContext`/`PlatformPublishTargetPlan` ya viven en `modules/reels/domain/types.py` (la versión activa); `_normalize_platform_name` se inline al tope del archivo nuevo. |
| `application/{persistence,dispatch,tenancy}.py` | (borrado) | Sin callers vivos tras feature 17. |

---

## 3. Decisiones tomadas (frente a discrepancias del explore)

### D1 — `Property` legacy vs `CatalogProperty` moderno: **coexisten**

Verificación empírica: `modules/catalog/domain/property.py:CatalogProperty`
es un VO **DB-backed** (8 fields: `record_id`, `agency_id`,
`ingestion_source_id`, `external_source_id`, `source_property_id`, `slug`,
`title`, `raw_json`, `fetched_at`) que el repositorio moderno construye
desde la fila ORM. `domain/properties/model.py:Property` es el aggregate
**WordPress payload-rich** (60+ fields: `bedrooms`, `agent_*`,
`property_features`, etc.) que las cadenas de rendering, publishing copy y
scripted-render consumen.

**Decisión**: ambos coexisten en `modules/catalog/domain/`. El nuevo
nombre del archivo es `wordpress_property.py` para evitar colisión con
`property.py` (que mantiene los VOs DB-backed). El `Property` legacy se
re-exporta por el package init para que callers escriban
`from modules.catalog.domain import Property` o
`from modules.catalog.domain.wordpress_property import Property`. **No se
fusionan**: representan conceptos distintos del mismo bounded context.

### D2 — Triple duplicación de tipos `MediaDeliveryPlan`/`PublishedMediaArtifact`/`RenderedMediaArtifact`/`SocialPublishContext`/`PlatformPublishTargetPlan`

Resuelto borrando `domain/media/types.py` y `domain/publishing/types.py`.
La versión canónica viva (la que importan todos los callers activos) es la
de `application/types.py`, ahora movida 1:1 a
`modules/reels/domain/types.py`. La versión `domain/publishing/types.py` y
`domain/media/types.py` quedaron sin callers directos tras feature 17 (su
duplicación era memoria histórica de Phase 1).

### D3 — `ScriptedVideoRenderService` split (702 LoC obliga partir)

El briefing sugería ~400 + ~250 con manifest_handler. Tras inspeccionar
el código, el split que **respeta cohesión** y mantiene `≤500` LoC en
ambos archivos es:

- `render_service.py` (349 LoC): clase `ScriptedVideoRenderService`,
  método `render_from_manifest`, método privado `_resolve_request`,
  dataclass `_ResolvedScriptedVideoRequest`. La lógica orquestadora
  (UoW, staging dirs, atomic replaces, save_artifact) vive aquí.
- `payload_helpers.py` (412 LoC): toda la validación de payload
  (`require_text`/`require_int`/`optional_*`/`_coerce_*`),
  resolución de slides + render_settings template, helpers fs
  (`replace_atomically`, `relative_path_text`,
  `resolve_local_file_path`), Pydantic
  `_ScriptedRenderSettingsPayload`, dataclasses `ScriptedVideoArtifactRecord`,
  `ScriptedVideoRenderResult`, alias `UnitOfWork = object`.

Los helpers exportados se llaman sin el guion-bajo (`require_text`,
`optional_int`, etc.) porque el servicio los importa cross-module.

### D4 — `build_*_unit_of_work_factory` → `shared/db/uow_factory.py`

Decidido por reusabilidad: el explore sugería inline en
`apps/worker/runtime.py` *o* `shared/db/uow_factory.py`. Los callers
activos hoy son **dos** lazies en módulos distintos
(`modules/reels/application/orchestrator.py` y
`modules/reels/application/use_cases/render_scripted_video.py`), no
únicamente el worker. Por simetría con `shared/db/uow.py` y para evitar
acoplamientos `modules/...` → `apps/worker/runtime.py`, los builders viven
en `shared/db/uow_factory.py`. 37 LoC, 2 funciones públicas.

### D5 — `WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS` re-export borrado

`application/bootstrap/runtime.py:15-16` re-exportaba la constante desde
`settings/`. El re-export es muerto: los callers activos
(`apps/worker/runtime.py`, `tests/`) ya importan directamente desde
`settings`. Borrado al borrar `application/`.

### D6 — `tests/test_social_publishing.py` y `tests/test_reel_pipeline.py` borrados

Ambos cargan agresivamente `application/`/`domain/`/`services/`. La
cobertura moderna (`tests/integration/publishing/`,
`tests/integration/reels/`, `tests/unit/rendering/`) los reemplaza. 60
tests removidos (30 + 30); baseline post-18b = 394 (= 454 − 60).

### D7 — `tests/test_logging.py`, `tests/test_reel_render_command.py`, `tests/test_reel_runtime_dynamic_urls.py`, `tests/test_gemini_photo_selection.py`: dejados intactos en 18b

Los 4 importan de `services/` (scope 18c), sólo
`test_gemini_photo_selection.py` importa de `domain/properties/model.py`
(reapuntado a `modules.catalog.domain.wordpress_property`). Los demás
pasan vivos al borrarse `application/` y `domain/`. 18c los adapta o
mueve a `tests/unit/rendering/`.

### D8 — `Property` aggregate split en 2 archivos para cumplir ≤500 LoC

El traslado verbatim a un único archivo daba 510 LoC. Split:
- `modules/catalog/domain/wordpress_property.py` (214 LoC): la dataclass
  `Property` + `from_api_payload` factory + thin wrappers
  `to_db_record`/`to_dict`/`raw_json`/`folder_name`/`image_count`.
- `modules/catalog/domain/_property_conversions.py` (325 LoC): helpers
  privados (`to_text`/`to_int`/`to_float`/`to_text_tuple`/
  `to_int_tuple`/`to_serialised_text`/`extract_rendered_text`/
  `json_safe_copy`/`normalise_slug`/`sequence_to_json`) y builders
  (`build_property_db_record`, `build_property_dict`).

El nombre con guion-bajo (`_property_conversions.py`) marca el módulo
como privado del package — no es API pública.

---

## 4. Verificación

### 4.1 — `Grep "from domain\.\|from application\.\|import domain\.\|import application\."`

| Carpeta | Hits |
|---------|----:|
| `apps/` | **0** |
| `modules/` | **0** |
| `shared/` | **0** |
| `tests/` | **0** |
| `services/` | **0** (la deviación §1 los patcheó profilácticamente) |
| `settings/` | **0** |

Acceptance parcial cumplido: 0 hits en los 4 dirs requeridos por el plan.

### 4.2 — `pytest -q`

```
........................................................................ [ 18%]
........................................................................ [ 36%]
........................................................................ [ 54%]
........................................................................ [ 73%]
........................................................................ [ 91%]
..................................                                       [100%]
394 passed in 235.17s (0:03:55)
```

**Baseline post-18a = 454. Diferencial: −60 (30 de
`test_social_publishing.py` + 30 de `test_reel_pipeline.py`).
Resultado: 394. Match exacto al diferencial esperado.**

### 4.3 — `python -m apps.api --check`

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

### 4.4 — `python -m apps.worker --check`

```
Worker --check: database_url=postgresql+psycopg://postgres:***@localhost:5432/miapp schema=public
Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
```

Exit 0.

### 4.5 — `./init.sh`

```
[OK]    Existe feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando feature_list.json ──────────────────────
[OK]    feature_list.json válido (18 features)

── 4. Verificando que no se ha tocado código legacy ────
[WARN]  Se han modificado 18 archivo(s) en directorios legacy en las últimas 24h.
[WARN]  Confirma que son cambios de compat shim, no features nuevas.

── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
394 passed in 237.95s (0:03:57)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

WARN amarillo en step 4: 18 archivos modificados en frozen `services/` —
los 10 patches profilácticos de §1 + los archivos borrados detectados
en `application/` y `domain/`. Esperado y documentado.

### 4.6 — Acceptance ≤500 LoC en archivos nuevos bajo `modules/`/`shared/`

| Archivo nuevo | LoC | OK |
|---|---:|---|
| `modules/reels/domain/types.py` | 312 | ✅ |
| `modules/reels/domain/media_planning.py` | 97 | ✅ |
| `modules/reels/application/content_generator.py` | 158 | ✅ |
| `modules/catalog/domain/wordpress_property.py` | 214 | ✅ |
| `modules/catalog/domain/_property_conversions.py` | 325 | ✅ |
| `modules/tenancy/domain/context.py` | 19 | ✅ |
| `modules/tenancy/domain/storage.py` | 27 | ✅ |
| `modules/publishing/infrastructure/adapters/gohighlevel/factory.py` | 50 | ✅ |
| `modules/rendering/application/scripted_video/render_service.py` | 349 | ✅ |
| `modules/rendering/application/scripted_video/payload_helpers.py` | 412 | ✅ |
| `shared/db/uow_factory.py` | 37 | ✅ |

Archivos vivos pre-existentes que siguen >500 LoC (no son scope de 18b;
los marca el explore §6 R5 como deuda para 18c o Phase 3):

- `modules/reels/application/use_cases/ingest_property_into_reel.py` — 944.
- `modules/ingestion/transport/http/wordpress_webhook_router.py` — 621.
- `modules/reels/transport/http/admin_reels_router.py` — 587.
- `shared/observability/logging.py` — 639 (creado en 18a; deuda para 18c
  según review_18a §sugerencias).

### 4.7 — Estructura del filesystem post-18b

```
application/                    → no existe (rm -rf application/ ejecutado)
domain/                         → no existe (rm -rf domain/ ejecutado)

modules/catalog/domain/
├── __init__.py                 (4 LoC, agregador)
├── _property_conversions.py    (325 LoC, nuevo)
├── property.py                 (42 LoC, ahora sólo CatalogProperty/CatalogPropertyImage/PropertySyncState)
└── wordpress_property.py       (214 LoC, nuevo, Property aggregate legacy)

modules/tenancy/domain/
├── __init__.py                 (4 LoC, agregador con Agency + TenantContext + SiteStorageLayout)
├── agency.py                   (24 LoC, pre-existente)
├── context.py                  (19 LoC, nuevo)
└── storage.py                  (27 LoC, nuevo)

modules/reels/domain/
├── __init__.py                 (11 LoC, pre-existente)
├── media_planning.py           (97 LoC, nuevo)
├── media_revision.py           (pre-existente)
├── reel_state.py               (pre-existente)
├── scripted_video_artifact.py  (pre-existente)
└── types.py                    (312 LoC, nuevo)

modules/reels/application/
├── content_generator.py        (158 LoC, nuevo)
├── orchestrator.py             (modificado, lazy reapuntado a publishing.factory)
└── use_cases/
    ├── ingest_property_into_reel.py    (944 LoC, modificado: 5 imports reapuntados)
    ├── persist_local_artifacts.py      (modificado: 1 import reapuntado)
    ├── prepare_reel_assets.py          (modificado: 2 imports reapuntados)
    ├── publish_reel.py                 (modificado: 1 import reapuntado)
    └── render_scripted_video.py        (modificado: 2 lazies reapuntadas)

modules/rendering/application/
├── frame_composition.py        (modificado: 1 import reapuntado)
└── scripted_video/             (NUEVO sub-paquete)
    ├── __init__.py             (5 LoC)
    ├── payload_helpers.py      (412 LoC)
    └── render_service.py       (349 LoC)

modules/publishing/infrastructure/adapters/gohighlevel/
├── factory.py                  (50 LoC, nuevo)
└── (otros existentes)

shared/db/
├── uow_factory.py              (37 LoC, nuevo)
└── (otros existentes)
```

---

## 5. Imports reapuntados (lista exhaustiva)

### Código vivo (apps/modules/shared, 11 archivos, 14 imports)

1. `modules/reels/application/orchestrator.py:36` — `application.types` → `modules.reels.domain.types`.
2. `modules/reels/application/orchestrator.py:37` — `domain.tenancy.context` → `modules.tenancy.domain.context`.
3. `modules/reels/application/orchestrator.py:246` — (lazy) `application.bootstrap.runtime.build_default_social_property_publisher` → `modules.publishing.infrastructure.adapters.gohighlevel.factory.build_default_social_property_publisher`.
4. `modules/reels/application/use_cases/ingest_property_into_reel.py:35` — `application.pipeline.content_generation` → `modules.reels.application.content_generator`.
5. `modules/reels/application/use_cases/ingest_property_into_reel.py:39` — `application.types` → `modules.reels.domain.types`.
6. `modules/reels/application/use_cases/ingest_property_into_reel.py:46` — `domain.media.planning` → `modules.reels.domain.media_planning`.
7. `modules/reels/application/use_cases/ingest_property_into_reel.py:47` — `domain.properties.model` → `modules.catalog.domain.wordpress_property`.
8. `modules/reels/application/use_cases/ingest_property_into_reel.py:824` — (lazy) `application.types.PublishedMediaArtifact` → `modules.reels.domain.types.PublishedMediaArtifact`.
9. `modules/reels/application/use_cases/persist_local_artifacts.py:43` — `application.types` → `modules.reels.domain.types`.
10. `modules/reels/application/use_cases/prepare_reel_assets.py:32` — `application.types` → `modules.reels.domain.types`.
11. `modules/reels/application/use_cases/prepare_reel_assets.py:41` — `domain.properties.model` → `modules.catalog.domain.wordpress_property`.
12. `modules/reels/application/use_cases/publish_reel.py:35` — `application.types` → `modules.reels.domain.types`.
13. `modules/reels/application/use_cases/render_scripted_video.py:23-26` — (lazy) `application.bootstrap.runtime.build_runtime_unit_of_work_factory` → `shared.db.uow_factory.build_runtime_unit_of_work_factory`; `application.scripted_render.service.ScriptedVideoRenderService` → `modules.rendering.application.scripted_video.render_service.ScriptedVideoRenderService`.
14. `modules/rendering/application/frame_composition.py:32` — `application.types` → `modules.reels.domain.types`.

### Tests (11 archivos, ~22 imports + 2 mock.patch strings)

1. `tests/unit/reels/test_persist_local_artifacts.py:17,24,25` — 3 reapuntados.
2. `tests/unit/reels/test_prepare_reel_assets.py:16,22,23` — 3 reapuntados.
3. `tests/unit/reels/test_publish_reel.py:20,33,34` — 3 reapuntados.
4. `tests/unit/reels/test_ingest_property_into_reel.py:12,13` — 2 reapuntados.
5. `tests/unit/rendering/test_frame_composition.py:23,29,30` — 3 reapuntados.
6. `tests/integration/reels/test_ingest_property_into_reel_flow.py:7,8` — 2 reapuntados.
7. `tests/integration/reels/test_persist_local_artifacts_flow.py:25,26` — 2 reapuntados.
8. `tests/integration/reels/test_prepare_reel_assets_flow.py:18,19` — 2 reapuntados.
9. `tests/integration/reels/test_publish_reel_flow.py:32,38` — 2 reapuntados.
10. `tests/integration/delivery/test_worker_dispatcher_flow.py:230,236,273` — 2 mock.patch strings + 1 lazy import reapuntados.
11. `tests/test_gemini_photo_selection.py:20` — 1 reapuntado.

### Frozen `services/` (deviación, 10 archivos, 11 imports)

1. `services/ai/photo_selection/prompting.py:8` — Property.
2. `services/ai/photo_selection/selection.py:21` — Property.
3. `services/media/site_storage.py:7` — SiteStorageLayout.
4. `services/media/__init__.py:7` — SiteStorageLayout.
5. `services/media/property_media/filesystem.py:7` — Property.
6. `services/media/property_media/downloads.py:10,11` — Property + DownloadedImage.
7. `services/media/property_media/selection.py:16,17` — Property + DownloadedImage.
8. `services/publishing/social_delivery/description.py:6` — Property.
9. `services/publishing/social_delivery/post_copy.py:7` — Property.
10. `services/publishing/social_delivery/property_publisher.py:6` — PlatformPublishTargetPlan + PropertyContext + PublishedMediaArtifact.

---

## 6. Desviaciones frente al plan

### 6.1 — `Property` split en 2 archivos (no era explícito en briefing)

El briefing decía: "**Si algún archivo nuevo en `modules/` excede 500
LoC**, debes partirlo." El traslado verbatim daba 510 LoC. Decisión:
split entre `wordpress_property.py` (clase + factory) y
`_property_conversions.py` (helpers + builders). El `Property` aggregate
sigue siendo el único símbolo público; los helpers son privados al
package (`_property_conversions.py` con prefijo `_`).

### 6.2 — Patches a `services/` (frozen, scope 18c) — mismo patrón que 18a §2.2

El briefing 18b dice: "Si encuentras imports cruzados que no esperabas
(p.ej. un módulo de `services/` cargando algo que estás moviendo):
documéntalo, NO toques `services/`, deja la deuda para 18c."

Verificación empírica: tras borrar `domain/` físicamente, los imports
`from domain.properties.model import Property` en
`services/{ai,media,publishing}/` fallan al cargarse transitivamente
desde callers vivos:
- `modules/reels/application/use_cases/prepare_reel_assets.py:42-49` →
  `services/media/property_media/__init__.py` →
  `services/media/property_media/{downloads,filesystem,selection}.py` →
  `from domain.properties.model import Property` → **ModuleNotFoundError**.
- `modules/reels/application/content_generator.py` →
  `services/publishing/social_delivery/{description,post_copy}.py` →
  **ModuleNotFoundError**.
- `modules/rendering/application/scripted_video/render_service.py` →
  `services/media/{site_storage,reel_rendering}` →
  `services/ai/photo_selection/{prompting,selection}.py` →
  **ModuleNotFoundError**.

El acceptance de 18b exige simultáneamente:
1. `application/` y `domain/` borrados.
2. `pytest -q` ≥ 394 (= 454 − 60 tests removidos).

La única forma de cumplir ambos sin romper la baseline es **patchear los
`from domain.X` y `from application.X` que vivan en frozen** y que
carguen al cargar el módulo activo. La alternativa (mantener
`domain/properties/model.py` o `application/types.py` como shim) la
prohibe el acceptance "borrado físicamente".

**Por tanto, decisión** (mismo patrón que 18a §2.2): aplicar el patch
mínimo (1-2 líneas por archivo, sustitución textual de `from <legacy>` →
`from <new>`) en los 10 archivos frozen. La API pública no cambia; sólo
cambia la fuente del import. Tests pasan, dirs se borran, frozen sigue
importable.

Briefing también ofrece esta vía: "**Alternativa**: si puedes redefinir
inline el símbolo necesario en `services/<X>.py` (frozen, ~30 LoC), eso
es aceptable porque feature 18c lo borra entero." En este caso es
preferible reapuntar (más mecánico, menos código nuevo) que redefinir
inline.

### 6.3 — `services/publishing/social_delivery/property_publisher.py` re-apuntado a `modules.reels.domain.types`

Este es el caso más delicado: `property_publisher.py:6` antes importaba
`PlatformPublishTargetPlan, PropertyContext, PublishedMediaArtifact` de
`application.types`. Tras el move, ese path no existe → reapunto a
`modules.reels.domain.types`. **Cross-module read**: `services/publishing/`
(legacy) leyendo de `modules.reels.domain` (moderno). Esto rompería la
regla "un módulo puede importar de `<otro>.domain`, nunca de
`<otro>.application` ni `<otro>.infrastructure`" PERO `services/` no es
un módulo bounded context, es legacy en transición; 18c lo borra entero.
Aceptable como deuda transitoria.

### 6.4 — `feature_list.json` feature 18 sigue `pending`

NO se promueve a `done`. Se mantiene `pending` (NO `in_progress`)
porque: (1) la sub-tarea 18b está implementada pero pendiente de review
del leader; (2) el cierre administrativo (promover a `in_progress` /
`done`) lo decide el leader/closer; (3) feature 18 sólo cierra cuando
18c termine. Conforme al briefing: "**NO marques feature 18 `done`**
(sigue `in_progress` hasta 18c)".

---

## 7. Estado tras 18b

- `application/`: **borrado**.
- `domain/`: **borrado**.
- `services/`: pendiente (scope 18c). Hits frozen → activo restantes:
  ~50 (símbolos `services.media.reel_rendering.*`,
  `services.publishing.social_delivery.*`,
  `services.ai.photo_selection.*`, `services.media.property_media.*`,
  `services.media.site_storage`, `services.transport.http.operations`).
- 0 imports `from domain.|from application.|import domain.|import application.` en `apps/`, `modules/`, `shared/`, `tests/`, `services/`, `settings/`.
- Feature 18 sigue `pending` hasta que 18c termine (tras revisión del
  leader y la sub-tarea 18c).
- Sub-tarea 18b: implementada y autoverificada; pendiente de revisión.

## 8. Pendiente (no es scope de 18b)

- 18c — disuelve `services/`, mueve ~12 800 LoC a
  `modules/{rendering,publishing}/infrastructure/`,
  `shared/storage/site_layout.py`, partir
  `services/ai/photo_selection/selection.py` (774 LoC) y otros que
  excedan 500 LoC al moverse. Borrar `tests/test_*.py` raíz restantes
  (`test_logging.py`, `test_reel_render_command.py`,
  `test_reel_runtime_dynamic_urls.py`, `test_gemini_photo_selection.py`)
  o moverlos a `tests/unit/<bc>/`. Cierre Phase 2: actualizar
  `AGENTS.md`, `REFACTOR_STATUS.md`, `docs/architecture.md`,
  `docs/conventions.md`, `docs/phase_2_operating_rules.md`, `init.sh`.
