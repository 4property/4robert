# Convenciones de código (`4reels back/`)

> Homogeneidad extrema. La IA predice mejor cuando el repositorio se parece
> a sí mismo en todas partes.

## Estilo Python

- **Versión:** Python 3.11+ (sintaxis `list[str]` y `X | None` permitidas).
- **Formato:** PEP 8. Líneas máximo 100 caracteres.
- **Imports:** stdlib primero, terceros después, locales al final. Una
  línea por módulo. Nada de `import *`.
- **Strings:** comillas dobles `"..."` siempre. Comillas simples solo
  para escapar comillas dobles dentro.
- **f-strings** para interpolación. Nada de `.format()` ni `%`.
- **Type hints obligatorios** en firmas públicas. En cuerpos de funciones,
  solo cuando el tipo no es evidente.

## Nombres

| Tipo                    | Convención        | Ejemplo                |
|-------------------------|-------------------|------------------------|
| Módulos                 | `snake_case`      | `reel_query.py`        |
| Clases                  | `PascalCase`      | `ReelStateRepository`  |
| Funciones / variables   | `snake_case`      | `claim_next_ready_job` |
| Constantes              | `UPPER_SNAKE`     | `DEFAULT_QUEUE_NAME`   |
| Privadas                | prefijo `_`       | `_atomic_write`        |
| Use cases (archivo)     | `<verbo>_<recurso>.py` | `publish_reel.py` |
| Use cases (clase)       | `<Verbo><Recurso>UseCase` | `PublishReelUseCase` |
| Repositorios            | `<Aggregate>Repository` | `IngestionSourceRepository` |
| Routers                 | `<recurso>_router.py` | `agencies_router.py` |

## Estructura de archivo

Cada archivo bajo `apps/`, `modules/`, `shared/` empieza con:

```python
"""Una línea describiendo el propósito del módulo."""
from __future__ import annotations

# stdlib
import json
from datetime import datetime, timezone

# terceros
from sqlalchemy.orm import Session
from pydantic import BaseModel

# locales
from shared.db import DatabaseUnitOfWork
from modules.tenancy.domain import Agency
```

## Tests

- Estructura: `tests/{unit,integration,support}/`.
- Un archivo de test por unidad lógica: `test_<recurso>_<verbo>.py` o
  `test_<recurso>_flow.py` para integración.
- Cada test usa `tempfile.TemporaryDirectory()` para artefactos en disco
  y los helpers de `tests/support/postgres.py` para DB.
- **No mockees Postgres.** Usa `seed_tenant`, `seed_provider_connection`,
  `seed_ingestion_source`, etc.
- Nombres descriptivos:
  `test_publish_reel_marks_outbox_completed_when_ghl_returns_2xx`.

## Manejo de errores

```python
from shared.errors import ApplicationError

class ReelPublishFailed(ApplicationError):
    """Falla de publicación a un provider."""

# Lanzar con context completo
raise ReelPublishFailed(
    stage="publish",
    code="PROVIDER_5XX",
    retryable=True,
    context={"provider": "gohighlevel", "reel_id": str(reel_id)},
)
```

- El transport (router FastAPI) captura `ApplicationError`, lo mapea a
  HTTP status según `code`, y devuelve un JSON estructurado.
- Nunca propaga stack traces al usuario.
- Nada de `print()` para errores. Usa `logging.getLogger(__name__)` con
  los filtros de `shared/observability/`.

## Repositorios y UoW

```python
# Correcto
with DatabaseUnitOfWork() as uow:
    agency = uow.tenancy.agencies.get_by_slug("acme")
    source = uow.ingestion.sources.get_by_kind_external_id(
        kind="wordpress", external_id="acme.example.com",
    )
# uow.__exit__ commitea (o rollbackea si se levantó excepción)
```

- **Nunca** `session.commit()` dentro de un repositorio.
- **Nunca** abras un UoW dentro de un use case que ya recibe uno por
  parámetro. La regla: el use case recibe `uow`, no lo crea.
