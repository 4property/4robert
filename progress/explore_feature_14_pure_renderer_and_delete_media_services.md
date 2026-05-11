# Explore — Feature 14 `rendering_pure_renderer_and_delete_media_services`

> Mapa de extracción del cómputo puro restante (`DefaultMediaRenderer`) desde
> `application/pipeline/media_services.py` hacia `modules/rendering/application/`,
> borrado total de `media_services.py`, ajuste de bootstrap/bridge worker e
> inlining de los 4 adapters delgados sobrevivientes a las features 10-13.

Contexto leído (en el orden exigido por la tarea):

- `feature_list.json` (entry id=14, acceptance literal).
- `progress/explore_feature_13_publish_reel.md` (§10 LoC residual; D9 sobre
  `application/pipeline/__init__.py` 1839 LoC dead code).
- `progress/impl_13_publish_reel.md` y `progress/review_13_publish_reel.md`
  (patrón aplicado: adapter delgado + use case en `modules/reels/application/`).
- `application/pipeline/media_services.py` (377 LoC actual, leído íntegro).
- `application/pipeline/media_pipeline.py` (`PropertyMediaPipeline` orquestador,
  133 LoC). Invoca `media_renderer.render_media(context, prepared_assets)` en
  `:95`.
- `application/pipeline/interfaces.py` (Protocols, 112 LoC). `MediaRenderer`
  en `:62-68`, `MediaPublisher` en `:71-83`.
- `application/pipeline/default_services.py` (re-export de los 6 símbolos
  desde `media_services.py`, 17 LoC).
- `application/pipeline/__init__.py` (1839 LoC dead code, NO importado
  desde ningún caller — `grep "from application.pipeline import"` en repo
  sólo da hits de progress/ y de `application/pipeline/__init__.py` interno).
- `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py`
  (byte-iguales, 187 LoC cada uno).
- `apps/worker/runtime.py` (288 LoC; bridge `reel_publish` → `ReelPipeline.handle`
  en `:271-274`). NO importa nada de `application/pipeline/*` directamente.
- `apps/worker/main.py` (CLI `--check`).
- `modules/reels/application/orchestrator.py` (`ReelPipeline`; lazy import en
  `:25` de `application.bootstrap.runtime.build_default_job_handler`).
- `modules/rendering/application/` (vacío excepto
  `use_cases/enqueue_scripted_render.py` de feature 8 + `__init__.py` placeholders).
- `modules/rendering/infrastructure/` con `ai_photo_selection/`, `ffmpeg/`,
  `layout/` (placeholder), `manifest/` (placeholder), `photos/` (placeholder),
  `poster/` (placeholder), `preparation/` (placeholder), `runtime/` (con
  `assets.py`, `branding.py`, `slides.py`).
- `services/media/reel_rendering/` — concretiza el render. Files de interés:
  `data.py` (100), `filters.py` (329), `formatting.py` (494), `layout.py`
  (1038), `manifest.py` (321), `models.py` (146), `poster.py` (390),
  `preparation.py` (450), `render.py` (75 — facade hacia
  `modules/rendering/infrastructure/ffmpeg/*`), `runtime.py` (222 — facade
  hacia `modules/rendering/infrastructure/runtime/*`), `__init__.py` (34).
- `services/media/site_storage.py` — `SiteStorageLayout`,
  `GENERATED_MEDIA_*_DIRNAME`, `safe_site_dirname`,
  `resolve_site_storage_layout`.
- `tests/unit/rendering/` (sólo `test_enqueue_scripted_render.py`),
  `tests/integration/rendering/` (sólo `test_scripted_router.py`).
- `tests/test_reel_pipeline.py` (1381 LoC) — tests legacy que ejercitan
  `prepare_reel_render_assets`, `generate_property_reel_from_data`,
  `generate_property_poster_from_data`, `build_reel_template_for_render_profile`
  directamente (NO llaman a `DefaultMediaRenderer`).
- `tests/test_reel_runtime_dynamic_urls.py` (172 LoC).
- `tests/` — `grep "DefaultMediaRenderer|render_media|render_video|media_services|default_services"`
  → **0 hits**. Ningún test importa el renderer-orquestador ni el módulo
  legacy directamente.
- `application/types.py` (legacy `PropertyContext`, `RenderedMediaArtifact`,
  `PreparedMediaAssets`, `SiteStorageLayout`).
- `application/pipeline/job_runner.py` (75 LoC) — `PropertyMediaJobRunner`
  envuelve `PropertyMediaPipeline.run_job` con file-lock + logging.
