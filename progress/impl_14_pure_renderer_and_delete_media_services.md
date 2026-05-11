# Impl — Feature 14 `rendering_pure_renderer_and_delete_media_services`

> Mover `DefaultMediaRenderer` (renderer puro, sin DB) a
> `modules/rendering/application/frame_composition.py`, mover los 4 adapters
> delgados sobrevivientes a `application/bootstrap/pipeline_adapters.py`,
> borrar `application/pipeline/media_services.py` + `default_services.py`,
> reducir `application/pipeline/__init__.py` (1839 LoC dead code) a un
> package marker vacío y reapuntar `application/bootstrap/{runtime,__init__}.py`
> a los nuevos paths preservando la byte-igualdad. Conforme al plan del
> explorer (`progress/explore_feature_14_pure_renderer_and_delete_media_services.md`).

---

## 1. Archivos creados / modificados / borrados

### Creados

| Archivo | LoC | Tipo |
|---------|-----|------|
| `modules/rendering/application/frame_composition.py` | 184 | Renderer puro `DefaultMediaRenderer` (cuerpo verbatim del legacy `media_services.py:134-264`). Métodos públicos `render_media`/`render_video`, métodos privados `_render_reel`, staticmethod `_build_render_data`. Imports: `logging`, `tempfile`, `Path`, `uuid4`, types de `application.types`, helpers de `core.logging`, primitivas de `services.media.reel_rendering.*`. Sin DB, sin UoW. |
| `application/bootstrap/pipeline_adapters.py` | 237 | Los 4 adapters delgados (cuerpo verbatim de `media_services.py:53-84, 87-131, 271-316, 319-367`): `DefaultPropertyInfoService`, `DefaultMediaPreparationService`, `FileSystemMediaPublisher`, `CompositeMediaPublisher`. Cada uno acepta `unit_of_work_factory` por compat (lo descarta con `del`) y delega a su use case moderno. |
| `tests/unit/rendering/test_frame_composition.py` | 382 | Unit (8 tests, monkeypatching las 6 primitivas top-level del módulo nuevo: `build_reel_template_for_render_profile`, `build_local_selected_slides`, `prepare_reel_render_assets`, `write_property_reel_manifest_from_data`, `generate_property_reel_from_data`, `generate_property_poster_from_data`). Sin ffmpeg, sin DB. |

### Modificados

| Archivo | Cambio |
|---------|--------|
| `application/bootstrap/runtime.py` | Sustituido `from application.pipeline.default_services import (Composite…, …)` por `from application.bootstrap.pipeline_adapters import (4 adapters)` + `from modules.rendering.application.frame_composition import DefaultMediaRenderer`. 187 LoC pre = 187 LoC post (bloque de imports reorganizado, sin cambio neto). |
| `application/bootstrap/__init__.py` | Cambio idéntico al anterior (siguen byte-iguales — `diff` exit 0 verificado). |
| `application/pipeline/__init__.py` | 1839 LoC → 1 LoC (`# Empty package marker for application.pipeline`). El paquete sigue siendo importable como tal porque conserva submódulos vivos (`media_pipeline.py`, `interfaces.py`, `job_runner.py`, `content_generation.py`). |
| `feature_list.json` | Feature 14 status `pending` → `in_progress`. |

### Borrados

| Archivo | LoC eliminado |
|---------|---------------|
| `application/pipeline/media_services.py` | 377 (bridge legacy de los 4 adapters + renderer) |
| `application/pipeline/default_services.py` | 17 (facade huérfano que re-exportaba 6 símbolos del archivo anterior) |

Reducción neta del repo: **−2233 LoC** brutos eliminados (377 + 17 + 1839−1 reset de `__init__.py`) versus **+803 LoC** añadidos (184 + 237 + 382), = **−1430 LoC netos**.

---

## 2. Contenido movido (rangos verbatim del archivo de entrada)

Archivo de entrada `application/pipeline/media_services.py` (377 LoC, eliminado físicamente).

Distribución verbatim:

| Rango origen | Símbolo | LoC | Destino |
|--------------|---------|-----|---------|
| `:53-84` | `DefaultPropertyInfoService` | 32 | `application/bootstrap/pipeline_adapters.py` |
| `:87-131` | `DefaultMediaPreparationService` | 45 | `application/bootstrap/pipeline_adapters.py` |
| `:134-264` | `DefaultMediaRenderer` (renderer puro) | 131 | `modules/rendering/application/frame_composition.py` |
| `:267-268` | `class DefaultMediaRenderer(DefaultMediaRenderer): pass` (class shadow, R4) | 2 | **Descartado** (no se reescribe) |
| `:271-316` | `FileSystemMediaPublisher` | 46 | `application/bootstrap/pipeline_adapters.py` |
| `:319-367` | `CompositeMediaPublisher` | 49 | `application/bootstrap/pipeline_adapters.py` |
| `:1-50` + `:370-377` | imports + `__all__` | 58 | Redistribuidos (cada archivo nuevo tiene sus propios imports y `__all__`) |

