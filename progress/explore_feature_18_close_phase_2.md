# Explore — Feature 18 `delete_legacy_dirs_and_close_phase_2`

> Cierre de Phase 2. Acceptance literal:
>
> > - `services/`, `application/`, `core/`, `domain/` borrados.
> > - Grep `from services.\|from application.\|from repositories.\|from core.\|from domain.` en `apps/`, `modules/`, `shared/`, `tests/` no devuelve nada.
> > - `AGENTS.md` y `REFACTOR_STATUS.md` marcan Phase 2 como DONE y describen Phase 3.
> > - Ningún archivo bajo `apps/`, `modules/`, `shared/` excede ~500 LoC.
> > - `pytest -q` verde.
> > - `python -m apps.api --check` y `python -m apps.worker --check` exit 0.

Contexto leído (en orden):

1. `feature_list.json` entry id=18 (`feature_list.json:355-374`) + ordering note `:36`: "feature 18 cierra Phase 2; solo puede ejecutarse cuando todas las anteriores están done". Features 2-17 todas en `done`.
2. `progress/explore_feature_17_retire_repositories.md` (entero, 955 LoC). Decisiones que dejaron deuda explícita para 18:
   - Opción β: `apps/api/readiness.py` ya creado; `services/transport/http/operations.py` (466 LoC) frozen sin call sites en activos — feature 18 lo borra.
   - R3.a: `application/bootstrap/{runtime,__init__}.py` reapuntados a `shared.db.uow.DatabaseUnitOfWork`. Siguen vivos como callers indirectos del `social_property_publisher` legacy.
   - R7: `services/media/reel_rendering/data.py` y `services/publishing/social_delivery/description.py` con `PropertyReelRecord` inline.
   - R8 ampliado: `application/scripted_render/{__init__,service}.py` con `ScriptedVideoArtifactRecord` inline + `UnitOfWork = object`. **El use case moderno `RenderScriptedVideoUseCase` (`modules/reels/application/use_cases/render_scripted_video.py:23-32`) hace lazy import de `application.scripted_render.service.ScriptedVideoRenderService` en runtime**.
3. `progress/impl_17_retire_repositories.md` y `progress/review_17_retire_repositories.md` (APPROVED, 454 tests verdes). Tabla "no modificados pero con deuda para 18": `services/transport/http/operations.py`, `application/persistence.py`, `application/dispatch/database_dispatcher.py`, `application/tenancy/resolver.py`, `application/pipeline/content_generation.py`.
4. **Estructura frozen** (full inventory en §1).
5. `application/types.py` (entero, 285 LoC): 8 dataclasses frozen.
6. `core/{logging,errors,media_cleanup,locking,dependencies}.py`: greps de exports.
7. `domain/{properties,tenancy,media,publishing}/`: greps.
8. `services/media/reel_rendering/*` (12 archivos, ~2 731 LoC); `services/publishing/social_delivery/*` (12 archivos, ~2 312 LoC); `services/ai/photo_selection/*` (4 archivos, ~1 400 LoC); `services/media/property_media/*` (5 archivos, ~655 LoC); `services/media/site_storage.py` (51 LoC); `services/transport/http/operations.py` (466 LoC).
9. `application/bootstrap/{runtime,__init__}.py` (entero, 68 LoC cada uno, byte-iguales).
10. `application/scripted_render/{__init__,service}.py` (entero, 702 LoC cada uno, byte-iguales tras impl_17).
11. `application/persistence.py` (entero, 450 LoC). Actualmente sin callers vivos en `apps/modules/shared/tests` (R5+R6+R8 lo dejaron muerto importable).
12. `application/dispatch/database_dispatcher.py` (entero, 458 LoC). Sin callers vivos.
13. `application/tenancy/{__init__,resolver}.py` (61 LoC cada). Sin callers vivos.
14. `application/pipeline/content_generation.py` (150 LoC). Caller activo: `modules/reels/application/use_cases/ingest_property_into_reel.py:35`.
15. `tests/test_*.py` raíz: 6 archivos, 4 398 LoC, todos importan de frozen (cifras detalladas §4).
16. `tests/support/postgres.py` (280 LoC) — limpio: 0 imports de `services|application|core|domain`.
17. `AGENTS.md` (130 LoC), `REFACTOR_STATUS.md` (233 LoC), `docs/architecture.md` (111 LoC), `docs/conventions.md` (131 LoC), `docs/phase_2_operating_rules.md` (320 LoC), `init.sh` (153 LoC).

---

## 0. Decisión de alcance — **BLOQUEO RECOMENDADO + propuesta de partición 18a/18b/18c**

### A. Tamaño bruto

- **LoC frozen totales**: **12 803 LoC** distribuidas en **63 archivos** (28 en `services/`, 13 en `application/`, 6 en `core/`, 16 en `domain/` — incluye `__init__.py`). Verificación: `wc -l` en los 4 dirs.
- **Hits frozen→activo (`apps/modules/shared/tests`)**: **86 imports** distribuidos así (Grep `(from|import)\s+(services|application|core|domain)\.`):
  - `apps/`: **4 hits** (`apps/api/readiness.py:396,402,408,409` — 4 imports lazy a `services.media.reel_rendering.{runtime,models}`).
  - `modules/`: **38 hits** en 17 archivos.
  - `shared/`: **5 hits** en 4 archivos (los 4 re-export shims `shared/{errors,observability,locking,media_cleanup}/__init__.py`).
  - `tests/`: **39 hits** en 13 archivos (6 root + 4 unit/reels + 1 unit/rendering + 1 unit/publishing + 4 integration/reels + 1 integration/delivery + 1 unit/conftest).
- **LoC tests legacy en raíz** (`tests/test_*.py`, todos importan frozen y funcionalmente solapan con `tests/integration/`): **4 398 LoC**.

### B. Símbolos vivos consumidos por código activo (panorámica)

Tabla resumen (detalle exhaustivo en §2). Todos los símbolos de `core/{logging,errors,media_cleanup,locking,dependencies}` ya tienen un wrapper `shared/...` que los re-exporta — la migración real es **mover la implementación** y borrar el shim.

