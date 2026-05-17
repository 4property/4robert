# Arquitectura — Qué significa "hacer un buen trabajo" (`/opt/projects/4Reels-Backend`)

> Este documento es un **resumen operativo** para el agente. La fuente de
> verdad es [`ARCHITECTURE.md`](../ARCHITECTURE.md) en la raíz del proyecto.
> Si hay conflicto, gana `ARCHITECTURE.md`.

## Principios

1. **Modular monolith con worker desacoplado.**
   Dos procesos: `apps/api/` (FastAPI, HTTP-only) y `apps/worker/` (job
   dispatcher). Comparten Postgres y volúmenes de media; no se comunican
   por HTTP.

2. **Capas dentro de cada módulo.** Cada módulo bajo `modules/<bc>/` se
   divide en cuatro capas y solo cuatro:
   - `domain/` — value objects puros, sin SQLAlchemy.
   - `application/use_cases/` — un verbo-recurso por archivo.
   - `infrastructure/` — repositorios SQLAlchemy + clientes externos.
   - `transport/` — routers FastAPI + payloads Pydantic.

3. **Aislamiento entre módulos.**
   - Un módulo PUEDE importar de `shared/` y de `<otro>.domain`.
   - Un módulo NO puede importar de `<otro>.application` ni
     `<otro>.infrastructure`.
   - La composición cross-module vive en `apps/api/app_factory.py` o
     `apps/worker/runtime.py`, **nunca** dentro de un módulo.

4. **Persistencia vía Unit of Work.** Todo acceso a DB pasa por
   `shared/db/uow.DatabaseUnitOfWork`, que expone repositorios
   namespacados por módulo (`uow.tenancy.agencies`,
   `uow.ingestion.sources`, `uow.publishing.connections`, etc.).
   Repositorios extienden `shared/db/repository_base.ModuleRepository` y
   **no llaman `commit()`** por su cuenta — el UoW commitea en `__exit__`
   y rollbackea en excepción.

5. **Errores explícitos.** Las funciones que pueden fallar lanzan
   `ApplicationError` (o subclase de `shared/errors/`) con `stage`,
   `code`, `retryable`, `context`, `external_trace_id`. No devuelven
   `None` ambiguo, no propagan stack traces al usuario.

6. **Schema additivo por discriminador.** Añadir un nuevo origen de
   ingestión o un nuevo publisher es **una fila** en
   `ingestion_sources(kind=…)` o `provider_connections(provider=…)` +
   un adaptador en el módulo correspondiente. **No se añade tabla**.

7. **Secretos cifrados en reposo.** Los tokens y secrets que viajan a la
   DB van por `shared/db/security.py` (Fernet) y aterrizan en columnas
   `*.secrets_encrypted` BYTEA.

## Flujo de datos

```
WordPress / GoHighLevel
        │
        ▼
 apps/api  ──►  modules/ingestion  ──►  modules/catalog
        │                                    │
        │                                    ▼
        └──►  modules/delivery.jobs  ◄──  modules/reels (use case)
                       │
                       ▼
              apps/worker (claim FOR UPDATE SKIP LOCKED)
                       │
                       ▼
           modules/reels.application.orchestrator
                       │
            ┌──────────┴──────────┐
            ▼                     ▼
       modules/rendering    modules/publishing (adapters)
                                  │
                                  ▼
                        modules/delivery.outbox
```

## Módulos (bounded contexts)

| Módulo            | Responsable de                                                  |
|-------------------|-----------------------------------------------------------------|
| `tenancy`         | agencies + super-admin + resolución de tenant.                  |
| `ingestion`       | `ingestion_sources(kind)` + adapters (WordPress, …).            |
| `catalog`         | `properties` + `property_images`.                               |
| `reels`           | pipeline de reels + estado + `media_revisions` + scripted.      |
| `configuration`   | brand / defaults / automation / social templates / music.       |
| `publishing`      | `provider_connections(provider)` + adapters (GoHighLevel, …).   |
| `rendering`       | ffmpeg + layout + selección de fotos.                           |
| `delivery`        | jobs + outbox + dispatcher contract.                            |
| `notifications`   | email delivery (audit table, dispatcher, worker handler). Subscribes to `delivery.outbox` events of type `review_requested` (feature 27). |

## Qué NO hacer

- ❌ Importar de `services/`, `application/`, `repositories/`, `core/` o
  `domain/`. **Esos directorios no existen** — Phase 2 los eliminó por
  completo (cierre 2026-05-06). Toda la lógica vive en `apps/`,
  `modules/<bc>/` y `shared/`.
- ❌ Que un módulo importe de la `application/` o `infrastructure/` de
  otro módulo.
- ❌ Que un repositorio llame `session.commit()` directamente.
- ❌ Persistir tokens/secrets en plano. Siempre Fernet.
- ❌ Llamar al worker desde la API por HTTP. Comparten Postgres, punto.
- ❌ Añadir una tabla nueva para soportar un nuevo proveedor. Usa el
  discriminador (`kind`, `provider`).
- ❌ Mezclar lógica de dominio con SQLAlchemy en `domain/`.
- ❌ Usar `print()` para errores. Usa `shared.observability` y
  `ApplicationError`.

## Estado del refactor

Phase 1 ✅ — schema + skeleton + API/worker split + compat shims (2026-04-30).
Phase 2 ✅ — split de god-files; eliminación física de `services/`,
`application/`, `repositories/`, `core/` y `domain/` (2026-05-06).
Phase 3 ✅ — rename de URLs a `/v1/*` + lockstep con el frontend (2026-05-06).
Phase 4 ✅ — hardening del contrato live front↔back: JWT agency-scoped y
payloads Pydantic estrictos (2026-05-07).

**Sin fase activa.** El repo está en modo mantenimiento: solo hotfixes o
features explícitamente añadidas y aprobadas. Backlog candidato a Phase 5
en [`phase_4_operating_rules.md`](phase_4_operating_rules.md) §3.

Ver [`REFACTOR_STATUS.md`](../REFACTOR_STATUS.md) para el detalle histórico.
