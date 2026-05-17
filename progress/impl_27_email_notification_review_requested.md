# Implementer report — feature 27 `email_notification_review_requested`

- **Fecha:** 2026-05-15
- **Agente:** Claude (implementer subagente, lanzado por el leader)
- **Estado feature_list.json:** `in_progress` (NO se marca `done`; lo hace el reviewer)

## Resumen

Cablea la infraestructura de email entregada por #26 al evento real
`review_requested` del outbox. La feature aporta:

1. **Outbox subscriber** nuevo (`apps/worker/outbox_subscriber.py`).
   No existía relay del outbox; este es el primero. Polea
   `outbox_events` con `status='pending' AND event_type='...'` usando
   `SELECT … FOR UPDATE SKIP LOCKED`. Multi-worker safe.
2. **Use case** `DispatchReviewRequestedEmailUseCase` en
   `modules/notifications/application/use_cases/` que:
   - Carga `defaults.settings['automation.reviewEmails']`.
   - Normaliza CSV-legacy o `list[str]` → tupla lowercased,
     deduplicada, regex-validada (`shared/email/validators.py`).
   - Throttle 60 s por (agency, recipient) vía
     `EmailNotificationRepository.find_recent_sent`.
   - Decide `event_kind`: `review_requested` (primera vez) vs
     `review_requested_resent` (re-render — preserva UNIQUE).
   - Resuelve `agency_name` (de `agencies`), `property_title` y
     `property_address` (de `properties.raw_json`).
   - INSERT pending N filas en `email_notifications` + ENQUEUE 1 job
     `email_send` con shape rico documentado en `docs/API.md` §7c.
   - Marca outbox como `dispatched` (o no-op si nadie pasa el filtro).
3. **Job handler** `SendEmailJobHandler` registrado para `email_send`
   en `apps/worker/runtime.py`. Renderiza subject + plain + HTML,
   manda con el `EmailSender` inyectado, y propaga el
   `provider_message_id` a las N filas vía `mark_sent`. On exception
   marca todas como `failed` y re-raise.
4. **Templates** en `assets/email/templates/`:
   - `review_requested.txt` (plain, canónico).
   - `review_requested.html` (HTML opcional con botón "Review reel").
   Renderer `EmailTemplateRenderer` simple (`str.format` + `html.escape`
   para HTML); zero deps externas.
5. **URL builder** `shared.email.url_builder.build_reel_editor_url` que
   construye `{FRONTEND_BASE_URL}/reels?site_id=&property_id=`.
6. **`OutboxRepository`** extendido con `mark_status(...)` (status
   genérico para `dispatched`/`failed`/`processing`) y
   `claim_pending_event(event_type)` (FOR UPDATE SKIP LOCKED).
7. **`apps/worker/main.py`** arranca el subscriber junto al
   dispatcher; `--check` reporta también los `outbox_events` types.

Sin migración (la tabla `email_notifications` ya existe). Cambios al
schema: ninguno. `publish_reel.py` intacto.

## Archivos creados / modificados

### Nuevos

| Ruta                                                                                              | Tipo |
|---------------------------------------------------------------------------------------------------|------|
| `shared/email/validators.py`                                                                      | Email regex + `normalise_review_emails(CSV ∪ list[str])` |
| `shared/email/url_builder.py`                                                                     | `build_reel_editor_url(...)` |
| `shared/email/templates.py`                                                                       | `EmailTemplateRenderer` (file-cached, `str.format`-based) |
| `assets/email/templates/review_requested.txt`                                                     | Plain text body |
| `assets/email/templates/review_requested.html`                                                    | HTML body con botón |
| `modules/notifications/application/__init__.py`                                                   | Package init |
| `modules/notifications/application/use_cases/__init__.py`                                         | Re-exports |
| `modules/notifications/application/use_cases/dispatch_review_requested_email.py`                  | Outbox handler (use case) |
| `modules/notifications/application/use_cases/send_email_job_handler.py`                           | `email_send` worker handler |
| `apps/worker/outbox_subscriber.py`                                                                | Loop nuevo (no existía relay) |
| `docs/email_notifications.md`                                                                     | Runbook ops |
| `tests/unit/notifications/test_review_emails_normaliser.py`                                       | Unit (normaliser + regex) |
| `tests/unit/notifications/test_url_builder.py`                                                    | Unit (URL builder) |
| `tests/unit/notifications/test_template_renderer.py`                                              | Unit (templates + HTML escape) |
| `tests/integration/notifications/test_review_requested_flow.py`                                   | Integration E2E (4 tests: happy path, CSV legacy, invalid filter, empty no-op) |
| `tests/integration/notifications/test_review_requested_throttle.py`                               | Integration (throttle 60s) |
| `tests/integration/notifications/test_review_requested_resent.py`                                 | Integration (resent kind) |
| `tests/integration/notifications/test_email_send_handler_failure.py`                              | Integration (SMTP fallo) |

