# Implementer report — feature 20 (backend)

**Feature:** `extend_social_templates_payload_with_title_and_hashtags`
**Repo:** `/opt/projects/4Reels-Backend`
**Fecha:** 2026-05-14
**Agente:** implementer (lanzado por leader Claude)
**Schema:** NO se tocó. Las columnas `title_template` y `hashtags` ya existían en `agency_social_templates` desde la migración inicial `20260501_0001`.

---

## 1. Resumen

Esta feature amplía el contrato del PUT `/v1/admin/agencies/{id}/social-templates`
para que cada plataforma pueda enviar, además del legacy
`description_template`, un `title_template` y una lista `hashtags`. Toda la
cadena de consumo (use case → repository → SocialPublishContext →
content_generator → publisher) se ha extendido para que el caption
publicado en la red termine en la concatenación de los hashtags
configurados por la agency y para que las redes con campo `title`
(Pinterest / YouTube) reciban el título renderizado con variables.

Backward-compat estricta: las 9 tests integration de feature 11 siguen
verdes; los admin clients pinned a la v1 (string plano por plataforma)
no necesitan cambios.

---

## 2. Archivos modificados / creados

### Payload (transport)

- `modules/configuration/transport/payloads/social_templates.py` — añade
  `SocialTemplateRichPayload` (Pydantic, `extra='forbid'`) y modifica
  `SocialTemplatesReplacePayload.templates` a
  `dict[str, str | SocialTemplateRichPayload] | None`. La union se resuelve
  automáticamente por Pydantic v2.

### Router (transport)

- `modules/configuration/transport/http/social_templates_router.py`:
  - Nueva función `_normalize_templates()` que colapsa la union en
    `dict[str, SocialTemplateUpsert]` antes de validar y antes de pasar al
    use case.
  - `_collect_unknown_template_variables()` ahora valida tanto
    `description_template` como `title_template`. Shape mixto del error
    (ver decisión 4.1).
  - Nuevo `_collect_hashtag_errors()` + `_invalid_hashtag_response()` que
    emiten `422 SOCIAL_TEMPLATE_INVALID_HASHTAG` con
    `details.hashtag_errors_by_platform`.

### Domain

- `modules/configuration/domain/agency_settings.py` — añade
  `SocialTemplateUpsert(description_template, title_template, hashtags)`.
- `modules/configuration/domain/social_templates_variables.py` — añade
  `HASHTAG_PATTERN = re.compile(r"^#[\w-]{1,50}$")`,
  `MAX_HASHTAGS_PER_PLATFORM = 30`, `is_valid_hashtag()`,
  `find_invalid_hashtags()`.
- `modules/configuration/domain/__init__.py` — re-exporta los nuevos
  símbolos.

### Application

- `modules/configuration/application/use_cases/replace_social_templates.py`:
  - `ReplaceSocialTemplatesInput.templates` ahora es
    `dict[str, SocialTemplateUpsert]`.
  - El use case importa `SocialTemplateUpsert` desde `domain/` (no desde
    `infrastructure/` ni se redefine local) para respetar layer rules.

### Infrastructure

- `modules/configuration/infrastructure/social_template_repository.py`:
  - `replace_all_for_agency()` recibe `Mapping[str, SocialTemplateUpsert]`
    y persiste los 3 campos.
  - Import de `SocialTemplateUpsert` desde `domain/`, no desde
    `application/` (layer rule).

### Reels — domain + application

- `modules/reels/domain/types.py`:
  - `SocialPublishContext` gana
    `social_title_templates: tuple[tuple[str, str], ...]`,
    `social_hashtags: tuple[tuple[str, tuple[str, ...]], ...]`.
  - Propiedades `social_title_templates_map` y `social_hashtags_map`.
  - `from_dict()` y `to_dict()` ampliados con backward-compat: si
    `social_title_templates` o `social_hashtags` no aparecen en el payload
    persistido se asumen vacíos.
- `modules/reels/application/content_generator.py`:
  - `ContentGenerator` Protocol y `DeterministicPropertyContentGenerator`
    reciben `title_templates_by_platform` y `hashtags_by_platform`.
  - Nueva helper `append_hashtags(description, hashtags)` que concatena
    con `\n\n` y respeta `description=""` (devuelve solo los hashtags) y
    `hashtags=()` (no toca la descripción).
  - El title se renderiza con `render_template_with_property` (mismas
    reglas que la descripción).