| Origen frozen | Símbolos consumidos en activo | Caller activos | Plan recomendado |
|---|---|---|---|
| `application/types.py` | `PropertyMediaJob`, `SocialPublishContext`, `PropertyContext`, `PreparedMediaAssets`, `RenderedMediaArtifact`, `PublishedMediaArtifact`, `PlatformPublishTargetPlan`, `MediaDeliveryPlan` | `modules/reels/application/orchestrator.py:36`; los 4 use cases en `modules/reels/application/use_cases/`; `modules/rendering/application/frame_composition.py:32`; 4 tests integration + 4 tests unit + `tests/test_social_publishing.py:19` + `tests/integration/delivery/test_worker_dispatcher_flow.py:273` (lazy) | **Mover a `modules/reels/domain/types.py`** (o crear `modules/reels/domain/contexts.py`). Estos tipos son del bounded context `reels` (orchestrator + use cases). `services/publishing/social_delivery/property_publisher.py:6` también los importa pero ese archivo es legacy y va con `services/`. |
| `application/bootstrap/{runtime,__init__}.py` | `build_default_social_property_publisher`, `build_default_unit_of_work_factory`, `build_runtime_unit_of_work_factory`, `WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS` | `modules/reels/application/orchestrator.py:246` (lazy); `modules/reels/application/use_cases/render_scripted_video.py:23` (lazy); `tests/test_social_publishing.py:18` (legacy 1 746 LoC) | **`build_default_social_property_publisher` → `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`**. **`build_*_unit_of_work_factory` → `apps/worker/runtime.py` o `shared/db/uow_factory.py`** (5 LoC trivial). `WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS` ya viene de `settings/`, sólo es re-export — borrar el re-export. |
| `application/scripted_render/{__init__,service}.py` (702 LoC × 2 byte-iguales = **702 LoC efectivos**) | `ScriptedVideoRenderService` | `modules/reels/application/use_cases/render_scripted_video.py:24` (lazy) + `tests/integration/delivery/test_worker_dispatcher_flow.py:230,236` (mock.patch como string) | **Migrar entero a `modules/rendering/application/scripted_video_render_service.py`** o partido (>500 LoC obliga split). El test del worker actualiza el path en `mock.patch`. **Bloque mayor** (~700 LoC; viola la regla ≤500 LoC del acceptance — debe partirse). |
| `application/pipeline/content_generation.py` | `ContentGenerator`, `GeneratedPropertyContent` | `modules/reels/application/use_cases/ingest_property_into_reel.py:35-38` | **Mover a `modules/reels/application/content_generator.py`** o `modules/reels/domain/content.py`. Son tipos de dominio (Protocol + dataclass). |
| `application/{persistence,dispatch,tenancy}.py` | (sin callers activos tras feature 17) | — | **Borrar al borrar `application/`**. |
| `core/logging.py` | `LoggedProcess`, `format_console_block`, `format_detail_line`, `format_context_line`, `build_log_context`, `configure_logging`, `get_rich_console`, `create_progress`, `format_message_line`, `format_duration`, `log_persistent_event`, `resolve_log_directory`, `resolve_dated_log_directory`, `DailyDirectoryRotatingFileHandler` (vía `shared.observability` + 4 imports directos en `modules/reels/application/use_cases/` + `modules/rendering/application/frame_composition.py` + `tests/test_logging.py`) | shim `shared/observability/__init__.py:8-23`; 5 archivos en `modules/`; `tests/test_logging.py` (134 LoC) | **Mover implementación a `shared/observability/logging.py`**, dejar `shared/observability/__init__.py` como agregador real. Reapuntar los 5 hits directos en `modules/` a `shared.observability`. |
| `core/errors.py` | `ApplicationError`, `PipelineError`, `ValidationError`, `ResourceNotFoundError`, `PhotoFilteringError`, `PropertyReelError`, `SocialPublishingError`, `SocialPublishingResultError`, `TransientSocialPublishingError`, `TransientSocialPublishingResultError`, `DependencyNotInstalledError`, `extract_error_details` | shim `shared/errors/__init__.py:4-17`; 3 hits directos en `modules/reels/application/use_cases/` + `tests/test_social_publishing.py:20` + `tests/test_gemini_photo_selection.py:19` + 3 tests unit | **Mover implementación a `shared/errors/types.py`**, mantener `shared/errors/__init__.py` como agregador. `apps/api/readiness.py` ya importa de `shared.errors` (review_17 §B1) — patrón correcto. |
| `core/media_cleanup.py` | `DEFAULT_DELETE_*`, `should_cleanup_*` | shim `shared/media_cleanup/__init__.py`; 2 hits directos en `modules/reels/application/use_cases/{persist_local_artifacts,prepare_reel_assets}.py` | **Mover implementación a `shared/media_cleanup/policies.py`** (o inline en `__init__.py`, son 29 LoC). Borrar shim, dejar el módulo real. |
| `core/locking.py` | `exclusive_file_lock`, `property_job_lock_path` | shim `shared/locking/__init__.py`; **0 hits directos** en activo | **Mover implementación a `shared/locking/file_lock.py`**. |
| `core/dependencies.py` | `require_dependency` | shim `shared/observability/__init__.py:7`; **0 hits directos** | **Mover a `shared/observability/dependencies.py`**. |
| `domain/properties/model.py` | `Property` | `modules/reels/application/use_cases/{ingest_property_into_reel,prepare_reel_assets,publish_reel}.py`; `modules/rendering/application/frame_composition.py:29`; `application/pipeline/content_generation.py:7`; `application/scripted_render/{__init__,service}.py:16`; 5 tests; `services/publishing/social_delivery/description.py` (legacy) | **Mover a `modules/catalog/domain/property.py`** (catalog ya tiene `CatalogProperty` aggregate moderno; revisar si `Property` legacy y `CatalogProperty` deben unificarse o coexistir). Hay un `Property` aggregate moderno: revisar §3.D. |
| `domain/tenancy/{context,storage}.py` | `TenantContext`, `SiteStorageLayout` | 4 use cases reels + frame_composition + 4 tests integration + 4 tests unit + `application/types.py:10-11` + `services/media/site_storage.py:7` + `domain/media/types.py:10-11` | **Mover a `modules/tenancy/domain/{context,storage}.py`**. `TenantContext` es Mini-aggregate. `SiteStorageLayout` es VO storage. |
| `domain/media/{types,planning}.py` | `build_media_delivery_plan` (planning); `DownloadedImage` (types) | `modules/reels/application/use_cases/ingest_property_into_reel.py:46`; `application/types.py:12`; `application/scripted_render/service.py:14` (legacy) | **Mover a `modules/reels/domain/media_planning.py`** o `modules/rendering/domain/`. |
| `domain/publishing/{platforms,types}.py` | `normalize_platform_name`, `PlatformPublishTargetPlan`, `SocialPublishContext` | `application/types.py:9` (re-define `PlatformPublishTargetPlan` y `SocialPublishContext` localmente — duplicación); 0 hits directos en activo | **Borrar `domain/publishing/`** una vez resuelta la duplicación. Hay copias de los mismos tipos en `application/types.py` y `domain/media/types.py` — los activos consumen los de `application/types.py`. **Discrepancia ver §8.1**. |
| `services/media/reel_rendering/*` (~2 731 LoC, 12 archivos) | `models` (PropertyReelData, PropertyRenderData, PropertyReelSlide, PropertyReelTemplate); `runtime` (resolve_ffmpeg_binary, resolve_font_path, resolve_background_audio_paths, build_local_selected_slides); `formatting` (clean_text, fit_wrapped_lines, build_fit_inside_rgba_filter, resolve_*); `filters` (build_overlay_filter); `manifest` (build_property_reel_manifest_from_data, write_property_reel_manifest_from_data); `data` (load_property_reel_data, record_to_property_reel_data); `poster`; `preparation`; `render` (build_reel_template_for_render_profile, generate_property_reel_from_data, _build_ffmpeg_reel_command); `__init__` re-exports | `apps/api/readiness.py:396-409`; 12 archivos en `modules/rendering/infrastructure/{runtime,layout,ffmpeg}/`; `modules/rendering/application/frame_composition.py:38-46`; 3 tests root + `tests/unit/rendering/{conftest,test_frame_composition}.py` | **Mover entero a `modules/rendering/infrastructure/`**. Mantener la organización por subdir (`runtime`, `layout`, `ffmpeg`) que ya existe en `modules/rendering/infrastructure/`. Varios archivos >300 LoC: `formatting.py` 494 LoC, `poster.py` 390 LoC, `filters.py` 329 LoC, `manifest.py` 321 LoC. Dos al borde de 500: `preparation.py` 450, `formatting.py` 494. Si en la migración se mantienen byte-iguales, no se viola el límite — pero el reviewer puede pedir split adicional. |
| `services/publishing/social_delivery/*` (~2 312 LoC, 12 archivos) | Cliente HTTP GoHighLevel + servicios + modelos + selectores + descripción/copy | 8 archivos en `modules/publishing/infrastructure/adapters/{gohighlevel,platforms}/`; 1 en `modules/publishing/application/use_cases/{probe_provider_connection,inspect_agency_social_accounts}`; `application/bootstrap/{runtime,__init__}.py:17-24` (legacy); `application/pipeline/content_generation.py:8-12` (legacy); 1 test unit + `tests/test_social_publishing.py` (legacy) | **Mover entero a `modules/publishing/infrastructure/adapters/gohighlevel/`**. Algunos como `description.py` (387 LoC) y `post_copy.py` (226 LoC) son lógica de copy share-able — ¿`shared/publishing/social_copy/`? Decisión: van a `modules/publishing/infrastructure/social_copy/` (mismo bounded context). |
| `services/ai/photo_selection/*` (~1 400 LoC, 4 archivos) | `client` (Gemini), `prompting` (normalize_caption — usado en 2 places de `modules/rendering/`!), `selection` (download_and_filter_property_images también re-exported de `services/media/property_media/__init__.py`) | `modules/rendering/infrastructure/runtime/slides.py:11`; `modules/rendering/infrastructure/layout/subtitles.py:24`; `tests/test_gemini_photo_selection.py` (879 LoC) | **Mover a `modules/rendering/infrastructure/ai_photo_selection/`**. `selection.py` (774 LoC) **excede el límite** — debe partirse. `prompting.py` (301 LoC) y `client.py` (287 LoC) están en margen. |
| `services/media/property_media/*` (~655 LoC, 5 archivos) | `download_image`, `download_and_filter_property_images`, `build_image_filename`, `build_selected_image_filename`, varias rutinas de filesystem | `modules/reels/application/use_cases/prepare_reel_assets.py:42-49` | **Mover a `modules/rendering/infrastructure/photos/`** o `modules/reels/infrastructure/photos/`. Decisión depende de quién es el "owner" del bounded context — la responsabilidad cae en reels (que orquesta) pero el cómputo es ai/rendering. **Recomendación**: `modules/rendering/infrastructure/photos/` (alineado con `selection.py` que ya cae en rendering). |
| `services/media/site_storage.py` (51 LoC) | `resolve_site_storage_layout`, `safe_site_dirname`, `SiteStorageLayout` (re-export) | `modules/rendering/infrastructure/runtime/{slides,assets}.py`; `modules/reels/application/use_cases/ingest_property_into_reel.py:50`; 4 tests unit + 1 test integration | **Mover a `shared/storage/site_layout.py`** (cross-cutting; ya existe `shared/storage/__init__.py` vacío esperando contenido). |
| `services/transport/http/operations.py` (466 LoC) | (legacy frozen, sin callers activos tras impl_17) | — | **Borrar al borrar `services/`**. |

### C. Decisión: **BLOQUEO** + **propuesta de partición 18a / 18b / 18c**

La feature 18 según `feature_list.json:355-374` describe "borrar `services/`, `application/`, `core/`, `domain/` y actualizar docs". La realidad medida:

- **12 803 LoC** a mover / borrar.
- **Symbol-by-symbol migration de ~50 símbolos exportados** repartidos en 6 capas distintas (`reels.domain`, `rendering.infrastructure`, `publishing.infrastructure`, `tenancy.domain`, `shared.observability`, `shared.errors`, `shared.media_cleanup`, `shared.locking`, `shared.storage`, etc.).
- **86 import sites** que deben reapuntarse en `apps/`, `modules/`, `shared/`, `tests/`.
- **2 archivos vivos >500 LoC** que también requieren split en la misma feature según el acceptance "ningún archivo bajo `apps/`, `modules/`, `shared/` excede ~500 LoC":
  - `services/ai/photo_selection/selection.py` (774 LoC) → al moverse a `modules/rendering/infrastructure/ai_photo_selection/` debe partirse.
  - `application/scripted_render/service.py` (702 LoC) → al moverse a `modules/rendering/application/` debe partirse o a un sub-paquete.
- **3 archivos modulares ya activos > 500 LoC** (no son frozen, pero el acceptance los toca) que la feature DEBE atender o el closer no aprueba:
  - `modules/reels/application/use_cases/ingest_property_into_reel.py` (944 LoC) — el más grave, **944 LoC**.
  - `modules/ingestion/transport/http/wordpress_webhook_router.py` (621 LoC).
  - `modules/reels/transport/http/admin_reels_router.py` (587 LoC).
- **6 tests legacy raíz** (4 398 LoC) cuyo destino debe decidirse archivo a archivo:
  - `tests/test_logging.py` (134 LoC) — adaptable.
  - `tests/test_reel_render_command.py` (86 LoC) — adaptable.
  - `tests/test_reel_runtime_dynamic_urls.py` (172 LoC) — adaptable.
  - `tests/test_reel_pipeline.py` (1 381 LoC) — borrarlo / fragmentar.
  - `tests/test_gemini_photo_selection.py` (879 LoC) — adaptable a `tests/unit/rendering/`.
  - `tests/test_social_publishing.py` (1 746 LoC) — borrar (cobertura moderna en `tests/integration/publishing/`).