### Modificados

| Ruta                                                              | Motivo |
|-------------------------------------------------------------------|--------|
| `shared/email/__init__.py`                                        | Re-exporta validators / url_builder / templates. |
| `modules/delivery/infrastructure/outbox_repository.py`            | `mark_status(...)` + `claim_pending_event(...)` con FOR UPDATE SKIP LOCKED. |
| `apps/worker/runtime.py`                                          | Registra handler `email_send` + helper `build_default_outbox_subscriber`. |
| `apps/worker/main.py`                                             | Arranca subscriber junto al dispatcher; `--check` reporta event types. |
| `docs/API.md`                                                     | Sección 7c `Notifications — review_requested flow (feature 27)`. |
| `docs/architecture.md`                                            | Añade `notifications` al inventario de bounded contexts. |

## Decisiones tomadas

1. **Outbox subscriber nuevo, no inline**: la docstring del
   `OutboxRepository` mencionaba un "relay" pero **no existía**. Construí
   `apps/worker/outbox_subscriber.py` como segundo loop dentro del
   proceso `apps.worker`. Razones:
   - Mantiene `publish_reel.py` intacto (event-sourcing puro).
   - El loop usa `claim_pending_event` (FOR UPDATE SKIP LOCKED) + transición
     `'pending' → 'processing' → 'dispatched'/'failed'` para soportar
     múltiples workers sin double-delivery.
   - Se inyecta tipo de evento → handler, así crecer a futuros eventos
     (e.g. `publish_completed` → email "tu reel ya está vivo") es
     `subscriber.register_handler("publish_completed", ...)`.
2. **Synthetic `webhook_events` row por job email_send**: la cola de
   jobs exige `event_id` (`JobORM` FK semántica) y el worker runtime
   hace `update_event_status(event_id, ...)` sobre `webhook_events`.
   Para no romper ese contrato cuando el origen es el outbox (no un
   webhook), el dispatcher crea una fila `webhook_events` con
   `source_kind='notification'` y `raw_payload_hash=''`. Trade-off
   aceptado: rompe la pureza semántica de `webhook_events`, pero no
   altera el dispatcher principal — alternativa hubiera sido refactorizar
   `runtime.py` para hacer el `update_event_status` opcional, scope
   demasiado grande para esta feature.
3. **`event_kind` resolver lee `list_by_agency`** (limit 200) y filtra
   en Python por slot. Alternativa hubiera sido un nuevo método
   especializado en el repositorio. El volumen previsto (200 dispatches
   recientes por agencia, raros eventos `review_requested`) hace que
   este recorrido sea constante y barato; documentado el porqué inline.
4. **Multi-recipient = 1 envío + N filas** (decisión §D.3 del design
   doc). El handler usa el mismo `EmailMessage.to=tuple(recipients)`
   en una sola llamada a `EmailSender.send`. Los N filas reciben el
   mismo `provider_message_id` (None en `ConsoleEmailSender`,
   `<Message-ID>` en `SmtpEmailSender`).
5. **HTML escape vía `html.escape`** (stdlib), no jinja. Cumple
   el requisito explícito "NO mete jinja2 ni librerías externas".
   El renderer cachea el source raw del template; los valores del
   context se escapan SOLO para HTML, no para plain (este es el
   patrón estándar y matchea lo que pide el plan de la feature).
