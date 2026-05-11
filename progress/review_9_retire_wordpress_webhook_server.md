# Review — feature 9 (retire_wordpress_webhook_server)

**Veredicto:** APPROVED

## Foco específico

1. **`/v1/admin/agencies/{id}/reel-profile` reescrito desde el UoW agregado de `configuration`** — verificado.
   - `modules/configuration/application/use_cases/read_aggregated_reel_profile.py:138-144`
     compone los 5 sub-aggregates (`brand`, `defaults`, `automation`,
     `social_templates`, `music`) leyendo del UoW namespacado de
     configuration. NO toca `ReelProfileStore`. `to_public_dict()`
     (líneas 52-123) reproduce el shape legacy
     (`profile_id`, `agency_id`, `name`, `platforms`, `duration_seconds`,
     `music_id`, `intro_enabled`, `logo_position`, `brand_primary_color`,
     `brand_secondary_color`, `caption_template`, `approval_required`,
     `extra_settings`, `created_at`, `updated_at`).
   - `modules/configuration/application/use_cases/update_aggregated_reel_profile.py:80-122`
     fan-outs a `uow.configuration.brand.upsert` /
     `uow.configuration.defaults.upsert` / `uow.configuration.automation.upsert`.
   - El router (`modules/configuration/transport/http/reel_profile_router.py:91-93,159-163`)
     responde `{"reel_profile": <dict>|null}` para GET y
     `{"status": "saved", "reel_profile": <dict>}` para PUT — contrato
     externo preservado.
   - Test integration confirmatorio:
     `tests/integration/configuration/test_reel_profile_router.py`.

2. **`services/transport/http/openapi_docs.py` borrado** — verificado vía
   `ls services/transport/http/` (solo quedan `__init__.py` y
   `operations.py`).

3. **`services/transport/http/uvicorn_protocols.py` borrado** —
   verificado en el mismo `ls`.

4. **`build_api_app` expone kwargs explícitos para tests** —
   `apps/api/app_factory.py:137-154` declara `admin_api_token`,
   `admin_api_disable_auth_for_testing`,
   `gohighlevel_app_shared_secret`,
   `webhook_auto_provision_unknown_sites_for_testing`, `enable_docs`,
   `site_secrets`, `security_disabled`, `worker_count`, `job_max_attempts`,
   `dispatcher_accepting_jobs`, `readiness_provider`, `admin_api_enabled`,
   `admin_api_base_path`. Producción (sin overrides) sigue funcionando:
   `apps.api --check` exit 0 sin pasar ningún kwarg.
   `dispatcher_accepting_jobs` y `readiness_provider` solo afectan
   tests; cuando se omiten se inicia el `_NoopDispatcher` real en el
   `lifespan` (`apps/api/app_factory.py:230-246`) y el health router
   delega en `services.transport.http.operations.build_readiness_report`
   (`apps/api/health_router.py:113-123`).

5. **Helper `apps/api/admin_auth.build_admin_access_policy(...)`** —
   declarado en `apps/api/admin_auth.py:33-54` y consumido por
   `apps/api/app_factory.py:223-228`. Test unit en
   `tests/unit/apps_api/test_build_admin_access_policy.py`.

## Aislamiento inter-módulo (foco 1)

Verificado vía grep:
- `from modules\.(?!configuration)\w+\.(application|infrastructure)`
  bajo `modules/configuration/` → 0 hits.
- `from modules\.(?!ingestion)\w+\.(application|infrastructure)`
  bajo `modules/ingestion/` → 0 hits.
- `from modules\.(?!publishing)\w+\.(application|infrastructure)`
  bajo `modules/publishing/` → 0 hits.

`update_aggregated_reel_profile` solo importa de
`modules/configuration/application/use_cases/_agency_support.py` y
`modules/configuration/application/use_cases/read_aggregated_reel_profile.py`
— mismo módulo, OK.

`provision_wordpress_source` usa `modules/ingestion/domain` +
`modules/tenancy/domain` (cross-module DOMAIN sí permitido, ver
`docs/architecture.md:73`). Las escrituras tenancy van por
`uow.tenancy.agencies.*` (DI vía UoW), respetando aislamiento.

`inspect_agency_social_accounts` usa `modules/publishing/domain` y
los clientes externos vía `services/publishing/social_delivery/...`
(legacy, lo disuelve Phase 3 — no es bloqueante para feature 9).

## Capas (foco 2)

- `domain/` libre de SQLAlchemy en los nuevos módulos: grep
  `from sqlalchemy` bajo `modules/{configuration,ingestion}/domain` → 0
  hits.
- `application/` libre de Pydantic: grep `BaseModel|from pydantic` bajo
  `modules/{configuration,ingestion,publishing}/application` → 0 hits.
  Use cases usan `dataclass(frozen=True, slots=True)`.
