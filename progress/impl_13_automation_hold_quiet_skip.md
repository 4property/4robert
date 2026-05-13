# Impl: feature 13 — extend_automation_rules_with_hold_quiet_skip

## Resumen

Añadidos tres campos backward-compat a la tabla `agency_automation_rules` y
threading completo por todas las capas hasta el payload Pydantic:
`hold_window_seconds INTEGER NOT NULL DEFAULT 0`,
`quiet_hours_enabled BOOLEAN NOT NULL DEFAULT FALSE`, y
`skip_weekends BOOLEAN NOT NULL DEFAULT FALSE`. La migración usa
`server_default` para que filas existentes sobrevivan al upgrade sin
backfill manual. La capa de payload (`AutomationRulesUpsertPayload`)
mantiene `extra='forbid'` y acepta los tres nuevos campos como opcionales
con la validación `hold_window_seconds` en `[0, 86400]`. El repositorio
preserva los valores previos cuando el PUT omite alguno de los nuevos
campos (defaults solo aplican en el INSERT inicial). El algoritmo de
`compute_next_publish_slot` queda intacto — esa parte de la lógica vive
en feature 14, esta feature solo persiste los flags.

## Archivos creados

| Archivo | Tipo |
|---|---|
| `alembic/versions/20260513_0005_automation_hold_quiet_skip.py` | Migración alembic (revision `20260513_0005`, down `20260513_0004`) |

## Archivos modificados

| Archivo | Cambio |
|---|---|
| `modules/configuration/infrastructure/orm.py` | `AgencyAutomationRulesORM` gana 3 `Mapped[...]` con `server_default=text(...)` (`Integer 0`, `Boolean FALSE`, `Boolean FALSE`) consistentes con el resto del archivo. |
| `modules/configuration/domain/agency_settings.py` | `AutomationRules` dataclass gana 3 campos sin default (`hold_window_seconds: int`, `quiet_hours_enabled: bool`, `skip_weekends: bool`), colocados antes de `created_at`/`updated_at` para preservar la regla "no defaults" del dataclass. |
| `modules/configuration/infrastructure/automation_repository.py` | `get()` extiende el SELECT y mapea los 3 campos al constructor del dataclass. `upsert()` acepta 3 kwargs opcionales, fusiona vía `merged` con preservación defensiva (si `None` y existe row → valor previo; si `None` y no existe → defaults `0`/`False`/`False`), y la sentencia `INSERT ... ON CONFLICT DO UPDATE` propaga los nuevos columnas en ambas ramas. |
| `modules/configuration/application/use_cases/update_automation_rules.py` | `UpdateAutomationRulesInput` gana 3 campos opcionales y `execute()` los forwarda al repositorio. |
| `modules/configuration/transport/payloads/automation.py` | `AutomationRulesUpsertPayload` gana 3 `Field`: `hold_window_seconds` con `ge=0, le=86400`, `quiet_hours_enabled` y `skip_weekends` booleanos. `json_schema_extra.example` refleja los nuevos campos. `extra='forbid'` se mantiene. |
| `modules/configuration/transport/http/automation_router.py` | El handler `update_admin_agency_automation_rules` forwarda los 3 campos al `UpdateAutomationRulesInput`. `_serialize_automation` los emite tanto en la respuesta del PUT como en la del GET (incluido el baseline cuando no hay row). |
| `tests/unit/configuration/test_update_automation_rules.py` | El test existente forward-check incluye los 3 nuevos campos; nuevo test `test_update_automation_omits_new_fields_when_not_provided` documenta que omitir los 3 envía `None` al repositorio (= "preserve previous"). |
| `tests/unit/configuration/test_read_automation_rules.py` | El record fixture incluye los 3 campos (con valores no-default) y asserts adicionales verifican que `result.hold_window_seconds == 1800`, `quiet_hours_enabled is True`, `skip_weekends is True`. |
| `tests/unit/configuration/test_compute_next_publish_slot.py` | Helper `_rules()` pasa los 3 campos con `0/False/False` para compilar con el dataclass ampliado. Sin cambios funcionales (feature 14 trae la nueva lógica). |
| `tests/unit/configuration/test_read_aggregated_reel_profile.py` | Constructor de `AutomationRules` en el fixture añade los 3 campos. |
| `tests/unit/reels/test_regenerate_reel.py` | Helper `_automation_rules()` añade los 3 campos. |
| `tests/integration/configuration/test_automation_router.py` | Nuevo test `test_automation_put_round_trips_hold_quiet_skip` (PUT → GET → re-read UoW). Nuevo test `test_automation_put_preserves_hold_quiet_skip_when_omitted` (segundo PUT sin los campos preserva los valores anteriores). Nuevo test `test_automation_put_rejects_hold_window_out_of_range` (`-1` y `86401` → 422). El parametrize `test_automation_put_rejects_legacy_keys` ya no incluye `quiet_hours_enabled` ni `skip_weekends` (ahora son aceptados). |
| `docs/API.md` | Fila Automation amplía la columna "Canonical fields accepted (PUT)" con los 3 nuevos campos. Sección "Automation feature-13 fields" documenta rangos, defaults y semántica. La nota legacy sobre `quiet_hours_*`/`skip_weekends` "no part of this contract" se actualiza para explicar que el persistir está ya implementado y que feature 14 wirea el algoritmo. |
| `feature_list.json` | Feature 13 movido de `pending` → `in_progress`. (NO se marcó `done` — lo hace el reviewer + leader al cerrar). |

