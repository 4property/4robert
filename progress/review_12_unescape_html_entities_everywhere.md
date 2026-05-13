# Review — feature 12 (`unescape_html_entities_everywhere`)

**Veredicto:** APPROVED

- Fecha review: 2026-05-12
- Agent: reviewer (Opus 4.7 1M)
- Branch: `ghl`
- Implementer report: `progress/impl_12_unescape_html_entities_everywhere.md`

## Checkpoints

- C1 (acceptance: title/caption decodificados en overlay MP4): [x]
  - `modules/reels/application/content_generator.py:111` aplica
    `html.unescape(rendered)` justo después de la sustitución de variables en
    `render_template_with_property`, lo que cubre `{{property_title}}`,
    `{{neighborhood}}` y cualquier otra variable sustituida desde
    `Property.from_api_payload`.
  - `modules/rendering/infrastructure/ai_photo_selection/prompting.py:85`
    aplica `html.unescape(clean_whitespace(str(value or "")))` al inicio de
    `normalize_caption`, antes del `strip("\"'")` y de la detección de
    terminador. El test edge case
    `test_normalize_caption_strips_html_entities_before_appending_terminator`
    (`tests/unit/rendering/test_normalize_caption_unescape.py:67-73`) pinea que
    `Hello&#33;` → `Hello!` sin punto extra.
- C2 (acceptance: summary del POST GHL decodificado, test con mock HTTP
  client): [x]
  - `modules/publishing/infrastructure/adapters/gohighlevel/social_service.py:108-110`
    decodifica `description` y `title` justo antes de armar `json_body`. La
    variable decodificada se inyecta en `summary` (línea 113) y en el builder
    del payload por plataforma (línea 127, `title=decoded_title`).
  - `tests/unit/publishing/test_social_service_unescape.py` ejercita el flujo
    con `MagicMock` sobre `client.request_json` y verifica `json_body["summary"]`
    decodificado (7 tests, todos en verde).
- C3 (acceptance: ≥6 casos unit con decimal, hex, named, anidados,
  idempotencia, empty): [x]
  - Los 6 casos cubiertos por cada uno de los 3 puntos de integración:
    - `tests/unit/reels/test_content_generator_unescape.py` (7 tests, incluye
      end-to-end con `DeterministicPropertyContentGenerator.generate_property_content`).
    - `tests/unit/rendering/test_normalize_caption_unescape.py` (7 tests,
      incluye edge case de `&#33;`).
    - `tests/unit/publishing/test_social_service_unescape.py` (7 tests, incluye
      caso específico para `title` propagado al payload de YouTube).
  - Total: 21 tests, todos PASSED.
- C4 (verification[0] `bash ./init.sh` verde): [x]
  - `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh` → exit 0.
  - 471 passed, 2 failed (`tests/integration/test_http_transport.py::test_health_endpoints_*`).
  - Esos 2 fallos son **preexistentes**, documentados por el leader en el
    heads-up al implementer y **NO bloquean** la feature.
  - No hay fallos NUEVOS introducidos por la feature.
- C5 (verification[1] `pytest tests/unit/rendering/ tests/unit/publishing/ -q`
  verde): [x]
  - `97 passed in 0.95s` (83 baseline + 14 nuevos en esos dos directorios).
- C6 (`apps.api --check` y `apps.worker --check` exit 0): [x]
  - `.venv/bin/python -m apps.api --check` → API READINESS REPORT, RUNTIME
    READY=Yes, exit 0.
  - `.venv/bin/python -m apps.worker --check` → Worker --check OK, exit 0.
- C7 (no se introduce `html.unescape` en domain/ ni se añade dependencia
  externa cuando stdlib basta): [x]
  - `grep -rn "html.unescape\|import html" modules/reels/domain/` → vacío.
  - Todos los usos de `html.unescape` añadidos por la feature viven en
    `application/` (content_generator) y `infrastructure/` (prompting,
    social_service). El módulo `html` es stdlib, sin dependencias nuevas en
    `pyproject.toml`.
- C8 (no toca schema cuando feature dice `"schema": "No"`): [x]
  - `git diff -- shared/db/orm.py alembic/versions/` → vacío. Sin migraciones
    nuevas. Sin cambios de ORM.
- C9 (idempotencia documentada y testeada): [x]
  - `test_render_template_is_idempotent_on_already_decoded_title`,
    `test_normalize_caption_is_idempotent_on_already_decoded_text`,
    `test_create_social_post_is_idempotent_on_already_decoded_description`.
    Las 3 verifican que re-decodificar texto ya limpio devuelve el mismo
    texto. Documentado también en docstrings de los 3 puntos modificados.
- C10 (decodificación de un solo nivel pinneada como contrato): [x]
  - 3 tests `*_decodes_nested_entities_one_level` confirman que
    `&amp;amp;` → `&amp;` (NO `&`). Comportamiento alineado con la stdlib
    `html.unescape` y documentado en los tests.

## Verificación reproducida

| Comando | Resultado |
|---|---|
| `.venv/bin/python -m pytest tests/unit/rendering/ tests/unit/publishing/ -q` | `97 passed in 0.95s` |
| `.venv/bin/python -m pytest tests/unit/reels/test_content_generator_unescape.py -q` | `7 passed in 0.44s` |
| `.venv/bin/python -m pytest <3 archivos unescape> -v` | `21 passed in 0.33s` |
| `.venv/bin/python -m apps.api --check` | `exit 0`, RUNTIME READY=Yes |
| `.venv/bin/python -m apps.worker --check` | `exit 0` |
| `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh` | `exit 0`, 471 passed, 2 failed preexistentes |