6. **`property_title` / `property_address` se resuelven en el
   dispatcher** desde `properties.raw_json`, con fallback a payload
   del outbox event. Razón: `publish_reel.py` no incluye esos campos
   en su `_build_workflow_payload` y este implementer no debe tocar
   `publish_reel.py` (scope #27 limita al subscriber + handler).
   `_extract_address` toma `property_area_label, property_county_label`
   como en el render (`frame_composition.py`).

## Tests — output

```
$ .venv/bin/python -m pytest tests/unit/notifications/ tests/integration/notifications/ -q
.......................................................                  [100%]
55 passed in 23.05s
```

Desglose (28 nuevos sobre la baseline de #26):

- Unit (3 archivos nuevos): 41 tests pasan (10 normaliser + 6 URL +
  7 templates + 18 pre-existentes de #26).
- Integration (4 archivos nuevos): 14 tests pasan (4 flow + 1
  throttle + 1 resent + 1 failure + 7 pre-existentes de #26).

## Readiness checks

```
$ .venv/bin/python -m apps.api --check
[…] API READINESS REPORT — RUNTIME READY: Yes
exit=0

$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render
outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
exit=0
```

El `--check` ahora reporta también los `outbox_events` types
registrados (`review_requested`).

## `bash ./init.sh`

```
[OK] apps.api --check verde
[OK] apps.worker --check verde
[OK] pytest verde
3 failed, 897 passed, 14 warnings in 397.30s
```

Los 3 fallos son los **baseline** conocidos
(`test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
+ los 2 en `test_http_transport.py`). Pre-existentes; documentados en
`progress/current.md` y en el informe de #26. NO son introducidos por
esta feature. 869 baseline + 28 nuevos = 897.

## Migración

**No aplica.** La tabla `email_notifications` se creó en `20260514_0007`
(feature 26). Esta feature solo añade business logic encima.

## Self-check

- ✅ `publish_reel.py` no se ha tocado (verificado: `git diff
  modules/reels/application/use_cases/publish_reel.py` vacío).
- ✅ Layer rule: `modules/notifications/` no importa de
  `modules/reels/application/` ni `modules/configuration/application/`.
  Solo toca repositorios (`uow.configuration.defaults.get`,
  `uow.notifications.emails.*`, `uow.delivery.outbox.mark_status`,
  `uow.delivery.jobs.enqueue_job`) y dominios (`OutboxEvent`,
  `JobEnqueueRequest`).
- ✅ Capa `shared/email/{validators,url_builder,templates}.py` sin
  imports de `settings/` ni `modules/` (templates importa solo
  stdlib).
- ✅ Repositorio extiende `ModuleRepository`; ningún
  `session.commit()` dentro del repo (la UoW commitea).
- ✅ Worker registra `email_send` junto a `reel_publish` y
  `scripted_render`. `outbox_subscriber.OutboxSubscriber` corre en
  thread daemon y se para gracefully con SIGTERM.
- ✅ Tests cubren los 10 acceptance criteria del feature_list.json:
  flow E2E (1+2+3), resent (4), throttle (5), CSV legacy + dedup
  + invalid filter (6+7+8), failure path (9), template render con
  link al frontend (10).
- ✅ `pytest tests/unit/notifications/ tests/integration/notifications/` 100%.
- ✅ `init.sh` exit 0 con la baseline conocida (3 fallos
  pre-existentes), 897 passed.

## Riesgos / follow-ups

1. **`property_title` / `property_address` desde `raw_json`** depende
   de que `properties` esté sembrada antes del trigger. En el flujo
   real eso lo garantiza `ingest_property_into_reel.py` (paso 1 del
   pipeline). En tests no sembrar la propiedad resulta en strings
   vacíos en el email — comportamiento documentado y aceptado para el
   no-op path (`test_empty_review_emails_results_in_no_op_dispatched`).
2. **Throttle hardcoded a 60s**: hoy no es env-var. Si producto pide
   tunearlo, exponerlo como `EMAIL_THROTTLE_SECONDS` y cablearlo en
   `build_default_outbox_subscriber`.
3. **Webhook event sintético**: el flow crea filas en `webhook_events`
   con `source_kind='notification'`. Si en el futuro algún query asume
   `source_kind='wordpress'`, hay que extenderlo. Hoy sólo
   `webhook_events.update_event_status(event_id)` toca esa fila — sin
   filtros — así que el riesgo es bajo.
4. **`tests/integration/notifications/test_review_requested_resent.py`
   usa `mark_sent` con `sent_at` 120s en el pasado**: si el reviewer
   estima frágil esta inyección de timestamp, sustituirlo por
   `throttle_seconds=0` en una instancia ad-hoc del use case.
5. **Frontend feature 26 (chip editor) ya cerró** (según el contexto
   del leader). El back acepta `list[str]` directamente y mantiene
   compat con string CSV — no debería romper a clientes legacy.

## Cómo integré el outbox subscriber (resumen)

- **No existía relay del outbox previo.** El docstring del
  `OutboxRepository` decía "relay polls pending rows" pero no había
  ningún caller fuera de las consultas `list_events` y los `add_event`
  inline en `publish_reel.py` + `persist_local_artifacts.py`.
- Construí `apps/worker/outbox_subscriber.py` como segundo loop:
  - Constructor recibe `OutboxSubscriberSettings(poll_interval_seconds,
    database_locator, base_dir, shutdown_timeout_seconds)`.
  - API pública: `register_handler(event_type, callable)`,
    `process_once()` (drena una pasada — útil en tests),
    `start()/stop()`, `run_forever()`.
  - Concurrencia: thread daemon con `threading.Event` para señalizar
    parada; SIGINT/SIGTERM lo paran limpiamente.
  - Multi-worker safe vía `claim_pending_event(...)` que delega en
    `OutboxRepository.claim_pending_event` (FOR UPDATE SKIP LOCKED).
  - Estado del outbox event:
    `pending → processing (al claim) → dispatched (success) | failed (exception)`.
- Wiring en `apps.worker.runtime.build_default_outbox_subscriber`
  registra `review_requested → DispatchReviewRequestedEmailUseCase`.
- `apps.worker.main` arranca el subscriber antes del dispatcher y lo
  para en el `finally`. `--check` reporta `outbox_events=...` además
  de `kinds=...`.

Pendiente: revisión por `reviewer`. Yo NO marco `done` en
`feature_list.json` — ese paso es del reviewer.