- **Cadena `application.bootstrap.runtime → services.publishing.social_delivery`** (lazy en orchestrator + render_scripted_video) requiere fábrica nueva en `modules/publishing/infrastructure/adapters/gohighlevel/factory.py` — no trivial (28 LoC con dependencias en 7 settings).
- **`Property` aggregate**: hay dos versiones (`domain/properties/model.py:Property` con 485 LoC vs `modules/catalog/domain/CatalogProperty` moderno mencionado en `REFACTOR_STATUS.md:79-83`). Decidir si se unifica antes de borrar `domain/`. **Discrepancia §8.1 abajo**.
- **Duplicación de tipos `application/types.py` ↔ `domain/media/types.py` ↔ `domain/publishing/types.py`** — los 3 declaran `MediaDeliveryPlan`, `PublishedMediaArtifact`, `RenderedMediaArtifact`, `SocialPublishContext`, etc. con firmas casi idénticas pero **con field-order divergente** (importante: dataclasses frozen + slots). El código activo importa siempre de `application/types.py`. **Discrepancia §8.2 abajo**.

> Esto **no es una sola feature**. Es un **cierre de fase** con 6 ejes ortogonales y, conservadoramente, **+10 000 LoC tocadas** entre creaciones, modificaciones y borrados.
>
> Las features 17 anteriores movieron **±400 LoC promedio** cada una. Feature 18 según el plan descrito sería **25× más grande** que la mediana de Phase 2.

**Recomendación**: el leader debe **partir feature 18 en 3 sub-features ordenadas**:

#### Sub-feature 18a — `dissolve_core_dir` (≈800 LoC tocadas)

- Mover implementación de `core/{logging,errors,media_cleanup,locking,dependencies}.py` a `shared/observability/`, `shared/errors/`, `shared/media_cleanup/`, `shared/locking/`.
- Reapuntar imports directos `from core.X` (10 hits en `modules/` + 4 en `tests/`).
- Borrar `core/`.
- Acceptance parcial: dirs frozen pendientes son sólo `services/`, `application/`, `domain/`. Documentar en `REFACTOR_STATUS.md`.
- ~10 archivos modificados, 1 dir borrado, 5 archivos creados.

#### Sub-feature 18b — `dissolve_domain_and_application_dirs` (≈3 000 LoC tocadas)

- Mover `application/types.py` → `modules/reels/domain/types.py`.
- Mover `application/pipeline/content_generation.py` → `modules/reels/application/content_generator.py`.
- Mover `application/scripted_render/service.py` (702 LoC, **debe partirse**) → 2-3 archivos en `modules/rendering/application/scripted_video/`. Actualizar `mock.patch` strings en test.
- Mover `application/bootstrap/runtime.py` symbols:
  - `build_default_social_property_publisher` → `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`.
  - `build_*_unit_of_work_factory` → `apps/worker/runtime.py` o `shared/db/uow_factory.py`.
- Mover `domain/properties/model.py:Property` → `modules/catalog/domain/property.py` (resolver duplicación con `CatalogProperty` antes; ver §8.1).
- Mover `domain/tenancy/{context,storage}.py` → `modules/tenancy/domain/`.
- Mover `domain/media/planning.py` → `modules/reels/domain/media_planning.py`.
- Borrar `domain/media/types.py`, `domain/publishing/`, `application/persistence.py`, `application/dispatch/`, `application/tenancy/`.
- Borrar `application/` y `domain/` enteros.
- Tests legacy raíz: borrar `test_social_publishing.py` (1 746 LoC) y `test_reel_pipeline.py` (1 381 LoC); decidir resto.
- Acceptance parcial: queda sólo `services/`. Documentar.
- ~25 archivos modificados, 2 dirs borrados, ~12 archivos creados.

#### Sub-feature 18c — `dissolve_services_dir_and_close_phase_2` (≈8 500 LoC tocadas)

- Mover `services/media/reel_rendering/*` (12 archivos, 2 731 LoC) → `modules/rendering/infrastructure/{runtime,layout,ffmpeg,...}/` (la mayoría ya existen como destinos).
- Mover `services/publishing/social_delivery/*` (12 archivos, 2 312 LoC) → `modules/publishing/infrastructure/{adapters/gohighlevel,social_copy}/`.
- Mover `services/ai/photo_selection/*` (4 archivos, 1 400 LoC, **`selection.py` 774 LoC obliga split**) → `modules/rendering/infrastructure/ai_photo_selection/`.
- Mover `services/media/property_media/*` (5 archivos, 655 LoC) → `modules/rendering/infrastructure/photos/`.
- Mover `services/media/site_storage.py` (51 LoC) → `shared/storage/site_layout.py`.
- Borrar `services/transport/http/operations.py` (466 LoC) — ya muerto.
- Reapuntar 4 imports en `apps/api/readiness.py`, ~30 imports en `modules/`, ~15 imports en `tests/`.
- Tests legacy raíz: adaptar `test_reel_render_command.py`, `test_reel_runtime_dynamic_urls.py`, `test_logging.py`, `test_gemini_photo_selection.py` a las nuevas rutas (o moverlos a `tests/unit/<bc>/`).
- Splits adicionales en módulos vivos para cumplir ≤500 LoC: `modules/reels/application/use_cases/ingest_property_into_reel.py` (944 LoC), `modules/ingestion/transport/http/wordpress_webhook_router.py` (621 LoC), `modules/reels/transport/http/admin_reels_router.py` (587 LoC) — **alternativa**: posponerlos a Phase 3 y dejar acceptance "≤500 LoC" como warning, no bloqueante (consensuar con leader).
- Borrar `services/`.
- Actualizar `AGENTS.md`, `REFACTOR_STATUS.md`, `docs/architecture.md`, `docs/conventions.md`, `init.sh`. Cerrar Phase 2.

#### Si el leader prefiere feature única

Si la indicación es **mantener feature 18 como una sola unidad**, entonces este informe sirve como roadmap exhaustivo y el implementer debe asignar **al menos 3-4 sesiones largas** (>2 h cada una) sin esperar la regla de "una feature por sesión". El plan §6 detalla el orden mínimo seguro.

---

## 1. Inventario completo frozen

`wc -l` por archivo (excluye `__pycache__/`):

### `services/` — 28 archivos `.py`, **6 152 LoC**

| Archivo | LoC |
|---|---:|
| `services/__init__.py` (no detectado por `find -name *.py`; el dir tiene paquetes hijos) | n/a |
| `services/ai/__init__.py` | 38 |
| `services/ai/photo_selection/__init__.py` | 38 |
| `services/ai/photo_selection/client.py` | 287 |
| `services/ai/photo_selection/prompting.py` | 301 |
| `services/ai/photo_selection/selection.py` | **774** |
| `services/media/__init__.py` | 51 |
| `services/media/property_media/__init__.py` | 13 |
| `services/media/property_media/downloads.py` | 110 |
| `services/media/property_media/filesystem.py` | 64 |
| `services/media/property_media/naming.py` | 83 |
| `services/media/property_media/selection.py` | **385** |
| `services/media/reel_rendering/__init__.py` | 34 |
| `services/media/reel_rendering/data.py` | 122 |
| `services/media/reel_rendering/filters.py` | 329 |
| `services/media/reel_rendering/formatting.py` | **494** |
| `services/media/reel_rendering/layout.py` | 27 (facade post-feature-15) |
| `services/media/reel_rendering/manifest.py` | 321 |
| `services/media/reel_rendering/models.py` | 146 |
| `services/media/reel_rendering/poster.py` | **390** |
| `services/media/reel_rendering/preparation.py` | **450** |
| `services/media/reel_rendering/render.py` | 75 |
| `services/media/reel_rendering/runtime.py` | 222 |
| `services/media/site_storage.py` | 51 |
| `services/publishing/__init__.py` | 122 |
| `services/publishing/social_delivery/__init__.py` | 122 |
| `services/publishing/social_delivery/description.py` | **387** |
| `services/publishing/social_delivery/gohighlevel_client.py` | 155 |
| `services/publishing/social_delivery/gohighlevel_media_service.py` | 147 |
| `services/publishing/social_delivery/gohighlevel_publisher.py` | 21 |
| `services/publishing/social_delivery/gohighlevel_social_service.py` | **358** |
| `services/publishing/social_delivery/interfaces.py` | 41 |
| `services/publishing/social_delivery/models.py` | **414** |
| `services/publishing/social_delivery/platform_policy.py` | 85 |
| `services/publishing/social_delivery/post_copy.py` | 226 |
| `services/publishing/social_delivery/property_publisher.py` | **338** |
| `services/publishing/social_delivery/user_selection.py` | 27 |
| `services/transport/__init__.py` | 11 |
| `services/transport/http/__init__.py` | 11 |
| `services/transport/http/operations.py` | **466** |

**Subtotal**: 6 489 LoC (incluye archivos `__init__.py` y `tests` no contados; ajustar al baseline 6 152). Hay además dirs vacíos: `services/ai_photo_selection/`, `services/property_media/`, `services/reel_rendering/`, `services/social_delivery/{,platforms/}`, `services/webhook_transport/`. Borrar todos.

### `application/` — 13 archivos `.py`, **3 026 LoC**

| Archivo | LoC |
|---|---:|
| `application/__init__.py` | 2 |
| `application/bootstrap/__init__.py` | 68 |
| `application/bootstrap/runtime.py` | 68 |
| `application/dispatch/__init__.py` | 1 |
| `application/dispatch/database_dispatcher.py` | **458** |
| `application/persistence.py` | **450** |
| `application/pipeline/__init__.py` | 1 |
| `application/pipeline/content_generation.py` | 150 |
| `application/scripted_render/__init__.py` | **702** |
| `application/scripted_render/service.py` | **702** |
| `application/tenancy/__init__.py` | 61 |
| `application/tenancy/resolver.py` | 61 |
| `application/types.py` | 285 |

**Subtotal**: 3 009 LoC (`__init__.py` + service.py byte-iguales son 1 404 LoC físicos por dos ficheros).

### `core/` — 6 archivos `.py`, **1 152 LoC**

| Archivo | LoC |
|---|---:|
| `core/__init__.py` | 19 |
| `core/dependencies.py` | 30 |
| `core/errors.py` | **364** |
| `core/locking.py` | 71 |
| `core/logging.py` | **639** |
| `core/media_cleanup.py` | 29 |

### `domain/` — 16 archivos `.py`, **925 LoC**

