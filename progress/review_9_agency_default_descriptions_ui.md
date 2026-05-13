# Review — feature 9 (`agency_default_descriptions_ui`)

**Veredicto:** APPROVED

## Scope verificado contra decisión del leader

Decisión del leader: **KEEP** `agency_reel_defaults.caption_template`
(no schema, no alembic). El implementer debía limitarse a validación de
variables del `description_template` + tests + `docs/API.md`.

`git diff` confirma que NINGÚN archivo prohibido fue modificado por esta
feature (en lo que respecta a `caption_template`):

- `shared/db/orm.py` — sin cambios.
- `alembic/versions/` — sin cambios (`git status --porcelain alembic/` vacío).
- `modules/configuration/domain/agency_settings.py` — sin cambios.
- `modules/configuration/infrastructure/social_template_repository.py` — sin cambios.
- `modules/configuration/application/use_cases/replace_social_templates.py` — sin cambios.
- `modules/configuration/application/use_cases/read_social_templates.py` — sin cambios.
- `modules/configuration/application/use_cases/update_reel_defaults.py` — sin cambios.
- `modules/configuration/application/use_cases/update_aggregated_reel_profile.py` — sin cambios.

Los archivos `defaults_repository.py`, `defaults_router.py`,
`payloads/defaults.py`, `payloads/reel_profile.py`,
`tenancy/admin_agencies_router.py` y
`read_aggregated_reel_profile.py` SÍ aparecen en `git diff` pero
únicamente con cambios de **drift pre-existente** (añadir `"pinterest"`
a listas de plataformas, de la feature 8). `grep '^[+-].*caption_template'`
sobre el diff completo del árbol confirma cero hits en código: las únicas
menciones a `caption_template` aparecen en `feature_list.json` y
`progress/current.md` (documentación, no código). El implementer no tocó
`caption_template` en ningún sentido — coherente con la decisión KEEP.

## Checkpoints

- C1 (capas — domain libre de ORM/SQLAlchemy): [x]
  `modules/configuration/domain/social_templates_variables.py` solo usa
  `re` de stdlib y `frozenset`. Sin Pydantic, sin SQLAlchemy
  (`social_templates_variables.py:17-78`).
- C2 (aislamiento entre módulos): [x]
  `modules/reels/application/content_generator.py:13-15` importa
  `modules.configuration.domain.social_templates_variables.TEMPLATE_VARIABLE_PATTERN`.
  Reels → configuration **domain** está permitido por
  `ARCHITECTURE.md:96-100` (`A module may import from shared/ and from
  another module's domain/`). Configuration no importa de reels, no hay
  ciclo.
- C3 (nombres por convenciones): [x] `ALLOWED_TEMPLATE_VARIABLES`
  (`UPPER_SNAKE` para constante), `TEMPLATE_VARIABLE_PATTERN`,
  `extract_template_variables`, `find_unknown_template_variables` siguen
  `docs/conventions.md`.
- C4 (errores con shape canónico): [x] El router devuelve
  `json_error(422, ..., code="SOCIAL_TEMPLATE_UNKNOWN_VARIABLE", hint=...,
  details={"unknown_variables_by_platform": ..., "allowed_variables": ...})`
  (`social_templates_router.py:196-219`). Coincide con el shape
  `{error, code, hint, details}` que usa el resto del repo.
- C5 (test con Postgres real, no mock): [x] Los 5 tests de integración
  usan `temporary_postgres_schema` + `seed_tenant` + `build_configuration_client`
  (`tests/integration/configuration/test_social_templates_router.py:113-263`).
  El test 422 además verifica que la DB **no** persistió nada
  (`stored == ()` en línea 148-151).
- C6 (test focal verde): [x]
  `.venv/bin/python -m pytest tests/unit/configuration/
  tests/integration/configuration/ -q` → **100 passed in 58.97s**.
- C7 (`./init.sh` verde excepto fallos pre-existentes documentados): [x]
  `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh` →
  exit 0; 483 passed, 2 failed. Los 2 fallos son los pre-existentes de
  `/health` (`test_health_endpoints_include_paused_dispatcher_state`,
  `test_health_endpoints_return_minimal_payloads`) que el leader marcó
  como no bloqueantes. NO hay fallos nuevos.
- C8 (`apps.api --check` y `apps.worker --check` exit 0): [x] ambos
  retornan 0 con `RUNTIME READY: Yes` / `Worker --check OK`.

## Validación del contrato

- **Constante con 16 keys exactas**: `ALLOWED_TEMPLATE_VARIABLES` en
  `modules/configuration/domain/social_templates_variables.py:21-40`
  contiene exactamente las 16 claves (`property_title, price, bedrooms,
  bathrooms, size_m2, property_type, city, neighborhood, neighborhood_tag,
  eircode, short_description, agent_name, agent_phone, agent_email,
  booking_link, property_url`). El test
  `test_allowed_template_variables_contains_exactly_the_expected_sixteen_keys`
  (`tests/unit/configuration/test_social_templates_variables.py:28-48`)
  pina el conjunto.
