# Implementer report — Feature 38 `db_backed_webhook_secrets`

- **Inicio:** 2026-05-16
- **Agente:** Claude (implementer)
- **Toca schema?:** No. Cero DDL nuevo (la columna `ingestion_sources.secrets_encrypted` ya existía).
- **Toca alembic?:** No. Cero migración.

## Resumen

El webhook `POST /v1/ingest/wordpress/property` ahora resuelve el secret
HMAC en este orden: (1) `ingestion_sources.secrets_encrypted` descifrado
con `shared.db.security.decrypt_text`; (2) `WEBHOOK_SITE_SECRETS` (env)
como fallback legacy con `logger.warning`; (3) `None` → 401
`INVALID_WEBHOOK_CREDENTIALS` (idéntica rama que antes). Con esto una
agencia puede recibir webhooks de N sitios WordPress provisionados vía
`PUT /v1/admin/wordpress-sources/{site_id}` sin tocar la env ni
reiniciar el servicio.

## Archivos modificados / creados

| Archivo | Tipo | Cambio |
|---------|------|--------|
| `modules/ingestion/transport/http/wordpress_webhook_router.py` | router | Nuevo helper `_resolve_expected_secret(uow, site_id, env_site_secrets, logger)` y sustitución de la línea 179 por una llamada al helper dentro de un `unit_of_work_factory()` corto y cerrado antes del 401. Import de `shared.db.security.decrypt_text`. |
| `modules/ingestion/domain/ingestion_source.py` | domain | Añadido campo opcional `secrets_encrypted: bytes | None = None` al dataclass `IngestionSource` (default-friendly: no rompe los call sites que crean instancias sin pasarlo). |
| `modules/ingestion/infrastructure/ingestion_source_repository.py` | infra | `_row_to_source` propaga ahora `secrets_encrypted=bytes(row.secrets_encrypted)` cuando hay valor, `None` cuando no. `has_secret` sigue calculándose igual. |
| `tests/integration/ingestion/test_wordpress_webhook_flow.py` | test | +4 tests extendidos (no archivo nuevo): `test_webhook_accepts_with_db_persisted_secret`, `test_webhook_rejects_wrong_signature_for_db_secret`, `test_webhook_fallbacks_to_env_secret_with_warning`, `test_webhook_accepts_two_distinct_sites_for_same_agency`. Helpers nuevos `_post_signed_webhook`, `_clear_ingestion_source_secret`, `_add_secondary_wordpress_source`, `_build_secure_client`. |
| `tests/unit/ingestion/test_wordpress_webhook_secret_resolution.py` | test (nuevo) | 4 casos unit con `caplog`: DB-only, DB-null→env, ninguno, sin row→env. |

## Resumen del refactor del helper

```python
def _resolve_expected_secret(
    *,
    uow: DatabaseUnitOfWork,
    site_id: str,
    env_site_secrets: dict[str, str],
    logger: logging.Logger,
) -> str | None:
    record = None
    if uow.ingestion is not None:
        record = uow.ingestion.sources.get_by_kind_external_id(
            kind="wordpress", external_id=site_id
        )
    if record is not None and record.secrets_encrypted is not None:
        decoded = decrypt_text(record.secrets_encrypted)
        if decoded:
            return decoded
    env_secret = env_site_secrets.get(site_id)
    if env_secret:
        logger.warning(
            "Webhook secret resolution: using legacy env secret for site_id=%s; "
            "provision secret in DB to retire this fallback",
            site_id,
        )
        return env_secret
    return None
```

Llamada desde el handler:

```python
if not settings.security_disabled:
    with unit_of_work_factory() as secret_uow:
        expected_secret = _resolve_expected_secret(
            uow=secret_uow,
            site_id=site_id,
            env_site_secrets=settings.site_secrets,
            logger=logger,
        )
    if expected_secret is None:
        # 401 INVALID_WEBHOOK_CREDENTIALS — body, code, hint, details intactos
```

## Decisiones tomadas

- **Dónde se abre el uow para el lookup**: se abre un `unit_of_work_factory()`
  corto exclusivamente para resolver el secret y se cierra ANTES de la rama
  de 401 (no se mantiene una sesión abierta cubriendo la respuesta de
  error). El UoW principal del use case (`ingest_wordpress_property.execute`)
  se sigue abriendo después, ya con el secret resuelto, exactamente como
  antes.
