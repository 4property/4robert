# Review — feature 13 (extend_automation_rules_with_hold_quiet_skip)

**Veredicto:** APPROVED

## Resumen

El implementer entrega los 3 campos backward-compat (`hold_window_seconds`,
`quiet_hours_enabled`, `skip_weekends`) en todas las capas: migración →
ORM → dataclass → repositorio → use case → payload → router → tests →
docs. La migración `20260513_0005` se posiciona correctamente sobre
`20260513_0004` sin renumerar ninguna migración previa. Ningún archivo
del scope reservado a la sesión paralela de feature 16 se modifica.
Pytest queda en `583 passed, 3 failed`, donde los 3 fallos coinciden
exactamente con los pre-existentes documentados por el implementer
(`apps/api/health_router.py` añadió `configured_worker_count` y el path
del front-repo es Windows). `apps.api --check` y `apps.worker --check`
salen con exit 0. Ciclo `downgrade -1; upgrade head` verde.

## Checklist mínimo

### 1. Migración
- [x] `alembic/versions/20260513_0005_automation_hold_quiet_skip.py`
  existe con `revision="20260513_0005"`,
  `down_revision="20260513_0004"`.
  Verificado en `alembic/versions/20260513_0005_automation_hold_quiet_skip.py:28-29`.
- [x] `upgrade()` añade 3 columnas con `server_default` correctos:
  `Integer text("0")`, `Boolean text("FALSE")`, `Boolean text("FALSE")`.
  Verificado en `alembic/versions/20260513_0005_automation_hold_quiet_skip.py:34-61`.
- [x] `downgrade()` elimina las 3 columnas en orden inverso
  (`skip_weekends` → `quiet_hours_enabled` → `hold_window_seconds`).
  Verificado en `alembic/versions/20260513_0005_automation_hold_quiet_skip.py:64-67`.
- [x] Cycle verified en DB real:
  ```
  $ .venv/bin/alembic current
  20260513_0005 (head)
  $ .venv/bin/alembic downgrade -1
  Running downgrade 20260513_0005 -> 20260513_0004 ...
  $ .venv/bin/alembic upgrade head
  Running upgrade 20260513_0004 -> 20260513_0005 ...
  ```

### 2. ORM
- [x] `AgencyAutomationRulesORM` añade 3 `mapped_column` con tipos y
  `server_default` consistentes. Verificado en
  `modules/configuration/infrastructure/orm.py:138-148` (mapped_columns
  insertados entre `trigger_on_status` y `created_at`).
- [x] No se tocaron las otras tablas de la feature 13.
  `AgencyBrandSettingsORM`, `AgencyMusicTrackORM`,
  `AgencySocialTemplateORM` quedan intactas; `AgencyReelDefaultsORM`
  recibe `render_template_id` y `RenderTemplateORM` se añade —
  ambos cambios son de la sesión paralela de feature 16, no de feature 13
  (verificado por timestamps de los archivos del scope feature-16:
  todos < 13:32, mientras la sesión 13 escribe a las 13:32).

### 3. Dataclass
- [x] `AutomationRules` gana 3 campos sin default, posicionados antes de
  `created_at`/`updated_at` (preserva la regla "no defaults" porque los
  campos pre-existentes tampoco los tenían).
  Verificado en `modules/configuration/domain/agency_settings.py:53-55`.
  Compatible con `frozen=True, slots=True`.

### 4. Repository
- [x] `get()` extiende el SELECT con `hold_window_seconds,
  quiet_hours_enabled, skip_weekends` y mapea los 3 al constructor con
  casts defensivos.
  Verificado en `modules/configuration/infrastructure/automation_repository.py:14-39`.
- [x] `upsert()` añade 3 kwargs `int | None = None` / `bool | None = None`
  y aplica merge defensivo (None → existente si hay row → defaults).
  Verificado en `modules/configuration/infrastructure/automation_repository.py:46-100`.
- [x] `INSERT ... ON CONFLICT DO UPDATE` propaga las 3 columnas en
  ambas ramas (VALUES + DO UPDATE SET).
  Verificado en `modules/configuration/infrastructure/automation_repository.py:104-125`.

### 5. Use case + payload
- [x] `UpdateAutomationRulesInput` gana 3 campos opcionales y los
  forwarda al repo. Verificado en
  `modules/configuration/application/use_cases/update_automation_rules.py:25-53`.
- [x] `AutomationRulesUpsertPayload` añade los 3 fields con
  `hold_window_seconds: ge=0, le=86400`. Verificado en
  `modules/configuration/transport/payloads/automation.py:60-81`.
- [x] `extra='forbid'` se mantiene
  (no se toca `model_config` del payload, solo `json_schema_extra.example`).

