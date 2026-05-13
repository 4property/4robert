# Review — feature 8 (pinterest_social_platform_support)

**Veredicto:** APPROVED

Reviewer: Claude (Opus 4.7 — sub-agent reviewer)
Fecha: 2026-05-12
Implementer: Codex (no dejó `progress/impl_8_pinterest_social_platform_support.md`; la bitácora vive en `progress/current.md` líneas 53-61).

## Resumen ejecutivo

El implementer añade Pinterest como destino social reconocido por el contrato
backend de plataformas: registro de plataformas (con aliases `pin`, `pins`),
defaults de publicación, perfil agregado del reel, payload GHL específico
(`pinterestPostDetails`), y se documenta en `docs/API.md`. La política de
publicación heredada (cap 500 chars, `post`, `reel_video`/`poster_image`) se
aplica sin código adicional al estar canalizada por `get_platform_config()`.
No hay cambios de schema (consistente con `feature_list.json` → `"schema": "No"`).

Verificación completa: focal tests verdes (14 passed), contract test cross-repo
verde con `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend`, `apps.api --check`
y `apps.worker --check` exit 0. `bash ./init.sh` termina verde para el arnés
salvo 3 fallos pytest preexistentes documentados (ver §"Pre-existentes" abajo)
que NO son introducidos por esta feature y que el usuario indicó expresamente
no bloquean este APPROVE.

## Cumplimiento del acceptance (feature_list.json id 8)

| # | Criterio | Estado | Evidencia |
|---|---|---|---|
| 1 | El registro de plataformas incluye pinterest y normaliza alias simples | OK | `modules/publishing/infrastructure/adapters/platforms/pinterest.py` líneas 11-23 (`platform="pinterest"`, `aliases=("pin", "pins")`); registrado en `registry.py:33`. Test `tests/unit/publishing/test_platform_registry.py::test_pinterest_is_registered_as_a_supported_gohighlevel_platform` verifica `get_platform_config("pin")` → pinterest y `normalise_platform_name("Pins") == "pinterest"`. |
| 2 | `SUPPORTED_GOHIGHLEVEL_PLATFORMS` contiene `pinterest` | OK | `modules/publishing/infrastructure/adapters/gohighlevel/normalization.py:15` construye el frozenset desde `list_supported_platforms()`; al añadir pinterest al registro queda incluido automáticamente. Asserción explícita en `tests/unit/publishing/test_platform_registry.py:19`. |
| 3 | Defaults de plataformas incluyen pinterest en defaults, aggregated reel profile y admin agencies | OK | `modules/configuration/infrastructure/defaults_repository.py:60-68`, `modules/configuration/transport/http/defaults_router.py:39`, `modules/configuration/application/use_cases/read_aggregated_reel_profile.py:40`, `modules/tenancy/transport/http/admin_agencies_router.py:40`. Ejemplos OpenAPI actualizados en `transport/payloads/defaults.py:24,50` y `payloads/reel_profile.py:27`. |
| 4 | `GET /v1/admin/agencies/{agency_id}/social-accounts` serializa cuentas Pinterest | OK | El router pasa el `SocialAccount` raw devuelto por GHL — no hay allowlist por plataforma. Verificado por `tests/integration/publishing/test_social_accounts_router.py::test_returns_items_when_upstream_succeeds` (líneas 99-130 del diff) que añade `pin-1`/Brand Pinterest/platform=pinterest, espera `count == 2` y `items[1]["platform"] == "pinterest"`. |
| 5 | La política de publicación permite pinterest con media requerido | OK | `pinterest.py:14-21` define `default_artifact_kind="reel_video"`, `allowed_artifact_kinds=("reel_video", "poster_image")`, `allowed_social_post_types=("post",)`, `max_caption_length=500`. Test `test_pinterest_policy_enforces_caption_limit` cubre el límite de caption; `test_pinterest_gohighlevel_payload_includes_title_and_link` cubre el payload GHL (`pinterestPostDetails` con `title` truncado a 100 chars y `link`). El media requerido lo aplica el flujo existente vía `default_artifact_kind`. |
| 6 | Tests unit/integration relevantes pasan | OK | 14 passed in 10.73s (unit + integration focales); 1 passed in 1.59s (contract cross-repo). |

## Checkpoints (`CHECKPOINTS.md` / `docs/conventions.md`)

- **C1 Capas (domain/application/infrastructure/transport):** [x]
  El cambio se concentra en `infrastructure/adapters/platforms/pinterest.py` (nuevo) y `registry.py` (alta), no hay imports cross-layer indebidos. `read_aggregated_reel_profile.py` (application) sólo añade un literal a una tupla constante interna; sigue sin importar Pydantic. `transport/payloads/*.py` sólo cambia ejemplos OpenAPI. `transport/http/*_router.py` sólo añade literal en tupla local.
- **C2 Aislamiento entre módulos:** [x]
  No hay imports nuevos entre módulos. `modules.publishing.infrastructure.adapters.platforms.pinterest` consume solo `shared.py` y `models.py` del mismo paquete.
- **C3 Convenciones de nombre:** [x]
  Sigue el patrón de `facebook.py`/`linkedin.py`/`youtube.py`/`google_business_profile.py`. La función helper se llama `build_pinterest_gohighlevel_payload` (snake_case + verb prefix) consistente con `build_youtube_gohighlevel_payload`.
- **C4 Errores y observabilidad:** [x]
  No introduce errores nuevos; la validación va por `validate_platform_publish_request` que ya está integrada con `shared.errors`.