- **Exposición de `secrets_encrypted` en el domain**: el spec dice
  literalmente "El registro retornado incluye `secrets_encrypted: bytes |
  None`" y "NO inventes alias en el repo. Reusa
  `IngestionSourceRepository.get_by_kind_external_id`". Pero el dataclass
  `IngestionSource` actual solo exponía `has_secret: bool`. Decisión: añadir
  el campo `secrets_encrypted: bytes | None = None` con default-None al
  dataclass `IngestionSource` (frozen+slots). Es la mínima extensión
  compatible: ninguno de los call sites existentes (8 sitios) pasa el
  campo, todos heredan el default; ningún test rompe. Patrón consistente
  con cómo `ProviderConnectionWithSecrets` ya expone secretos descifrados
  en `modules/publishing/`.
- **Cómo se siembra el secret en los tests**: para el happy path (`...with_db_persisted_secret`)
  reusé `seed_tenant`, que ya escribe `encrypt_text("test-secret")` en la
  columna (línea 223 de `tests/support/postgres.py`); el test simplemente
  firma con ese secret. Para el caso de fallback (`...with_warning`) hago
  `UPDATE ingestion_sources SET secrets_encrypted = NULL` después del
  seed via SQL directo (helper `_clear_ingestion_source_secret`). Para el
  caso multi-WP (`...two_distinct_sites...`) añado una segunda fila WP
  directamente con SQL (helper `_add_secondary_wordpress_source`) reusando
  `encrypt_text` para mantener la encripción consistente con
  `ProvisionWordPressSourceUseCase`.
- **No se tocaron** `apps/api/app_factory.py`, `settings/`, `alembic/`,
  `shared/db/orm.py`, `modules/reels/`, `modules/rendering/`,
  `docs/API.md`, `docs/http_surface.md`, `docs/openapi.json`,
  `ProvisionWordPressSourceUseCase`, ni `wordpress_sources_router.py`,
  conforme al scope estricto y a las reglas anti-colisión con feature 37.

## Verificación

### 1. `.venv/bin/python -m apps.api --check`

```
                             API READINESS REPORT
                             RUNTIME READY: Yes
                             PRODUCTION READY: No
                             ...
                             FFMPEG: /usr/bin/ffmpeg
```

### 2. `.venv/bin/python -m apps.worker --check`

```
INFO     Worker --check OK: kinds=email_send, reel_publish, scripted_render
         outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
```

### 3. `.venv/bin/python -m pytest tests/unit/ingestion/test_wordpress_webhook_secret_resolution.py -q`

```
....                                                                     [100%]
4 passed in 1.04s
```

### 4. `.venv/bin/python -m pytest tests/integration/ingestion/test_wordpress_webhook_flow.py -q`

```
..........                                                               [100%]
10 passed in 15.62s
```

(6 existentes + 4 nuevos = 10, todos verdes.)

### 5. `bash ./init.sh`

```
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 1040 passed, 14 warnings in 548.03s
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Baseline preservada: los 3 fallos conocidos (`test_http_surface_contract.py`
y los dos de `test_http_transport.py`) siguen siendo exactamente los mismos
y no crecen. **1040 passed = 1032 (baseline post-feature-37) + 8 nuevos**
(4 unit + 4 integration).

## Conteo de tests

- **Nuevos:** 8 (4 unit en `test_wordpress_webhook_secret_resolution.py`
  + 4 integration en `test_wordpress_webhook_flow.py`).
- **Existentes en `test_wordpress_webhook_flow.py` que siguen verdes:** 6
  (happy path, unknown site, missing GHL, paused dispatcher, supersede,
  quiet hours).
- **Total file `test_wordpress_webhook_flow.py`:** 10 passed.
- **Total file `test_wordpress_webhook_secret_resolution.py`:** 4 passed.

## Estado

- `feature_list.json` → feature 38 en `in_progress`. No marcado `done`
  por el implementer (espera reviewer).
- `progress/current.md` → bloque "Feature 38 — db_backed_webhook_secrets
  (Claude implementer)" añadido.

## Notas para el reviewer

- El helper `_resolve_expected_secret` es testeado a 4 niveles unit con mocks
  (DB-only, DB-null→env, ninguno, sin row→env) y end-to-end con DB real en
  el integration suite. El warning estructurado es capturable con
  `caplog.at_level(logging.WARNING, logger="modules.ingestion.transport.http.wordpress_webhook_router")`.
- El UoW se abre y se cierra exclusivamente para el lookup (no se mantiene
  abierta durante el `return json_error(401, ...)`).
- El cambio del dataclass `IngestionSource` añade un campo opcional al
  final con default `None`. Verificado con `grep` que las 8 creaciones
  existentes (5 tests + repo + 2 specs de feature 37) siguen funcionando
  sin pasarlo. Las que sí lo pasan (a través del repo) son sólo `_row_to_source`.
- El comportamiento de la rama 401 y la del `settings.security_disabled`
  está intacto; sólo cambia la fuente del secret. El response body 202 y
  el shape de error no se tocan.
