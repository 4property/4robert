# Review — feature 4 (ingestion_routers)

**Veredicto:** APPROVED

## Checkpoints

- C1: [x] `init.sh` exit 0; harness completo (AGENTS.md, CLAUDE.md, docs/, CHECKPOINTS.md presentes).
- C2: [x] Solo feature 4 en `in_progress` (`feature_list.json:86`); el implementer no marca `done`, queda al closer.
- C3: [x]
  - Cero imports `from modules.<otro>.application` o `from modules.<otro>.infrastructure` desde `modules/ingestion/` (verificado con grep). Solo `from modules.delivery.domain import JobEnqueueRequest` (`modules/ingestion/application/use_cases/ingest_wordpress_property.py:11`), permitido.
  - `domain/` libre de SQLAlchemy.
  - `IngestionSourceRepository.create/update` cifran con Fernet via `encrypt_text(secret)` (`modules/ingestion/infrastructure/ingestion_source_repository.py:177, 208`). Sin plaintext persistido.
  - Sin código nuevo en `services/`, `application/`, `repositories/`, `core/`, `domain/`. El legacy intacto solo donde aún tiene call sites desde `server.py:543, 549, 550, 1313` (endpoint global `/v1/admin/wordpress-sources/{site_id}` que retira feature 9). Acorde con `phase_2_operating_rules.md` §2 ("Excepción única: legacy que otras features 2-8 todavía consumen NO se borra").
- C4: [x]
  - 19 unit + 10 integration tests añadidos para esta feature (`tests/unit/ingestion/test_*.py`, `tests/integration/ingestion/test_wordpress_webhook_flow.py`, `tests/integration/ingestion/test_sources_router.py`).
  - Los 4 tests legacy de webhook adaptados al router nuevo en `tests/integration/test_http_transport.py:202-282` (sin `xfail`, `grep -rn xfail tests/` devuelve cero).
  - Total verde: **197 passed in 76.88s** (baseline 168 + 29).
  - `python -m apps.api --check` y `python -m apps.worker --check` exit 0.
- C5: [x] Feature 4 NO toca schema. No se requiere migración.
- C6: [x] No hay archivos `*.tmp`, `.tmp_debug*/` ni `__pycache__/` rastreados en git status sospechosos. No se filtra `.env`.

## Foco específico

1. **Naming descriptivo (5 verbos exactos):** [OK]
   - `register_ingestion_source.py / RegisterIngestionSourceUseCase`
   - `list_ingestion_sources.py / ListIngestionSourcesUseCase`
   - `inspect_ingestion_source.py / InspectIngestionSourceUseCase`
   - `reconfigure_ingestion_source.py / ReconfigureIngestionSourceUseCase`
   - `decommission_ingestion_source.py / DecommissionIngestionSourceUseCase`
   - `ingest_wordpress_property.py / IngestWordPressPropertyUseCase`
   Cero archivos con prefijo `create/get/update/delete`. El router endpoint
   handlers también renombrados (`sources_router.py:63, 104, 124, 148, 187`).

2. **Path real preservado:** [OK]
   - `WordPressWebhookSettings.path` default `/v1/ingest/wordpress/property`
     (`modules/ingestion/transport/http/wordpress_webhook_router.py:48`).
   - `app_factory.py:139` lo cablea a `WEBHOOK_PATH` settings.
   - Tests legacy `test_http_transport.py:217, 248, 262, 286` continúan
     posteando a `/v1/ingest/wordpress/property`.

3. **HMAC fórmula byte-a-byte preservada:** [OK]
   `shared/http/webhook_signature.py:22-40` (`_build_signature_message`) replica
   exactamente la concatenación legacy `timestamp\n + site_id\n + location_id\n
   + access_token\n + raw_body`. `verify_webhook_signature` (línea 92-136)
   acepta `location_id=""` y `access_token=""` como defaults para preservar la
   compatibilidad. El router lo invoca sin pasar `location_id`/`access_token`
   (`wordpress_webhook_router.py:193-200`), por lo que la firma de WordPress
   en producción se valida idéntica a la legacy.

4. **Cadena de superseding intacta:** [OK]
   `ingest_wordpress_property.py:135-146` llama
   `uow.delivery.jobs.supersede_queued_jobs(...)` y itera sobre los event_ids
   superseded llamando `uow.delivery.webhook_events.update_event_status(...,
   status="superseded", error_message="Superseded by a newer queued job.")`
   ANTES de `create_event` (línea 148) y `enqueue_job` (línea 159).

5. **`provider_secret_bundle` exacto:** [OK]
   `ingest_wordpress_property.py:125-129`:
   ```python
   provider_secret_bundle = json.dumps(
       {"access_token": access_token, "provider": "gohighlevel"},
       ensure_ascii=False,
       sort_keys=True,
   )
   ```
   Coincide con la formula requerida en `phase_2_operating_rules.md:168-170`.
   Verificado contra los tests integration (`test_http_transport.py:238-240`,
   `test_wordpress_webhook_flow.py:72-73`) que afirman
   `bundle == {"access_token": ..., "provider": "gohighlevel"}`.

