# Feature 9 - `agency_default_descriptions_ui` (implementer)

Scope: validacion de variables permitidas en `description_template` del PUT
`/v1/admin/agencies/{agency_id}/social-templates`, tests, docs. Decision
leader: **KEEP** `caption_template` como dead code (no schema, no alembic).

## Archivos creados / modificados

| Tipo | Path | Cambio |
|---|---|---|
| domain (nuevo) | `modules/configuration/domain/social_templates_variables.py` | Constante `ALLOWED_TEMPLATE_VARIABLES` (frozenset de 16 keys), regex compartido `TEMPLATE_VARIABLE_PATTERN`, helpers `extract_template_variables` y `find_unknown_template_variables`. |
| domain (mod) | `modules/configuration/domain/__init__.py` | Re-export del modulo nuevo. |
| transport (mod) | `modules/configuration/transport/payloads/social_templates.py` | Docstring del `Field` describe el contrato; ningun validator Pydantic (la validacion vive en el router para garantizar 422 con shape canonico). |
| transport (mod) | `modules/configuration/transport/http/social_templates_router.py` | Nuevo paso de validacion en el PUT: `_collect_unknown_template_variables` + `_unknown_variable_response`. Devuelve 422 `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE` con `unknown_variables_by_platform` y `allowed_variables` en `details`. Imports anaden `ALLOWED_TEMPLATE_VARIABLES` y `find_unknown_template_variables`. |
| application (mod) | `modules/reels/application/content_generator.py` | Sustituye su regex local por el import canonico de `modules.configuration.domain.social_templates_variables.TEMPLATE_VARIABLE_PATTERN`. Elimina `import re` (ya no se usa). Docstring de `_build_property_template_variables` actualizado para referenciar `ALLOWED_TEMPLATE_VARIABLES`. |
| tests (nuevo) | `tests/unit/configuration/test_social_templates_variables.py` | 7 tests: pina las 16 keys, pina sync con el runtime mapping del content_generator, pina la regex y el comportamiento de `extract_template_variables` / `find_unknown_template_variables`. |
| tests (mod) | `tests/integration/configuration/test_social_templates_router.py` | +5 tests integration: 422 con variable desconocida (incl. `details` y assert que la BBDD no persiste nada), 200 con varias permitidas, 200 sin variables, 200 con llaves literales que no forman variable, 422 con multiples plataformas ofensoras a la vez. |
| docs (mod) | `docs/API.md` | Nueva subseccion **Social template variables** con la tabla de 16 keys + origen en `Property`, regla de tolerancia a llaves literales, y tabla de codigos de error del endpoint (incluye `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE`). |
| harness (mod) | `feature_list.json` | Status de feature 9 -> `in_progress`. |
| harness (mod) | `progress/current.md` | Header de feature + plan + decisiones + bitacora. |

NO tocados (decision leader): schema, `alembic/versions/*`, `agency_reel_defaults.caption_template`,
`defaults_repository.py`, `defaults_router.py`, payloads de defaults / reel_profile,
`update_reel_defaults.py`, `update_aggregated_reel_profile.py`, `admin_agencies_router.py`,
ningun test de los listados arriba que referencia `caption_template`.

## Decision tecnica: ubicacion de `ALLOWED_TEMPLATE_VARIABLES`

**Decision**: vive en `modules/configuration/domain/social_templates_variables.py`,
no en `modules/reels/application/content_generator.py`.

**Razon**: la regla de capas del repo
(`ARCHITECTURE.md:70-77`) prohibe que un modulo importe de
`<otro-bc>/application/` o `<otro-bc>/infrastructure/`. Solo `<otro-bc>/domain/`
es importable. El payload de transport
(`modules/configuration/transport/payloads/social_templates.py`) y el router
necesitan la constante para validar; el `content_generator` (en
`modules/reels/application/`) tambien la necesita para mantener un unico
catalogo. La unica colocacion que respeta la regla en ambos sentidos es
`modules/configuration/domain/`:

- `modules/configuration/transport/` puede importar de `modules/configuration/domain/` (intra-modulo, sin restriccion).
- `modules/reels/application/` puede importar de `modules/configuration/domain/` (otra-bc / domain, permitido).

Ademas, el contrato de **que variables son aceptables en la API** lo posee
naturalmente el bounded context que es dueno de la tabla `agency_social_templates`
(configuration), no el motor de substitucion (reels). El `content_generator`
sigue siendo el unico sitio que asigna **valores** a esas variables, pero la
**lista de nombres** la fija el contrato del endpoint.