- `application/pipeline/content_generation.py` (no leído entero pero referido).
- `docs/phase_2_operating_rules.md` (sección 2 "borrar legacy a medida que se
  mueve"; sección 4 "sin commits"; sección 8 "blocked si premisas cambian").
- `progress/impl_12_persist_local_artifacts.md` y
  `progress/explore_feature_12_persist_local_artifacts.md`.

---

## 0. Decisión de alcance

`feature_list.json` #14 dice literalmente:

> El cómputo puro (frame composition, transitions) que queda en
> `media_services.py` se mueve a `modules/rendering/application/`. Una vez
> vacío, `application/pipeline/media_services.py` se elimina y se ajustan
> los imports del bridge worker.

Y la acceptance:

> - Existen archivos en `modules/rendering/application/` con la lógica de
>   composición pura (cada uno < 500 LoC).
> - `application/pipeline/media_services.py` borrado.
> - Bridge worker actualizado para no importarlo.
> - `tests/unit/rendering/` cubre la lógica trasladada.
> - `pytest -q` termina verde.
> - `python -m apps.worker --check` termina exit 0.

Por lo tanto la feature 14 hace 3 cosas:

- **(a)** Mover el cuerpo de `DefaultMediaRenderer` (`media_services.py:134-268`)
  a `modules/rendering/application/`.
- **(b)** Borrar `application/pipeline/media_services.py` físicamente
  (incluye los 4 adapters delgados — `DefaultPropertyInfoService`,
  `DefaultMediaPreparationService`, `FileSystemMediaPublisher`,
  `CompositeMediaPublisher` — y el class-shadow `DefaultMediaRenderer:267-268`).
- **(c)** Actualizar el bridge `application/bootstrap/{runtime,__init__}.py`
  (que es lo que el worker invoca indirecto vía `ReelPipeline.handle` →
  `build_default_job_handler` → `build_default_property_media_pipeline`).

### Qué hacer con los 4 adapters delgados

Tras las features 10-13, los 4 adapters de `media_services.py`
(`DefaultPropertyInfoService`, `DefaultMediaPreparationService`,
`FileSystemMediaPublisher`, `CompositeMediaPublisher`) son
**bridges sin lógica propia**: cada uno construye un use case moderno y
delega. Constan de ~32, ~45, ~46, ~50 LoC respectivamente, sólo `__init__`
+ alias.

Como el acceptance pide borrar `media_services.py` físicamente, esos 4
bridges no pueden quedarse ahí. Hay 3 opciones:

- **(A)** Inline-arlos en `application/bootstrap/{runtime,__init__}.py`:
  el `PropertyMediaPipeline` se construye instanciando los use cases
  modernos directamente (`IngestPropertyIntoReelUseCase(...)`,
  `PrepareReelAssetsUseCase(...)`, `PersistLocalArtifactsUseCase(...)`,
  `PublishReelUseCase(...)`). Pero los Protocols
  `PropertyInfoService`/`MediaPreparationService`/`MediaPublisher`
  (`interfaces.py`) esperan métodos `ingest_property`/`prepare_assets`/
  `publish_media`, mientras que los use cases exponen `execute(...)`. Hay
  un **mismatch de naming** → opción A obliga a tocar también `interfaces.py`
  y `media_pipeline.py` para invocar `execute(...)` en lugar de los
  nombres legacy, o a envolver cada use case con un lambda/clase
  ad-hoc en bootstrap.
- **(B)** Moverlos a `modules/<bc>/transport/` o similar — **no encaja**:
  no son transport, son adapters de inyección.
- **(C)** Crear un facade ligero en `application/bootstrap/<...>.py`
  (p. ej. `application/bootstrap/pipeline_adapters.py`) que mantenga los
  4 adapters bridges y deje `application/bootstrap/runtime.py` como hoy.
  Mantiene los Protocols intactos; concentra el bridge en un único
  archivo legacy bajo `application/bootstrap/` (recordatorio: feature 18
  borra todo `application/`).

**Mi lectura preferida: Opción C con un giro — los 4 adapters van a un
nuevo archivo `application/bootstrap/pipeline_adapters.py` (~165 LoC),
NO a un módulo nuevo bajo `modules/`**. Ventajas:

- Cumple acceptance literal: `application/pipeline/media_services.py`
  desaparece físicamente.
- Mantiene el Protocol `MediaRenderer`/`MediaPublisher`/etc intactos.
  `media_pipeline.py` sigue invocando `media_renderer.render_media(...)` y
  `media_publisher.publish_media(...)` sin cambios.
- Simétrico al patrón de Phase 2: `application/` es legacy frozen y la
  feature 18 borra todo `application/` de un golpe; concentrar los
  bridges ahí está alineado con esa trayectoria. Mover los 4 adapters a
  `modules/...` los volvería a poner en código vivo y feature 18 tendría
  que volver a tocarlos.
- Mínimo cambio en bootstrap (sólo cambia el path del import, no la
  estructura de la llamada).

**Trade-off explicado:** Opción A es la "fundamentalmente correcta"
(elimina los bridges) pero requiere repensar los Protocols y la API del
`PropertyMediaPipeline`, y feature 16 los va a borrar **enteros** de
todas formas (sustituye `PropertyMediaPipeline` legacy por una composición
moderna de los 4 use cases en `modules/reels/application/`). Opción C
respeta el alcance estrecho de feature 14 ("mover renderer puro y borrar
`media_services.py`"), no fuerza decisiones que pertenecen a feature 16.

**Excepción: el class-shadow `DefaultMediaRenderer:267-268`** desaparece
en el rewrite (no se mantiene ningún `class X(X): pass` en el código nuevo).

Si el leader prefiere Opción A o quiere empujar la consolidación a
feature 16, lo planteo como bloqueo. Mi default es Opción C.

### Qué hacer con `application/pipeline/__init__.py` (1839 LoC dead code)

`grep "from application.pipeline import"` en `apps/`, `modules/`, `shared/`,
`tests/`: **0 hits no-pyc**. El archivo es un blob legacy que duplica el
universo entero del pipeline original (sin call sites). Borrarlo es seguro
y elimina ~1839 LoC del repo sin afectar a nadie.

**Recomendación**: feature 14 también **borra ese archivo** y lo deja como
package marker mínimo (`pass` o un `__init__.py` vacío). Razones:

- Cumple el espíritu del acceptance ("una vez vacío, `media_services.py`
  se elimina"): el `__init__.py` es la última pieza dead-code del
  paquete `application/pipeline/` (junto con `media_services.py`) y
  borrarlo limpia el horizon.
- El paquete sigue vivo (`media_pipeline.py`, `interfaces.py`,
  `default_services.py`, `job_runner.py`, `content_generation.py`,
  `__init__.py` vacío). `application/bootstrap/` y `media_pipeline.py`
  importan submódulos concretos, no del `__init__.py`.
- Reduce ~1839 LoC del repo de un golpe.

Si el leader lo prefiere out-of-scope (feature 18 lo barre con
`application/`), lo dejamos. **Mi default: borrarlo en feature 14**.

### Qué hacer con `default_services.py`

Hoy re-exporta los 6 símbolos del módulo borrado. Tras la extracción:

- Si Opción C: `default_services.py` queda como re-export de los 4
  adapters movidos a `application/bootstrap/pipeline_adapters.py` + el
  `LocalPhotoSelectionEngine` (que vive en
  `modules/reels/application/use_cases/prepare_reel_assets.py`) +
  `DefaultMediaRenderer` (que ahora vive en
  `modules/rendering/application/...`).
- **Pero**: el único caller de `default_services.py` es
  `application/bootstrap/{runtime,__init__}.py`. Si esos 2 archivos
  importan **directamente** desde `application.bootstrap.pipeline_adapters`
  y desde `modules.rendering.application.frame_composition` (renderer
  nuevo), entonces `default_services.py` también puede borrarse —
  queda como facade huérfano sin call sites.

**Recomendación**: borrar `default_services.py` también. La cadena
queda: bootstrap → pipeline_adapters (4 bridges) +
`modules.rendering.application.<renderer>` (renderer puro) +
`modules.reels.application.use_cases` (use cases). Sin facade legacy
intermedio.

### Resumen del alcance final propuesto

| Acción | Archivos |
|--------|----------|
| **Crear** | `modules/rendering/application/frame_composition.py` (renderer puro). Posible split en 2 archivos si pasa de 500 LoC, pero no lo pasa. |
| **Crear** | `application/bootstrap/pipeline_adapters.py` (4 adapters bridges movidos desde `media_services.py`). |
| **Crear** | `tests/unit/rendering/test_frame_composition.py` (cubre el renderer nuevo). |
| **Borrar** | `application/pipeline/media_services.py` (377 LoC). |
| **Borrar** | `application/pipeline/default_services.py` (17 LoC, facade huérfano). |
| **Borrar** | `application/pipeline/__init__.py` (1839 LoC dead code) — reemplazar por package marker vacío. |
| **Modificar** | `application/bootstrap/runtime.py` y `__init__.py` (cambian imports de `application.pipeline.default_services` → `application.bootstrap.pipeline_adapters` + `modules.rendering.application.frame_composition`). |
| **NO tocar** | `application/pipeline/media_pipeline.py`, `application/pipeline/interfaces.py`, `application/pipeline/job_runner.py`, `application/pipeline/content_generation.py` (los necesita feature 16). |
| **NO tocar** | `apps/worker/runtime.py` — no importa nada del módulo borrado. La acceptance "Bridge worker actualizado para no importarlo" se satisface vacuamente: hoy ya no lo importa. |
| **NO tocar** | `services/media/reel_rendering/*` (todo el cómputo de bajo nivel sigue ahí; lo orquesta el renderer movido). |

---

## 1. Alcance exacto del archivo `application/pipeline/media_services.py`

`media_services.py` tras feature 13 (377 LoC, `wc -l` confirmado).
Composición:

| Rango | Símbolo | LoC | Acción feature 14 |
|-------|---------|-----|-------------------|
| `:1-50` | imports + logger | 50 | Distribuir entre los 2 archivos nuevos. Borrar archivo. |
| `:53-84` | `DefaultPropertyInfoService` | 32 | **Mover** a `application/bootstrap/pipeline_adapters.py`. |
| `:87-131` | `DefaultMediaPreparationService` | 45 | **Mover** a `application/bootstrap/pipeline_adapters.py`. |
| `:134-264` | `class DefaultMediaRenderer` (renderer puro) | 131 | **Mover** a `modules/rendering/application/frame_composition.py`. |
| `:267-268` | `class DefaultMediaRenderer(DefaultMediaRenderer): pass` (class shadow) | 2 | **Borrar** (no se reescribe). |
| `:271-316` | `FileSystemMediaPublisher` (adapter feature 12) | 46 | **Mover** a `application/bootstrap/pipeline_adapters.py`. |
| `:319-367` | `CompositeMediaPublisher` (adapter feature 13) | 49 | **Mover** a `application/bootstrap/pipeline_adapters.py`. |
| `:370-377` | `__all__` | 8 | **Borrar** (cada archivo nuevo tiene su `__all__`). |
| **Total** | | 377 | **Archivo borrado físicamente.** |

### Detalle de los imports actuales y su redistribución

Imports actuales en `media_services.py:1-48`:

```python
from __future__ import annotations
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from application.pipeline.content_generation import ContentGenerator
from application.persistence import UnitOfWork
from application.types import (
    PreparedMediaAssets,
    PropertyContext,
    PropertyMediaJob,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
)
from core.media_cleanup import (
    DEFAULT_DELETE_SELECTED_PHOTOS,
    DEFAULT_DELETE_TEMPORARY_FILES,
)
from core.logging import (
    format_console_block,
    format_detail_line,
)
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from modules.reels.application.use_cases.persist_local_artifacts import (
    PersistLocalArtifactsUseCase,
)
from modules.reels.application.use_cases.prepare_reel_assets import (
    LocalPhotoSelectionEngine,
    PrepareReelAssetsUseCase,
)
from modules.reels.application.use_cases.publish_reel import PublishReelUseCase
from services.media.reel_rendering import (
    PropertyRenderData,
    build_reel_template_for_render_profile,
    generate_property_reel_from_data,
    write_property_reel_manifest_from_data,
)
from services.media.reel_rendering.poster import (
    generate_property_poster_from_data,
    resolve_property_poster_output_path,
)
from services.media.reel_rendering.preparation import prepare_reel_render_assets
from services.media.reel_rendering.runtime import build_local_selected_slides
```

**Distribución al refactor:**

- `application/bootstrap/pipeline_adapters.py` (los 4 adapters) usa:
  `Callable`, `UnitOfWork`, `Path`, `ContentGenerator`,
  `PreparedMediaAssets`, `PropertyContext`, `PropertyMediaJob`,
  `PublishedMediaArtifact`, `RenderedMediaArtifact`,
  `DEFAULT_DELETE_SELECTED_PHOTOS`, `DEFAULT_DELETE_TEMPORARY_FILES`,
  `IngestPropertyIntoReelUseCase`, `PersistLocalArtifactsUseCase`,
  `LocalPhotoSelectionEngine`, `PrepareReelAssetsUseCase`,
  `PublishReelUseCase`. **Sin cambios funcionales — copy-paste.**
  `tempfile`, `uuid4`, `logging`, `format_console_block`,
  `format_detail_line` NO los usa (eran del renderer).
- `modules/rendering/application/frame_composition.py` (renderer puro) usa:
  `logging`, `tempfile`, `Path`, `uuid4`, `format_console_block`,
  `format_detail_line`, `PreparedMediaAssets`, `PropertyContext`,
  `RenderedMediaArtifact`, `PropertyRenderData`,
  `build_reel_template_for_render_profile`,
  `generate_property_reel_from_data`,
  `write_property_reel_manifest_from_data`,
  `generate_property_poster_from_data`,
  `prepare_reel_render_assets`, `build_local_selected_slides`. **Sin
  cambios funcionales — copy-paste.**
- `resolve_property_poster_output_path` (importado en
  `media_services.py:45`) **no se usa** dentro del archivo: lo importa
  pero ningún call site lo invoca (verificable con `Grep`). Era una
  herencia legacy. **Se descarta** en la mudanza.

---

## 2. Estructura recomendada de `modules/rendering/application/`

El renderer puro extraído cabe holgadamente en **un solo archivo**
(~140 LoC con docstring + helper estático). Estructura propuesta:

```
modules/rendering/application/
├── __init__.py                  (existente, queda como está)
├── frame_composition.py         (NUEVO, ~140 LoC)
└── use_cases/
    ├── __init__.py              (existente)
    └── enqueue_scripted_render.py  (existente, feature 8)
```

### `modules/rendering/application/frame_composition.py` — esqueleto

```python
"""Pure frame composition for property reels (step 2 of the pipeline).

Orchestrates the low-level rendering primitives in
`services.media.reel_rendering.*` and `modules.rendering.infrastructure.*`
to produce a `RenderedMediaArtifact` for a `PropertyContext` + prepared
`PreparedMediaAssets`. No DB access, no HTTP, no outbox: pure compute +
filesystem writes inside a per-reel staging directory.

Replaces the body of `DefaultMediaRenderer` from
`application/pipeline/media_services.py` (which feature 14 deletes).
The bridge `application.bootstrap.pipeline_adapters` re-exports the
class so `application/bootstrap/{runtime,__init__}.py` keep wiring it
into `PropertyMediaPipeline.media_renderer` without structural change.

Note on naming: the legacy class was `DefaultMediaRenderer`; we
preserve the name 1:1 to avoid forcing changes in
`application/pipeline/interfaces.py:62-68` (Protocol `MediaRenderer`),
which feature 16 will retire.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from application.types import (
    PreparedMediaAssets,
    PropertyContext,
    RenderedMediaArtifact,
)
from core.logging import format_console_block, format_detail_line
from services.media.reel_rendering import (
    PropertyRenderData,
    build_reel_template_for_render_profile,
    generate_property_reel_from_data,
    write_property_reel_manifest_from_data,
)
from services.media.reel_rendering.poster import generate_property_poster_from_data
from services.media.reel_rendering.preparation import prepare_reel_render_assets
from services.media.reel_rendering.runtime import build_local_selected_slides

logger = logging.getLogger(__name__)


class DefaultMediaRenderer:
    def __init__(self, workspace_dir: str | Path) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()

    def render_media(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        return self._render_reel(context, prepared_assets)

    def render_video(
        self,
        context: PropertyContext,
        selected_photos: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        return self.render_media(context, selected_photos)

    def _render_reel(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        # Cuerpo verbatim de media_services.py:152-225 (revision_id, staging
        # dirs, prepared assets, manifest write, reel render, poster render,
        # log block, return RenderedMediaArtifact).
        ...

    @staticmethod
    def _build_render_data(
        *,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
        selected_slides,
    ) -> PropertyRenderData:
        # Cuerpo verbatim de media_services.py:227-264.
        ...


__all__ = ["DefaultMediaRenderer"]
```

LoC estimado total: **130-145 LoC** (cuerpo legal verbatim + docstring).
Bien por debajo del límite de 500.

### Por qué un solo archivo y no un split

El renderer es secuencial y compacto:

1. genera `revision_id`
2. resuelve `staging_dir` bajo `context.storage_paths.generated_reels_root / "_staging"`
3. invoca `prepare_reel_render_assets(...)` (preparación de slides + overlays)
4. invoca `write_property_reel_manifest_from_data(...)`
5. invoca `generate_property_reel_from_data(...)` (ffmpeg)
6. invoca `generate_property_poster_from_data(...)` (poster)
7. log block + return `RenderedMediaArtifact`

Toda la complejidad real ya vive en
`services/media/reel_rendering/preparation.py`,
`services/media/reel_rendering/render.py` (facade ➜
`modules/rendering/infrastructure/ffmpeg/render_reel.py`),
`services/media/reel_rendering/poster.py`,
`services/media/reel_rendering/manifest.py`. **Splittear sería overhead:
no hay 500 LoC para distribuir.**

### Si el leader insiste en 2 archivos

Alternativa de mínima invasión (no recomendada, but documented):

- `modules/rendering/application/frame_composition.py` (`DefaultMediaRenderer`,
  ~110 LoC).
- `modules/rendering/application/render_data_mapper.py` (`_build_render_data`,
  ~50 LoC) — sólo si el leader prefiere aislar la conversión.

No tiene beneficio operativo claro. Mantener en un solo archivo.

---

## 3. Mapeo a UoW moderno

**El renderer puro NO toca DB.** Verificación:

- `grep "unit_of_work|DatabaseUnitOfWork|uow\." application/pipeline/media_services.py`
  → 14 hits, **TODOS** dentro de los 4 adapters legacy
  (`DefaultPropertyInfoService`, `DefaultMediaPreparationService`,
  `FileSystemMediaPublisher`, `CompositeMediaPublisher`). El cuerpo de
  `DefaultMediaRenderer` (`:134-264`) **no contiene** referencias a
  `unit_of_work`/`uow`/`DatabaseUnitOfWork`/`database_locator`. Cero.
- El `__init__` del renderer recibe sólo `workspace_dir: str | Path`
  (`media_services.py:135`). No `unit_of_work_factory`, no
  `database_locator`. Es el único de los 5 servicios que **nunca**
  recibió ese kwarg.

**Conclusión:** El renderer es compute puro: escribe artefactos a disco
bajo `context.storage_paths.generated_reels_root / "_staging" / <uuid>`,
nada más. No hay UoW que migrar. La feature 14 NO toca `shared/db/uow.py`
ni los repositorios.

### Operaciones de filesystem

- Crea `staging_root = context.storage_paths.generated_reels_root / "_staging"`
  (directorio).
- Crea `staging_dir = tempfile.mkdtemp(prefix=<slug>, dir=staging_root)`.
- Escribe (vía las primitivas de `services.media.reel_rendering`):
  - `<staging>/<slug>-reel.json` (manifest).
  - `<staging>/<slug>-reel.mp4` (vídeo, ffmpeg).
  - `<staging>/<slug>-poster.jpg` (poster, ffmpeg).
  - `<staging>/_prepared/...` (slides normalizados, overlays, BER icon, etc).

El `staging_dir` lo limpia el `PersistLocalArtifactsUseCase` (feature 12)
**después** de promover los artefactos a `generated_reels_root` /
`generated_posters_root`. El renderer NO tiene responsabilidad de
cleanup (lo hereda del flujo legacy).

### ffmpeg / ffprobe binaries

- `services.media.reel_rendering.runtime.resolve_ffmpeg_binary()` resuelve
  el binario (vía `modules.rendering.infrastructure.runtime.assets.resolve_ffmpeg_binary`).
- El renderer no invoca ffmpeg directamente — delega 100% a las
  primitivas. Por tanto los tests del nuevo `frame_composition.py`
  pueden **patchear** `services.media.reel_rendering.preparation`,
  `...render`, `...poster` y `...manifest` (con `monkeypatch`) y NO
  necesitan ffmpeg disponible. Patrón idéntico a
  `tests/test_reel_pipeline.py:1270` (`monkeypatch.setattr` sobre las
  funciones top-level).

---

## 4. Call sites externos a actualizar

### `application/bootstrap/runtime.py` y `__init__.py` (byte-iguales)

Hoy (`runtime.py:7-13`):

```python
from application.pipeline.default_services import (
    CompositeMediaPublisher,
    DefaultMediaPreparationService,
    DefaultMediaRenderer,
    DefaultPropertyInfoService,
    FileSystemMediaPublisher,
)
```

Tras feature 14:

```python
from application.bootstrap.pipeline_adapters import (
    CompositeMediaPublisher,
    DefaultMediaPreparationService,
    DefaultPropertyInfoService,
    FileSystemMediaPublisher,
)
from modules.rendering.application.frame_composition import DefaultMediaRenderer
```

(O importar `DefaultMediaRenderer` también vía
`pipeline_adapters` re-export — opcional. Mantener simple: importar
directo del módulo nuevo.)

**Cambio de imports en 2 archivos byte-iguales: aplicar idéntico en ambos
para preservar la byte-igualdad.**

`build_default_property_media_pipeline:117` mantiene sin cambios:
```python
media_renderer=DefaultMediaRenderer(workspace_path),
```

(Mismo símbolo, distinto path de import.)

### `application/pipeline/default_services.py`

**Borrar archivo entero**. Único caller: `application/bootstrap/{runtime,__init__}.py`,
que pasan a importar de los nuevos paths (Opción C).

### `application/pipeline/__init__.py`

**Vaciar archivo** a `# Package marker for application.pipeline` (1 LoC) o
borrar enteramente. Borrar es más limpio: el paquete sigue siendo
importable como package porque tiene otros submódulos
(`media_pipeline.py`, `interfaces.py`, `job_runner.py`,
`content_generation.py`, `default_services.py` borrado, `media_services.py`
borrado).

**Confirmación de seguridad**:

- `grep -rln "from application.pipeline import\|import application.pipeline\b"`
  en `apps/`, `modules/`, `shared/`, `tests/`, `application/` → 0 hits no-pyc
  (excepto el propio `application/pipeline/__init__.py`).
- Verificado leyendo el archivo: no exporta nada que se importe desde
  fuera. Es código viejo del pipeline god-class duplicado.

### `application/pipeline/media_pipeline.py`

**No tocar**. Sigue importando los Protocols (`interfaces.py`) y
construyendo el `PropertyMediaPipeline`. Lo necesita feature 16.

### `application/pipeline/interfaces.py`

**No tocar**. Los Protocols `MediaRenderer`, `MediaPublisher`,
`MediaPreparationService`, `PropertyInfoService` siguen vivos. Los
cumplen los adapters movidos a `pipeline_adapters.py`. Feature 16 los
retira cuando reemplaza `PropertyMediaPipeline`.

### `application/pipeline/job_runner.py`

**No tocar**. Sigue importando `PropertyMediaPipeline`. Lo necesita
feature 16.

### `application/pipeline/content_generation.py`

**No tocar**. Lo importan tanto `pipeline_adapters` (vía
`DefaultPropertyInfoService`) como
`modules/reels/application/use_cases/ingest_property_into_reel.py`.

### `apps/worker/runtime.py`

**No tocar**. `grep` en `apps/`: cero imports de `application.pipeline`
o `application.pipeline.default_services` o `media_services`. El bridge
worker llega al pipeline indirecto vía `ReelPipeline.handle` →
`build_default_job_handler` (lazy import dentro de
`modules/reels/application/orchestrator.py:25`). El acceptance "Bridge
worker actualizado para no importarlo" se satisface vacuamente: hoy ya
no lo importa directamente.

### `modules/reels/application/orchestrator.py:25-30`

**No tocar**. Lazy import de `application.bootstrap.runtime.build_default_job_handler`,
nada cambia.

### Tests

`grep "media_services|default_services|DefaultMediaRenderer|render_media|render_video"`
en `tests/`: **0 hits**. Ningún test importa de los archivos borrados
ni del símbolo movido. **Cero adaptaciones de tests existentes.**

---

## 5. Tests existentes y nuevos

### Tests existentes que tocan rendering

- `tests/test_reel_pipeline.py` (1381 LoC): **NO toca `DefaultMediaRenderer`
  ni `media_services.py`**. Ejercita las primitivas de
  `services.media.reel_rendering.*` directamente
  (`prepare_reel_render_assets`, `generate_property_reel_from_data`,
  `generate_property_poster_from_data`, `build_reel_template_for_render_profile`,
  `PropertyRenderData`). Todas esas siguen vivas tras feature 14.
  **No requiere cambios.**
- `tests/test_reel_runtime_dynamic_urls.py` (172 LoC): cubre
  `services/media/reel_rendering/runtime.py`. **No requiere cambios.**
- `tests/unit/rendering/test_enqueue_scripted_render.py`: feature 8.
  No relacionado con el renderer. **No requiere cambios.**
- `tests/integration/rendering/test_scripted_router.py`: feature 8. **No
  requiere cambios.**
- `tests/test_social_publishing.py`: importa
  `application.bootstrap.runtime.build_default_social_property_publisher`.
  Bootstrap se modifica pero ese símbolo sigue exportado. **No requiere
  cambios.**

### Tests nuevos requeridos por la acceptance

> `tests/unit/rendering/` cubre la lógica trasladada.

#### `tests/unit/rendering/test_frame_composition.py`

Tests sugeridos (~6-8 tests, ~250-350 LoC esperado):

1. **`test_render_media_returns_rendered_artifact_with_uuid_revision_id`** —
   patchea las 4 primitivas (`prepare_reel_render_assets`,
   `write_property_reel_manifest_from_data`,
   `generate_property_reel_from_data`,
   `generate_property_poster_from_data`) con `monkeypatch.setattr` sobre
   `modules.rendering.application.frame_composition.<func>`. Verifica
   que el `RenderedMediaArtifact` resultante tiene
   `artifact_kind="reel_video"`, `revision_id` UUID-hex (32 chars),
   `staging_dir` bajo `<workspace>/.../generated_media/<site>/reels/_staging/`,
   `media_path` con sufijo `-reel.mp4`, `metadata_path` con sufijo
   `-reel.json`.
2. **`test_render_media_creates_staging_dir_under_generated_reels_root`** —
   verifica que el `staging_dir` se crea bajo
   `context.storage_paths.generated_reels_root / "_staging"` con prefijo
   `<slug>-` (vía `tempfile.mkdtemp`).
3. **`test_render_media_invokes_prepare_reel_render_assets_with_workspace_and_template`** —
   spy/patch `prepare_reel_render_assets` y verifica que recibe
   `(workspace_dir, property_render_data, template=<built_template>,
   working_dir=<staging>/_prepared)`.
4. **`test_render_media_invokes_write_manifest_with_correct_paths`** —
   spy `write_property_reel_manifest_from_data`. Verifica
   `output_path=<staging>/<slug>-reel.json`.
5. **`test_render_media_invokes_generate_reel_with_correct_paths`** —
   spy `generate_property_reel_from_data`. Verifica
   `output_path=<staging>/<slug>-reel.mp4`.
6. **`test_render_media_invokes_generate_poster_with_correct_paths`** —
   spy `generate_property_poster_from_data`. Verifica
   `output_path=<staging>/<slug>-poster.jpg`.
7. **`test_render_video_alias_delegates_to_render_media`** — calle
   `render_video(context, prepared)` y verifica que produce el mismo
   resultado que `render_media(context, prepared)`.
8. **`test_build_render_data_maps_property_fields`** — staticmethod
   `_build_render_data`: pass un `PropertyContext` con valores
   conocidos y verifica que el `PropertyRenderData` resultante tiene
   `site_id`, `property_id`, `slug`, `title`, `link`, `bedrooms`,
   `agent_name`, `agency_logo_url`, etc., todos copiados con los
   valores correctos. Verifica también que `selected_slides` es un
   `tuple` (no list).

Los stubs son patches de las 4 funciones top-level del renderer; no se
usan stubs de UoW (no hay UoW). No se ejecuta ffmpeg.

**Total LoC estimado**: 250-350 LoC unit tests. Cumple acceptance
("`tests/unit/rendering/` cubre la lógica trasladada").

#### Integration test (opcional)

La acceptance literal NO pide un integration test. Sin embargo, el patrón
de features 10-13 sumó uno por feature. Recomendación: **omitirlo**
porque:

- El renderer es compute puro sin DB → un integration test repetiría
  lógica ya cubierta por unit tests con patches.
- Generar mp4 reales requiere ffmpeg en CI, y los tests existentes
  (`tests/test_reel_pipeline.py`) ya lo cubren con escenarios
  end-to-end de primitivas.
- Feature 16 añadirá `tests/integration/delivery/test_worker_dispatcher_flow.py`
  que cubre el flujo end-to-end claim → handler → outbox.

Si el leader prefiere uno, sería:
`tests/integration/rendering/test_frame_composition_flow.py` que
construye un `PropertyContext` real + monkeypatcha ffmpeg/poster, y
verifica que los archivos aparecen en el `staging_dir`. ~150 LoC.
**Default mío: omitirlo.**

### Tests existentes que se mantienen verdes

- Las 409 verdes de baseline (post-feature-13) deben quedar intactas.
- Esperado tras feature 14: 409 + 6-8 unit tests rendering = **415-417
  verdes**.

---

## 6. Riesgos / acoplamientos

### R1 — Doble UoW finalmente eliminado para los caminos publish/persist

Tras features 10-13, los 4 adapters legacy hacen `del unit_of_work_factory`
(no lo consumen). Cada use case abre su propio `DatabaseUnitOfWork`.
Eso significa que un job de `reel_publish` abre **3-4 UoWs separados**
(ingest + prepare + persist + publish). Cada UoW commits independiente.

**Feature 14 NO arregla esto** — sigue siendo doble UoW. Lo arregla
feature 16 cuando reemplaza `PropertyMediaPipeline` legacy por una
composición moderna donde los 4 use cases comparten un UoW pasado por
parámetro `uow=...` (ya soportado en `PersistLocalArtifactsUseCase` y
`PublishReelUseCase`).

**Documento como riesgo aceptado** — fuera de scope de feature 14.

### R2 — Naming `DefaultMediaRenderer` se preserva

El renderer movido conserva el nombre `DefaultMediaRenderer` (no se
renombra a `FrameCompositionUseCase` o similar). Razón: cumple Protocol
`MediaRenderer` (`interfaces.py:62-68`) sin tocar el Protocol ni
`media_pipeline.py`. Renombrar forzaría cambios en feature 16, que ya
los hace de todas formas.

**Trade-off**: el nombre `DefaultMediaRenderer` no encaja con el
naming Phase 2 (use cases se llaman `<Verb><Noun>UseCase`). **Aceptable
por simetría con feature 16** (que retira la clase entera).

### R3 — `application/pipeline/__init__.py` 1839 LoC dead code

Documentado en §0. **Feature 14 lo borra** (recomendación). Si el
leader prefiere out-of-scope, queda para feature 18.

### R4 — Class shadow `DefaultMediaRenderer:267-268`

Heredado de feature 11 (originalmente seguido del bug-fix de class
shadows en features 11-13). En feature 14 **no se reescribe**: el
archivo se borra y el nuevo `frame_composition.py` no contiene
class-shadow.

### R5 — `LocalPhotoSelectionEngine` re-export

`application/pipeline/default_services.py:7,16` re-exporta
`LocalPhotoSelectionEngine` desde
`application/pipeline/media_services.py:33`. **El símbolo real vive
en `modules/reels/application/use_cases/prepare_reel_assets.py`.**

Single caller actual: `application/bootstrap/{runtime,__init__}.py:9,12`.
Pero esos archivos NO instancian `LocalPhotoSelectionEngine` directamente —
sólo re-importan-y-no-usan a través del bridge.

`grep -rn "LocalPhotoSelectionEngine" apps/ modules/ shared/ tests/ application/ services/`:

- `application/pipeline/default_services.py`: re-export.
- `application/pipeline/media_services.py`: re-import.
- `application/bootstrap/runtime.py`, `__init__.py`: imports (no usados).
- `modules/reels/application/use_cases/prepare_reel_assets.py`: definición.

Tras feature 14 (Opción C):

- `application/bootstrap/pipeline_adapters.py` importa y usa
  `LocalPhotoSelectionEngine` dentro de `DefaultMediaPreparationService.__init__`
  (idéntico al patrón hoy en `media_services.py:110`).
- Bootstrap NO importa `LocalPhotoSelectionEngine` directamente (no lo
  necesita; lo encapsula el adapter).

**Acción**: borrar la línea `LocalPhotoSelectionEngine` del import
block de `bootstrap/runtime.py` y `__init__.py` si no la usan
(verificación final con `grep` durante implementación).

### R6 — `application/types.py` (legacy `PropertyContext`, etc.)

El acceptance **no lo toca**. `PropertyContext`, `RenderedMediaArtifact`,
`PreparedMediaAssets` siguen en `application/types.py`. Feature 18 los
retira cuando borra `application/`.

Tanto el renderer movido como los 4 adapters siguen importando de
`application.types`. **Sin cambios.**

### R7 — ffmpeg/ffprobe binaries en el renderer

Documentado en §3. El renderer no invoca ffmpeg directamente; lo hacen
las primitivas en `services.media.reel_rendering.*`. Tests con patches
no requieren ffmpeg.

### R8 — Naming Protocol `MediaPublisher` vs `execute`/`execute_existing`

Documentado en §0 (Opción A vs C). Con Opción C, los Protocols quedan
intactos y los adapters siguen exponiendo `publish_media`,
`publish_existing_media`, `ingest_property`, `prepare_assets`,
`render_media`, `cleanup_prepared_assets`. **Sin cambios.**

### R9 — Bridge worker no se altera materialmente

Acceptance literal: "Bridge worker actualizado para no importarlo
[`media_services.py`]". `apps/worker/runtime.py` hoy NO lo importa. La
ruta indirecta es `worker → ReelPipeline.handle → build_default_job_handler
→ build_default_property_media_pipeline → CompositeMediaPublisher(...)`.
Esa cadena cambia su único import: `application.pipeline.default_services`
→ `application.bootstrap.pipeline_adapters`. **El worker mismo no se
toca**, sólo el bootstrap (que es lo que el worker invoca).

**Verificación**: `python -m apps.worker --check` debe terminar exit 0
tras la modificación. La función `_check()` en `apps/worker/main.py`
construye un `WorkerSettings` + invoca `build_default_dispatcher`, que
construye `JobDispatcher` y registra los 2 handlers (`reel_publish` y
`scripted_render`). Ningún paso intermedio carga
`application/pipeline/media_services.py` salvo si se invoca el handler
real → ese carga vía lazy import. Como `--check` solo registra (no
ejecuta), `--check` debería pasar incluso con `media_services.py` ya
borrado, **siempre que** `application/bootstrap/{runtime,__init__}.py`
hayan sido actualizados a los nuevos paths.

### R10 — Doble copia de bootstrap (`runtime.py` ≡ `__init__.py`)

Patrón pre-existente: ambos archivos son byte-iguales (verificado en
features 12-13). **Aplicar el mismo cambio en ambos** para preservar la
byte-igualdad. Cualquier divergencia rompe el patrón establecido.

### R11 — Renderer no tiene `database_locator` ni `unit_of_work_factory`

`DefaultMediaRenderer.__init__(self, workspace_dir: str | Path)` —
única dependencia. Esto **simplifica** el integration con bootstrap:
sigue siendo `DefaultMediaRenderer(workspace_path)` en
`build_default_property_media_pipeline:117`.

### R12 — Storage paths y `context.storage_paths.generated_reels_root`

El renderer accede a `context.storage_paths.generated_reels_root` y
`context.storage_paths.generated_posters_root` (pasado a
`generate_property_poster_from_data` indirecto via la primitiva). Estos
campos vienen de `domain.tenancy.storage.SiteStorageLayout`, construido
en `services/media/site_storage.py:resolve_site_storage_layout`. **No
hay nada que migrar — todo vive ya en módulos que feature 14 no toca.**

### R13 — `application/pipeline/__init__.py` borrar puede romper algo no
detectado por grep

Búsqueda exhaustiva (`grep "from application.pipeline import"` y
`grep "import application.pipeline$"`) NO da hits. Pero por defensa en
profundidad: el archivo tiene `__all__` con 17 símbolos
(`media_services.py:1832-1835`). Si algún test usa `import` dinámico
(`importlib.import_module("application.pipeline")`), no lo detectaría
el grep. **Recomendación implementer**: tras borrar el `__init__.py`,
correr `pytest -q` completo. Si rompe, restaurar a un `__init__.py`
vacío y documentar como discrepancia.

---

## 7. Plan de implementación recomendado

### Archivos a crear

1. **`modules/rendering/application/frame_composition.py`** (~140 LoC).
   - Cuerpo verbatim de `media_services.py:134-264`.
   - Imports limitados a los necesarios (ver §1).
   - Single class `DefaultMediaRenderer`.
   - `__all__ = ["DefaultMediaRenderer"]`.

2. **`application/bootstrap/pipeline_adapters.py`** (~165-180 LoC).
   - Cuerpo verbatim de los 4 adapters de `media_services.py`:
     `DefaultPropertyInfoService` (`:53-84`),
     `DefaultMediaPreparationService` (`:87-131`),
     `FileSystemMediaPublisher` (`:271-316`),
     `CompositeMediaPublisher` (`:319-367`).
   - Imports: `Callable`, `UnitOfWork`, `Path`, `ContentGenerator`,
     `PreparedMediaAssets`, `PropertyContext`, `PropertyMediaJob`,
     `PublishedMediaArtifact`, `RenderedMediaArtifact`,
     `DEFAULT_DELETE_SELECTED_PHOTOS`, `DEFAULT_DELETE_TEMPORARY_FILES`,
     `IngestPropertyIntoReelUseCase`, `PersistLocalArtifactsUseCase`,
     `LocalPhotoSelectionEngine`, `PrepareReelAssetsUseCase`,
     `PublishReelUseCase`.
   - `__all__ = ["CompositeMediaPublisher",
     "DefaultMediaPreparationService", "DefaultPropertyInfoService",
     "FileSystemMediaPublisher", "LocalPhotoSelectionEngine"]`
     (re-exporta `LocalPhotoSelectionEngine` para mantener la API
     legacy del extinto `default_services.py`).

3. **`tests/unit/rendering/test_frame_composition.py`** (~250-350 LoC).
   - 6-8 tests con `monkeypatch` sobre las primitivas (ver §5).

### Archivos a modificar

1. **`application/bootstrap/runtime.py`** y
   **`application/bootstrap/__init__.py`** (byte-iguales):
   - Sustituir `from application.pipeline.default_services import (...)`
     por:
     ```python
     from application.bootstrap.pipeline_adapters import (
         CompositeMediaPublisher,
         DefaultMediaPreparationService,
         DefaultPropertyInfoService,
         FileSystemMediaPublisher,
     )
     from modules.rendering.application.frame_composition import DefaultMediaRenderer
     ```
   - Verificar byte-igualdad con `diff` tras el cambio.

### Archivos a borrar

1. **`application/pipeline/media_services.py`** (377 LoC).
2. **`application/pipeline/default_services.py`** (17 LoC).
3. **`application/pipeline/__init__.py`** (1839 LoC) — opcional, ver §0
   y R13. Recomendación: borrar y reemplazar por package marker vacío
   (`__init__.py` con `# Empty package marker`, ~1 LoC). Si rompe,
   restaurar a vacío sin contenido.

### Archivos NO modificados

- `application/pipeline/media_pipeline.py` (orquestador legacy; feature 16).
- `application/pipeline/interfaces.py` (Protocols; feature 16).
- `application/pipeline/job_runner.py` (runner legacy; feature 16).
- `application/pipeline/content_generation.py` (generator legacy).
- `apps/worker/runtime.py` (no importa `media_services.py`).
- `apps/api/app_factory.py` (no importa `media_services.py`).
- `modules/reels/application/orchestrator.py` (lazy import).
- `modules/reels/application/use_cases/*.py`.
- `modules/rendering/infrastructure/*` (todo intacto).
- `services/media/reel_rendering/*` (todo intacto).
- `services/media/site_storage.py`.
- `tests/test_reel_pipeline.py` (1381 LoC, no toca el renderer-orquestador).
- `tests/test_social_publishing.py`.
- `tests/integration/test_worker_runtime.py`.

### Orden sugerido

1. **Implementer crea** `modules/rendering/application/frame_composition.py`
   con `DefaultMediaRenderer` (cuerpo verbatim).
2. **Crea** `application/bootstrap/pipeline_adapters.py` con los 4
   adapters (cuerpo verbatim).
3. **Crea** `tests/unit/rendering/test_frame_composition.py` y los hace
   pasar (`pytest -q tests/unit/rendering/test_frame_composition.py`).
4. **Modifica** `application/bootstrap/runtime.py` y `__init__.py`
   (cambia paths de import). Verifica `diff` exit 0.
5. **Borra** `application/pipeline/default_services.py`.
6. **Borra** `application/pipeline/media_services.py`.
7. **Borra/vacía** `application/pipeline/__init__.py` (recomendado;
   sino skip).
8. **Verifica `pytest -q`** completo. Esperado: **415-417 verdes**
   (409 baseline + 6-8 nuevos).
9. **Verifica `python -m apps.worker --check`** → exit 0.
10. **Verifica `python -m apps.api --check`** → exit 0.

### LoC esperado

| Archivo | Pre | Post |
|---------|-----|------|
| `application/pipeline/media_services.py` | 377 | **0 (borrado)** |
| `application/pipeline/default_services.py` | 17 | **0 (borrado)** |
| `application/pipeline/__init__.py` | 1839 | **0 (borrado)** o 1 (marker) |
| `application/bootstrap/runtime.py` | 187 | ~189 (+2 LoC: re-routing imports) |
| `application/bootstrap/__init__.py` | 187 | ~189 (idem; byte-igual) |
| `modules/rendering/application/frame_composition.py` | — | ~140 (nuevo) |
| `application/bootstrap/pipeline_adapters.py` | — | ~175 (nuevo) |
| `tests/unit/rendering/test_frame_composition.py` | — | ~300 (nuevo) |
| **Total delta** | | **~−1818 LoC en `application/pipeline/`** |

Reducción neta del repo: **~1818 LoC borrados, ~615 LoC añadidos** = **−1203
LoC netos** post-feature-14. La mayor reducción de Phase 2 hasta este
punto.

---

## 8. Discrepancias detectadas

### D1 — Acceptance "Bridge worker actualizado para no importarlo" es vacuo

Documentado en §4 / §6 R9. `apps/worker/runtime.py` ya NO importa
`application/pipeline/media_services.py`. La cadena worker → bootstrap
→ pipeline pasa por imports indirectos que cambian de path tras la
mudanza, pero el archivo `apps/worker/runtime.py` no se toca. La
acceptance se interpreta como "tras la mudanza, el worker sigue
funcionando" (sin imports rotos).

### D2 — `default_services.py` no se menciona en la acceptance

Acceptance dice "`media_services.py` borrado". `default_services.py` es
un facade que reexporta de `media_services.py` y queda huérfano si solo
se borra el segundo. **Recomendación**: borrar también
`default_services.py` (Opción C en §0). El leader puede preferir
mantenerlo apuntando al nuevo `pipeline_adapters.py` por consistencia,
pero sin call sites externos no aporta valor.

### D3 — `application/pipeline/__init__.py` 1839 LoC dead code

Pre-existente, documentado en reviews features 10-13. **Recomendación**:
borrarlo en feature 14 (R3 / R13). Si el leader lo prefiere out of
scope, queda para feature 18.

### D4 — Naming `DefaultMediaRenderer` no encaja con Phase 2

Documentado en §6 R2. Conservar el nombre por compat con Protocol
`MediaRenderer`. Feature 16 retira la clase entera y la sustituye por
una composición moderna; renombrar ahora forzaría doble cambio.

### D5 — Opción A (inline use cases en bootstrap) vs Opción C (mover
adapters a `pipeline_adapters.py`)

Documentado en §0. **Recomendación**: Opción C. El leader puede preferir
Opción A si la consolidación entre features 14 y 16 le parece natural,
pero requiere tocar `interfaces.py` + `media_pipeline.py` que feature 16
ya planea retirar.

### D6 — `tests/integration/rendering/test_frame_composition_flow.py` no
está en la acceptance

Acceptance solo pide `tests/unit/rendering/`. **Recomendación**: omitir
integration test (§5). El leader puede pedirlo si quiere defensa en
profundidad.

### D7 — `LocalPhotoSelectionEngine` re-export

Documentado en §6 R5. Verificar durante implementación que ningún
caller externo lo importa de `default_services.py` (probable que no, ya
que feature 11 lo movió a `modules/reels/`). Si el grep da 0 hits,
omitir el re-export en `pipeline_adapters.py.__all__`.

### D8 — Splittear el renderer en > 1 archivo no aporta valor

Documentado en §2. El acceptance dice "cada uno < 500 LoC"; el renderer
extraído cabe en ~140 LoC en un solo archivo. **No splittear**. El
leader puede pedir 2 archivos si prefiere granularidad mayor; mi default
es uno solo.

### D9 — `services/media/reel_rendering/layout.py` (1038 LoC) NO se toca
en feature 14

Acceptance feature 15 (`rendering_layout_split`) lo cubre. Feature 14
solo mueve el renderer-orquestador.

### D10 — `application/types.py` permanece intacto

Acceptance feature 18 lo retira. Feature 14 sigue importándolo.

### D11 — Cero cambios en tests existentes

Documentado en §5. Las 409 verdes baseline pasan intactas.

---

**Fin del informe.**