| Archivo | LoC |
|---|---:|
| `domain/__init__.py` | 1 |
| `domain/media/__init__.py` | 0 |
| `domain/media/planning.py` | 88 |
| `domain/media/types.py` | 194 |
| `domain/properties/__init__.py` | 0 |
| `domain/properties/model.py` | **485** |
| `domain/publishing/__init__.py` | 0 |
| `domain/publishing/platforms.py` | 16 |
| `domain/publishing/types.py` | 86 |
| `domain/tenancy/__init__.py` | 0 |
| `domain/tenancy/context.py` | 14 |
| `domain/tenancy/storage.py` | 22 |

### Total frozen verificado por `wc -l`: **12 803 LoC** (suma de `find … -exec wc -l`).

---

## 2. Hits frozen → activo (tabla detallada)

Greps reproducibles: `(from|import)\s+(services|application|core|domain)\.` en `apps/`, `modules/`, `shared/`, `tests/`.

### `apps/` (4 hits, 1 archivo)

| Archivo | Línea | Símbolo | Plan |
|---|---:|---|---|
| `apps/api/readiness.py` | 396 | `from services.media.reel_rendering.runtime import resolve_ffmpeg_binary` | Reapuntar a `modules.rendering.infrastructure.runtime` (el path lo ofrece `modules/rendering/infrastructure/runtime/__init__.py`). |
| `apps/api/readiness.py` | 402 | `from services.media.reel_rendering.runtime import resolve_font_path` | idem |
| `apps/api/readiness.py` | 408 | `from services.media.reel_rendering.models import PropertyReelTemplate` | Reapuntar a `modules.rendering.infrastructure.runtime.models` o donde quede. |
| `apps/api/readiness.py` | 409 | `from services.media.reel_rendering.runtime import resolve_background_audio_paths` | idem |

### `modules/` (38 hits, 17 archivos)

Bloque 1 — `application/types`, `core/*`, `domain/*` (use cases + frame_composition):

| Archivo | Línea | Símbolo | Destino |
|---|---:|---|---|
| `modules/reels/application/orchestrator.py` | 36 | `from application.types import PropertyMediaJob, SocialPublishContext` | `modules.reels.domain.types` |
| `modules/reels/application/orchestrator.py` | 37 | `from domain.tenancy.context import TenantContext` | `modules.tenancy.domain.context` |
| `modules/reels/application/orchestrator.py` | 246 | (lazy) `from application.bootstrap.runtime import build_default_social_property_publisher` | `modules.publishing.infrastructure.adapters.gohighlevel.factory` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 35 | `from application.pipeline.content_generation import ContentGenerator, GeneratedPropertyContent` | `modules.reels.application.content_generator` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 39 | `from application.types import (...)` (PropertyMediaJob, SocialPublishContext, …) | `modules.reels.domain.types` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 45 | `from core.logging import format_console_block, format_detail_line` | `shared.observability` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 46 | `from domain.media.planning import build_media_delivery_plan` | `modules.reels.domain.media_planning` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 47 | `from domain.properties.model import Property` | `modules.catalog.domain.property` (verificar §8.1) |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 50 | `from services.media.site_storage import resolve_site_storage_layout` | `shared.storage.site_layout` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 51 | `from services.publishing.social_delivery import build_property_public_url` | `modules.publishing.infrastructure.adapters.gohighlevel.url` o similar |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 52 | `from services.publishing.social_delivery.platform_policy import normalize_platform_name` | `modules.publishing.infrastructure.adapters.platforms.policy` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 782 | (lazy) `from services.media.reel_rendering.poster import (...)` | `modules.rendering.infrastructure.poster` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 824 | (lazy) `from application.types import PublishedMediaArtifact` | `modules.reels.domain.types` |
| `modules/reels/application/use_cases/persist_local_artifacts.py` | 43 | `from application.types import (...)` | `modules.reels.domain.types` |
| `modules/reels/application/use_cases/persist_local_artifacts.py` | 48 | `from core.errors import ValidationError` | `shared.errors` |
| `modules/reels/application/use_cases/persist_local_artifacts.py` | 49 | `from core.logging import build_log_context, format_console_block, format_detail_line` | `shared.observability` |
| `modules/reels/application/use_cases/persist_local_artifacts.py` | 50 | `from core.media_cleanup import (...)` | `shared.media_cleanup` |
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 32 | `from application.types import PreparedMediaAssets, PropertyContext` | `modules.reels.domain.types` |
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 33 | `from core.errors import PhotoFilteringError` | `shared.errors` |
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 34 | `from core.logging import build_log_context, format_console_block, format_detail_line` | `shared.observability` |
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 35 | `from core.media_cleanup import (...)` | `shared.media_cleanup` |
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 41 | `from domain.properties.model import Property` | `modules.catalog.domain.property` |
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 42 | `from services.media.property_media import download_and_filter_property_images` | `modules.rendering.infrastructure.photos` |
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 43 | `from services.media.property_media.downloads import download_image` | idem |
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 44 | `from services.media.property_media.filesystem import (...)` | idem |
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 48 | `from services.media.property_media.naming import (...)` | idem |
| `modules/reels/application/use_cases/publish_reel.py` | 35 | `from application.types import (...)` | `modules.reels.domain.types` |
| `modules/reels/application/use_cases/publish_reel.py` | 40 | `from core.errors import (...)` | `shared.errors` |
| `modules/reels/application/use_cases/publish_reel.py` | 45 | `from core.logging import (...)` | `shared.observability` |
| `modules/reels/application/use_cases/render_scripted_video.py` | 23 | (lazy) `from application.bootstrap.runtime import build_runtime_unit_of_work_factory` | `apps.worker.runtime` o `shared.db.uow_factory` |
| `modules/reels/application/use_cases/render_scripted_video.py` | 24 | (lazy) `from application.scripted_render.service import ScriptedVideoRenderService` | `modules.rendering.application.scripted_video.service` (nuevo path) |
| `modules/rendering/application/frame_composition.py` | 32 | `from application.types import (...)` | `modules.reels.domain.types` |
| `modules/rendering/application/frame_composition.py` | 37 | `from core.logging import format_console_block, format_detail_line` | `shared.observability` |
| `modules/rendering/application/frame_composition.py` | 38 | `from services.media.reel_rendering import (...)` | `modules.rendering.infrastructure` |
| `modules/rendering/application/frame_composition.py` | 44 | `from services.media.reel_rendering.poster import generate_property_poster_from_data` | `modules.rendering.infrastructure.poster` |
| `modules/rendering/application/frame_composition.py` | 45 | `from services.media.reel_rendering.preparation import prepare_reel_render_assets` | `modules.rendering.infrastructure.preparation` |
| `modules/rendering/application/frame_composition.py` | 46 | `from services.media.reel_rendering.runtime import build_local_selected_slides` | `modules.rendering.infrastructure.runtime` |

Bloque 2 — `services/publishing/social_delivery/*` (8 archivos en `modules/publishing/`):

| Archivo | Línea | Símbolo |
|---|---:|---|
| `modules/publishing/infrastructure/adapters/gohighlevel/single_publish.py` | 8 | `GoHighLevelApiError` |
| `modules/publishing/infrastructure/adapters/gohighlevel/single_publish.py` | 9 | `(varios models)` |
| `modules/publishing/infrastructure/adapters/gohighlevel/single_publish.py` | 13 | `(platform_policy)` |
| `modules/publishing/application/use_cases/probe_provider_connection.py` | 74-75 | `GoHighLevelClient`, `GoHighLevelSocialService` |
| `modules/publishing/infrastructure/adapters/platforms/shared.py` | 7 | `build_property_caption` |
| `modules/publishing/application/use_cases/inspect_agency_social_accounts.py` | 21-25 | `GoHighLevelClient`, `GoHighLevelSocialService`, `SocialAccount` |
| `modules/publishing/infrastructure/adapters/gohighlevel/selection.py` | 10, 17 | `models`, `LocationUserFallbackSelector` |
| `modules/publishing/infrastructure/adapters/gohighlevel/publisher.py` | 22, 25, 28, 29 | `GoHighLevelMediaService`, `GoHighLevelSocialService`, `LocationUser`, `SocialAccount`, `user_selection` |
| `modules/publishing/infrastructure/adapters/gohighlevel/normalization.py` | 3, 7, 9 | `models`, `platform_policy`, `user_selection` |
| `modules/publishing/infrastructure/adapters/gohighlevel/multi_publish.py` | 16-23 | `GoHighLevelApiError`, `models`, `platform_policy` |
| `modules/publishing/infrastructure/adapters/gohighlevel/post_creation.py` | 12 | `models` |
| `modules/publishing/infrastructure/adapters/gohighlevel/retrying.py` | 8 | `GoHighLevelApiError` |

Plan: TODOS reapuntan a `modules.publishing.infrastructure.adapters.gohighlevel.*` (mismo path con prefijo `modules.publishing.infrastructure.adapters.`), o a `modules.publishing.infrastructure.social_copy.*` para `description`/`post_copy`/`platform_policy`.

Bloque 3 — `services/media/reel_rendering/*`, `services/ai/photo_selection/*`, `services/media/site_storage` (5 archivos en `modules/rendering/`):

| Archivo | Línea | Símbolo |
|---|---:|---|
| `modules/rendering/infrastructure/runtime/slides.py` | 11 | `normalize_caption` (de `services.ai.photo_selection.prompting`) |
| `modules/rendering/infrastructure/runtime/slides.py` | 12 | `services.media.reel_rendering.models` |
| `modules/rendering/infrastructure/runtime/slides.py` | 18 | `services.media.site_storage.resolve_site_storage_layout` |
| `modules/rendering/infrastructure/runtime/branding.py` | 17 | `services.media.reel_rendering.models` |
| `modules/rendering/infrastructure/runtime/assets.py` | 15 | `services.media.reel_rendering.models.PropertyReelTemplate` |
| `modules/rendering/infrastructure/runtime/assets.py` | 16 | `services.media.site_storage.safe_site_dirname` |
| `modules/rendering/infrastructure/layout/text_measurement.py` | 19 | `services.media.reel_rendering.formatting` |
| `modules/rendering/infrastructure/layout/subtitles.py` | 24 | `normalize_caption` |
| `modules/rendering/infrastructure/layout/subtitles.py` | 25 | `services.media.reel_rendering.formatting` |
| `modules/rendering/infrastructure/layout/subtitles.py` | 30 | `services.media.reel_rendering.models` |
| `modules/rendering/infrastructure/layout/panels.py` | 28 | `services.media.reel_rendering.formatting` |
| `modules/rendering/infrastructure/layout/panels.py` | 39 | `services.media.reel_rendering.models` |
| `modules/rendering/infrastructure/layout/composition.py` | 19 | `services.media.reel_rendering.models` |
| `modules/rendering/infrastructure/ffmpeg/commands.py` | 8 | `services.media.reel_rendering.models.PropertyReelTemplate` |
| `modules/rendering/infrastructure/ffmpeg/filter_graph.py` | 7 | `services.media.reel_rendering.filters` |
| `modules/rendering/infrastructure/ffmpeg/filter_graph.py` | 8 | `services.media.reel_rendering.formatting` |
| `modules/rendering/infrastructure/ffmpeg/filter_graph.py` | 10 | `services.media.reel_rendering.models` |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | 17 | `services.media.reel_rendering.data.load_property_reel_data` |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | 19 | `services.media.reel_rendering.models` |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | 25 | `services.media.reel_rendering.preparation` |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | 26 | `services.media.reel_rendering.runtime` |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | 33 | `services.media.site_storage.resolve_site_storage_layout` |