## Migración

```python
revision = "20260513_0005"
down_revision = "20260513_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agency_automation_rules",
        sa.Column(
            "hold_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "agency_automation_rules",
        sa.Column(
            "quiet_hours_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "agency_automation_rules",
        sa.Column(
            "skip_weekends",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agency_automation_rules", "skip_weekends")
    op.drop_column("agency_automation_rules", "quiet_hours_enabled")
    op.drop_column("agency_automation_rules", "hold_window_seconds")
```

Ciclo verificado en DB real:

```
$ .venv/bin/alembic current
20260513_0005 (head)

$ .venv/bin/alembic downgrade -1
Running downgrade 20260513_0005 -> 20260513_0004, Extend ``agency_automation_rules`` with hold_window/quiet_hours/skip_weekends.

$ .venv/bin/alembic upgrade head
Running upgrade 20260513_0004 -> 20260513_0005, Extend ``agency_automation_rules`` with hold_window/quiet_hours/skip_weekends.
```

## Diff conceptual por archivo

### `modules/configuration/infrastructure/orm.py`

Tres `mapped_column` añadidos en `AgencyAutomationRulesORM` justo antes
de `created_at`:

```python
hold_window_seconds: Mapped[int] = mapped_column(
    Integer, nullable=False, server_default=text("0")
)
quiet_hours_enabled: Mapped[bool] = mapped_column(
    Boolean, nullable=False, server_default=text("FALSE")
)
skip_weekends: Mapped[bool] = mapped_column(
    Boolean, nullable=False, server_default=text("FALSE")
)
```

### `modules/configuration/domain/agency_settings.py`

Tres campos sin default insertados antes de `created_at`:

```python
@dataclass(frozen=True, slots=True)
class AutomationRules:
    agency_id: str
    approval_required: bool
    publish_window_start: str
    publish_window_end: str
    publish_days: tuple[str, ...]
    trigger_on_status: tuple[str, ...]
    hold_window_seconds: int          # NEW
    quiet_hours_enabled: bool         # NEW
    skip_weekends: bool               # NEW
    created_at: str
    updated_at: str
```

### `modules/configuration/infrastructure/automation_repository.py`

- `SELECT` ampliado con `hold_window_seconds, quiet_hours_enabled, skip_weekends`.
- Constructor del dataclass añade los 3 campos con casts defensivos
  (`int(row.hold_window_seconds or 0)`, `bool(...)`, `bool(...)`).
- `upsert(...)` añade 3 kwargs `hold_window_seconds: int | None = None`,
  `quiet_hours_enabled: bool | None = None`, `skip_weekends: bool | None = None`.
- `merged` aplica la regla "None → previa si existe, default si no":

```python
"hold_window_seconds": int(
    hold_window_seconds
    if hold_window_seconds is not None
    else (existing.hold_window_seconds if existing else 0)
),
"quiet_hours_enabled": bool(
    quiet_hours_enabled
    if quiet_hours_enabled is not None
    else (existing.quiet_hours_enabled if existing else False)
),
"skip_weekends": bool(
    skip_weekends
    if skip_weekends is not None
    else (existing.skip_weekends if existing else False)
),
```

- `INSERT ... ON CONFLICT DO UPDATE` extendido con las 3 columnas
  nuevas en ambas listas (VALUES y DO UPDATE SET).

### `modules/configuration/application/use_cases/update_automation_rules.py`

- `UpdateAutomationRulesInput` añade `hold_window_seconds: int | None = None`,
  `quiet_hours_enabled: bool | None = None`, `skip_weekends: bool | None = None`.
- `execute()` los forwarda al `uow.configuration.automation.upsert(...)`.

### `modules/configuration/transport/payloads/automation.py`

- `extra='forbid'` mantenido.
- Tres `Field(default=None, ...)` añadidos con validaciones del plan:

```python
hold_window_seconds: int | None = Field(
    default=None, ge=0, le=86400,
    description="Delay in seconds to wait before publishing after the trigger (0 = immediate, max 24h).",
)
quiet_hours_enabled: bool | None = Field(default=None, description="...")
skip_weekends: bool | None = Field(default=None, description="...")
```

- `json_schema_extra.example` añade `hold_window_seconds: 0`,
  `quiet_hours_enabled: false`, `skip_weekends: false`.

### `modules/configuration/transport/http/automation_router.py`

