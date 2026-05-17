# Review — feature 38 (db_backed_webhook_secrets)

- **Reviewer:** Claude (reviewer)
- **Fecha:** 2026-05-16
- **Veredicto:** **APPROVED**

## Resumen

El implementer cumple el alcance estricto: refactoriza
`POST /v1/ingest/wordpress/property` para resolver el secret HMAC desde
`ingestion_sources.secrets_encrypted` (Fernet) primero, cae a
`WEBHOOK_SITE_SECRETS` con `logger.warning` después, y devuelve `None`
(→ 401 `INVALID_WEBHOOK_CREDENTIALS`) si ninguno aparece. No toca
schema, no toca migraciones, no toca docs de contrato. La baseline de
`./init.sh` se mantiene: 1040 passed / 3 failed (los 3 baseline flakes
documentados).

## Checkpoints

- **C1** [x] Arnés intacto. `./init.sh` verde (excluyendo baseline
  flakes `test_http_surface_contract.py` + 2 de
  `test_http_transport.py`, mismos que en el report del implementer).
- **C2** [x] Feature 38 sigue en `in_progress` (NO marcado `done`).
  Sólo una feature activa.
- **C3** [x] Arquitectura respetada:
  - `modules/ingestion/transport/http/wordpress_webhook_router.py:32`
    importa `shared.db.security.decrypt_text` (shared, no cross-module).
  - `_resolve_expected_secret` (líneas 67-102) recibe el UoW por
    inyección y delega el lookup en
    `uow.ingestion.sources.get_by_kind_external_id(...)` (repo
    existente, sin alias inventados).
  - `modules/ingestion/domain/ingestion_source.py:28` añade
    `secrets_encrypted: bytes | None = None` al dataclass `frozen+slots`.
    Sigue siendo `domain/` puro (sin SQLAlchemy).
  - `modules/ingestion/infrastructure/ingestion_source_repository.py:46-60`
    propaga el blob al dataclass; sigue extendiendo `ModuleRepository`
    y no llama `commit()` (`grep` verificado, 0 hits).
  - Secret cifrado: persistencia y descifrado pasan por
    `shared.db.security` (Fernet). No hay plaintext en ningún lado.
- **C4** [x] Verificación real:
  - 4 tests unit nuevos en
    `tests/unit/ingestion/test_wordpress_webhook_secret_resolution.py`
    cubren los 4 ramales del decision tree (DB-hit, DB-null→env,
    todo None, sin row→env). Patch quirúrgico de `decrypt_text`,
    `caplog` validado.
  - 4 tests integration nuevos en
    `tests/integration/ingestion/test_wordpress_webhook_flow.py`
    (DB happy, wrong sig 401, env fallback con warning capturable,
    2 sites misma agency). Todos usan `tests/support/postgres.py`
    (`temporary_postgres_schema`, `seed_tenant`, `seed_provider_connection`)
    — no se mockea Postgres.
  - Los 6 tests preexistentes del archivo siguen verdes (10/10).
  - `.venv/bin/python -m apps.api --check` y
    `.venv/bin/python -m apps.worker --check` exit 0 (re-verificado
    por el reviewer, no sólo confiando en el report).
- **C5** [x] Schema/migraciones coherentes:
  - `shared/db/orm.py` NO tocado por esta feature (verificado con
    `find -newer modules/ingestion/domain/ingestion_source.py`).
  - `alembic/versions/` sin archivos nuevos por feature 38
    (verificado con `find -newer ...`; la columna
    `ingestion_sources.secrets_encrypted` ya existía desde el schema
    inicial).
  - Por tanto no aplican `alembic upgrade head` / `downgrade -1`.
- **C6** [x] Cierre de sesión:
  - 0 archivos temporales (`*.tmp`, `.tmp_debug*`, `__pycache__`
    sueltos) en el patchset de feature 38.
  - 0 `print()`, `TODO`, `FIXME`, `breakpoint` en los 5 archivos
    tocados (`grep` verificado).
  - `feature_list.json` mantiene feature 38 en `in_progress`. El cierre
    a `done` lo hará el leader tras este APPROVED.

## Verificación reproducida por el reviewer

| Comando | Resultado |
|---|---|
| `pytest tests/unit/ingestion/test_wordpress_webhook_secret_resolution.py` | 4 passed |
| `pytest tests/integration/ingestion/test_wordpress_webhook_flow.py` | 10 passed (6 existentes + 4 nuevos) |
| `python -m apps.api --check` | exit 0 |
| `python -m apps.worker --check` | exit 0 |
| `./init.sh` | 1040 passed, 3 failed (baseline preservada) |