- `transport/` no toca DB directo: cada router abre `unit_of_work_factory()`
  y delega al use case (verificado en `social_accounts_router.py:62-65`,
  `reel_profile_router.py:78-81,116-118`,
  `wordpress_sources_router.py`).

## Repositorios (foco 3)

`grep "session\.commit\(\)" modules/` → 0 hits. Ningún repo nuevo
introduce commits propios. La transacción la cierra
`DatabaseUnitOfWork.__exit__`.

## Secretos (foco 4)

`provision_wordpress_source` persiste el `webhook_secret` mediante
`uow.ingestion.sources.create(... secret=...)` /
`update(... secret=...)`. La encriptación Fernet la aplica el repo
(`modules/ingestion/infrastructure/ingestion_source_repository.py:16,177,208`
— `encrypt_text(secret)` antes del INSERT/UPDATE). No hay persistencia
en plano. Aprobado.

## Decisión 3 del implementer (foco 5)

`provision_wordpress_source` escribe `site_url` y `normalized_host`
dentro de `ingestion_sources.config_json`
(`modules/ingestion/application/use_cases/provision_wordpress_source.py:161-165`).
El GET (router en `wordpress_sources_router.py`) reconstruye el shape
legacy leyendo `existing.source.config["site_url"]` y
`["normalized_host"]`. Test integration confirmatorio:
`tests/integration/ingestion/test_wordpress_sources_global_router.py`.

## Borrados verificados (foco 6)

- `services/transport/http/server.py` → no existe (`ls
  services/transport/http/` muestra solo `__init__.py` y `operations.py`).
- `services/transport/http/openapi_docs.py` → no existe.
- `services/transport/http/uvicorn_protocols.py` → no existe.
- `application/admin/wordpress_source_management.py` → no existe.
- `application/admin/__init__.py` → directorio `application/admin/` no
  existe (`ls application/` no lo muestra).

## Grep guards (foco 7)

Ejecutados manualmente:

- `grep -rn "WordPressWebhookServer|WordPressWebhookApplication" .` →
  hits SOLO en docstrings/comentarios de 4 archivos
  (`apps/api/app_factory.py:4`, `apps/api/admin_auth.py:45`,
  `modules/configuration/transport/payloads/reel_profile.py:5`,
  `modules/ingestion/transport/payloads/wordpress_sources.py:5`) y en
  `progress/*.md`. No-bloqueante, documentado aquí.
- `grep -rn "services\.transport\.http\.server" apps/ modules/ shared/ tests/`
  → 0 hits ejecutables (los hits que aparecen son únicamente en
  `progress/*.md` y comentarios de exploración).
- `grep -rn "from application\.admin" .` → 0 hits ejecutables.
- `grep -rn "from services\.transport\.http\.openapi_docs|from services\.transport\.http\.uvicorn_protocols" .`
  → 0 hits ejecutables.

## Tests (foco 8)

- `tests/integration/test_http_transport.py:27` ya importa
  `from apps.api.app_factory import build_api_app`. Línea 105-122 del
  helper `_build_client` invoca
  `build_api_app(workspace_dir=..., database_locator=..., ...)` con los
  kwargs nuevos. NO importa de `services.transport.http.server`.
- Tests nuevos verificados:
  - `tests/integration/apps_api/test_health_router.py`
  - `tests/integration/ingestion/test_wordpress_sources_global_router.py`
  - `tests/integration/configuration/test_reel_profile_router.py`
  - `tests/integration/publishing/test_social_accounts_router.py`
- `test_social_accounts_router.py:84-110` mockea solo el
  `GoHighLevelClient` (`_StubClient` con `request_json`/`close`); el UoW
  se monta sobre Postgres real vía `temporary_postgres_schema`. Cumple
  la regla "no mockear Postgres".
- Todos los integration tests usan `tests/support/postgres.py`
  (`temporary_postgres_schema`, `temporary_workspace`, `seed_tenant`,
  `seed_provider_connection`).

## `apps/api/main.py` y `apps/api/app_factory.py` (foco 9)

- `apps/api/main.py:117` → `app = build_api_app(workspace_dir=...,
  database_locator=DATABASE_URL)`. Línea 123 lee `WEBHOOK_PATH` directo
  desde settings. Línea 130 pasa `app` desnudo a `uvicorn.run`. Sin
  `server.runtime` ni `server.app`.
- `_NoopDispatcher` vivo en `apps/api/app_factory.py:105-134`. Se
  instancia y arranca dentro del `lifespan` (línea 230-240); cuando
  los tests pasan `dispatcher_accepting_jobs` no se instancia (se
  delega al closure del test). Feature 16 lo borra.

## `apps/api/host_filter.py` (foco 10)