- Cross-aggregate JOIN reads viven en `<bc>.queries.*`, no en
  repositorios de aggregate (ver `uow.reels.queries`).

## Pydantic v2

- Esquemas de transport viven en `modules/<bc>/transport/payloads/`.
- Reusa `BaseModel` con `model_config = ConfigDict(frozen=True)` cuando
  representen value objects.
- Usa `Field(...)` con `description` en payloads expuestos por la API
  (alimentan OpenAPI).

## Comentarios

Por defecto **no** se escriben. Solo se permiten cuando explican un
*por qué* no obvio (workaround documentado, invariante sutil, hack para
un comportamiento de FastAPI/SQLAlchemy). Los nombres deben hacer el
resto. **Prohibido**: comentarios que describen *qué* hace la función,
referencias a tickets ("added for #123"), o "// removed code".

## Migraciones Alembic

- Una migración por feature que toque schema. Mensaje:
  `<feature>__<acción_corta>` (snake_case).
- `upgrade()` y `downgrade()` deben ser reversibles. Si no lo son,
  documenta el motivo en un comentario al inicio del archivo.
- Antes de commitear: `alembic upgrade head` y `alembic downgrade -1`
  deben funcionar limpio sobre una DB vacía.
- Renames van con `op.alter_column(..., new_column_name=...)`, no con
  drop+create (preserva los datos).

## Auth en `/v1/admin/*`

- Todo handler bajo `/v1/admin/*` debe llamar `authorize_admin_request(request,
  admin_access_policy)` como primera línea y devolver el `JSONResponse` que
  retorne (early return). El patrón canónico vive en
  `modules/configuration/transport/http/brand_router.py:59-61`.
- El helper acepta dos tipos de bearer:
  - **Super-admin** — `ADMIN_API_TOKEN` (`secrets.compare_digest`); ámbito
    global, todas las rutas.
  - **Agency JWT** — HS256 firmado con `ADMIN_AGENCY_TOKEN_SECRET`, emitido
    por `POST /v1/sessions/gohighlevel/session`. Solo válido en
    `/v1/admin/agencies/{agency_id}/...` cuyo `agency_id` coincida con el
    claim `agency_id` del token.
- Mismo error code (`INVALID_ADMIN_TOKEN`) para firma mala y token caducado:
  el cliente no debe distinguir.
- Para escenarios cross-tenant que se rechazan: 403 con
  `AGENCY_TOKEN_AGENCY_MISMATCH` (otra agencia) o
  `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE` (rutas globales tipo
  `/v1/admin/agencies` listado o `/v1/admin/wordpress-sources`). Ambos casos
  van a `log_persistent_event("admin.authorization_failed", reason=...)` con
  el `reason` correspondiente.
- Issue/decode del JWT vive en `apps/api/agency_token.py`. Las excepciones
  `AgencyTokenExpired`/`AgencyTokenInvalid` se mantienen dentro del módulo
  (no se exportan PyJWT exceptions hacia routers).

## Contrato HTTP front-back

- La superficie HTTP canonica del backend se genera desde la app real con
  `python scripts/generate_http_surface.py --write`.
- El comando actualiza `docs/http_surface.md` y `docs/openapi.json`; ejecutalo
  cada vez que anadas, renombres o elimines rutas FastAPI.
- `tests/integration/test_http_surface_contract.py` lee
  `FRONTEND_REPO_ROOT` (default: `C:/Users/4pm/Desktop/4reels/4reels front`) y
  compara cada `apiRequest(...)` del front contra las rutas reales del back.
- Si el front introduce un placeholder nuevo en una URL, amplia
  `PLACEHOLDER_NAMES` en ese test en el mismo cambio que introduce la llamada.
- Si una llamada usa un helper nuevo para construir paths, anade su normalizador
  al test; no skipees expresiones que no pueda entender.