Coste: el `content_generator` ahora importa de `modules.configuration.domain`,
lo cual es legal y no genera dependencia circular (configuration no importa
de reels).

## Decision tecnica: validacion en router, no en `field_validator`

**Razon**: queremos un 422 con shape canonico `{error, code, hint, details}`
y `code="SOCIAL_TEMPLATE_UNKNOWN_VARIABLE"`. Si la validacion vive en un
`field_validator` Pydantic y lanza `ValueError`, FastAPI devuelve un 422 pero
con el shape de Pydantic v2 (`{"detail": [{"type": "value_error", ...}]}`),
no el nuestro. Hacerlo en el router (despues de que Pydantic valide el shape)
da control total sobre el status code, el `code`, el mensaje, el hint y los
`details`. El precio (una funcion adicional `_collect_unknown_template_variables`)
es minimo y casa con el patron `json_error(422, ...)` ya usado en otros sitios.

## Verificacion

### `pytest` focal (lo que toca esta feature)
```
$ .venv/bin/python -m pytest tests/unit/configuration/test_social_templates_variables.py -q
.......                                                                  [100%]
7 passed in 0.49s

$ .venv/bin/python -m pytest tests/integration/configuration/test_social_templates_router.py -q
.........                                                                [100%]
9 passed in 13.22s
```

### `pytest` por modulos (regresion en configuration y reels)
```
$ .venv/bin/python -m pytest tests/unit/configuration/ tests/integration/configuration/ -q
....................................................................... [ 72%]
............................                                             [100%]
100 passed in 59.22s

$ .venv/bin/python -m pytest tests/unit/reels/ -q
.......................................................                  [100%]
55 passed in 1.02s
```

### `./init.sh`
```
$ FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh
...
[OK]    apps.api --check verde
[OK]    apps.worker --check verde
...
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
2 failed, 483 passed, 14 warnings in 207.24s (0:03:27)
[OK]    pytest verde
[OK]    Entorno listo.
```
Exit code: 0.

Los 2 fallos son **preexistentes** (warned por el leader): el endpoint `/health`
expone un campo `configured_worker_count` que el test antiguo no espera. No
toca el scope de feature 9.

### `apps.api --check` / `apps.worker --check`
```
$ .venv/bin/python -m apps.api --check; echo $?
... RUNTIME READY: Yes ...
0

$ .venv/bin/python -m apps.worker --check; echo $?
... Worker --check OK ...
0
```

### `tests/integration/test_http_surface_contract.py`
```
$ FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend .venv/bin/python -m pytest tests/integration/test_http_surface_contract.py -q
.                                                                        [100%]
1 passed in 1.69s
```

## Detalles de comportamiento (para la review)

- **422 con variable desconocida**: el handler lista por plataforma todas las
  variables desconocidas (no solo la primera), dedupea repeticiones dentro de
  un mismo template, y preserva el orden de aparicion. El body incluye:
  ```json
  {
    "error": "One or more description templates reference unknown variables: instagram: {{cosa_inventada}}.",
    "code": "SOCIAL_TEMPLATE_UNKNOWN_VARIABLE",
    "hint": "Use only the supported variables: agent_email, agent_name, ...",
    "details": {
      "unknown_variables_by_platform": {"instagram": ["cosa_inventada"]},
      "allowed_variables": ["agent_email", "agent_name", ...]
    }
  }
  ```
- **Sin escritura parcial**: el test `test_social_templates_put_rejects_unknown_variable_with_422`
  comprueba que ante un 422 la BBDD permanece intacta (no se persiste nada). El
  router corta antes de abrir el UoW.
- **Plataformas vacias / blank** (`""`, `"   "`) se siguen filtrando en el
  mismo paso de normalizacion del use case; aqui las descartamos antes de
  inspeccionar el template para no reportar plataformas "fantasma" en el
  error.
- **Llaves literales sueltas** (`{{`, `}}`, `{{ }}`, `{{ has space }}`) no
  matchean el regex `\{\{\s*([\w.]+)\s*\}\}`, por lo que no son tratadas como
  variables ni en validacion ni en runtime. El test
  `test_social_templates_put_accepts_literal_braces_that_do_not_form_a_variable`
  lo pina.
- **Single source of truth**: el test
  `test_allowed_variables_match_runtime_substitution_table` falla si
  alguien anade una key en `_build_property_template_variables` sin
  reflejarla en `ALLOWED_TEMPLATE_VARIABLES`, o viceversa.

## Pendiente (no es mio)

- Review de feature 9 por el `reviewer` antes de marcar `done`.
- Limpieza futura de `caption_template` (feature aparte segun decision del
  leader).