## Reglas duras — re-chequeo del bloque de exclusión

| Regla | Estado |
|---|---|
| NO tocar `modules/reels/` | OK (mtime previa a feature 38) |
| NO tocar `modules/rendering/` | OK |
| NO tocar `shared/db/orm.py` | OK (mtime 0 cambios tras feature 38) |
| NO tocar `alembic/` (sin migración nueva) | OK (0 archivos nuevos tras feature 38) |
| NO tocar `docs/API.md`, `docs/http_surface.md`, `docs/openapi.json` | OK |
| NO tocar `ProvisionWordPressSourceUseCase`, `wordpress_sources_router.py`, `sources_router.py` | OK |
| NO tocar `settings/` (sólo lectura) | OK (`WEBHOOK_SITE_SECRETS` sigue siendo fallback) |
| NO marcar `done` en `feature_list.json` | OK (sigue `in_progress`) |
| Rama `settings.security_disabled` intacta | OK (línea 217) |
| Body del 401 (`INVALID_WEBHOOK_CREDENTIALS` + hint + details) preservado byte-a-byte | OK (líneas 235-244) |

## Decisiones del implementer revisadas

1. **Exposición de `secrets_encrypted` en el domain dataclass**
   (`ingestion_source.py:28`) — Aceptable. El spec literalmente pedía
   "El registro retornado incluye `secrets_encrypted: bytes | None`".
   El campo se añade como opcional con `default=None`, no rompe
   instancias existentes (verificado: las 5 creaciones manuales en
   tests no pasan el campo, todas heredan el default; sólo
   `_row_to_source` lo setea). Patrón consistente con
   `ProviderConnectionWithSecrets` en `modules/publishing/`.

2. **UoW corto sólo para el lookup**
   (`wordpress_webhook_router.py:218-224`) — Correcto. El `with
   unit_of_work_factory()` se cierra antes de la rama 401, evitando
   mantener una transacción abierta durante el render del error. El
   UoW principal del use case se abre en línea 297 ya con el secret
   resuelto.

3. **`logger.warning` cuando se usa env**
   (`wordpress_webhook_router.py:96-100`) — El mensaje
   `"Webhook secret resolution: using legacy env secret for site_id=%s; ..."`
   es capturable con
   `caplog.at_level(logging.WARNING,
   logger="modules.ingestion.transport.http.wordpress_webhook_router")`.
   Verificado en
   `test_webhook_fallbacks_to_env_secret_with_warning`.

4. **Side effect del implementer en
   `tests/integration/ingestion/test_wordpress_webhook_flow.py:228`**
   (añadir `workspace_dir=workspace_dir` al `seed_tenant` del test
   preexistente `quiet_hours`) — Cambio defensivo necesario para que
   `seed_tenant` hidrate los assets locales de música seedeada (feature
   23). No es expansión de scope, es un fix de regresión inevitable; el
   test seguía pasando antes porque `workspace_dir=None` hace el seed
   skip silencioso, pero ahora con el orden seguro queda explícito.

## Follow-ups no bloqueantes

1. **(Mantenimiento)** Tras una ventana de varias semanas con cero
   warnings `"legacy env secret"` en producción, abrir feature para
   retirar `WEBHOOK_SITE_SECRETS` de `settings/security.py` y de
   `.env.example`. No bloquea cierre de esta feature: la coexistencia
   está cubierta y documentada.

2. **(Limpieza)** El mensaje del hint del 401 sigue diciendo:
   `"Add the site to WEBHOOK_SITE_SECRETS on the deployed service
   and restart it."` (línea 230 del router). Cuando feature 38 cierre y
   la documentación del admin CRUD esté publicada, conviene actualizar
   ese hint a algo como
   `"Provision the site via PUT /v1/admin/wordpress-sources/{site_id} or
   add it to WEBHOOK_SITE_SECRETS (legacy)."` Es change cosmético, no
   bloquea.

3. **(Cobertura)** Considerar un test unit adicional para el caso
   `decrypt_text` devuelve `""` (cifrado corrupto / Fernet expired) —
   el helper actual maneja ese caso correctamente (`if decoded:`
   en línea 92 cae al fallback), pero sólo está probado
   end-to-end implícitamente. No bloquea: el rama está cubierta por
   inspección de código y los 4 unit tests más los 4 integration tests
   ya verifican los caminos importantes.

## Veredicto final

**APPROVED.** El leader puede ejecutar el cierre de la feature 38
(marcar `done` en `feature_list.json`, mover el bloque de
`progress/current.md` a `progress/history.md`).