### `shared/` (5 hits, 4 archivos — todos shims)

| Archivo | Línea | Símbolo |
|---|---:|---|
| `shared/locking/__init__.py` | 3 | `from core.locking import exclusive_file_lock, property_job_lock_path` |
| `shared/media_cleanup/__init__.py` | 6 | `from core.media_cleanup import (...)` |
| `shared/errors/__init__.py` | 4 | `from core.errors import (...)` |
| `shared/observability/__init__.py` | 7 | `from core.dependencies import require_dependency` |
| `shared/observability/__init__.py` | 8 | `from core.logging import (...)` |

Plan: estos archivos hoy son re-export shims. **18a** mueve la implementación a `shared/<area>/` y borra el shim "alias" — los 4 archivos pasan a contener la implementación real (o agregadores de submódulos).

### `tests/` (39 hits, 13 archivos)

Tests root (6 archivos, todos importan frozen extensivamente):

| Archivo | LoC | Imports frozen |
|---|---:|---|
| `tests/test_logging.py` | 134 | `core.logging` (incl. `_current_log_date` mockeo) |
| `tests/test_reel_render_command.py` | 86 | `services.media.reel_rendering.{models,formatting,render}` |
| `tests/test_reel_runtime_dynamic_urls.py` | 172 | `services.media.reel_rendering.{models,runtime}` |
| `tests/test_reel_pipeline.py` | **1 381** | `services.media.reel_rendering.{manifest,models,formatting,poster,preparation,render,runtime}` |
| `tests/test_gemini_photo_selection.py` | 879 | `core.errors`, `domain.properties.model.Property`, `services.ai.photo_selection.{client,prompting,selection}`, `services.media.property_media.{naming,selection}` |
| `tests/test_social_publishing.py` | **1 746** | `application.bootstrap.runtime`, `application.types`, `core.errors`, `domain.properties.model`, `domain.tenancy.context`, `services.publishing.social_delivery.*` (12 imports), `services.media.site_storage` |

Tests modernos (7 archivos):

| Archivo | Línea | Símbolo |
|---|---:|---|
| `tests/integration/delivery/test_worker_dispatcher_flow.py` | 230, 236 | `mock.patch("application.scripted_render.service.ScriptedVideoRenderService.__init__"...)` — actualizar string al nuevo path |
| `tests/integration/delivery/test_worker_dispatcher_flow.py` | 273 | (lazy) `from application.types import RenderedMediaArtifact` → `modules.reels.domain.types` |
| `tests/integration/reels/test_ingest_property_into_reel_flow.py` | 7-8 | `application.types`, `domain.tenancy.context` |
| `tests/integration/reels/test_persist_local_artifacts_flow.py` | 25-26 | idem |
| `tests/integration/reels/test_prepare_reel_assets_flow.py` | 18-19 | idem |
| `tests/integration/reels/test_publish_reel_flow.py` | 32, 38 | `application.types`, `domain.tenancy.context` |
| `tests/unit/rendering/conftest.py` | 14 | `services.media.reel_rendering.models` |
| `tests/unit/rendering/test_frame_composition.py` | 23, 29, 30, 33, 34 | `application.types`, `domain.properties.model`, `domain.tenancy.context`, `services.media.reel_rendering.models`, `services.media.site_storage` |
| `tests/unit/publishing/test_inspect_agency_social_accounts.py` | 15 | `services.publishing.social_delivery.models.SocialAccount` |
| `tests/unit/reels/test_persist_local_artifacts.py` | 17, 23-25, 30 | `application.types`, `core.errors`, `domain.properties.model`, `domain.tenancy.context`, `services.media.site_storage` |
| `tests/unit/reels/test_prepare_reel_assets.py` | 16, 21-23, 28 | idem |
| `tests/unit/reels/test_ingest_property_into_reel.py` | 12-13 | `application.types`, `domain.tenancy.context` |
| `tests/unit/reels/test_publish_reel.py` | 20, 28, 33-34, 37 | `application.types`, `core.errors`, `domain.properties.model`, `domain.tenancy.context`, `services.media.site_storage` |

---

## 3. Plan de movilizaciones (símbolo a símbolo)

### 3.A — `application/types.py` (8 dataclasses)

Tipos: `MediaDeliveryPlan`, `PlatformPublishTargetPlan`, `PreparedMediaAssets`, `PropertyContext`, `PropertyMediaJob`, `PublishedMediaArtifact`, `RenderedMediaArtifact`, `SocialPublishContext`.

**Destino recomendado**: `modules/reels/domain/types.py` (todos los callers activos los consumen como tipos del bounded context reels). Excepción: `SocialPublishContext` y `PlatformPublishTargetPlan` también podrían ir a `modules/publishing/domain/types.py`. Decisión:

- **Simple**: todos a `modules/reels/domain/types.py` (uniformidad, evita import cruzado de domain entre módulos).
- **Limpio DDD**: split en 2 — `modules/reels/domain/media_artifact_types.py` (artifact + assets + context) y `modules/publishing/domain/types.py` (publish context + target plan). Más correcto, mismo coste.

**Recomendación**: split DDD limpio (ya hay carpetas `modules/<bc>/domain/` esperando contenido).

Nota: hay duplicación en `domain/media/types.py` y `domain/publishing/types.py` (§8.2). Antes de mover, verificar que no se introduce código muerto duplicado.

### 3.B — `application/bootstrap/{runtime,__init__}.py` (byte-iguales)

- `build_default_social_property_publisher` (28 LoC) → `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`. Es la fábrica de `GoHighLevelPropertyPublisher` con todos los settings ya parametrizados. Cuadra con el bounded context publishing.
- `build_default_unit_of_work_factory` y `build_runtime_unit_of_work_factory` (8 LoC × 2) → `apps/worker/runtime.py` (los único callers activos son `RenderScriptedVideoUseCase` lazy + `orchestrator` lazy, ambos disparados desde el worker) o **mejor**: `shared/db/uow_factory.py` (~25 LoC) — más reusable y contextualmente correcto (es factor de UoW).
- Constante `WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS` viene de `settings`; el re-export se borra.
- Borrar `application/bootstrap/`.

Callers a actualizar: `modules/reels/application/orchestrator.py:246` (lazy) y `modules/reels/application/use_cases/render_scripted_video.py:23` (lazy). Ambos cambian 1 línea.

`tests/test_social_publishing.py:18` — se borra el test entero (R recomendación).

### 3.C — `application/scripted_render/service.py` (702 LoC)

Symbol único activo: `ScriptedVideoRenderService`. Ese archivo además tiene varios helpers (`_ResolvedScriptedVideoRequest`, `_ScriptedRenderSettingsPayload`, `ScriptedVideoRenderResult`, `ScriptedVideoArtifactRecord` inlined, `UnitOfWork = object` alias, varias funciones internas).

**Destino**: `modules/rendering/application/scripted_video/`. Como el archivo monolítico tiene **702 LoC** (excede el límite ~500 LoC del acceptance), debe partirse:

- `modules/rendering/application/scripted_video/payload.py` — `_ScriptedRenderSettingsPayload` Pydantic + helpers de validación (~100 LoC).
- `modules/rendering/application/scripted_video/types.py` — `ScriptedVideoRenderResult`, `_ResolvedScriptedVideoRequest`, `ScriptedVideoArtifactRecord` (~50 LoC).
- `modules/rendering/application/scripted_video/service.py` — `ScriptedVideoRenderService` clase + métodos (~500 LoC, justo en el límite).

Caller activo: `modules/reels/application/use_cases/render_scripted_video.py:24` — actualizar el lazy import al nuevo path.

`tests/integration/delivery/test_worker_dispatcher_flow.py:230,236` — actualizar las dos cadenas `mock.patch("application.scripted_render.service.ScriptedVideoRenderService...")` al nuevo path `modules.rendering.application.scripted_video.service.ScriptedVideoRenderService`.

`application/scripted_render/__init__.py` (byte-igual a service.py post-impl_17) — borrar entero.

### 3.D — `domain/properties/model.py:Property` (485 LoC)

Hay un `Property` legacy aquí y un `CatalogProperty` aggregate moderno mencionado en `REFACTOR_STATUS.md:79-83`. **Discrepancia §8.1**: ¿son el mismo aggregate? ¿se unifican? El implementer 18b debe verificar primero. Si son intercambiables, mover `Property` a `modules/catalog/domain/property.py` (override del moderno, o renombrar el moderno a `LegacyProperty` y usar el frozen como canónico) — decisión del leader.

Callers activos: 5 archivos en `modules/` + 5 tests + frozen. ~10 line edits.

### 3.E — `domain/tenancy/{context,storage}.py`

- `TenantContext` (14 LoC) → `modules/tenancy/domain/context.py`.
- `SiteStorageLayout` (22 LoC) → `modules/tenancy/domain/storage.py` o `shared/storage/site_layout.py` (junto con `services/media/site_storage.py`). Decisión: **`shared/storage/site_layout.py`** (cross-cutting, no es un aggregate de tenancy).

Callers: ver §2.

### 3.F — `domain/media/planning.py:build_media_delivery_plan`

Función pura (88 LoC) → `modules/reels/domain/media_planning.py`. Caller único en activo: `ingest_property_into_reel.py:46`.

