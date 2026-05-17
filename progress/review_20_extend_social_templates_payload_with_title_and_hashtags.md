# Review: feature 20 — extend_social_templates_payload_with_title_and_hashtags (2026-05-14)

## Veredicto

APPROVED

## Cumplimiento acceptance criteria

- [x] **1. PUT acepta shape plano y shape rico, backward-compatible.**
  - Pydantic union `dict[str, str | SocialTemplateRichPayload]` en
    `modules/configuration/transport/payloads/social_templates.py:101`.
  - Colapsado a `SocialTemplateUpsert` en
    `modules/configuration/transport/http/social_templates_router.py:195-223`
    (`_normalize_templates`).
  - Test `test_put_legacy_string_shape_still_works`
    (`tests/integration/configuration/test_social_templates_router.py:461`)
    pasa con `templates[platform] = "<string>"`.

- [x] **2. `title_template` valida variables `{{...}}` con la misma lista canónica; variable desconocida → 422.**
  - `_collect_unknown_template_variables` ejecuta `find_unknown_template_variables`
    sobre `title_template` además de `description_template`
    (`social_templates_router.py:226-259`).
  - `find_unknown_template_variables`, `ALLOWED_TEMPLATE_VARIABLES` y
    `TEMPLATE_VARIABLE_PATTERN` viven en
    `modules/configuration/domain/social_templates_variables.py:24-82`
    (única fuente, compartida).
  - Test
    `test_put_rejects_unknown_variable_in_title_template_with_422`
    (`test_social_templates_router.py:326`).

- [x] **3. `hashtags` valida formato (`^#[\w-]{1,50}$`) y máx 30; inválido → 422 `SOCIAL_TEMPLATE_INVALID_HASHTAG`.**
  - `HASHTAG_PATTERN`, `MAX_HASHTAGS_PER_PLATFORM = 30`,
    `is_valid_hashtag`, `find_invalid_hashtags` en
    `modules/configuration/domain/social_templates_variables.py:53-105`.
  - `_collect_hashtag_errors` + `_invalid_hashtag_response` en
    `social_templates_router.py:296-356`. Devuelve
    `details.hashtag_errors_by_platform[platform] = {invalid: [...], count, max}`
    cuando aplica.
  - Tests `test_put_rejects_invalid_hashtag_with_422` y
    `test_put_rejects_more_than_30_hashtags_with_422`
    (`test_social_templates_router.py:396, 429`).

- [x] **4. Repository persiste los 3 campos; GET los devuelve.**
  - `SocialTemplatesRepository.replace_all_for_agency` recibe
    `Mapping[str, SocialTemplateUpsert]` y persiste los 3 campos vía
    `upsert(..., description_template, title_template, hashtags)`
    (`modules/configuration/infrastructure/social_template_repository.py:117-143`).
  - `list_for_agency` lee las 3 columnas
    (`social_template_repository.py:14-33`). GET serializa los 3 en
    `items[]`
    (`social_templates_router.py:183-192` — `_serialize_record`).

- [x] **5. `PublishMediaRequest.description` incluye hashtags al final con separador `\n\n` si están configurados.**
  - `append_hashtags(description, hashtags)` en
    `modules/reels/application/content_generator.py:132-146` aplica
    `f"{description}\n\n{joined}"`.
  - El generator concatena dentro de `generate_property_content`
    (`content_generator.py:195-200`) tanto sobre la plantilla renderizada
    como sobre el caption determinista fallback.
  - Las captions resultantes alimentan `publish_descriptions_by_platform`
    en `_ingest_property_planning.py:162-185`, que `property_publisher`
    pasa como `description=` al `PublishMediaRequest`
    (`modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py:151-181`).

- [x] **6. `PublishMediaRequest.title` se manda a las redes que lo soportan.**
  - `PublishMediaRequest.title: str | None` ya existía (commit
    `2f106e7`, antes de feature 20). Verificado por
    `git log -p --follow modules/publishing/infrastructure/adapters/gohighlevel/models.py`.
  - El title renderizado se propaga vía
    `publish_titles_by_platform` → `_resolve_target_title` →
    `PublishMediaRequest(title=...)` en
    `property_publisher.py:294-308`.
  - Title rendering nuevo se produce en
    `content_generator.py:201-222`.

- [x] **7. Los 9 tests integration existentes siguen verdes.**
  - `git diff tests/integration/configuration/test_social_templates_router.py`
    confirma que sólo hay adiciones a partir de la línea 261 — los 9
    originales no se han tocado.
  - Ejecutado: `15 passed in 22.33s` (9 originales + 6 nuevos).

- [x] **8. Tests nuevos cubren los 4 casos requeridos.**
  - Rich PUT: `test_put_accepts_rich_shape_with_title_and_hashtags`.
  - Title var inválida: `test_put_rejects_unknown_variable_in_title_template_with_422`.
  - Hashtag inválido: `test_put_rejects_invalid_hashtag_with_422`.
  - GET tras PUT rico: `test_put_accepts_rich_shape_with_title_and_hashtags`
    (incluye round-trip GET asegurando los 3 campos).
  - Extras: `test_put_reports_both_fields_when_each_has_unknown_variables`
    (mixed-shape 422) y `test_put_rejects_more_than_30_hashtags_with_422`
    (cap 30).

