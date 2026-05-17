# Reviewer report — feature 27 `email_notification_review_requested`

- **Fecha:** 2026-05-15
- **Reviewer:** Claude (reviewer subagente, lanzado por el leader)
- **Veredicto:** **APPROVED**
- **Implementer report:** `progress/impl_27_email_notification_review_requested.md`
- **Diseño base:** `progress/design_email_notifications_and_brand_customisation.md` §A + §D

## 1. Resumen del veredicto

Wiring completo del pipeline `review_requested` end-to-end: outbox subscriber
nuevo en `apps/worker/outbox_subscriber.py` (primer relay real del outbox en
el repo), `DispatchReviewRequestedEmailUseCase` con normalización, throttle y
resolución de event_kind, `SendEmailJobHandler` registrado en el dispatcher
para `email_send`, y templates plain + HTML con renderer minimal sin deps
externas. `publish_reel.py` intacto (0 líneas de diff). HOTFIX de Codex en
`modules/rendering/infrastructure/ffmpeg/` intacto. Layer rule respetada en
`shared/email/`. Tests específicos (55) y suite global (897 passed + 3
baseline known fails) verdes.

## 2. Workaround `webhook_events` sintético: aceptable / requiere refactor

**Aceptable, pero documentado como follow-up.**

El dispatcher inserta una fila en `webhook_events` con
`source_kind='notification'` por cada job `email_send` encolado, para que el
`JobDispatcher._process_next_job` pueda hacer `update_event_status(event_id,
...)` sin romper la semántica actual del runtime.

Razones por las que NO se bloquea el cierre:

1. **Ningún consumer filtra por `source_kind`**: `grep` confirma que solo
   `webhook_event_repository.create_event` lo escribe; ninguna query lo usa
   en WHERE. El valor es puramente etiqueta de auditoría.
2. **Refactor alternativo (hacer `update_event_status` opcional en el
   runtime) está fuera de scope**: tocaría el dispatcher principal, que
   procesa también `reel_publish` y `scripted_render`. Es un cambio que
   merece su propia feature.
3. **El trade-off está documentado explícitamente** en el implementer
   report §"Decisiones tomadas" y en el docstring del use case (líneas
   265-270 de `dispatch_review_requested_email.py`).

**Recomendación follow-up (no bloqueante)**: en una feature futura,
desacoplar `webhook_events` del runtime del worker. Opciones:
(a) introducir una columna `job_origin` distinta en `jobs` con
`update_event_status` opcional según origen;
(b) extraer el callback de "marcar evento finalizado" como dependencia
inyectada del dispatcher, con un no-op para jobs de origen `outbox`.

## 3. Checks ejecutados

### 3.1 `bash ./init.sh`

```
[OK]    apps.api --check verde
[OK]    apps.worker --check verde
3 failed, 897 passed, 14 warnings in 395.40s (0:06:35)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Los 3 baseline fails:
- `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
- `tests/integration/test_http_transport.py::test_health_endpoints_include_paused_dispatcher_state`
- `tests/integration/test_http_transport.py::test_health_endpoints_return_minimal_payloads`