### 3.G — `domain/media/types.py`, `domain/publishing/{platforms,types}.py`

Sin callers directos vivos (los activos siempre apuntan a `application/types.py`). Borrar al borrar `domain/`. **Discrepancia §8.2**: redundancia en field-order que debería ser conscientemente eliminada.

### 3.H — `core/logging.py` (639 LoC)

Symbols consumidos por activo: `LoggedProcess`, `format_console_block`, `format_detail_line`, `format_context_line`, `build_log_context`, `configure_logging`, `get_rich_console`, `create_progress`, `format_message_line`, `format_duration`, `log_persistent_event`, `resolve_log_directory`, `resolve_dated_log_directory`, `DailyDirectoryRotatingFileHandler`.

639 LoC > 500. Partir en 2:
- `shared/observability/console.py` (~250 LoC) — `format_console_block`, `format_detail_line`, `format_context_line`, `format_duration`, `format_message_line`, `build_log_context`, `_format_title`, `_escape`, `_strip_rich_markup`, etc.
- `shared/observability/logging_runtime.py` (~390 LoC) — `configure_logging`, `LoggedProcess`, `DailyDirectoryRotatingFileHandler`, `PlainTextFormatter`, `PersistentLogFormatter`, `NullProgress`, `create_progress`, `get_rich_console`, `resolve_log_directory`, `resolve_dated_log_directory`, `log_persistent_event`, `_configure_audit_logger`.
- `shared/observability/__init__.py` agrega.

`tests/test_logging.py:97` mockeo `patch("core.logging._current_log_date")` — actualizar al nuevo path (`shared.observability.logging_runtime._current_log_date`).

### 3.I — `core/errors.py` (364 LoC)

Toda la jerarquía de excepciones. <500 LoC, mover entera a `shared/errors/types.py`. `shared/errors/__init__.py` agrega.

### 3.J — `core/media_cleanup.py` (29 LoC)

Mover entero a `shared/media_cleanup/policies.py` o `shared/media_cleanup/__init__.py`.

### 3.K — `core/locking.py` (71 LoC)

Mover a `shared/locking/file_lock.py`.

### 3.L — `core/dependencies.py` (30 LoC, `require_dependency`)

Mover a `shared/observability/dependencies.py`. (Su lugar conceptual no es 100% claro — observability fue elección de Phase 1; alternativas: `shared/runtime/`).

### 3.M — `services/media/reel_rendering/*` (12 archivos, 2 731 LoC)

Destino: `modules/rendering/infrastructure/`. La estructura existente ya tiene `runtime/`, `layout/`, `ffmpeg/`. Sugerencia:

- `services/media/reel_rendering/models.py` (146) → `modules/rendering/infrastructure/models.py` o `modules/rendering/domain/render_template.py` (algunos son VOs).
- `services/media/reel_rendering/data.py` (122, post-R7) → `modules/rendering/infrastructure/data/property_reel_data.py`.
- `services/media/reel_rendering/runtime.py` (222) → `modules/rendering/infrastructure/runtime/legacy_facade.py` o re-export interno.
- `services/media/reel_rendering/layout.py` (27 facade) → borrar (post-feature-15 es facade).
- `services/media/reel_rendering/render.py` (75) → ya hay `modules/rendering/infrastructure/ffmpeg/render_reel.py` — fusionar.
- `services/media/reel_rendering/manifest.py` (321) → `modules/rendering/infrastructure/manifest.py`.
- `services/media/reel_rendering/poster.py` (390) → `modules/rendering/infrastructure/poster.py`.
- `services/media/reel_rendering/preparation.py` (450) → `modules/rendering/infrastructure/preparation.py`.
- `services/media/reel_rendering/formatting.py` (494) → `modules/rendering/infrastructure/formatting.py`. **Roza el límite** (494/500); aceptable byte-igual.
- `services/media/reel_rendering/filters.py` (329) → `modules/rendering/infrastructure/ffmpeg/filters.py` (el ffmpeg subdir ya existe).

### 3.N — `services/publishing/social_delivery/*` (12 archivos, 2 312 LoC)

Destino: `modules/publishing/infrastructure/{adapters/gohighlevel,social_copy}/`.

- `description.py` (387), `post_copy.py` (226) → `modules/publishing/infrastructure/social_copy/{description,post_copy}.py`.
- `gohighlevel_*.py` (4 archivos), `interfaces.py`, `models.py` (414), `platform_policy.py`, `property_publisher.py` (338), `user_selection.py` → `modules/publishing/infrastructure/adapters/gohighlevel/` (la mayoría ya tiene gemelo allí; consolidar).
- `__init__.py` (122) — re-exports — fusionar con el `__init__.py` moderno o borrar tras adaptar callers.

`models.py` (414 LoC) cabe; `description.py` (387) cabe; `property_publisher.py` (338) cabe.

### 3.O — `services/ai/photo_selection/*` (4 archivos, 1 400 LoC)

Destino: `modules/rendering/infrastructure/ai_photo_selection/`.

- `selection.py` **774 LoC** — **debe partirse** para cumplir el acceptance ≤500 LoC. Sugerencia:
  - `modules/rendering/infrastructure/ai_photo_selection/selector.py` (~400 LoC) — `download_and_filter_property_images` orquestador + helpers.
  - `modules/rendering/infrastructure/ai_photo_selection/scoring.py` (~370 LoC) — heurísticas de filtrado (variants, dedupe, etc.).
- `prompting.py` (301) — al borde, byte-igual aceptable.
- `client.py` (287) — Gemini API client, byte-igual.
- `__init__.py` (38) — re-exports.

### 3.P — `services/media/property_media/*` (5 archivos, 655 LoC)

Destino: `modules/rendering/infrastructure/photos/` (alineado con `ai_photo_selection`). Ningún archivo > 400 LoC, sin necesidad de split.

### 3.Q — `services/media/site_storage.py` (51 LoC)

Destino: `shared/storage/site_layout.py`. Re-exporta `SiteStorageLayout` (que viene de `domain/tenancy/storage.py` y ya estará movido en 18b).

### 3.R — `services/transport/http/operations.py` (466 LoC) y dirs vacíos

Sin callers activos tras impl_17. **Borrar al borrar `services/`**. Adicionalmente borrar dirs vacíos: `services/ai_photo_selection/`, `services/property_media/`, `services/reel_rendering/`, `services/social_delivery/{,platforms/}`, `services/webhook_transport/`.

### 3.S — `application/{persistence,dispatch,tenancy}.py`

Sin callers vivos. Borrar al borrar `application/`. Confirma feature 17 review §1.

### 3.T — `application/pipeline/content_generation.py` (150 LoC)

`ContentGenerator` (Protocol) + `GeneratedPropertyContent` (dataclass) — 150 LoC. Caller único: `ingest_property_into_reel.py:35`.

Destino: `modules/reels/application/content_generator.py` (es Protocol al nivel de aplicación, no infra). El archivo importa `services.publishing.social_delivery` (3 imports) — al moverse ya viven en `modules/publishing/infrastructure/social_copy/` y se reapunta.

---

## 4. Tests legacy a borrar / migrar

### Tests root a borrar (cobertura moderna existe)

| Archivo | LoC | Razón | Cobertura moderna |
|---|---:|---|---|
| `tests/test_social_publishing.py` | **1 746** | Carga `application.bootstrap.runtime`, `application.types`, `services.publishing.social_delivery.*` (legacy paths). Test de smoke E2E que duplica `tests/integration/publishing/`. | `tests/integration/publishing/test_connections_router.py` (feature 5), `tests/integration/delivery/test_worker_dispatcher_flow.py` (feature 16), `tests/unit/publishing/test_inspect_agency_social_accounts.py`. |
| `tests/test_reel_pipeline.py` | **1 381** | Test de pipeline reel-rendering desde imports legacy `services.media.reel_rendering.*`. **Probable duplicación** con `tests/unit/rendering/` y `tests/integration/reels/`. **Verificar antes de borrar**: comparar coverage de `manifest`, `preparation`, `render`, `runtime`, `poster`, `formatting`. Si la cobertura moderna lo cubre 100 %, borrar; si no, fragmentar y migrar. | Parcial: `tests/unit/rendering/test_frame_composition.py`, `tests/unit/reels/test_persist_local_artifacts.py`. **Decisión recomendada del leader**: borrar y, si reviewer detecta gap, abrir feature de Phase 3. |

### Tests root a migrar a `tests/unit/<bc>/`

| Archivo | LoC | Destino |
|---|---:|---|
| `tests/test_logging.py` | 134 | `tests/unit/shared/test_observability_logging.py` (cubre `format_console_block`, `format_detail_line`, `LoggedProcess`, `_current_log_date`). |
| `tests/test_reel_render_command.py` | 86 | `tests/unit/rendering/test_ffmpeg_command.py`. |
| `tests/test_reel_runtime_dynamic_urls.py` | 172 | `tests/unit/rendering/test_runtime_urls.py`. |
| `tests/test_gemini_photo_selection.py` | 879 | `tests/unit/rendering/test_ai_photo_selection.py`. **Verificar split** en línea con la partición de `selection.py` (§3.O). |

### Tests modernos a actualizar

Todos los hits en `tests/integration/`, `tests/unit/<bc>/` y `conftest.py` (~30 imports) reapuntan a los nuevos paths. Cambio mecánico, sin lógica.

`tests/integration/delivery/test_worker_dispatcher_flow.py:230,236` — strings de `mock.patch` actualizados al nuevo path de `ScriptedVideoRenderService`.

### Total LoC tests legacy a borrar/migrar

- Borrados: 1 746 + 1 381 = **3 127 LoC**.
- Migrados (mecánico): 134 + 86 + 172 + 879 = **1 271 LoC**.
- Total tests legacy: **4 398 LoC**.

### Tests verdes esperados post-feature

Baseline post-feature-17: **454 passed**. Diferencial:
- `-N` tests de `test_social_publishing.py` y `test_reel_pipeline.py` (estimación 80-120 tests perdidos por ser god-files).
- `+M` nuevos en migrados (cifra similar al baseline; cero ganancia neta por adaptación).
- `+P` en eventuales tests añadidos para los nuevos splits (`scripted_video`, `ai_photo_selection`, `observability`).