- `modules/reels/application/use_cases/_ingest_property_planning.py` —
  pasa los nuevos `title_templates_by_platform` y `hashtags_by_platform`
  al `content_generator.generate_property_content()`.

### Ingestion

- `modules/ingestion/application/use_cases/ingest_wordpress_property.py`:
  - Al construir el `publish_context` persistido en `jobs.payload`, añade
    `social_title_templates` y `social_hashtags` solo para las
    plataformas con valores no vacíos (el `from_dict` toleraría dicts
    vacíos, pero así el payload queda compacto).

### Tests (unit)

- `tests/unit/configuration/test_social_templates_payload.py` *(nuevo)* —
  6 tests sobre `SocialTemplateRichPayload` y la union.
- `tests/unit/configuration/test_social_templates_hashtags.py` *(nuevo)* —
  8 tests sobre `is_valid_hashtag`, `find_invalid_hashtags`,
  `HASHTAG_PATTERN` y `MAX_HASHTAGS_PER_PLATFORM`.
- `tests/unit/configuration/_uow_stubs.py` — `StubSocialTemplates`
  acepta el shape rico en `replace_all_for_agency`.
- `tests/unit/configuration/test_replace_social_templates.py` — tests
  existentes adaptados al shape rico + un test nuevo para verificar que
  título y hashtags se persisten.
- `tests/unit/reels/test_content_generator_hashtags_and_titles.py`
  *(nuevo)* — 8 tests cubriendo `append_hashtags()` y el flujo
  `generate_property_content()` con `title_templates_by_platform` y
  `hashtags_by_platform`.
- `tests/unit/ingestion/test_ingest_wordpress_property.py` — 1 test
  nuevo: el `publish_context` enqueued lleva los 3 campos correctamente
  filtrados (solo las plataformas con title/hashtags no vacíos).

### Tests (integration)

- `tests/integration/configuration/test_social_templates_router.py` — 6
  tests nuevos:
  1. `test_put_accepts_rich_shape_with_title_and_hashtags`
  2. `test_put_rejects_unknown_variable_in_title_template_with_422`
  3. `test_put_reports_both_fields_when_each_has_unknown_variables`
  4. `test_put_rejects_invalid_hashtag_with_422`
  5. `test_put_rejects_more_than_30_hashtags_with_422`
  6. `test_put_legacy_string_shape_still_works`

### Docs

- `docs/API.md`:
  - Tabla de configuration: la celda de "social-templates" describe la
    union string/objeto rico.
  - Sección "Social template variables" extendida: ejemplos de payload
    union, regla `\n\n` para hashtags, regex y cap 30.
  - Tabla de errores: nuevo `SOCIAL_TEMPLATE_INVALID_HASHTAG` con shape
    del `details`; aclaración del shape mixto de
    `unknown_variables_by_platform`.

### Progress

- `progress/current.md` — bitacora extendida en mi sección.

---

## 3. Decisiones

### 3.1 Union Pydantic

`templates: dict[str, str | SocialTemplateRichPayload]`. Pydantic v2 hace
el dispatch automático: si el valor es string mantiene `str`, si es
objeto valida como `SocialTemplateRichPayload`. El router colapsa la
union dentro de `_normalize_templates()` antes de validar, así toda la
lógica downstream trabaja con un único tipo (`SocialTemplateUpsert`).

Por qué Union y no schema versionado:
- mantiene la 422 actual cuando el cliente envía un campo desconocido
  dentro del objeto (`extra='forbid'`);
- el frontend feature 20 puede ir migrando plataforma a plataforma sin
  necesidad de coordinar un cutover;
- los 9 tests integration de feature 11 siguen verdes sin tocar.

### 3.2 Shape del error 422 `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE`

Mixto controlado:
- Si solo `description_template` tiene variables desconocidas, el value
  es la lista plana de siempre: `{instagram: ["foo"]}`. Mantiene los 9
  tests existentes.
- Si `title_template` está involucrado (solo o junto con description),
  el value pasa a ser un dict `{description_template: [...],
  title_template: [...]}`. Permite al frontend marcar el campo concreto
  con el error inline.

Documentado en `docs/API.md` § error reference y en el docstring de
`_collect_unknown_template_variables`.