- **C5 Repositorios y unit-of-work:** [x]
  Sin cambios en repos. `defaults_repository.py` solo cambia el default fallback de plataformas (lista in-memory), no toca `session.commit()`.
- **C6 Schema / migraciones:** [x]
  `feature_list.json` declara `"schema": "No"`. Verificado con `git status -s alembic/ shared/db/` y `git diff -- shared/db/orm.py alembic/` → 0 cambios. **No se requiere migración.**
- **C7 Secretos cifrados (Fernet):** [x] N/A — no se persisten secretos.
- **C8 Tests con `tests/support/postgres.py`:** [x]
  Los tests de integración añadidos/extendidos siguen el patrón existente (`tests/integration/publishing/test_social_accounts_router.py`, `tests/integration/configuration/test_defaults_router.py`).

## Verificación ejecutada

1. `bash ./init.sh` → readiness OK + 3 fallos pytest preexistentes documentados, exit 0 del script. (205.48s)
2. `.venv/bin/python -m pytest tests/unit/publishing/test_platform_registry.py tests/unit/publishing/test_inspect_agency_social_accounts.py tests/integration/publishing/test_social_accounts_router.py tests/integration/configuration/test_defaults_router.py -q` → **14 passed in 10.73s**.
3. `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend .venv/bin/python -m pytest tests/integration/test_http_surface_contract.py -q` → **1 passed in 1.59s**.
4. `.venv/bin/python -m apps.api --check` → **exit 0** (Runtime ready).
5. `.venv/bin/python -m apps.worker --check` → **exit 0** (kinds=reel_publish,scripted_render).

## Fallos pre-existentes confirmados (NO bloquean este APPROVE)

Coinciden exactamente con los 3 documentados en `progress/current.md` líneas 58-61:

1. `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes` — falla sin `FRONTEND_REPO_ROOT` porque el default apunta a una ruta Windows (`c:/Users/4pm/Desktop/4reels/4reels front/`) inexistente en este host Linux. Con `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend` pasa.
2. `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads` — el test espera payload mínimo en `/health` pero el endpoint actual incluye `configured_worker_count`.
3. `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state` — mismo problema de payload extendido en `/health`.

Ninguno de los tres toca el código de Pinterest. Por la regla explícita del leader (registrada en este briefing), **no son razón para CHANGES_REQUESTED**. Se sugiere abrir issue separado para alinear los tests de health con el shape actual o decidir si el shape del endpoint es el correcto.

## Fuera de scope (cambios sin commit en el repo, no relacionados con Pinterest)

El working tree mezcla cambios de varias sesiones previas. **Estos NO bloquean el APPROVE** pero quedan listados para visibilidad del leader:

### CORS private-network para flujo HighLevel iframe local (2026-05-11)
- `apps/api/app_factory.py`, `apps/api/main.py`, `apps/worker/main.py`, `apps/api/health_router.py`
- `tests/integration/test_http_transport.py` (test nuevo `test_cors_allows_private_network_preflight_for_local_ghl_embed`)
- `tests/integration/apps_api/test_health_router.py`
- `tests/test_logging.py`, `tests/unit/apps_api/test_agency_token.py`
- `shared/observability/persistent_log.py`
- `ARCHITECTURE.md`, `README.md`

### Fix de `aggregate_status` para no contar `skipped_missing_account` como fracaso (feature 7-related o pre-existente)
- `modules/publishing/infrastructure/adapters/gohighlevel/models.py` líneas 349-365 (lógica `effective_outcomes` y nuevo `aggregate_status`)
- Documentado en `docs/API.md` sección "Multi-platform publish aggregation" (líneas añadidas)

### Cambios alrededor del workflow de aprobación / reels admin
- `modules/reels/application/orchestrator.py`, `modules/reels/application/use_cases/regenerate_reel.py`, `modules/reels/transport/http/admin_reels_router.py`
- `modules/delivery/infrastructure/job_repository.py`
- `tests/integration/reels/test_admin_reels_router.py`, `tests/unit/reels/test_regenerate_reel.py`, `tests/unit/reels/_uow_stubs.py`
- `tests/unit/reels/test_build_property_media_job.py` (untracked)
- `tests/unit/publishing/test_multi_publish_result.py` (untracked)
- `docs/API.md` sección "Reel approval and publish status" (líneas añadidas)

### Otros archivos sin commit no relacionados
- `modules/configuration/transport/http/social_templates_router.py`, `modules/configuration/transport/payloads/social_templates.py` (cambios mínimos no-Pinterest)
- `modules/rendering/infrastructure/ai_photo_selection/prompting.py` (1 línea)
- `feature_list.json` (entradas 7-12 añadidas en sesiones previas)
- `progress/impl_ghl_probe_fb_gbp.md` (untracked, sesión feature 7)
- `LICENSE`, `main.py`, `deploy/backups/`, `deploy/migrate_legacy_schema_to_20260501.py`, `deploy/rocky-linux/*.service` (artefactos de onboarding del runtime, ver `MEMORY.md`)

**Recomendación al leader:** abrir un commit-fence con sólo los archivos de la feature 8 antes de marcar `done` para mantener el repo trivialmente verificable según la regla de Phase 4. Los demás cambios deberían cerrar features 7/CORS/aggregate_status por separado, cada uno con su `impl_*.md` y `review_*.md`.

## Cambios requeridos

Ninguno. APPROVED.
