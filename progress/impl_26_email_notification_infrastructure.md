# Implementer report — feature 26 `email_notification_infrastructure`

- **Fecha:** 2026-05-15
- **Agente:** Claude (implementer subagente, lanzado por el leader)
- **Estado feature_list.json:** `in_progress` (NO se marca `done`; lo hace el reviewer)

## Resumen

Infra pura para soportar notificaciones por email. La feature aporta:

1. Capa `shared/email/` con `EmailMessage`, `SentEmail`, Protocol
   `EmailSender` y dos backends concretos (`ConsoleEmailSender` y
   `SmtpEmailSender`).
2. `settings/notifications.py` (`NotificationSettings` +
   `load_notification_settings`) con defaults seguros para dev
   (`EMAIL_BACKEND=console`, etc.).
3. Migración Alembic `20260514_0007_email_notifications` que crea la
   tabla `email_notifications` con UNIQUE `(agency_id, site_id,
   source_property_id, recipient_email, event_kind)` + dos índices
   (status, agency_id+created_at DESC).
4. Módulo `modules/notifications/` con dominio mínimo (`EmailRecord` +
   status constants) y repositorio
   `EmailNotificationRepository` enchufado al UoW
   (`uow.notifications.emails`).
5. Documentación (`.env.example`, `docs/API.md` sección 7b,
   `docs/conventions.md` nota de extensión).

Cero business logic: `publish_reel`, el outbox y el worker NO se han
tocado. Feature #27 montará el dispatcher + handler `email_send` por
encima.

## Archivos creados / modificados

### Nuevos (untracked)

| Ruta                                                                                  | Tipo            |
|---------------------------------------------------------------------------------------|-----------------|
| `shared/email/__init__.py`                                                            | Package init / re-exports |
| `shared/email/sender.py`                                                              | Protocol + value objects (`EmailMessage`, `SentEmail`, `EmailSender`) |
| `shared/email/factory.py`                                                             | `build_email_sender(settings)` factory |
| `shared/email/backends/__init__.py`                                                   | Backends package init |
| `shared/email/backends/console_sender.py`                                             | `ConsoleEmailSender` (dev/tests) |
| `shared/email/backends/smtp_sender.py`                                                | `SmtpEmailSender` (stdlib `smtplib`) |
| `settings/notifications.py`                                                           | `NotificationSettings` + loader |
| `alembic/versions/20260514_0007_email_notifications.py`                                | Migración tabla `email_notifications` |
| `modules/notifications/__init__.py`                                                   | BC init |
| `modules/notifications/domain/__init__.py`                                            | Domain re-exports |
| `modules/notifications/domain/email_record.py`                                        | `EmailRecord` dataclass |
| `modules/notifications/domain/status.py`                                              | Constantes de status |
| `modules/notifications/infrastructure/__init__.py`                                    | Infra package init |
| `modules/notifications/infrastructure/email_notification_repository.py`                | Repositorio (insert_pending, list_by_*, mark_sent, mark_failed, find_recent_sent) |
| `tests/unit/notifications/test_email_message.py`                                      | Unit (value objects) |
| `tests/unit/notifications/test_console_sender.py`                                     | Unit (console backend) |
| `tests/unit/notifications/test_smtp_sender.py`                                        | Unit (SMTP backend con MagicMock) |
| `tests/unit/notifications/test_factory.py`                                            | Unit (loader + factory) |
| `tests/integration/notifications/test_migration_20260514_0007.py`                      | Integration (migración + UNIQUE) |
| `tests/integration/notifications/test_email_notification_repository.py`               | Integration (roundtrip vía UoW) |

### Modificados

| Ruta                          | Motivo |
|-------------------------------|--------|
| `settings/__init__.py`        | Re-exporta `NotificationSettings`, `load_notification_settings` y los `DEFAULT_*` para que `from settings import …` funcione fuera del submódulo. |
| `shared/db/uow.py`            | Añade `NotificationsNamespace` con `emails: EmailNotificationRepository`; lo monta en `__enter__` y lo limpia en `__exit__`. |
| `.env.example`                | Bloque "EMAIL NOTIFICATIONS (feature 26)" con todas las env vars (`EMAIL_BACKEND`, `SMTP_*`, `FRONTEND_BASE_URL`). |
| `docs/API.md`                 | Nueva sección "7b. Notifications (internal — feature 26)" describiendo la capa, sin rutas HTTP. |
| `docs/conventions.md`         | Nota: cómo añadir backends futuros (Resend, SES, …) implementando `EmailSender` y enchufándolos en el factory. |

## Decisiones tomadas