Idénticos al baseline reportado por el implementer (#26 y #27), sin
regresión.

### 3.2 Suite específica notifications

```
$ .venv/bin/python -m pytest tests/integration/notifications/ tests/unit/notifications/ -q
.......................................................                  [100%]
55 passed in 23.17s
```

### 3.3 Readiness checks

```
$ .venv/bin/python -m apps.api --check          → exit 0
$ .venv/bin/python -m apps.worker --check       → exit 0
  Worker --check OK: kinds=email_send, reel_publish, scripted_render
  outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
```

El `--check` ahora reporta también los `outbox_events` registrados, en
línea con lo prometido por el implementer.

## 4. Acceptance criteria — verificación

| #  | Criterio del feature_list.json                                                                                       | Cubierto por |
|----|----------------------------------------------------------------------------------------------------------------------|--------------|
| 1  | 2 destinatarios → 2 filas pending + 1 job `email_send` + 2 sent con mismo `provider_message_id`                       | `test_full_review_requested_pipeline_marks_two_rows_sent` |
| 2  | Re-render → `event_kind='review_requested_resent'`                                                                    | `test_second_dispatch_uses_review_requested_resent_event_kind` |
| 3  | Throttle <60s mismo (agency,recipient) → skip                                                                         | `test_second_dispatch_within_60s_skips_already_sent_recipient` |
| 4  | reviewEmails CSV legacy → list[str]                                                                                   | `test_csv_legacy_payload_is_accepted_and_normalised` + unit normaliser |
| 5  | Email inválido (regex fail) → filtra silenciosamente, resto se envía                                                  | `test_invalid_recipient_is_filtered_silently` + unit normaliser |
| 6  | Template render incluye link `FRONTEND_BASE_URL/reels?site_id=…&property_id=…`                                        | flow test (assert "https://admin.example.com/reels?site_id=ckp.ie&property_id=137") + `test_url_builder` |
| 7  | SmtpEmailSender falla → filas `failed` con `error_message`, logs                                                      | `test_handler_marks_rows_failed_and_reraises_when_sender_errors` |
| 8  | ConsoleEmailSender prefijo identificable en stdout                                                                    | flow test (assert subject + agency_name + property_address + URL en buffer) |
| 9  | `pytest -q` verde                                                                                                     | 897 passed + 3 baseline known fails sin regresión |
| 10 | `apps.api --check` y `apps.worker --check` exit 0                                                                     | Verificado arriba |

## 5. Layer rules + invariantes

- `grep -rn 'from settings\|import settings' shared/email/{validators,url_builder,templates}.py shared/email/backends/` → **0 hits**. Capa pura, importable desde cualquier sitio.
- `git diff modules/reels/application/use_cases/publish_reel.py` → **0 líneas**. Publisher intacto, event-sourcing limpio.
- `git diff modules/rendering/infrastructure/ffmpeg/` → cambios solo del HOTFIX de Codex pre-existente, no tocados por #27.
- `OutboxRepository.mark_status(...)` generaliza la transición (`pending →
  processing | dispatched | failed`). Backward compat: el método previo
  `mark_published` sigue existiendo para el path principal.
- `claim_pending_event(...)` usa `FOR UPDATE SKIP LOCKED LIMIT 1` →
  multi-worker safe. El subscriber re-mark a `processing` en una segunda
  UoW para que el handler no compita con otro claim.

## 6. Outbox subscriber — diseño

- **Nuevo módulo** `apps/worker/outbox_subscriber.py` (211 líneas).
  Estructura paralela a `JobDispatcher`: `register_handler` por
  `event_type`, `process_once` (drena 1 evento por type — usable en tests),
  `start/stop`, `run_forever` con SIGINT/SIGTERM handler.
- **Concurrencia**: thread daemon + `threading.Event` para shutdown;
  `process_once` aísla excepciones por evento y propaga a
  `_mark_failed` (best-effort write con su propia UoW).
- **Transiciones de estado**:
  `pending → processing` (al claim, UoW 1) →
  `dispatched | failed` (terminal, dentro del use case en UoW 2).
- **Wiring**: `build_default_outbox_subscriber` registra
  `review_requested → DispatchReviewRequestedEmailUseCase.execute`.
- **`apps.worker.main`** arranca el subscriber **antes** del dispatcher y
  lo para en `finally` (orden inverso correcto).

## 7. Templates + URL builder

- `shared/email/templates.py`: `EmailTemplateRenderer` cachea source en
  memoria con lock; `render_plain` (obligatorio, raise si falta) +
  `render_html` (opcional, devuelve `None` si no existe el `.html`).
  HTML escape vía `html.escape(quote=True)` en cada valor del context
  (no en el template raw → permite mantener markup en el `.html`).
- `_NoneSafeMapping` propaga `KeyError` ante placeholder faltante → loud
  failure, no leak de `{property_title}` en el cuerpo.
- `build_reel_editor_url` percent-escapa el `site_id` (caracteres URL-no
  seguros) y normaliza el trailing slash del base URL. Test cubre
  caso con dots, caracteres especiales y trailing slash.

## 8. Riesgos / follow-ups (no bloqueantes)

1. **Workaround `webhook_events.source_kind='notification'`** (§2): refactor
   futuro recomendado, no urgente. Tag tracked en este informe.
2. **Throttle hardcoded a 60s** en el use case (`_DEFAULT_THROTTLE_SECONDS`).
   No es env-var. Si producto pide tuning, exponer como `EMAIL_THROTTLE_SECONDS`
   en `settings/notifications.py`.
3. **`_resolve_event_kind` lee `list_by_agency(limit=200)`** y filtra en
   Python. Para agencias con >200 envíos recientes podría dar falso
   negativo (la lista no cubre el envío buscado). Recomendado en follow-up:
   método especializado `exists_for_slot(...)` o ordenar la query por
   `created_at DESC` con `LIMIT` mayor o sin límite + `WHERE` exacto.
4. **`property_title/property_address` desde `properties.raw_json`** — si
   la propiedad no está sembrada el email sale con strings vacíos. Path
   no-op cubierto por test.

## 9. Cross-repo — estado tras este cierre

- **back #26** (infra email) — done (review previo, deployado).
- **back #27** (este review) — APPROVED → será marcado done.
- **front #26** (chip editor multi-email en `/automation`) — ya cerrado
  autónomamente por el equipo front (manda `list[str]`; backward compat
  garantizada por `normalise_review_emails`).

**Pipeline email end-to-end activo** tras deploy de #27:
```
publish_reel.py (approval_required)
  → outbox_events(review_requested, pending)
  → OutboxSubscriber.process_once() [thread daemon en apps.worker]
  → DispatchReviewRequestedEmailUseCase.execute()
       → normalise(defaults.settings.automation.reviewEmails)
       → throttle filter (60s/agency/recipient)
       → insert_pending × N en email_notifications
       → enqueue_job(kind='email_send', recipients, context)
  → JobDispatcher claim email_send
  → SendEmailJobHandler
       → render(review_requested.txt + .html)
       → EmailSender.send (ConsoleEmailSender en dev, SmtpEmailSender en prod)
       → mark_sent × N (mismo provider_message_id)
```

## 10. Acciones post-review

1. `feature_list.json` id 27: `status="done"` + eliminar `started_at` + añadir
   `review` con la ruta de este informe.
2. `progress/history.md`: bloque cierre con resumen cross-repo
   (back #26 + back #27 + front #26 = pipeline email completo).
3. `progress/current.md`: eliminar la sección "Sesión paralela — email
   notifications" entera (94-126).
4. Restart de servicios :8001 (API + worker) para cargar el outbox
   subscriber y el handler `email_send`.

---

**Veredicto final: APPROVED.** Cierre cross-repo procede.