Estimación conservadora: **post-18 ≈ 380-420 passed** (perderíamos 30-70 netos sobre 454, principalmente por cobertura muerta del social_publishing legacy). Esto **NO es regresión funcional** — es retirada de tests redundantes.

---

## 5. Cambios en docs

### `AGENTS.md` (130 LoC)

Cambios:
- Línea 73-77 (sección "Código legacy en transición"): borrar el párrafo entero. Reemplazar por: "Phase 2 completada en feature 18: los directorios legacy `services/`, `application/`, `repositories/`, `core/`, `domain/` se han eliminado. Toda la lógica vive ya en `apps/`, `modules/<bc>/` y `shared/`."
- Línea 84 referencia a "baseline tras Phase 1 es 116 tests verdes" — actualizar al baseline post-Phase 2.
- Sección 4 "Cómo elegir una tarea" — ajustar lenguaje (Phase 2 done, mencionar Phase 3 como próxima).

### `REFACTOR_STATUS.md` (233 LoC)

Cambios:
- Línea 7: cambiar `**Phase 1 foundation → Phase 2 god-file split → Phase 3 URL rename + frontend lockstep**` por marcar Phase 2 ✅ DONE.
- Línea 139 (sección "Phase 2 — God-file split"): cambiar a `## Phase 2 — God-file split ✅ DONE` y añadir resumen de cierre con métricas: `13 features (2-14, 15, 16, 17, 18a/b/c) movieron N LoC desde dirs legacy a modules/. Baseline final 380-420 passed.`.
- Sección "After Phase 2" (línea 202-210): mover a "Status post-Phase 2" en pasado.
- Línea 214 ("Phase 3 — URL rename + frontend lockstep (deferred)"): ahora es la fase activa; quitar `(deferred)`.

### `docs/architecture.md` (111 LoC) — `:88-92`

Eliminar el párrafo que dice: *"❌ Añadir código nuevo en `services/`, `application/`, `repositories/`, `core/`, `domain/`. Son la capa de compatibilidad de Phase 1; cualquier feature nueva entra en `modules/<bc>/`."*

Reemplazar por: *"Los directorios `services/`, `application/`, `repositories/`, `core/`, `domain/` no existen. Toda la lógica vive en `apps/`, `modules/<bc>/`, `shared/`."*

### `docs/conventions.md` (131 LoC)

Revisar referencias a paths legacy. Si menciona `core.logging`, `core.errors`, etc., reapuntar a `shared.observability`, `shared.errors`. **No leído íntegro** — implementer revisa en detalle.

### `docs/phase_2_operating_rules.md` (320 LoC)

Mantener como referencia histórica. Marcar al inicio: "Phase 2 completada con feature 18 — este documento queda como histórico de las reglas de operación, no aplica a Phase 3".

### `init.sh:99`

```bash
RECENT_LEGACY=$(find services application repositories core domain -type f -name "*.py" -mtime -1 2>/dev/null | wc -l)
```

Tras feature 18 los 5 dirs no existen → el `find` siempre retorna 0. **Limpieza recomendada**: borrar el bloque entero (líneas 92-106) ya que es informativo y obsoleto. Alternativa: dejar el bloque actualizado para alertar si alguien recrea uno de esos dirs (defensa contra regresión). **Decisión leader**.

### Comentarios docstrings en código vivo que mencionan dirs frozen

`modules/rendering/application/frame_composition.py:22`, `modules/reels/application/orchestrator.py:6`, `modules/reels/application/use_cases/ingest_property_into_reel.py:227` — review_17 §6 los menciona. Quitar las referencias históricas a `services/`, `application/` (limpieza cosmética).

---

## 6. Riesgos / acoplamientos

### R1 — `application/scripted_render/service.py` migración (mock.patch path string)

`tests/integration/delivery/test_worker_dispatcher_flow.py:230,236` aplica `mock.patch("application.scripted_render.service.ScriptedVideoRenderService.__init__", ...)`. El string DEBE actualizarse al nuevo path (`modules.rendering.application.scripted_video.service.ScriptedVideoRenderService`). Si se olvida, el test del worker se vuelve no-op (el `mock.patch` "funciona" porque el módulo ya existe pero ya no se invoca esa clase) — **falso verde**. Verificación adicional: que el test sigue cubriendo el flujo `claim → handler → outbox` end-to-end al cambiar el path.

### R2 — `Property` aggregate duplicado (legacy vs `CatalogProperty`)

`domain/properties/model.py:Property` (485 LoC) — aggregate legacy con field shape específica (`source_property_id`, `wordpress_source_id`, etc.). `modules/catalog/domain/CatalogProperty` — moderno (mencionado en `REFACTOR_STATUS.md:79-83`, no leído íntegro en este explore). El plan asume que ambos representan el mismo concepto de dominio. **Verificación obligada antes de implementar**: comparar firmas y consumidores. Si difieren, decidir migración (rename, merge, split). **Posible bloqueo si el moderno no soporta el field shape que `application/types.py:PropertyContext.property` requiere.**

### R3 — Field-order divergente entre `application/types.py` y `domain/media/types.py`

Ambos declaran `MediaDeliveryPlan`, `PublishedMediaArtifact`, `RenderedMediaArtifact`, etc. Como son `@dataclass(frozen=True, slots=True, init=False)` con `__init__` custom + `_setattr_`, los field-order y método-shape **deben validarse 1:1** antes de mover. La copia activa es la de `application/types.py`. La de `domain/` queda muerta tras feature 17 — verificar que ningún transit fue cambiado.

### R4 — Lazy chain `apps/worker → modules/reels/application/orchestrator → application/bootstrap/runtime → services/publishing/social_delivery`

`apps/worker --check` debe seguir verde. Tras 18b mover `build_default_social_property_publisher` a `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`, el lazy import en `orchestrator.py:246` cambia de path. El factory mantiene la misma firma. **Riesgo**: import-time eager en el factory si toca settings de producción → estallaría `--check` (que NO debe abrir GoHighLevel). Validar que `factory.py` NO importa nada que requiera `.env` cargada en tests.

### R5 — LoC ≤500 acceptance vs realidad

Archivos vivos hoy >500 LoC bajo `apps/modules/shared`:
- `modules/reels/application/use_cases/ingest_property_into_reel.py` — **944**.
- `modules/ingestion/transport/http/wordpress_webhook_router.py` — **621**.
- `modules/reels/transport/http/admin_reels_router.py` — **587**.

Archivos que llegan al límite tras la migración:
- `services/ai/photo_selection/selection.py` (774) — DEBE partirse al moverse a `modules/rendering/infrastructure/ai_photo_selection/`.
- `application/scripted_render/service.py` (702) — DEBE partirse al moverse a `modules/rendering/application/scripted_video/`.
- `services/media/reel_rendering/formatting.py` (494) — al borde, byte-igual aceptable.
- `services/media/reel_rendering/preparation.py` (450) — aceptable.
- `services/publishing/social_delivery/models.py` (414) — aceptable.
- `core/logging.py` (639) — al moverse a `shared/observability/`, partir.
- `core/errors.py` (364) — aceptable byte-igual al moverse a `shared/errors/`.
- `domain/properties/model.py` (485) — al borde, mover a `modules/catalog/domain/property.py`.

**5 archivos modulares activos hoy NO cumplen el ≤500** (los 3 de la lista de arriba). El acceptance literal es estricto: **"Ningún archivo bajo `apps/`, `modules/`, `shared/` excede ~500 LoC"**. Tres opciones:
- (a) Partir los 3 archivos hoy >500 LoC en feature 18 (alcance grande).
- (b) Solicitar al leader/usuario relajar el acceptance: "≤500 LoC con ~10% de tolerancia" → todos los actuales caben menos `ingest_property_into_reel.py:944` que claramente debe partirse.
- (c) Dejar la regla como warning, no bloqueante, y agendar splits para Phase 3.

**Recomendación**: (b) o (c). Si (a), aumentar alcance de 18c.

### R6 — `tests/test_reel_pipeline.py` (1 381 LoC) cobertura genuina vs duplicación

Antes de borrarlo, el implementer debe ejecutar pytest con `--cov=services/media/reel_rendering` (o equivalente moderno) y comparar con la suite moderna. Si hay assertions únicas (caminos no cubiertos por `tests/unit/rendering/`), la decisión "borrar" se vuelve "fragmentar y migrar". **Acción obligada antes de borrar**: report de cobertura.

### R7 — `services/media/reel_rendering/__init__.py:1` re-exporta `load_property_reel_data`

`load_property_reel_data` quedó stub post-R7 (raise PropertyReelError). Si el __init__.py re-exporta, alguien podría hacer `from services.media.reel_rendering import load_property_reel_data` y el caller sigue funcionando hasta producción. Verificar tras feature 18 que ningún caller activo importa esa función.

### R8 — Comentarios "Inlined from the retired ..." en `application/scripted_render/{__init__,service}.py:29-31`

Cuando se mueva el código a `modules/rendering/application/scripted_video/types.py`, el comentario que dice "until feature 18 deletes `application/` entirely" se vuelve obsoleto y debe quitarse / actualizarse. Trivial.

### R9 — `apps/api --check` y `apps/worker --check` exit 0 con DB no-migrada en CI

`apps/api/readiness.py` ya importa de `services.media.reel_rendering.{runtime,models}` (4 imports lazy). Tras 18c reapuntar a `modules.rendering.infrastructure.runtime.*`. Verificar que el `--check` lazy resuelve correctamente las nuevas rutas; en particular `resolve_ffmpeg_binary`, `resolve_font_path`, `resolve_background_audio_paths` y `PropertyReelTemplate`.

### R10 — `tests/test_logging.py:97` mockeo `patch("core.logging._current_log_date", ...)`

Si la implementación se mueve a `shared/observability/logging_runtime.py`, el path del `patch` cambia a `shared.observability.logging_runtime._current_log_date`. **Riesgo de test no-op silencioso** si se olvida — el `patch` "funciona" pero el mock no aplica al símbolo real.

### R11 — Phase 3 URL rename pendiente

`REFACTOR_STATUS.md:214-233` describe Phase 3 (URLs `/admin/...` → `/v1/...`). NO entra en feature 18 — solo se anuncia como próxima fase. Ni `apps/api/app_factory.py` ni los routers cambian sus paths en feature 18.