- [x] **9. `pytest -q` verde excepto los 3 fallos preexistentes documentados.**
  - Ejecutado: `3 failed, 699 passed, 14 warnings in 261.96s`. Los 3
    fallos son `test_http_surface_contract`,
    `test_health_endpoints_include_paused_dispatcher_state`,
    `test_health_endpoints_return_minimal_payloads` — coinciden 1:1 con
    el baseline declarado en `progress/current.md`.

- [x] **10. `python -m apps.api --check` y `python -m apps.worker --check` exit 0.**
  - Salida verde con database_url + schema + ffmpeg para api; worker
    `kinds=reel_publish, scripted_render`.

## Verificación ejecutada

- `bash ./init.sh` → readiness verde, pytest 3 fail / 699 pass (baseline conocido).
- `.venv/bin/python -m pytest tests/integration/configuration/test_social_templates_router.py -v` → **15 passed**.
- `.venv/bin/python -m pytest tests/unit/configuration/test_social_templates_payload.py tests/unit/configuration/test_social_templates_hashtags.py tests/unit/reels/test_content_generator_hashtags_and_titles.py -v` → **22 passed**.
- `.venv/bin/python -m pytest tests/unit/ingestion/test_ingest_wordpress_property.py tests/unit/configuration/test_replace_social_templates.py -v` → **9 passed**.
- `.venv/bin/python -m pytest tests/integration/reels/ -q` → **29 passed in 42.91s**.
- `.venv/bin/python -m apps.api --check` → OK; `.venv/bin/python -m apps.worker --check` → OK.
- `.venv/bin/python -m pytest -q` → **3 failed, 699 passed** (exactamente el baseline preexistente).

### Checks adicionales del briefing

- **Layer rules.** `SocialTemplateUpsert` definido en
  `modules/configuration/domain/agency_settings.py:71-83`. El módulo
  `domain/` no importa nada de `application/` ni `infrastructure/`
  (verificado con `grep "from modules.configuration.application" modules/configuration/domain/` → vacío). El use case
  (`application/use_cases/replace_social_templates.py:12`) y el
  repository (`infrastructure/social_template_repository.py:7`)
  importan ambos desde `modules.configuration.domain`. OK.
- **Shape mixto del 422.** La rama "title sólo" funciona
  (`test_put_rejects_unknown_variable_in_title_template_with_422`); la
  rama "description + title" devuelve nested
  `{description_template, title_template}` cubierto por
  `test_put_reports_both_fields_when_each_has_unknown_variables`; la
  rama "description sólo" mantiene la lista plana legacy cubierta por
  los 9 tests originales más
  `test_social_templates_put_reports_every_offending_platform`. Todas
  las ramas tienen test.
- **Cap 30.** `MAX_HASHTAGS_PER_PLATFORM = 30` aparece en
  `social_templates_variables.py:54` y se aplica en
  `social_templates_router.py:313`; el 422 incluye `count` y `max` (vis
  `test_put_rejects_more_than_30_hashtags_with_422` asserta
  `count == 35` y `max == 30`).
- **Pipeline title pre-existente.** Confirmado: `git log -p --follow`
  muestra `title: str | None = None` introducido en
  `2f106e7 production test`, mucho antes de feature 20. La feature
  ahora rellena ese campo con el title renderizado vía
  `publish_titles_by_platform`. El implementer dijo bien.
- **Separador hashtags `\n\n`.** `append_hashtags` (`content_generator.py:146`)
  retorna `f"{description}\n\n{joined}"`; hashtags vacíos devuelven la
  description intacta (no quedan `\n\n` colgando), description vacía
  devuelve sólo los hashtags. Cubierto por
  `test_append_hashtags_returns_description_unchanged_when_empty_list` y
  `test_append_hashtags_with_empty_description_returns_hashtags_only`.
- **GET backward-compat.** `_serialize_templates`
  (`social_templates_router.py:171-180`) sigue devolviendo
  `dict[str, str]` con la description; el shape rico vive en
  `items[]`. Los 9 tests originales siguen leyendo `templates[platform]`
  como string (verificado en el diff: no cambian asserts del shape).
- **`SocialPublishContext`.** `from_dict`
  (`modules/reels/domain/types.py:94-164`) lee `payload.get(...)` con
  fallback `or {}` para los dos nuevos campos: un job ya enqueuado sin
  ellos retorna tuplas vacías (`normalized_title_templates = ()` y
  `normalized_hashtags = ()`). No rompe deserialización vieja.
