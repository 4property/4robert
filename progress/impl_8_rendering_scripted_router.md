# Impl — Feature 8 `rendering_scripted_router`

## Resumen

`POST /videos/scripted/render` se mueve de la god-class
`WordPressWebhookServer` a un router per-módulo bajo
`modules/rendering/transport/`. La semántica cambia de **síncrono 201**
(devuelve `{render_id, video_path, manifest_path, ...}`) a
**asíncrono 202** (devuelve `{status: "accepted", job_id, event_id,
site_id, source_property_id}`). El worker consume el job
`kind="scripted_render"` mediante el handler ya cableado en
`apps/worker/runtime.py:271-278` — esta feature **no toca el worker**.

Es un cambio de contrato HTTP confirmado en
`docs/phase_2_operating_rules.md` §5 Feature 8.

## Archivos creados

- `modules/rendering/transport/__init__.py` — paquete.
- `modules/rendering/transport/http/__init__.py` — paquete.
- `modules/rendering/transport/payloads/__init__.py` — paquete.
- `modules/rendering/application/use_cases/__init__.py` — paquete.
- `modules/rendering/transport/payloads/scripted.py` — payload Pydantic
  `ScriptedRenderResponse(status="accepted", job_id, event_id, site_id,
  source_property_id)`.
- `modules/rendering/transport/http/scripted_router.py` — router
  FastAPI: valida `Content-Type`/`Content-Length`/`max_payload_bytes`,
  parsea el body como dict, valida `site_id` y `source_property_id`
  eager, calcula `raw_payload_hash = sha256(raw_body).hexdigest()`,
  delega al use case y devuelve 202. Mapea `ResourceNotFoundError`→404,
  `ValidationError`→400, `ApplicationError`→500.
- `modules/rendering/application/use_cases/enqueue_scripted_render.py`
  — `EnqueueScriptedRenderUseCase`. Resolución de tenant inline:
  `uow.ingestion.sources.get_by_kind_external_id(kind="wordpress",
  external_id=site_id)` → 404 `UNKNOWN_WORDPRESS_SITE` si no existe / no
  está activa; luego `uow.tenancy.agencies.get_by_id(source.agency_id)`.
  Crea `webhook_events` con `source_kind="scripted_api"` y encola
  `JobEnqueueRequest(kind="scripted_render", payload=<body>,
  publish_context={}, provider_secret_bundle="",
  max_attempts=WORKER_JOB_MAX_ATTEMPTS)`.
- `tests/integration/rendering/test_scripted_router.py` — 6 tests:
  enqueue feliz + verificación de `webhook_events.source_kind` con SQL
  directo; `UNKNOWN_WORDPRESS_SITE`; falta `site_id`; falta
  `source_property_id`; body no-JSON; Content-Type incorrecto.
- `tests/unit/rendering/test_enqueue_scripted_render.py` — 5 tests:
  enqueue feliz; site desconocido; source pausada; site_id en blanco;
  agency huérfana.

## Archivos modificados

- `apps/api/app_factory.py` — import de `create_scripted_router` y
  `server.app.include_router(create_scripted_router(...))` justo antes
  del wordpress webhook router.
- `services/transport/http/server.py` — borrado (a) el handler
  `render_scripted_video` (≈115 LoC, decorador + closure), (b) el
  método `WordPressWebhookApplication.render_scripted_video`, (c) el
  atributo `self.scripted_video_service = ScriptedVideoRenderService(...)`
  que ya quedaba huérfano, (d) el import
  `from application.scripted_render.service import ScriptedVideoRenderService`.
- `services/transport/http/openapi_docs.py` — borrado
  `_decorate_scripted_render_operation` (≈130 LoC) y los helpers
  huérfanos `_scripted_render_request_schema`/`_settings_schema`/
  `_slide_image_path_schema`/`_slide_sources_schema`/`_response_schema`/
  `_request_example`/`_settings_example`. La llamada a
  `_decorate_scripted_render_operation(schema)` también se eliminó de
  `_enrich_openapi_schema`. La etiqueta `Video Rendering` se actualizó:
  ahora describe el render asíncrono. FastAPI auto-genera la doc del
  endpoint nuevo desde `ScriptedRenderResponse` + `summary`/`description`
  del decorador.
- `feature_list.json` — feature 8 marcada `in_progress` (no `done`).

## Verificaciones

- `python -m apps.api --check` → exit 0 (`API READINESS REPORT: RUNTIME
  READY: Yes`).
- `python -m apps.worker --check` → exit 0 (`Worker --check OK:
  kinds=reel_publish, scripted_render`).
- `pytest -q` → **331 passed in 161.25s**. Baseline pre-feature ≥320,
  sumamos 11 tests (6 integración + 5 unit) → 320 + 11 = 331. ✅
- `./init.sh` → todas las secciones [OK] (incluido el warning
  informativo sobre archivos legacy modificados, esperado: hemos
  borrado código en `services/transport/http/{server.py,openapi_docs.py}`).

## Decisiones no obvias

- **Sin importar `RenderScriptedVideoUseCase` desde `modules.reels`.**
  El use case nuevo solo encola el job; el handler del worker carga el
  bridge legacy lazy. Esto respeta la regla "rendering no importa
  reels.application" y deja que la feature 14 sustituya el bridge sin
  fricciones.
- **`source_kind="scripted_api"`.** Verificado en
  `alembic/versions/20260501_0001_initial_schema.py:486` que
  `webhook_events.source_kind` es `sa.Text()` sin CHECK constraint, así
  que se acepta el valor nuevo sin migración.
- **Sin Pydantic estricto del body.** Per `phase_2_operating_rules.md`
  §5 Feature 8 + explore §6, el manifiesto es semi-abierto y la
  validación full la hace el worker al ejecutar. El router solo valida
  eager `site_id` (str no vacío) y `source_property_id` (int) — campos
  necesarios para el routing del job.
- **Cambio sync→async en el contrato.** Los consumidores que parseaban
  `render_id`, `video_path`, `manifest_path`, `request_manifest_path`
  rompen. Confirmado por el usuario y documentado aquí.

## Estado

- `feature_list.json[id=8].status` = `in_progress` (NO marcado `done`).
- `progress/current.md` actualizado.
- Pendiente: revisión por reviewer.