1. **`EmailRecord.sent_at` se persiste como `str` ISO-8601**, no como
   `datetime` tz-aware. Las instrucciones decían `datetime`, pero el
   patrón del resto del repo (ver `modules/configuration/.../repository_helpers.py::isoformat`)
   serializa timestamps a string para que los dataclasses del dominio
   queden sin dependencia de `datetime`. Mantengo la firma de
   `mark_sent(sent_at: datetime)` y `find_recent_sent(since: datetime)`
   en la API del repositorio porque ahí sí entra valor tipado del
   caller; el dataclass de dominio lo expone como string al consumidor.
2. **`insert_pending` usa `ON CONFLICT ... DO UPDATE SET updated_at =
   EXCLUDED.updated_at RETURNING *`** en lugar de `DO NOTHING` para
   que la sentencia devuelva siempre la fila (nueva o existente). El
   trade-off (bumpea `updated_at` en conflicto) lo aprovechará la
   feature #27 para saber "última actividad sobre el slot".
3. **`Message-ID` se genera con `make_msgid(domain=from_address)`** y
   se devuelve como `provider_message_id`. Si el cliente SMTP raise
   durante `send_message`, el `finally` cierra la conexión con
   `quit()` (o `close()` si `quit()` falla) — verificado por
   `test_smtp_sender_closes_connection_on_send_failure`.
4. **No se registra handler `email_send`** en el worker — eso es
   alcance explícito de #27. El `apps/worker --check` sigue listando
   solo `reel_publish` y `scripted_render`.

## Tests — output

```
$ .venv/bin/python -m pytest tests/unit/notifications/ tests/integration/notifications/ -q
...........................                                              [100%]
27 passed in 12.93s
```

## Readiness checks

```
$ .venv/bin/python -m apps.api --check
[…] API READINESS REPORT — RUNTIME READY: Yes
exit=0

$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=reel_publish, scripted_render worker_count=1
exit=0
```

## Migración — upgrade / downgrade / upgrade

```
$ alembic upgrade head
… (no-op, ya en head 20260514_0007)

$ alembic downgrade -1
Running downgrade 20260514_0007 -> 20260514_0006, Create ``email_notifications`` table (feature 26).

$ alembic upgrade head
Running upgrade 20260514_0006 -> 20260514_0007, Create ``email_notifications`` table (feature 26).
```

La integración `test_migration_downgrade_drops_table_and_upgrade_recreates_it`
ejecuta el ciclo completo contra una schema efímera y verifica que la
tabla desaparece y reaparece con sus índices.

## `bash ./init.sh`

```
[OK] apps.api --check verde
[OK] apps.worker --check verde
[OK] pytest verde
3 failed, 869 passed, 14 warnings in 389.38s
```

Los 3 fallos son los baseline conocidos (
`test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
y los 2 en `test_http_transport.py`) ya documentados en
`progress/current.md`. Son preexistentes y NO los introduce esta feature.

## Riesgos / follow-ups para feature 27

- **Wiring `publish_reel` → outbox → handler `email_send`**: feature 26
  deja el repositorio listo (`insert_pending` idempotente), pero
  ningún caller. La 27 tiene que:
  1. Suscribir al outbox `review_requested` (usar el patrón ya
     existente del worker, no inline en `publish_reel.py`).
  2. Registrar el kind `email_send` en `apps/worker/runtime.py`.
  3. Validar emails (Pydantic) en el payload de `/defaults`
     (`reviewEmails`).
- **Throttle 1 envío / (agency, recipient) / minuto**: el método
  `find_recent_sent(since=...)` ya existe; la 27 lo consume con
  `since = utcnow() - timedelta(seconds=60)`.
- **`FRONTEND_BASE_URL`**: hoy default `http://localhost:5173`. Antes
  de salir a prod, hay que setearlo en el `.env` real
  (`https://4reelsfront-test.4property.com` para test).
- **Multi-recipient**: la decisión §D.3 del design es "un solo email
  con N To: visibles + N filas en `email_notifications` compartiendo
  `provider_message_id`". El repositorio lo soporta (`mark_sent`
  acepta el mismo `provider_message_id` en varias filas), pero la
  orquestación vive en la 27.

## Self-check

- ✅ Sin business logic nueva (publish_reel intacto, worker handlers
  intactos).
- ✅ Layer rule: `shared/email/sender.py` y `backends/*.py` no
  importan de `settings/` ni `modules/`; sólo `factory.py` toca
  settings.
- ✅ Repositorio extiende `ModuleRepository` y no llama
  `session.commit()`.
- ✅ Migración chained correctamente desde `20260514_0006`.
- ✅ UNIQUE `uq_email_notifications_dedup` cubre la tupla del design.
- ✅ Pytest verde para la suite nueva (27/27).
- ✅ `init.sh` verde salvo baseline conocido.

Pendiente: revisión por `reviewer`. Yo NO marco `done` en
`feature_list.json` — ese paso es del reviewer.