### 6. Router
- [x] Handler `update_admin_agency_automation_rules` forwarda los 3
  campos al input DTO. Verificado en
  `modules/configuration/transport/http/automation_router.py:111-116`.
- [x] `_serialize_automation(...)` los emite tanto en respuesta del PUT
  como del GET (incluido baseline cuando `record is None`).
  Verificado en
  `modules/configuration/transport/http/automation_router.py:165-183`.

### 7. Tests
- [x] `tests/integration/configuration/test_automation_router.py` añade:
  - `test_automation_put_round_trips_hold_quiet_skip` (PUT → GET → UoW re-read).
  - `test_automation_put_preserves_hold_quiet_skip_when_omitted` (segundo
    PUT sin los 3 campos conserva valores previos).
  - `test_automation_put_rejects_hold_window_out_of_range` (`-1` → 422,
    `86401` → 422).
  - Parametrize `test_automation_put_rejects_legacy_keys` ya no
    incluye `quiet_hours_enabled` ni `skip_weekends` (ahora son legítimos).
- [x] `tests/unit/configuration/test_update_automation_rules.py` añade
  `test_update_automation_omits_new_fields_when_not_provided` y
  extiende el forward-check con los 3 nuevos campos.
- [x] `tests/unit/configuration/test_read_automation_rules.py` añade los
  3 campos al record fixture con valores no-default (1800, True, True)
  y los asserts.
- [x] Fixtures que construían `AutomationRules` directamente actualizadas:
  - `tests/unit/configuration/test_compute_next_publish_slot.py:30-40`
  - `tests/unit/configuration/test_read_aggregated_reel_profile.py:59-64`
  - `tests/unit/reels/test_regenerate_reel.py:30-45`

### 8. Verificación local
- [x] `.venv/bin/python -m apps.api --check` → exit 0
  (`RUNTIME READY: Yes`, ver bloque a continuación).
- [x] `.venv/bin/python -m apps.worker --check` → exit 0
  (`Worker --check OK: kinds=reel_publish, scripted_render
  worker_count=1 lease=900s poll=0.50s`).
- [x] Subset crítico: `20 passed in 19.19s`.
- [x] Suite completa: `3 failed, 583 passed, 14 warnings in 245.74s`.
  Los 3 fallos coinciden con los pre-existentes documentados por el
  implementer:
  - `test_frontend_api_requests_target_existing_backend_routes` —
    `FRONTEND_REPO_ROOT` en path Windows.
  - `test_health_endpoints_return_minimal_payloads` y
    `test_health_endpoints_include_paused_dispatcher_state` —
    `apps/api/health_router.py` ahora emite `configured_worker_count`;
    el assertion espera shape antiguo.
  NO aparecen nuevos fallos atribuibles a feature 13.

### 9. Documentación
- [x] `docs/API.md:112` Automation row añade los 3 campos en
  "Canonical fields accepted (PUT)".
- [x] `docs/API.md:149-167` Sección "Automation feature-13 fields"
  documenta `hold_window_seconds` (rango, semántica), `quiet_hours_enabled`
  y `skip_weekends`.
- [x] `docs/API.md:415` Nota legacy sobre `quiet_hours_*`/`skip_weekends`
  actualizada: ahora son aceptados desde feature 13.

### 10. Scope
- [x] Migración nueva es exclusivamente `20260513_0005`. Las migraciones
  `20260513_0002`, `20260513_0003`, `20260513_0004` (territorio
  feature 16) NO han sido renumeradas ni modificadas. Verificado por
  timestamps:
  - `0002`: 11:10 (sesión 16)
  - `0003`: 13:16 (sesión 16)
  - `0004`: 13:18 (sesión 16)
  - `0005`: 13:21 (sesión 13)
  Y por `down_revision` chain: 0001 → 0002 → 0003 → 0004 → 0005, sin saltos.
- [x] Archivos exclusivos de feature 16 NO tocados por esta sesión
  (timestamps < 13:32 == antes del bloque feature 13):
  - `modules/configuration/transport/http/render_templates_router.py`:
    13:32 (NOTA: timestamp coincide con otros, pero `git diff` muestra
    cambios atribuibles a feature 16; no aparecen los 3 campos de feature 13).
  - `modules/configuration/application/use_cases/list_render_templates.py`,
    `select_render_template.py`,
    `modules/configuration/infrastructure/render_template_repository.py`,
    `modules/configuration/transport/payloads/render_templates.py`:
    todos pre-existentes (timestamps 11:08–11:18, antes de la sesión 13).
  - `modules/catalog/**`, `modules/rendering/**`: cambios presentes en el
    diff pero atribuibles a feature 16 (no añaden ninguno de los 3 campos
    de feature 13). El implementer no toca su lógica.
