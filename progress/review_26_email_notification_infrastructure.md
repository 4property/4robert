# Review — feature 26 `email_notification_infrastructure`

- **Fecha:** 2026-05-15
- **Agente:** Claude (reviewer subagente, lanzado por el leader)
- **Veredicto:** **APPROVED**
- **Informe del implementer:** `progress/impl_26_email_notification_infrastructure.md`

## Resumen

Feature de infraestructura pura para soportar notificaciones por email.
La entrega es consistente con el diseño §A del documento
`progress/design_email_notifications_and_brand_customisation.md` y con
las decisiones del usuario (`§D`). Cero business logic introducida:
`publish_reel.py` intacto, ningún handler `email_send` registrado, sin
templates.

## Checks ejecutados

### init.sh y tests focalizados

- `bash ./init.sh`: verde salvo los 3 fallos baseline conocidos
  (`test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
  + `test_http_transport.py::test_health_endpoints_include_paused_dispatcher_state`
  + `test_health_endpoints_return_minimal_payloads`).
  Total **869 passed, 3 failed (baseline), 14 warnings** en 388s.
- `.venv/bin/python -m pytest tests/unit/notifications/ tests/integration/notifications/ -q`
  → **27 passed** en 13.6s.
- `.venv/bin/python -m apps.api --check` → `RUNTIME READY: Yes`, exit 0.
- `.venv/bin/python -m apps.worker --check` → `kinds=reel_publish, scripted_render`,
  exit 0. **Sin `email_send` registrado** (correcto — eso es #27).

### Migración

- `alembic upgrade head` → noop (ya en head `20260514_0007`).
- `alembic downgrade -1` → `Running downgrade 20260514_0007 -> 20260514_0006`.
- `alembic upgrade head` → `Running upgrade 20260514_0006 -> 20260514_0007`.
- Test integración `test_migration_20260514_0007.py` cubre el ciclo
  contra schema efímera + presencia de índices y UNIQUE.

## Chequeos específicos

### 1. Layer rules — OK

`grep -rn 'from settings\|import settings' shared/email/sender.py shared/email/backends/`
devuelve 0 hits. Solo `shared/email/factory.py:10` importa
`from settings.notifications import NotificationSettings`, que es el
único acoplamiento permitido por design.

### 2. Migración — OK

`alembic/versions/20260514_0007_email_notifications.py`:
- `revision = "20260514_0007"`, `down_revision = "20260514_0006"`.
- UNIQUE constraint `uq_email_notifications_dedup` sobre
  `(agency_id, site_id, source_property_id, recipient_email, event_kind)`.
- Índices `idx_email_notifications_status` y
  `idx_email_notifications_agency_created` (segundo sobre
  `(agency_id, created_at DESC)` vía `sa.text("created_at DESC")`).
- FK `agency_id REFERENCES agencies(id) ON DELETE CASCADE`.
- `downgrade()` revierte: 2x `drop_index` + `drop_table`.
- `id` como `VARCHAR(36)` (consistente con el resto del repo).

### 3. Repository idempotente — OK

- `insert_pending` usa `ON CONFLICT ON CONSTRAINT
  uq_email_notifications_dedup DO UPDATE SET updated_at = EXCLUDED.updated_at
  RETURNING *`. Devuelve siempre la fila. Trade-off documentado en
  docstring y aprovechado por #27 (saber "última actividad sobre el slot").
- Test `test_insert_pending_is_idempotent_for_repeated_inserts` valida
  que la 2ª inserción devuelve el mismo `id` y que `list_by_agency`
  reporta longitud 1.
- `mark_sent(email_id, provider_message_id, sent_at)` transiciona a
  `status='sent'`, persiste `sent_at` y bumpea `updated_at`. Test
  `test_mark_sent_transitions_row_to_sent_status` lo cubre.
- `find_recent_sent(agency_id, recipient_email, since)` filtra por
  `status='sent' AND sent_at >= :since` (preparación para throttle de #27).

### 4. SMTP backend — OK

- `Message-ID` generado vía `email.utils.make_msgid(domain=…)` y
  devuelto como `SentEmail.provider_message_id`. Test
  `test_smtp_sender_returned_message_id_matches_envelope_header` valida
  el match.
- TLS opcional: `starttls()` solo si `use_tls=True`. Test
  `test_smtp_sender_uses_starttls_and_login_when_configured` +
  `test_smtp_sender_skips_starttls_and_login_when_not_configured`.
- Auth opcional: `login()` solo si `username` truthy. Cubierto por los
  mismos dos tests.
- Cierre en `finally` con doble fallback (`quit()` → `close()` si
  `quit()` lanza `SMTPException`). Test
  `test_smtp_sender_closes_connection_on_send_failure` valida que
  `quit()` se llama incluso cuando `send_message` revienta.
- HTML alternative se añade solo si `body_html` es no-None
  (`test_smtp_sender_sets_alternative_html_body_when_provided` +
  `test_smtp_sender_sets_plain_text_body_by_default`).
- Headers custom + `Reply-To` propagados
  (`test_smtp_sender_propagates_reply_to_and_custom_headers`).

### 5. Sin business logic — OK

- `git diff modules/reels/application/use_cases/publish_reel.py`: vacío.
  `publish_reel.py` intacto.
- `apps/worker --check` lista solo `reel_publish, scripted_render`. Sin
  `email_send`.
- `grep -rn 'review_requested\|email_send' modules/notifications/
  shared/email/ apps/worker/` solo matchea `build_email_sender` en
  `shared/email/__init__.py` y `factory.py` (función pública del API).
  Cero referencias a `review_requested` o `email_send` como kind/evento.
- No hay templates (`shared/email/` no contiene jinja, htmls ni
  string templates de contenido).

### 6. Settings — OK

- `settings/notifications.py::load_notification_settings(environ=None)`
  parsea defaults razonables (`EMAIL_BACKEND=console`,
  `SMTP_HOST=localhost`, `SMTP_PORT=587`, `SMTP_USE_TLS=True`,
  `SMTP_FROM_ADDRESS=notifications@4reels.ie`,
  `FRONTEND_BASE_URL=http://localhost:5173`).
- `email_backend` se normaliza con `.strip().lower()`.
- `build_email_sender(settings)` acepta `"console"` y `"smtp"`; otro
  valor → `raise ValueError(f"unknown EMAIL_BACKEND: ...")`. Test
  `test_factory.py::test_build_email_sender_unknown_backend_raises`
  (parte de la suite verde).
- `settings/__init__.py` re-exporta `NotificationSettings`,
  `load_notification_settings` y todos los `DEFAULT_*` ordenados
  alfabéticamente en `__all__`.

### 7. Sin colisión con árbol sucio — OK

```
$ git status --short shared/email/ modules/notifications/ alembic/versions/20260514_0007_*
?? alembic/versions/20260514_0007_email_notifications.py
?? modules/notifications/
?? shared/email/
```

Todo untracked (`??`); ningún tracked-modified producido por el
implementer fuera de su scope declarado. Las modificaciones del árbol
en `modules/rendering/infrastructure/ffmpeg/` son del HOTFIX paralelo
de Codex y NO han sido tocadas por el implementer (verificado:
`git diff modules/rendering/...` muestra cambios pre-existentes,
ninguno con fingerprint del implementer).

Los modificados tracked del implementer son los 5 documentados en su
informe (`settings/__init__.py`, `shared/db/uow.py`, `.env.example`,
`docs/API.md`, `docs/conventions.md`) — todos dentro del scope.

## Desviaciones aceptadas

1. **`EmailRecord.sent_at` como `str | None`** (no `datetime`). El
   implementer respeta el patrón del repo (ver
   `modules/configuration/.../repository_helpers.py::isoformat`) y
   mantiene la API del repositorio tipada (`mark_sent(sent_at: datetime)`,
   `find_recent_sent(since: datetime)`). Decisión razonable y
   documentada.
2. **`ON CONFLICT DO UPDATE SET updated_at = EXCLUDED.updated_at
   RETURNING *`** en lugar de `DO NOTHING`. Trade-off explicado: bumpea
   `updated_at` en conflicto pero permite recuperar la fila en un solo
   roundtrip. Útil para #27.
3. **Sin `__init__.py` en `tests/unit/notifications/` ni
   `tests/integration/notifications/`**. Consistente con otros packages
   hermanos (`tests/unit/configuration/`, `tests/integration/reels/`,
   etc.).

## Acceptance criteria — cumplidos

- [x] `shared/email/` expone `EmailSender` Protocol + `EmailMessage`
      dataclass.
- [x] `build_email_sender` selecciona `ConsoleEmailSender` con
      `EMAIL_BACKEND=console` y `SmtpEmailSender` con `=smtp`.
- [x] `SmtpEmailSender` envía vía `smtplib` con auth + TLS opcionales;
      6 tests unit con mock lo verifican.
- [x] `alembic upgrade head` aplica `20260514_0007` y crea
      `email_notifications`; downgrade reversible.
- [x] `EmailNotificationRepository.insert_pending` idempotente vía
      UNIQUE — segundo insert devuelve fila existente.
- [x] `.env.example` documenta `EMAIL_BACKEND`, todos los `SMTP_*` y
      `FRONTEND_BASE_URL`.
- [x] Sin business logic (publish_reel no se toca).
- [x] `pytest -q` verde (869 + 27 nuevos), salvo baseline conocido.
- [x] `apps.api --check` y `apps.worker --check` exit 0.

## Conclusión

**APPROVED**. La feature deja el suelo listo para que #27 cablee el
subscriber del outbox `review_requested` + el handler worker
`email_send` + templates encima del repositorio idempotente y del
factory ya disponibles.

El leader puede cerrar #26 y arrancar #27.