- **Tests nuevos.** Cuento verificado:
  - 6 integration (`test_put_*` añadidos a partir de la línea 261).
  - 3 unit files nuevos
    (`test_social_templates_payload.py`,
    `test_social_templates_hashtags.py`,
    `test_content_generator_hashtags_and_titles.py`).
  - 2 unit modificados:
    `test_replace_social_templates.py` (incluye el nuevo
    `test_replace_persists_title_and_hashtags_alongside_description`)
    y `test_ingest_wordpress_property.py` (incluye
    `test_ingest_wordpress_property_forwards_rich_social_templates_into_publish_context`).
- **No tocados.** El `git status` confirma que feature 20 NO tocó
  `modules/configuration/music/*`, `apps/api/music_*`,
  `shared/storage/music*`, ni nada bajo `tests/integration/configuration/test_music_*`.
  Los cambios en `modules/rendering/*` y los dos alembics nuevos
  `20260514_0001` y `20260514_0002` pertenecen a los hotfixes de Codex
  (`side_banner_footer_radius`, `classic_render_template_preview`) y a
  feature 19 (`include_pinterest_in_reel_defaults`), no a feature 20 ni
  a feature 22.

## Concurrencia

- **No detecté cambios de feature 22 (music)** en ningún archivo
  tocado por feature 20. `git status` no muestra modificaciones en
  `modules/configuration/music/`, `apps/api/music_*`,
  `shared/storage/`, ni tests `test_music_*` ni
  `tests/integration/apps_api/test_music_*`.
- Hotfixes de Codex (`modules/rendering/*`,
  `alembic/versions/20260514_0002_classic_render_template_preview.py`)
  presentes pero ortogonales — no afectan al veredicto.
- Cambios de feature 19 (Pinterest defaults) en
  `alembic/versions/20260514_0001_include_pinterest_in_reel_defaults.py`
  y `tests/integration/configuration/test_pinterest_in_reel_defaults_platforms.py`
  también ortogonales.

## Hallazgos

1. **(fyi)** El use case `ReplaceSocialTemplatesUseCase.execute`
   re-normaliza `SocialTemplateUpsert` tras la normalización ya hecha
   en `_normalize_templates` del router
   (`application/use_cases/replace_social_templates.py:37-46`). Es
   doble trabajo pero defensivo — preserva la garantía de que el use
   case sigue siendo seguro si lo invoca otro caller que no pase por el
   router. Sin acción.
2. **(fyi)** El test
   `test_replace_payload_mixed_shape_per_platform_is_allowed` valida
   que se pueden mezclar string y rich en la misma `PUT`. Buena
   cobertura del contrato real que el frontend feature 20 va a usar
   durante su rollout plataforma-a-plataforma.
3. **(nit)** El docstring de `_collect_hashtag_errors`
   (`social_templates_router.py:299-309`) habla de `too_many` pero la
   clave real emitida es `count`/`max`. Coherente con el test
   (`test_put_rejects_more_than_30_hashtags_with_422` asserta
   `count`/`max`), pero el docstring induce a confusión. Inofensivo;
   no bloqueante.
4. **(fyi)** El test
   `test_generate_property_content_falls_back_to_deterministic_title_when_template_empty`
   cubre el comportamiento de que un title vacío no aplasta el
   deterministic baseline. Bien.
5. **(fyi)** `SocialPublishContext.to_dict()`
   (`reels/domain/types.py:64-80`) emite siempre `social_title_templates`
   y `social_hashtags`, incluso vacíos. Eso engrosa ligeramente el
   `jobs.publish_context_json` pero simplifica el round-trip y mantiene
   simetría con `social_templates`. Consciente, OK.
6. **(fyi)** Los hashtags se persisten verbatim (sin trim) en el
   use case (`tuple(str(tag).strip() for tag in ...)` sí hace trim).
   Bien.
7. **(nit)** La key del legacy `templates` en el response sigue siendo
   `dict[str, str]`. Si el frontend feature 20 quisiera consumir la
   shape rica directamente desde `templates`, tendría que romper
   contrato. Por eso el implementer mueve los 3 campos a `items[]`
   correctamente. No bloqueante — sólo documentar bien la decisión (ya
   está en `docs/API.md`).
8. **(fyi)** El ingest filtra plataformas con `title_template` o
   `hashtags` no-vacíos antes de enqueuar
   (`ingest_wordpress_property.py:122-135`), manteniendo el
   `publish_context_json` compacto. El `from_dict` tolera ambas formas
   (filtrado o exhaustivo), así que no hay riesgo de regression al
   coexistir jobs viejos y nuevos.

## Recomendación

**APPROVED.** El implementer puede pasar a la fase de cierre:

- Marcar feature 20 como `done` en `feature_list.json` (acción del
  leader, no del reviewer).
- Mover la bitacora de `progress/current.md` a `progress/history.md`.
- Continuar con la parte frontend de la feature 20 (cross-repo
  `/opt/projects/4Reels-Frontend`).

No quedan changes-requested. Los 4 nits/fyi son meramente documentales
y no requieren cambios de código.