## Diff observado del scope de la feature

- `modules/reels/application/content_generator.py` — añade `import html` y
  envuelve el retorno de `render_template_with_property` con
  `html.unescape(rendered)`. Docstring extendido para documentar el contrato.
- `modules/rendering/infrastructure/ai_photo_selection/prompting.py` — añade
  `html.unescape(...)` al inicio de `normalize_caption` (línea 85, con
  comentario explicando por qué va antes de `strip`/terminator detection).
  `html` ya estaba importado (línea 11, usado en `html_to_text`); no se duplica.
- `modules/publishing/infrastructure/adapters/gohighlevel/social_service.py`
  — añade `import html` y decodifica `description`/`title` antes de armar
  `json_body` y de propagar al builder de payload por plataforma.

Sin cambios en `domain/`. Sin cambios en `application/use_cases/`. Sin
cambios en `transport/`. Sin cambios en repositorios. Sin cambios en
`shared/db/orm.py` ni `alembic/versions/`. Sin dependencias nuevas.

## Cambios requeridos

Ninguno bloqueante. La feature cumple los 3 puntos de acceptance, los 6
casos mínimos de tests, y todas las verificaciones del feature_list.json.

## Fuera de scope detectado en el working tree (no bloquea, pero a tener en cuenta)

El working tree contiene **drift acumulado de sesiones previas** que no
forma parte de esta feature ni del informe del implementer:

1. `modules/rendering/infrastructure/ai_photo_selection/prompting.py` líneas
   263-264 — el bloque "Rules" del prompt de selección de fotos cambió la
   instrucción sobre maps/floor plans:
   - Antes: `- Reject maps, floor plans, satellite screenshots, brochure graphics, and non-photo assets.`
   - Ahora: `- Never select a floor plan, house plan, site plan, map, satellite screenshot, brochure graphic, or other non-photo asset.` + `- Do not confuse an open-plan living/kitchen space with a floor plan drawing.`

   Este cambio NO está en el informe del implementer y NO tiene nada que ver
   con HTML entity decoding. Aparece en el mismo archivo pero en una sección
   completamente distinta (instrucciones para el modelo Gemini, no
   `normalize_caption`). El implementer no lo declara, y el flujo de tests
   no lo cubre. Probablemente sea drift de una sesión previa que quedó sin
   commitear; aun así conviene que el leader decida si se commitea con esta
   feature, en un commit aparte, o se revierte.

2. `git status` muestra **38 archivos modificados** y **8 untracked**
   (`LICENSE`, `deploy/backups/`, `deploy/migrate_legacy_schema_to_20260501.py`,
   `deploy/rocky-linux/reels-test*.service`, `main.py`,
   `modules/publishing/infrastructure/adapters/platforms/pinterest.py`,
   `progress/impl_ghl_probe_fb_gbp.md`,
   `progress/review_8_pinterest_social_platform_support.md`, y los nuevos
   tests `test_multi_publish_result.py`, `test_platform_registry.py`,
   `test_build_property_media_job.py`).

   Estos cambios cubren áreas completamente ajenas a HTML unescape:
   `apps/api/health_router.py`, `apps/worker/main.py`,
   `modules/configuration/...`, `modules/delivery/...`,
   `modules/publishing/infrastructure/adapters/platforms/{registry,shared}.py`,
   `modules/reels/application/orchestrator.py`,
   `modules/reels/application/use_cases/regenerate_reel.py`,
   `modules/reels/transport/http/admin_reels_router.py`,
   `modules/tenancy/transport/http/admin_agencies_router.py`,
   `shared/observability/persistent_log.py`, varios tests, etc.

   Estos NO son trabajo del implementer de feature 12 — coinciden con el
   patrón "git reflog HEAD@{0..N}: pull" donde solo hay un commit en cabeza
   y varias features anteriores quedaron sin commit local. La feature 12 en
   sí solo añade los 3 puntos de `html.unescape` + 3 archivos de tests, lo
   cual coincide exactamente con lo declarado en el impl report.

**Recomendación al leader**: separar el commit de feature 12 (solo los 4
archivos modificados + 3 tests nuevos relacionados con la feature) del
resto del drift acumulado. El cambio del prompt de Gemini (punto 1 arriba)
es una decisión de producto que merece su propia review/feature.

## Notas adicionales

- El test `test_create_social_post_decodes_title_used_by_platform_payload`
  usa `platform="youtube"` y verifica el `body` serializado vía `repr()`,
  cubriendo así que el title decodificado llega a `youTubeTitle` (u otro key
  específico de plataforma) sin entidades — buen test defensivo.
- El test `test_normalize_caption_decodes_named_entities` documenta
  explícitamente en su docstring la interacción con `strip("\"'")` legacy:
  `&quot;` en los extremos se decodifica y luego el strip lo limpia. El test
  ejercita el caso del medio del string para evitar la interacción.
  Decisión correcta: no toca la semántica legacy de `normalize_caption`,
  solo añade el decode delante.
- La feature equivalente en frontend (id 11 mismo nombre en
  `/opt/projects/4Reels-Frontend/feature_list.json`) está fuera del alcance
  de este review.

## Línea final

APPROVED -> progress/review_12_unescape_html_entities_everywhere.md
