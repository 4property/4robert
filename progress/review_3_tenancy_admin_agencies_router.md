# Review — feature 3 (tenancy_admin_agencies_router)

**Veredicto:** APPROVED

## Alcance Revisado

- `modules/tenancy/transport/http/admin_agencies_router.py`
- `modules/tenancy/transport/http/__init__.py`
- `modules/tenancy/transport/payloads/agencies.py`
- `modules/tenancy/transport/payloads/__init__.py`
- `modules/tenancy/application/use_cases/_agency_support.py`
- `modules/tenancy/application/use_cases/register_agency.py`
- `modules/tenancy/application/use_cases/list_agencies.py`
- `modules/tenancy/application/use_cases/inspect_agency.py`
- `modules/tenancy/application/use_cases/reconfigure_agency.py`
- `modules/tenancy/application/use_cases/decommission_agency.py`
- `modules/tenancy/application/use_cases/__init__.py`
- `modules/tenancy/infrastructure/agency_repository.py` (sin cambios respecto a baseline; ya soportaba `create/update/delete`).
- `apps/api/app_factory.py` (registro del router nuevo).
- `services/transport/http/server.py` (borrado de payloads/handlers/helpers/runtime methods de agencies).
- `tests/integration/test_http_transport.py` (tests legacy adaptados al UoW; sin `xfail`).
- `tests/integration/tenancy/test_admin_agencies_router.py` (cobertura del router nuevo).
- `tests/unit/tenancy/test_register_agency.py`
- `tests/unit/tenancy/test_list_agencies.py`
- `tests/unit/tenancy/test_inspect_agency.py`
- `tests/unit/tenancy/test_reconfigure_agency.py`
- `tests/unit/tenancy/test_decommission_agency.py`

Nota: no existe `progress/impl_3_tenancy_admin_agencies_router.md`; se usó
`progress/current.md` (bitácora con timestamps + plan + lista de archivos
modificados) y la lectura directa del diff como informe de implementación,
siguiendo el precedente de la feature 2.

## Checkpoints

- C1: [x] Archivos base presentes; `./init.sh` ejecutado y verde (exit 0).
- C2: [x] Sólo la feature 3 está `in_progress`. `progress/current.md`
  describe la sesión activa con bitácora real.
- C3: [x]
  - Naming descriptivo correcto: `register_agency`, `list_agencies`,
    `inspect_agency`, `reconfigure_agency`, `decommission_agency`. No
    quedan rastros de `create/get/update/delete_agency` como nombres
    de use case.
  - `modules/tenancy/domain/agency.py` no importa SQLAlchemy.
  - `modules/tenancy/application/use_cases/*` no importan Pydantic.
  - `modules/tenancy/infrastructure/agency_repository.py` extiende
    `ModuleRepository` y no llama `commit()` por su cuenta.
  - **Sin imports cruzados** desde `modules/tenancy/...` hacia
    `modules.<otro>.application` / `modules.<otro>.infrastructure`
    (verificado con grep). La hidratación cross-módulo se hace en el
    router consumiendo `uow.ingestion.sources`, `uow.publishing.connections`
    y `uow.configuration.{brand,defaults,automation}` — exactamente lo
    pedido por `docs/phase_2_operating_rules.md` §5 Feature 3.
  - El use case `inspect_agency` solo devuelve `Agency`; la hidratación
    queda en el router (`_load_agency_supporting_payloads`).
  - Payloads Pydantic en `modules/tenancy/transport/payloads/agencies.py`
    (públicos, `AdminAgencyCreatePayload` / `AdminAgencyUpdatePayload`).
  - Borrado de legacy verificado en `services/transport/http/server.py`:
    no hay `_AdminAgencyCreatePayload`, `_AdminAgencyUpdatePayload`,
    `_serialize_agency`, `_serialize_agency_summary`, `_slugify_admin`,
    `list_admin_agencies`, `create_admin_agency`, `get_admin_agency`,
    `update_admin_agency`, `delete_admin_agency`, `def create_agency`,
    `def update_agency`, `def delete_agency`. `WordPressWebhookApplication.get_agency`
    se conserva (lo siguen llamando features 4-7, líneas 1584/1698/1858/...).
  - `_serialize_wordpress_source_details` sigue presente en `server.py:3610`
    para las features 4 (acordado en operating rules §5 Feature 3).
- C4: [x]
  - Hay un test unitario por cada use case
    (`tests/unit/tenancy/test_*.py` × 5).
  - Hay un test de integración HTTP del router nuevo
    (`tests/integration/tenancy/test_admin_agencies_router.py`) que cubre
    list/create/update/delete, inspect con hidratación y colisión de slug.
  - `tests/integration/test_http_transport.py:366,374,389` siguen verdes
    contra el router nuevo (mismo path HTTP). El test legacy
    `test_admin_can_create_get_and_delete_an_agency` migró su
    verificación final a `uow.tenancy.agencies.get_by_id(...)` y eliminó
    el import `from repositories.stores.agency_store import AgencyStore`.
  - No hay `xfail` ni skip nuevos.
  - Tests usan `tests/support/postgres.py` (no mocks).
  - `pytest -q` reporta **168 passed**.
- C5: [x] No se tocó `shared/db/orm.py` ni `alembic/versions/`. Feature
  no toca schema (`progress/current.md` lo indica explícitamente).
- C6: [x] `python -m apps.api --check` y `python -m apps.worker --check`
  verdes. No se observan `print()` de debug ni TODOs sin contexto en el
  código nuevo (solo el TODO acordado en
  `_serialize_wordpress_source_details` del router de tenancy referente
  a feature 4). Estado `in_progress` correcto a la espera del cierre
  administrativo.

## Verificación

- `./init.sh` con Git Bash → **verde**, 168 passed in 62.20s.
- `python -m apps.api --check` → OK.
- `python -m apps.worker --check` → OK.
- Grep de imports cruzados desde `modules/tenancy/...` → solo
  `modules.tenancy.*` (correcto).
- Grep de `_AdminAgencyCreatePayload|_AdminAgencyUpdatePayload|_serialize_agency|_serialize_agency_summary|_slugify_admin|list_admin_agencies|create_admin_agency|get_admin_agency|update_admin_agency|delete_admin_agency`
  en `services/transport/http/server.py` → 0 coincidencias para los
  símbolos eliminados (las que aparecen son de otros sufijos:
  `delete_admin_agency_source`, `_serialize_agency_reel`, etc.).
- Grep de `def create_agency|def update_agency|def delete_agency|def list_agencies`
  en `services/transport/http/server.py` → 0 coincidencias.
- Grep de `_serialize_wordpress_source_details` en
  `services/transport/http/server.py` → presente en línea 3610
  (preservado para feature 4).
- Grep de `AgencyStore|AgencyRecord` bajo `tests/` → 0 coincidencias.
- Grep de `xfail|skip` en `tests/integration/test_http_transport.py` →
  0 coincidencias.

## Cambios Requeridos

Ninguno.