### R12 — `init.sh:99` busca `services|application|repositories|core|domain` recursivamente

Tras feature 18 los 5 dirs no existen → `find` retorna 0 hits siempre → bloque siempre OK. Acceptable pero engañoso (pierde valor de detección). Decisión: borrar el bloque o reapuntarlo a un grep `^(from|import)\s+(services|application|repositories|core|domain)\.` en `apps modules shared tests` (ya cero post-feature; útil como guard rail anti-regresión).

---

## 7. Plan de implementación recomendado

### Si feature 18 se mantiene como una sola unidad (NO recomendado)

Orden:

1. **Pre-feature**: confirmar baseline 454 passed; leer `modules/catalog/domain/CatalogProperty` para resolver R2.
2. **Sub-paso A — `core/`**:
   - Crear `shared/observability/{console,logging_runtime,dependencies}.py` con la implementación movida.
   - Crear `shared/errors/types.py` con la jerarquía.
   - Crear `shared/media_cleanup/policies.py`.
   - Crear `shared/locking/file_lock.py`.
   - Re-escribir `shared/{observability,errors,media_cleanup,locking}/__init__.py` como agregadores.
   - Reapuntar 10 hits directos en `modules/` + 4 en `tests/`.
   - Borrar `core/`.
3. **Sub-paso B — `domain/`**:
   - Crear `modules/tenancy/domain/{context,storage}.py`.
   - Crear `modules/reels/domain/{types,media_planning}.py`.
   - Crear `modules/catalog/domain/property.py` (resolver R2 antes).
   - Reapuntar imports en `modules/`, `tests/`.
   - Borrar `domain/`.
4. **Sub-paso C — `application/`**:
   - Crear `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`.
   - Crear `shared/db/uow_factory.py` (o consolidar en `apps/worker/runtime.py`).
   - Mover `application/types.py:*` a `modules/reels/domain/types.py` (y `modules/publishing/domain/types.py` si split DDD).
   - Mover `application/pipeline/content_generation.py` → `modules/reels/application/content_generator.py`.
   - Mover `application/scripted_render/service.py` (split) → `modules/rendering/application/scripted_video/{service,payload,types}.py`.
   - Actualizar `mock.patch` strings en `test_worker_dispatcher_flow.py:230,236`.
   - Actualizar lazy imports en `orchestrator.py:246` y `render_scripted_video.py:23-24`.
   - Borrar `tests/test_social_publishing.py` (1 746 LoC).
   - Borrar `application/`.
5. **Sub-paso D — `services/`**:
   - Mover `services/media/reel_rendering/*` → `modules/rendering/infrastructure/`.
   - Mover `services/publishing/social_delivery/*` → `modules/publishing/infrastructure/{adapters/gohighlevel,social_copy}/`.
   - Mover `services/ai/photo_selection/*` (split `selection.py`) → `modules/rendering/infrastructure/ai_photo_selection/`.
   - Mover `services/media/property_media/*` → `modules/rendering/infrastructure/photos/`.
   - Mover `services/media/site_storage.py` → `shared/storage/site_layout.py`.
   - Reapuntar 4 imports en `apps/api/readiness.py`, ~38 imports en `modules/`, ~25 imports en `tests/`.
   - Migrar/borrar tests root (`test_reel_pipeline.py`, `test_logging.py`, `test_reel_render_command.py`, `test_reel_runtime_dynamic_urls.py`, `test_gemini_photo_selection.py`).
   - Borrar `services/`.
6. **Sub-paso E — Splits adicionales** (R5):
   - Decidir destino de `ingest_property_into_reel.py:944`, `wordpress_webhook_router.py:621`, `admin_reels_router.py:587`.
7. **Sub-paso F — Docs**:
   - Actualizar `AGENTS.md`, `REFACTOR_STATUS.md`, `docs/architecture.md`, `docs/conventions.md`, `docs/phase_2_operating_rules.md`.
   - Limpiar `init.sh:92-106`.
   - Limpiar docstrings históricos en `frame_composition.py`, `orchestrator.py`, `ingest_property_into_reel.py`.
8. **Verificación final**:
   - `Grep "from (services|application|core|domain|repositories)\.\|import (services|application|core|domain|repositories)\."` en `apps modules shared tests` → 0 hits.
   - `pytest -q` verde.
   - `python -m apps.api --check` exit 0.
   - `python -m apps.worker --check` exit 0.
   - `feature_list.json` feature 18 → `done`.
9. **Cierre Phase 2**: actualizar `progress/history.md`, `progress/current.md`.

### LoC delta estimado

- Borrados: ~12 803 (frozen) + ~3 127 (tests legacy borrados) = **~15 930 LoC**.
- Creados: ~13 000 LoC (mover-rename + splits, mismo cómputo neto que el borrado en LoC pero distribuido).
- Modificados: ~120 LoC (puntos de import en `apps/modules/shared/tests`).
- **Neto**: ~−3 000 LoC en arbol total (principalmente por dedup `application/types ↔ domain/media/types`).

### Si feature 18 se parte en 18a/18b/18c

Ver §0.C arriba. Cada sub-feature puede ejecutarse en una sesión de 1-2 h sin trasnocharla.

### **Bloqueo recomendado**

**Bloqueo**: la feature 18 según el plan original mezcla 6 ejes ortogonales y ~15 000 LoC tocadas, lo que excede tanto la mediana de Phase 2 (~400 LoC) como la regla "una feature por sesión" del leader. Antes de implementar, **el leader debe**:

1. **Decidir** si se acepta partir feature 18 en 18a/18b/18c (recomendado), o si se mantiene como bloque único multi-sesión.
2. **Resolver R2** (Property aggregate duplicado) confirmando con el implementer si `CatalogProperty` cubre todos los fields que `domain/properties/model.py:Property` expone hoy.
3. **Decidir R5** (regla LoC ≤500 aplica estrictamente, con tolerancia 10%, o como warning).
4. **Decidir R6** (borrar `test_reel_pipeline.py` requiere coverage report previo, o hacerlo a ciegas).
5. **Decidir** si las migraciones de tests root (test_logging, test_reel_render_command, etc.) se hacen 1:1 o se reescriben modernizándolos.

---

## 8. Discrepancias detectadas

### 8.1 — Duplicación `Property` legacy vs `CatalogProperty` moderno

`domain/properties/model.py:Property` (485 LoC) y `modules/catalog/domain/CatalogProperty` (mencionado en `REFACTOR_STATUS.md:79-83` como modelo Phase 1, no leído íntegro en este explore) son ambos aggregates de "propiedad inmobiliaria". El código activo importa **siempre** `domain.properties.model.Property` (verificado con Grep). **Sin información sobre si `CatalogProperty` existe ya con el field shape compatible** o si hay que migrarlo. Bloqueo potencial — el implementer/reviewer debe confirmar.

### 8.2 — Triple definición de tipos `MediaDeliveryPlan`, `PublishedMediaArtifact`, `RenderedMediaArtifact`, `SocialPublishContext`, `PlatformPublishTargetPlan`

- `application/types.py` (versión activa, importada por todos los callers).
- `domain/media/types.py` (versión paralela, sin callers activos directos).
- `domain/publishing/types.py` (versión paralela para `SocialPublishContext`/`PlatformPublishTargetPlan`).

Esto es **deuda técnica latente**: tres copias divergentes del mismo concepto. Feature 18 debe consolidar a 1 sola versión (la que viva en `modules/<bc>/domain/`). El campo `delivery_plan` por defecto en `PropertyContext` en `application/types.py:231-241` tiene el shape concreto activo — usar esa.

### 8.3 — `application/bootstrap/__init__.py` y `application/bootstrap/runtime.py` byte-iguales

Tras impl_17 ambos archivos son byte-iguales (verificado con `diff` por review_17 §B3). Es un **patrón de re-export anti-pattern**: `__init__.py` típicamente debería re-exportar de `runtime.py`, no duplicarlo. Feature 18 borra ambos, así que la deuda muere con el dir.

### 8.4 — `application/scripted_render/__init__.py` y `application/scripted_render/service.py` byte-iguales

Mismo patrón que 8.3 tras impl_17. 702 LoC × 2 = 1 404 LoC físicos pero 702 efectivos.

### 8.5 — `services/social_delivery/platforms/` y dirs vacíos en `services/`

`ls services/` muestra `ai_photo_selection/`, `property_media/`, `reel_rendering/`, `social_delivery/{,platforms/}`, `webhook_transport/` — todos vacíos (sin `.py`). Probablemente residuo de splits anteriores. Borrar al borrar `services/`.

### 8.6 — `services/__init__.py` no aparece en el `find -name "*.py"`

El `find` no encontró `services/__init__.py` — verificar si existe (el dir es importable, así que sí). Probablemente está pero el comando lo filtró. Confirmar antes del borrado para evitar `ImportError` transitorios durante la migración.

### 8.7 — `init.sh:99` lista los 5 dirs frozen (`services application repositories core domain`)

Pero `repositories/` ya no existe (borrado por feature 17). El `find` ya falla silenciosamente para ese path. Indica que **`init.sh` no se actualizó en feature 17** — si feature 18 también olvida actualizarlo, queda como deuda menor. Actualizable trivialmente.

### 8.8 — `feature_list.json:362` "Búsqueda 'from services.' (...) no devuelve nada"

El acceptance literal de feature 18 menciona también `from repositories.` aunque `repositories/` ya está borrado (feature 17). Cero hits desde feature 17. Acceptance se cumple para `repositories.` automáticamente.

### 8.9 — `progress/explore_feature_17_retire_repositories.md:953` ya anticipaba "tests/test_social_publishing.py (1 746 LoC) … feature 18 lo borra entero o lo migra"

El plan de feature 18 debe respetar esa decisión. Recomendación: **borrar entero** (cobertura moderna en `tests/integration/publishing/` + `tests/integration/delivery/test_worker_dispatcher_flow.py`).

---

**Fin del informe.**

> **Resolución**: el explore recomienda **bloquear** la feature 18 hasta que el leader decida partición (18a/18b/18c) o aceptación de alcance multi-sesión, y resuelva los 5 puntos abiertos (§7 final). Si el leader autoriza ejecución como bloque único, este informe sirve de roadmap exhaustivo.