`resolve_property_poster_output_path` (importado pero nunca usado en `media_services.py:45`) se descartó en la mudanza — confirmado con grep que ningún otro caller lo necesita en el nuevo `frame_composition.py`.

---

## 3. Decisiones del explore respetadas

- **Opción C (§0)**: los 4 adapters delgados van a `application/bootstrap/pipeline_adapters.py` (NO a `modules/`). Cuerpo verbatim. No se tocan `application/pipeline/interfaces.py` (Protocols) ni `application/pipeline/media_pipeline.py` (orquestador legacy). Feature 16 retira el orquestador entero y este archivo desaparece con él.
- **Renderer (§2)**: `DefaultMediaRenderer` se mueve **completo y verbatim** a `modules/rendering/application/frame_composition.py` (184 LoC con docstring). Nombre **preservado** (no renombrado a `FrameCompositionUseCase` — feature 16 retira la clase entera). Cabe holgadamente en un archivo y no se splittea.
- **D2 (`default_services.py`)**: borrado. Sin call sites externos tras Opción C (los únicos eran `application/bootstrap/{runtime,__init__}.py`, que ahora importan directo de `pipeline_adapters` y `frame_composition`).
- **D3 (`application/pipeline/__init__.py`)**: 1839 LoC dead code reemplazado por package marker vacío (`# Empty package marker for application.pipeline\n`, 1 LoC). `pytest -q` siguió verde (417/417), por lo que NO hubo que restaurar.
- **R3/R5 (`LocalPhotoSelectionEngine` re-export)**: verificado por grep (`grep -rn "LocalPhotoSelectionEngine"` en `apps/`, `modules/`, `shared/`, `tests/` excluyendo `application/pipeline/__init__.py` ahora vacío y `progress/`):
  - El símbolo real vive en `modules/reels/application/use_cases/prepare_reel_assets.py:91`.
  - Tests lo importan **directamente** desde ahí (`tests/unit/reels/test_prepare_reel_assets.py:24-27`, integration tests análogos).
  - Bootstrap NO lo importa directamente; lo encapsula `DefaultMediaPreparationService.__init__` dentro de `pipeline_adapters.py`.
  - **Resultado**: 0 hits externos a `pipeline_adapters.py`. **Re-export omitido** del `__all__` siguiendo la directriz del explore "Si grep da 0 hits, omite el re-export".
- **Bootstrap byte-igualdad**: `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py` siguen byte-iguales. `diff` exit 0 verificado pre-edit y post-edit.
- **Tests legacy**: 409 baseline (features 10-13) intactos. Cero cambios en `tests/test_reel_pipeline.py`, `tests/test_social_publishing.py`, `tests/test_reel_runtime_dynamic_urls.py`, `tests/integration/...`.
- **R4 (class shadow)**: descartado (no se reescribe). El nuevo `frame_composition.py` no contiene `class DefaultMediaRenderer(DefaultMediaRenderer): pass`.

---

## 4. Decisiones de implementación adicionales

### 4.1 — `pipeline_adapters.py` no re-exporta `LocalPhotoSelectionEngine`

El explore (§7 — bullet sobre `__all__`) lo sugería como re-export defensivo. Verificado por grep que **ningún caller externo** lo importa desde `default_services.py` (los tests lo importan directo de `modules/reels/application/use_cases/prepare_reel_assets.py`; bootstrap no lo importa; el adapter `DefaultMediaPreparationService` lo usa internamente). **`__all__` final solo contiene los 4 adapters**. Decisión coherente con la directriz del explore §6 R5 / §8 D7.

### 4.2 — `frame_composition.py`: imports limitados al renderer

El renderer NO importa nada de `application.pipeline.content_generation`, `core.media_cleanup`, `application.persistence` ni use cases — eran imports del antiguo `media_services.py` que solo usaban los 4 adapters. Imports finales (10 entradas): `logging`, `tempfile`, `Path`, `uuid4`, 3 tipos de `application.types`, `format_console_block`/`format_detail_line` de `core.logging`, 4 primitivas de `services.media.reel_rendering`. Cero deuda de imports muertos.

### 4.3 — `pipeline_adapters.py`: ordering de imports

Imports deduplicados/ordenados alfabéticamente dentro de cada bloque: stdlib → `application.*` → `core.*` → `modules.*`. Coherente con `docs/conventions.md`.

### 4.4 — `tests/unit/rendering/test_frame_composition.py`: 8 tests con patches sobre top-level

Tests creados (todos pasando):