6. **Borrado legacy:** [OK]
   - `services/transport/http/security.py` borrado (`git status` muestra
     `D services/transport/http/security.py`; verificado con `ls services/transport/http/` que no lo lista).
   - `services/transport/http/server.py` ya no contiene
     `_AdminAgencySourceUpsertPayload`, `upsert_admin_agency_source`,
     `delete_admin_agency_source`, `receive_property_webhook` (grep cero).
   - El path `/v1/ingest/wordpress/property` ya no aparece en server.py.
   - Re-exports de `build_raw_payload_hash`/`is_signature_valid`/etc. también
     removidos de `services/transport/__init__.py` y
     `services/transport/http/__init__.py`.
   - **Nota:** `application/admin/wordpress_source_management.py`,
     `application/dispatch/webhook_acceptance.py` y
     `application/tenancy/resolver.py` NO se borraron — pero sí tienen call
     sites vivos en `server.py:543, 549, 550, 1313` (endpoint global
     `/v1/admin/wordpress-sources/{site_id}` y el `WebhookAcceptanceService`
     orquestado por la `WordPressWebhookApplication.runtime`). El test
     `tests/unit/test_tenancy.py` también referencia `TenantResolver`. Esto
     concuerda con `phase_2_operating_rules.md` §2 (excepción única) y con la
     decisión documentada por el implementer (`impl_4_ingestion_routers.md:80`)
     y se retira en feature 9.
   - Sin `xfail` ni compat shims: `grep -rn xfail tests/` devuelve cero.

7. **Aislamiento inter-módulo:** [OK] grep exhaustivo confirma cero
   importaciones de `modules.<otro>.application` / `modules.<otro>.infrastructure`
   en `modules/ingestion/`. Solo `modules.delivery.domain.JobEnqueueRequest`
   (permitido por `docs/architecture.md:21-23`) y travesías UoW
   (`uow.tenancy.agencies`, `uow.publishing.connections`,
   `uow.configuration.{defaults,automation,social_templates}`,
   `uow.delivery.{jobs,webhook_events}`).

8. **Cifrado del secret:** [OK]
   `IngestionSourceRepository.create` cifra con `encrypt_text(secret)`
   (`modules/ingestion/infrastructure/ingestion_source_repository.py:177`) y
   `update` solo aplica `encrypt_text` cuando `secret is not None` (líneas
   206-208). El use case `register_ingestion_source.py:81-90` y
   `reconfigure_ingestion_source.py:84-97` siempre llegan al repo con
   plaintext local que se cifra antes del INSERT/UPDATE.

9. **Tests adaptados sin `xfail`:** [OK]
   - `tests/integration/test_http_transport.py:202-282` (4 tests originales)
     reescritos contra el router nuevo, leyendo
     `uow.delivery.webhook_events.get_event` y
     `uow.delivery.jobs.get_job`, desempaquetando `provider_secret_bundle`
     con `json.loads` (línea 238).
   - `tests/integration/ingestion/test_wordpress_webhook_flow.py`: 5 tests
     (resolves+enqueue, unknown site, missing GHL, paused dispatcher,
     supersede previo).
   - `tests/integration/ingestion/test_sources_router.py`: 5 tests (bearer
     required, CRUD lifecycle, agency 404, duplicate site_id, inspect 404).
   - `tests/unit/ingestion/test_*.py`: 19 unit tests, uno por use case
     incluyendo `test_ingest_wordpress_property.py` con happy path + supersede
     + UNKNOWN_WORDPRESS_SITE + GHL_CONNECTION_NOT_FOUND.

10. **`./init.sh` verde:** [OK]
    ```
    [OK]    apps.api --check verde
    [OK]    apps.worker --check verde
    197 passed in 76.88s
    [OK]    pytest verde
    [OK]    Entorno listo.
    ```
    Conteo total: **197 passed** (168 baseline + 29 nuevos = 197 ≥ 168 + 29).

11. **CHECKPOINTS.md:** todos los boxes C1-C6 verificados arriba.

## Comentarios menores (no bloqueantes)

- `apps/api/app_factory.py:117` sigue construyendo
  `WordPressWebhookServer(...)` y luego incluye los routers nuevos sobre
  `server.app`. Es el patrón intermedio documentado en
  `explore_router_4_ingestion.md:362`. La composición canónica de feature 9
  reemplazará esta construcción.
- `tests/unit/test_tenancy.py:12` continúa importando
  `TenantResolver` legacy; consistente con la nota del implementer (no se
  borra hasta feature 9). El test sigue verde.
- `_serialize_source` en `sources_router.py:218-241` y
  `_serialize_source_with_agency` (244-270) tienen lógica duplicada de
  `config.get("site_url")`/`normalized_host` defaults; dejarse así no rompe
  contrato.

## Cambios requeridos

Ninguno. La feature está lista para cierre.