### 3.3 Shape del error 422 `SOCIAL_TEMPLATE_INVALID_HASHTAG`

`details.hashtag_errors_by_platform[platform]` es un objeto con dos claves
opcionales: `invalid: [hashtag, ...]` (entradas que fallan la regex,
incluidos blancos) y `count: int` + `max: int` (lista demasiado larga).
Permite que un único 422 reporte ambos problemas en un único round-trip.

### 3.4 Concatenación de hashtags

`append_hashtags("desc", ["#a", "#b"])` ⇒ `"desc\n\n#a #b"`. Reglas:
- description vacía + hashtags ⇒ devuelve solo los hashtags (la red no
  recibe caption blanco);
- description no vacía + hashtags vacíos ⇒ devuelve la description
  intacta (no se añade `\n\n` colgante);
- los hashtags se separan con un único espacio (la convención más
  amigable para todas las redes que soportan hashtags inline).

### 3.5 GET response shape (backward-compat)

`templates` se mantiene como `dict[platform, str]` (description plano).
Los 3 campos completos viven en `items[]`. Lo documentamos en el
docstring de `_serialize_templates()` y en `docs/API.md`. Evita romper:
- los 9 tests integration de feature 11 que dependen del shape plano;
- los admin clients pinned a la v1 (si los hay) que solo consumen
  `templates[platform]`.

### 3.6 Layer rules

`SocialTemplateUpsert` se sitúa en `domain/` para que tanto
`application/` como `infrastructure/` puedan importarlo sin que la
infrastructure dependa de application (lo cual violaría las layer
rules). El use case `ReplaceSocialTemplatesUseCase` deja de redefinirlo
local.

### 3.7 SocialPublishContext

Se mantiene la clave legacy `social_templates: tuple[tuple[str, str], ...]`
(platform, description) intacta para que cualquier job persistido antes
de esta feature siga funcionando tras el deploy. Las dos nuevas
secciones (`social_title_templates`, `social_hashtags`) son opcionales
en `from_dict` (default `()`), y `to_dict` siempre las emite (para los
jobs nuevos).

---

## 4. Verificación

Comandos ejecutados desde `/opt/projects/4Reels-Backend`:

```bash
.venv/bin/python -m pytest tests/integration/configuration/test_social_templates_router.py -q
# 15 passed in 22.54s  (9 existentes + 6 nuevos)

.venv/bin/python -m pytest tests/unit/configuration/ tests/unit/reels/ tests/unit/ingestion/ tests/integration/configuration/ -q
# 290 passed in 101.10s

.venv/bin/python -m pytest tests/integration/reels/ -q
# 29 passed in 43.25s

.venv/bin/python -m apps.api --check
# OK (database_url, schema, ffmpeg)
.venv/bin/python -m apps.worker --check
# OK (kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s)

.venv/bin/python -m pytest -q
# 3 failed, 699 passed, 14 warnings in 274.98s
# Los 3 failed son los baseline preexistentes:
#   tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
#   tests/integration/test_http_transport.py::test_health_endpoints_include_paused_dispatcher_state
#   tests/integration/test_http_transport.py::test_health_endpoints_return_minimal_payloads
# Verificado: mismo set de 3 fallos antes y después del cambio.
```

`bash ./init.sh` también ejercita el mismo suite (no se ejecutó al final
porque ya levantamos `pytest -q` que cubre el subset relevante). Si la
review lo pide, lo lanzamos.

---

## 5. Riesgos / consideraciones para la review

- **Migration:** ninguna. Las columnas ya existían. Si la review duda,
  puede ejecutar `alembic current` para confirmar `20260514_0001`/
  `20260514_0002` como heads cerradas (Codex/feature 19) y la cadena
  alembic intacta.
- **Backward-compat publish_context:** un job ya enqueuado antes del
  deploy y procesado después seguirá funcionando: `from_dict` tolera la
  ausencia de las 2 nuevas claves.
- **No tocado:** `modules/rendering/*` (Codex), nada relacionado con
  music (features 22-25, otro thread). Tampoco `modules/publishing/*`
  más allá de leer `PublishMediaRequest`: el campo `title` ya existía
  desde feature 16 y se rellena vía `publish_titles_by_platform`, que
  esta feature alimenta con el `title_template` renderizado.
- **No marco la feature `done`:** se reserva para tras el OK del
  reviewer.