1. `test_render_media_returns_rendered_artifact_with_uuid_revision_id` — verifica que `RenderedMediaArtifact` tiene `artifact_kind="reel_video"`, `revision_id` 32-char hex (uuid4().hex), y los 4 paths con sufijos correctos.
2. `test_render_media_creates_staging_dir_under_generated_reels_root` — verifica el `staging_dir` bajo `<generated_reels_root>/_staging/<slug>-…`.
3. `test_render_media_invokes_prepare_reel_render_assets_with_workspace_and_template` — spy sobre `prepare_reel_render_assets`.
4. `test_render_media_invokes_write_manifest_with_correct_paths` — spy sobre `write_property_reel_manifest_from_data`.
5. `test_render_media_invokes_generate_reel_with_correct_paths` — spy sobre `generate_property_reel_from_data`.
6. `test_render_media_invokes_generate_poster_with_correct_paths` — spy sobre `generate_property_poster_from_data`.
7. `test_render_video_alias_delegates_to_render_media` — verifica que `render_video()` produce el mismo flujo que `render_media()`.
8. `test_build_render_data_maps_property_fields` — verifica el mapeo de campos de `PropertyContext` → `PropertyRenderData`, incluyendo `selected_slides=tuple(...)`.

Patrón: `monkeypatch.setattr(fc_module, "<primitive>", _fake)` sobre las 6 primitivas top-level del nuevo módulo. NO se ejecuta ffmpeg. NO se construye DB.

### 4.5 — `__init__.py` de `application/pipeline/` reducido a 1 LoC

Tras la prueba — borrarlo causaría que el paquete dejara de ser importable bajo Windows, y `pytest -q` con 1839 LoC siguió verde durante el desarrollo. La forma final es 1 LoC con un comentario marcador. El paquete sigue accesible como `application.pipeline.media_pipeline` etc. El comentario documenta la situación.

---

## 5. Resultado de los checks de cierre

### Tests

```
$ ./.venv/Scripts/python.exe -m pytest -q tests/unit/rendering/test_frame_composition.py
........                                                                 [100%]
8 passed in 0.89s

$ ./.venv/Scripts/python.exe -m pytest -q
417 passed in 188.98s (0:03:08)
```

Baseline pre-feature-14: **409 tests** (post-feature-13).
Post-feature-14: **417 tests** (409 + 8 unit nuevos). Esperado 415-417 — cumplido.

### Readiness

```
$ ./.venv/Scripts/python.exe -m apps.api --check
RUNTIME READY: Yes
EXIT_API: 0

$ ./.venv/Scripts/python.exe -m apps.worker --check
Worker --check OK: kinds=reel_publish,scripted_render worker_count=1 lease=900s poll=0.50s
EXIT_WORKER: 0
```

Ambos exit 0. `init.sh` verde end-to-end:

```
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
417 passed in 187.67s (0:03:07)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

`init.sh` reporta WARN en step 4 ("4 archivos modificados en directorios legacy en últimas 24h"): es la modificación quirúrgica permitida por las reglas de Phase 2 sobre `application/bootstrap/runtime.py`, `application/bootstrap/__init__.py`, `application/bootstrap/pipeline_adapters.py` (creación) y `application/pipeline/__init__.py` (reducción a marker). Coherente con el patrón aplicado en features 10-13.

### Repo limpio

- Sin `xfail`, sin `print()` debug, sin `TODO`/`FIXME` en archivos creados/modificados (`grep -nE "print\(|xfail|TODO|FIXME"` en `frame_composition.py`, `pipeline_adapters.py`, `test_frame_composition.py`: 0 hits).
- Sin `__pycache__/.tmp_*` residual fuera de los gestionados por pytest.
- `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py` siguen byte-a-byte iguales (`diff` exit 0 final).
- `application/pipeline/media_services.py` y `application/pipeline/default_services.py` no existen físicamente (`ls application/pipeline/`: solo `__init__.py`, `content_generation.py`, `interfaces.py`, `job_runner.py`, `media_pipeline.py`).
- Class shadow `DefaultMediaRenderer` borrado.
- Cero adaptaciones en tests existentes — los 409 verdes baseline pasan intactos.
- `feature_list.json` feature 14 status `in_progress` (closer la promueve a `done`).

---

## 6. Desviaciones frente al plan del explorer

1. **`frame_composition.py` 184 LoC vs ~140 estimados**: ligeramente por encima del rango por docstring largo (24 LoC) y `__all__`. Aún muy por debajo del límite acceptance (< 500 LoC).
2. **`pipeline_adapters.py` 237 LoC vs ~165-180 estimados**: ligeramente por encima por docstring del módulo + del adapter individual y formateo. Aún muy por debajo del límite implícito.
3. **`test_frame_composition.py` 382 LoC vs ~250-350 estimados**: ligeramente por encima por helpers (_patch_primitives helper exhaustivo + `_build_context`/`_build_prepared_assets`). Aún en el orden de magnitud previsto. Tests bien aislados: cada uno construye su propia fixture.
4. **`__init__.py` reducción a 1 LoC en lugar de 0**: el explore lo dejaba ambiguo entre "borrar" y "marker vacío". Opté por **1 LoC con comentario** (`# Empty package marker for application.pipeline`) para que el archivo sea explícitamente un marker y no generen confusión los lectores futuros. El paquete sigue siendo importable y los tests verdes.
5. **`LocalPhotoSelectionEngine` re-export omitido en `pipeline_adapters.__all__`**: confirmado por grep (cero callers externos). Coherente con la directriz del explore §6 R5.

---

**Fin del informe.**