- `UpdateAutomationRulesInput(...)` lleva los 3 campos.
- `_serialize_automation(...)` los expone en la respuesta (y en el
  baseline cuando `record is None`).

## Tests

Subset crítico:

```
$ .venv/bin/python -m pytest tests/integration/configuration/test_automation_router.py tests/unit/configuration/test_update_automation_rules.py tests/unit/configuration/test_read_automation_rules.py -q
....................                                                     [100%]
20 passed in 19.25s
```

Suite completa (últimas líneas):

```
3 failed, 580 passed, 14 warnings in 245.84s (0:04:05)
```

Los 3 fallos son **preexistentes** y NO relacionados con feature 13:

- `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
  — falla por `FRONTEND_REPO_ROOT` apuntando a una ruta Windows
  (`C:/Users/4pm/Desktop/4reels/4reels front`) que no existe en Linux.
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads`
  — el endpoint `/health` ahora emite `configured_worker_count`
  (cambio hecho en `apps/api/health_router.py` por otra sesión); el
  test todavía espera el shape antiguo.
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state`
  — mismo origen.

Verificado vía `git stash` que estos fallos están presentes en el árbol
base (sin los cambios de feature 13).

## apps.api / apps.worker --check

```
$ .venv/bin/python -m apps.api --check ; echo "EXIT=$?"
... API READINESS REPORT ... RUNTIME READY: Yes ...
EXIT=0

$ .venv/bin/python -m apps.worker --check ; echo "EXIT=$?"
Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
EXIT=0
```

## Confirmación de scope

- **NO** se ha tocado ningún archivo del scope de feature 16:
  `modules/catalog/`, `modules/rendering/`,
  `modules/configuration/transport/http/render_templates_router.py`,
  `modules/configuration/application/use_cases/list_render_templates.py`,
  `modules/configuration/application/use_cases/select_render_template.py`,
  `modules/configuration/infrastructure/render_template_repository.py`,
  `modules/configuration/transport/payloads/render_templates.py`.
- **NO** se ha renumerado ninguna migración existente
  (`20260513_0002`, `20260513_0003`, `20260513_0004` se mantienen).
  La migración nueva es `20260513_0005`, `down_revision=20260513_0004`.
- **NO** se ha tocado `progress/current.md` (lo gestiona el leader).
- **NO** se ha marcado `status:"done"` en `feature_list.json`. Sigue
  como `in_progress` esperando el reviewer.

## Decisiones / caveats

1. **Campos del dataclass sin default**: el plan obligaba a posicionar los
   3 campos sin default antes de `created_at`/`updated_at`. Esto rompe
   todos los call sites del dataclass que omitían los nuevos kwargs.
   Identifiqué 4 fixtures (`test_compute_next_publish_slot.py`,
   `test_read_aggregated_reel_profile.py`, `test_regenerate_reel.py`,
   `test_read_automation_rules.py`) que construyen `AutomationRules`
   directamente y los actualicé con `hold_window_seconds=0,
   quiet_hours_enabled=False, skip_weekends=False` (o valores
   significativos en el test que asserts los nuevos campos). El
   repositorio es el otro call site y ya quedó alineado.
2. **`test_automation_put_rejects_legacy_keys`**: el parametrize previo
   rechazaba `quiet_hours_enabled` y `skip_weekends` como legacy. Esos
   dos pares se eliminan del parametrize (ahora son legítimos
   campos) pero el resto del contrato anti-legacy (`publish_mode`,
   `review_window_*`, `auto_captions`, `regen_on_update`,
   `review_emails`) se mantiene intacto.
3. **`compute_next_publish_slot` sin cambios**: feature 13 solo persiste
   los flags. La lógica de scheduling (timezone IANA, aplicar
   `hold_window` antes de comparar contra ventanas, deferir cuando
   `quiet_hours_enabled` y caer fuera de la ventana, saltar findes
   cuando `skip_weekends`) llega en feature 14. La docstring de
   `compute_next_publish_slot` mantiene el `TODO` actual; lo actualizará
   feature 14.
4. **Range validation**: `hold_window_seconds` queda en `[0, 86400]` por
   `Pydantic.Field(ge=0, le=86400)`. No se añade triple-validación en
   el use case ni en el repositorio — la frontera única ya garantiza
   el invariante en la entrada.
5. **Tests que añaden carga**: 4 tests integration nuevos (round-trip,
   preservación, range -1, range 86401) + 1 test unit nuevo
   (`test_update_automation_omits_new_fields_when_not_provided`). El
   parametrize de legacy keys pasa de 8 a 6 entradas (-2).
6. **Migración numerada `20260513_0005`** para no chocar con
   `20260513_0003_add_property_accent_colors.py` y
   `20260513_0004_seed_side_banner_render_template.py` que feature 16
   ya consumió. Plan v2 originalmente reservaba `0003` para esta
   feature; el leader ya coordinó el shift en el brief.