- **Validación en el router con 422**: el handler PUT llama
  `_collect_unknown_template_variables` ANTES de abrir la UoW
  (`social_templates_router.py:109-111`); si hay desconocidas devuelve
  `_unknown_variable_response` que produce el 422 con
  `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE`. Sin escritura parcial — verificado
  en el test (`stored == ()` post-422 en línea 148-151 del test
  integration).
- **Código de error consistente**: `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE`
  documentado en `docs/API.md:165-167` (tabla de error codes del
  endpoint), emitido en `social_templates_router.py:210`, comprobado en
  `tests/integration/configuration/test_social_templates_router.py:139`
  y `:259`.
- **Single source of truth**: el test
  `test_allowed_variables_match_runtime_substitution_table`
  (`tests/unit/configuration/test_social_templates_variables.py:51-64`)
  ata el catálogo a las keys efectivas que
  `_build_property_template_variables` produce; si alguien añade/quita
  una key en el runtime sin actualizar el contrato (o viceversa), el
  test rompe.

## Decisión de ubicación de la constante — justificada y coherente

El implementer colocó `ALLOWED_TEMPLATE_VARIABLES` en
`modules/configuration/domain/social_templates_variables.py`, NO en
`modules/reels/application/content_generator.py`. La justificación que
escribió en `progress/impl_9_agency_default_descriptions_ui.md` líneas
27-53 cita literalmente la regla de capas de `ARCHITECTURE.md:96-100`:

> A module may import from shared/ and from another module's domain/.
> A module may not import another module's application/ or infrastructure/.

Verificado: `modules/configuration/transport/http/social_templates_router.py:25-28`
importa `ALLOWED_TEMPLATE_VARIABLES, find_unknown_template_variables`
desde `modules.configuration.domain.social_templates_variables` (intra-módulo,
trivialmente legal). `modules/reels/application/content_generator.py:13-15`
importa `TEMPLATE_VARIABLE_PATTERN` desde el mismo módulo
(reels.application → configuration.domain, permitido). La alternativa
"dejar el catálogo en `content_generator.py` e importarlo desde
configuration/transport" habría sido **ilegal** (configuration → reels.application).
Decisión correcta y bien argumentada.

## Tests añadidos

Integración (`tests/integration/configuration/test_social_templates_router.py`):
- `test_social_templates_put_rejects_unknown_variable_with_422` (líneas 113-151)
  → 422 + `details.unknown_variables_by_platform == {"instagram":
  ["cosa_inventada"]}` + verificación de que la BBDD queda intacta.
- `test_social_templates_put_accepts_allowed_variables_only` (líneas 154-181)
  → 200 con varias variables del catálogo en 2 plataformas.
- `test_social_templates_put_accepts_template_without_any_variables`
  (líneas 184-206) → 200 con strings sin `{{...}}`.
- `test_social_templates_put_accepts_literal_braces_that_do_not_form_a_variable`
  (líneas 209-232) → 200 con `{{`, `{{ }}`, `{{ has space }}`.
- `test_social_templates_put_reports_every_offending_platform` (líneas 235-263)
  → 422 con múltiples plataformas con variables desconocidas.

Cumple los 4 casos requeridos (de hecho son 5).

Unit (`tests/unit/configuration/test_social_templates_variables.py`):
7 tests que pinan el contrato, el sync con runtime, y el regex.

## docs/API.md

Nueva subsección **Social template variables** (`docs/API.md:120-167`):
- Tabla de las 16 keys con su origen en `Property`.
- Regla de tolerancia a llaves literales sueltas.
- Tabla de códigos de error del endpoint, incluyendo
  `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE` con descripción del shape de
  `details.unknown_variables_by_platform` y `details.allowed_variables`.
- Apunta explícitamente a `ALLOWED_TEMPLATE_VARIABLES` y al runtime
  table como las dos fuentes que el test unit mantiene en sync.

## Out-of-scope drift en el working tree (informativo, no bloqueante)

El working tree tiene muchos cambios sin commit que NO son de esta
feature (feature 8 Pinterest, feature 12 unescape de HTML, feature 13
idempotencia, etc.). Confirmado revisando el `git diff` de archivos
prohibidos: solo aparecen renames de `"pinterest"` en listas de
plataformas y el `html.unescape` en `content_generator.py:113` que el
spike ya identificó como pre-existente. El implementer trabajó sobre
ese árbol respetando los archivos prohibidos.

## Cambios requeridos

Ninguno.