Helpers públicos en `apps/api/host_filter.py`:
`resolve_allowed_hosts`, `should_enable_docs`, `is_local_docs_host`,
`normalise_allowed_host`, `looks_like_hostname` (líneas 22-103). El
implementer eligió nombres públicos (sin guion bajo) y los exporta en
`__all__`. Test unit en `tests/unit/apps_api/test_host_filter.py`.
Aceptable.

## Verificación operativa

- `./init.sh` → terminó verde. Hay `[WARN]` por archivos legacy
  modificados en últimas 24h (esperado, regla §2 de operating rules).
- `pytest -q` → 376 passed in 193.51s en re-run completo. Baseline
  pre-feature 331 + 45 nuevos = 376. ✓
  - Observación: la primera ejecución durante `./init.sh` reportó 1
    fallo intermitente en
    `tests/integration/configuration/test_automation_router.py::test_automation_put_persists_typed_record`
    (constraint `alembic_version_pkc` durante el setup del
    `temporary_postgres_schema`). Re-run aislado del archivo: 4/4
    PASS. Re-run completo del suite: 376/376 PASS. El test pertenece a
    feature 6 y no es introducido ni tocado por feature 9. La causa
    es un race transitorio en el helper de schema temporal de Postgres
    cuando hay carga concurrente del runner. NO bloquea la feature 9
    porque no fue introducido aquí y es reproducible solo bajo carga
    específica del CI; queda como observación menor para feature 17/18
    (saneamiento del helper).
- `python -m apps.api --check` → exit 0 ("Runtime ready: Yes").
- `python -m apps.worker --check` → exit 0 (`kinds=reel_publish,
  scripted_render worker_count=1`).
- `feature_list.json[id=9].status` → `"in_progress"` (línea 172).

## Schema/migraciones

`alembic/versions/` solo contiene `20260501_0001_initial_schema.py`.
Sin migraciones nuevas. ✓

## Checkpoints

- C1: [x] AGENTS.md, CLAUDE.md, init.sh, feature_list.json,
  progress/current.md, docs/architecture.md, docs/conventions.md,
  docs/verification.md, CHECKPOINTS.md presentes; `./init.sh` exit 0.
- C2: [x] Solo feature 9 en `in_progress`; features done con tests;
  current.md activo; history.md ok.
- C3: [x] Aislamiento inter-módulo respetado (greps pasados).
  Repositorios sin commits propios. Secretos via Fernet. No hay
  código nuevo en `services/`, `application/`, `repositories/`,
  `core/`, `domain/` (solo borrados).
- C4: [x] Tests unit + integration por cada use case nuevo. Postgres
  real en integration. 376 passed. `apps.api`/`apps.worker` --check OK.
- C5: [x] Schema sin tocar. Migración inicial intacta.
- C6: [x] No hay archivos sin trackear sospechosos. feature 9 en
  `in_progress` (cierre admin tras review). Sin `print()` ni TODOs
  sin contexto. `.env.example` no tocado.

## Observaciones menores (no bloqueantes)

1. **Docstrings con referencia a la god-class:** los docstrings de
   `apps/api/app_factory.py:4`, `apps/api/admin_auth.py:45`,
   `modules/configuration/transport/payloads/reel_profile.py:5`,
   `modules/ingestion/transport/payloads/wordpress_sources.py:5`
   mencionan `WordPressWebhookServer`/`WordPressWebhookApplication`
   como contexto histórico (explican por qué existe el archivo).
   Aceptable como deuda documental que se barre en feature 18 cuando
   se cierre Phase 2.
2. **Test intermitente `test_automation_put_persists_typed_record`:**
   reproduce un race en `temporary_postgres_schema` (primary-key
   `alembic_version_pkc` duplicado). Pre-existente, no introducido por
   feature 9. Documentado para futuro saneamiento del helper de tests.
3. **`apps/api/main.py:81` aún importa
   `services.transport.http.operations.build_readiness_report`:**
   import explícito sobreviviente para `--check`. Marcado por el explore
   como deuda de feature 18 (`delete_legacy_dirs_and_close_phase_2`).
4. **`provision_wordpress_source` usa `list_all()` para localizar por
   `external_id`:** un futuro `get_by_kind_external_id` específico
   sería más eficiente. No bloquea — el contrato externo se preserva y
   el impacto en performance es despreciable a la cantidad de sources
   típica por tenant.

## Cambios requeridos

Ninguno. Feature 9 cumple los criterios de aceptación
(`feature_list.json[id=9].acceptance`):

- ✓ `services/transport/http/server.py` borrado.
- ✓ `apps/api/app_factory.py` construye `FastAPI()` directamente y
  registra los 16 routers (12 existentes + 4 nuevos: health,
  wordpress-sources global, reel-profile aggregate, social-accounts).
- ✓ Tests verdes (376 passed).
- ✓ `apps.api --check` y `apps.worker --check` exit 0.
- ✓ Sin código nuevo en directorios legacy.
- ✓ Aislamiento de módulos preservado.