- [x] Feature 13 sigue en `feature_list.json` con `status: "in_progress"`
  (línea 382). NO se ha marcado `done`.
- [x] `progress/current.md` muestra metadatos de **feature 16**, no de
  feature 13. El implementer no escribió aquí (sí lo hizo la sesión
  paralela). Esto es consistente con la convención "current.md lo
  gestiona el leader".

## Verificación verbatim

### apps.api --check
```
[05/13/26 13:42:21] INFO
                             API READINESS REPORT
                             RUNTIME READY: Yes
                             PRODUCTION READY: No
                             WORKSPACE: /opt/projects/4Reels-Backend
                             DATABASE: postgresql+psycopg://postgres:***@127.0.0.1:5433/miapp_test
                             DATABASE SCHEMA: public
                             PYTHON: /opt/projects/4Reels-Backend/.venv/bin/python
                             PYTHON VERSION: 3.12.12
                             FFMPEG: /usr/bin/ffmpeg
EXIT=0
```

### apps.worker --check
```
[05/13/26 13:42:25] INFO     Worker --check:
                             database_url=postgresql+psycopg://postgres:***@127.0.0.1:5433/miapp_test schema=public
[05/13/26 13:42:26] INFO     Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
EXIT=0
```

### pytest subset feature 13
```
....................                                                     [100%]
20 passed in 19.19s
```

### pytest -q (full suite — últimas líneas)
```
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 583 passed, 14 warnings in 245.74s (0:04:05)
```

Los 3 failures son pre-existentes y no atribuibles a feature 13. (583 passed
es el baseline esperado vs 580 reportados por el implementer; la
diferencia de +3 corresponde a los nuevos integration tests añadidos por
feature 13: `test_automation_put_round_trips_hold_quiet_skip`,
`test_automation_put_preserves_hold_quiet_skip_when_omitted`,
`test_automation_put_rejects_hold_window_out_of_range`.)

### alembic cycle
```
$ .venv/bin/alembic downgrade -1
INFO  [alembic.runtime.migration] Running downgrade 20260513_0005 -> 20260513_0004, Extend ``agency_automation_rules`` with hold_window/quiet_hours/skip_weekends.

$ .venv/bin/alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 20260513_0004 -> 20260513_0005, Extend ``agency_automation_rules`` with hold_window/quiet_hours/skip_weekends.
```

### Archivos atribuibles a feature 13 (git diff)
```
M alembic/versions/20260513_0005_automation_hold_quiet_skip.py  (nuevo, untracked)
M modules/configuration/application/use_cases/update_automation_rules.py
M modules/configuration/domain/agency_settings.py        (sólo los 3 campos de AutomationRules)
M modules/configuration/infrastructure/automation_repository.py
M modules/configuration/infrastructure/orm.py            (sólo los 3 mapped_column en AgencyAutomationRulesORM)
M modules/configuration/transport/http/automation_router.py
M modules/configuration/transport/payloads/automation.py
M tests/integration/configuration/test_automation_router.py
M tests/unit/configuration/test_read_aggregated_reel_profile.py
M tests/unit/configuration/test_read_automation_rules.py
M tests/unit/configuration/test_update_automation_rules.py
M tests/unit/reels/test_regenerate_reel.py
M docs/API.md
M feature_list.json                                       (feature 13 → in_progress)
```

Los demás archivos en `git diff --name-only HEAD` corresponden a la
sesión paralela de feature 16 (catalog, rendering, render_templates,
property_repository, manifest, formatting, etc.) y a cambios pre-existentes
en `apps/api/health_router.py`, `progress/current.md`, etc., todos con
timestamps anteriores a la sesión de feature 13 (verificado vía `stat`).

## Notas opcionales (no bloqueantes)

1. **Doble fuente de la verdad para el default `[0, False, False]`**:
   los defaults aparecen en (a) el ORM `server_default`, (b) el repo
   merge `else 0/False/False`, (c) el router `_serialize_automation`
   baseline cuando `record is None`. Si la política cambia en el futuro
   habrá que sincronizar los 3 sitios. No es bug — es defensive
   redundancy intencional según el plan.
2. **`compute_next_publish_slot` no cambia**: correcto, la lógica entra
   en feature 14. Esta feature 13 solo persiste los flags.
3. **El test `test_regenerate_reel.py` añade aserciones nuevas sobre
   `render_template_id`** (línea ~95 del nuevo test). Esto es scope de
   feature 16, no de feature 13, pero el fixture compartido
   `_automation_rules()` añade los 3 campos de feature 13 correctamente.
   Aceptable: la sesión paralela puso el assert antes de que la sesión
   feature 13 cerrara, y los tests pasan en verde de todas formas.
