# Explore: email notifications (backend) — 2026-05-14

## TL;DR

El trigger único de "reel listo para revisar" está en
`modules/reels/application/use_cases/publish_reel.py:219-235`, donde
`publish_status` pasa a `pending_review` y se emite un `outbox_event`
tipo `review_requested`. **NO existe infraestructura de email** en el
repo: ni cliente SMTP/SendGrid/Resend, ni env vars, ni templates.
Los destinatarios viajan hoy en `agency_reel_defaults.settings.automation.reviewEmails`
(JSONB, namespaced), como string CSV — vestigio de la feature 6 del front.
**No existe `FRONTEND_BASE_URL`** en `.env.example`, así que no hay forma
de construir el link al editor del reel; hay que añadirlo. La cola de
jobs ya soporta un kind nuevo (`email_send`) sin tocar schema. NO existe
tabla de audit/idempotencia.

## 1. Trigger del evento "reel creado / listo para revisar"

**Punto único confirmado**: `modules/reels/application/use_cases/publish_reel.py:219-235`.

- Línea 223: `workflow_state='awaiting_review'`.
- Línea 224: emite un `outbox_event` tipo `review_requested`.
- Línea 225: `publish_status='pending_review'` persiste.

La bifurcación es:
```
IF (agency.approval_required OR settings.REVIEW_WORKFLOW_ENABLED):
  publish_status := 'pending_review'
  emit outbox_event(type='review_requested')
```

**Candidato alternativo descartado**: `regenerate_reel.py:142-148` —
ahí el admin pasa el reel de `pending_review` a `pending_publish` al
APROBAR. No corresponde al evento "creado/listo".

**Recomendación**: el publisher del email se cuelga del `outbox_event`
ya emitido (no inline en el use case). Esto preserva el patrón
event-sourcing y desacopla email del pipeline crítico.

## 2. Infraestructura de email

**Estado**: ❌ NO existe.

Búsqueda exhaustiva (`smtplib | sendgrid | mailgun | resend | SMTP |
SendGrid | mailer | sendmail | email_send | postmark`) → 0 hits
relevantes en `modules/`, `shared/`, `apps/`, `settings/`, `.env.example`.

**Opciones recomendadas**:

1. **Resend** (API REST + SDK Python). Free tier 100/día → suficiente
   para MVP. Webhooks para delivery/bounce. Templates en MD.
   - Pros: UX limpia, fácil debugging via dashboard.
   - Contras: vendor lock-in; requiere API key.

2. **SMTP genérico (stdlib `smtplib` + `email.message`)**. Sin deps.
   - Pros: cero vendor lock-in; compatible con AWS SES, Postfix local.
   - Contras: cliente lo construyes a mano; bounces/delivery no
     observables sin parsers extra.

3. **AWS SES / Mailgun / Postmark**: alternativas SaaS.

**Recomendación**: empezar con **smtplib** + provider configurable por
env var (`EMAIL_BACKEND=smtp|resend|console`). Console backend para
dev: stdout el email sin enviar. SMTP por defecto con creds en env.
Resend se enchufa luego cambiando un backend sin tocar el use case.

## 3. Persistencia de destinatarios

**Hoy**: `agency_reel_defaults.settings.automation.reviewEmails` (JSONB,
namespaced; key literal `"automation.reviewEmails"`).

- Shape actual: **string CSV** (vestigio del mock del front feature 6).
- No es columna nativa; está en el JSONB de "orphan toggles" de
  `defaults.settings` (documentado en `progress/history.md` feature 6 y
  feature 16).
- El back HOY NO lee ese valor (es decorativo end-to-end).

**Recomendación de evolución**:
- Mantener el path actual (`defaults.settings.automation.reviewEmails`)
  por compat, pero migrar el shape a `list[str]` (array de emails
  normalizados/lowercased).
- O migrar a un sub-objeto `defaults.settings.notifications.email_recipients[]`
  como hicimos con `settings.music.selection_rules` en feature 24 — más
  limpio si crecen los settings de notificaciones.
- **Mínimo invasivo**: aceptar `list[str]` bajo
  `settings.automation.reviewEmails`. Mantiene retrocompat con clientes
  que mandaban string CSV (`split(',')` defensivo).

## 4. URL del editor del admin

**Hoy**: ❌ No existe env var de base URL del frontend en `.env.example`
ni en `settings/`. Existe `GO_HIGH_LEVEL_BASE_URL` (para social-delivery
API, NO para el admin panel).

**Acción requerida**:
- Añadir `FRONTEND_BASE_URL` a `.env.example` (p.ej. en prod
  `https://admin.4reels.ie`, en dev `http://localhost:5173`).
- Añadir a `settings/app.py` (o el módulo de settings correspondiente).

**Convención del path** (a confirmar con el frontend):
- El editor de un reel concreto en el admin es probablemente
  `/reels` (lista) o `/reels?selected=<reel_id>`. El reel se
  identifica internamente por tupla `(agency_id, site_id, source_property_id)`.
- **Recomendación**: `{FRONTEND_BASE_URL}/reels?site_id={site_id}&property_id={property_id}`
  (el front lo abre y selecciona). El backend ofrece este link en el
  email.
- Alternativa: `{FRONTEND_BASE_URL}/reels/{site_id}/{property_id}` si
  el routing del frontend lo soporta. Confirmar.

## 5. Async / job queue

**Ya existe**: `modules/delivery/infrastructure/job_repository.py` +
`apps/worker/` ejecuta `reel_publish` y `scripted_render` con
`SELECT ... FOR UPDATE SKIP LOCKED`. La columna `kind` es un string
arbitrario, así que añadir un kind nuevo no requiere migración de
schema, solo registrar el handler en el worker.

**Propuesta**:
- Nuevo `kind="email_send"` con payload:
  ```json
  {
    "event_kind": "review_requested",
    "agency_id": "...",
    "site_id": "...",
    "property_id": 123,
    "recipient_emails": ["ops@4pm.ie", "boss@4pm.ie"],
    "subject_template_id": "review_requested_v1",
    "context": {
      "reel_url": "https://admin.../reels/...",
      "property_title": "28 Priory Walk...",
      "agency_name": "CKP"
    }
  }
  ```
- Worker handler: render template + enviar via `EmailBackend` configurable.

## 6. Idempotencia y audit

**No existe** tabla `email_notifications` ni `email_delivery_log`.

**Schema propuesto** (migración nueva):
```sql
CREATE TABLE email_notifications (
    id UUID PRIMARY KEY,
    agency_id VARCHAR(36) NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    event_kind TEXT NOT NULL,          -- 'review_requested', 'reel_published', etc.
    site_id TEXT NOT NULL,
    source_property_id INTEGER NOT NULL,
    recipient_email TEXT NOT NULL,
    status TEXT NOT NULL,              -- 'queued', 'sent', 'failed', 'bounced'
    provider_message_id TEXT,
    error_message TEXT,
    sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE (agency_id, site_id, source_property_id, recipient_email, event_kind)
);
CREATE INDEX idx_email_notifications_status ON email_notifications(status);
CREATE INDEX idx_email_notifications_agency ON email_notifications(agency_id, created_at DESC);
```

**Política idempotente**:
- Antes de encolar, INSERT con `ON CONFLICT DO NOTHING` por la UNIQUE.
  Si la fila existía con `sent_at IS NOT NULL` → skip.
- Si el reel sufre `regenerate_reel` (cambio post-render): emitir un
  nuevo `event_kind='review_requested_resent'` (no duplicar la fila
  original). Decisión a confirmar.

## 7. Decisiones pendientes (para preguntar al usuario)

1. **Provider de email**: ¿SMTP genérico (con qué relay: Gmail / AWS SES
   / Postfix local del host) o SaaS (Resend / SendGrid / Mailgun)?
2. **De-from**: ¿quién manda el email? `noreply@4pm.ie`,
   `notifications@4reels.ie`, o el email del agente?
3. **Multi-recipient**: ¿un único mensaje con varios `To:`/`Bcc:`, o
   N mensajes separados (uno por destinatario)? Importa por privacidad
   y por la idempotencia. **Recomendado**: N mensajes (un Bcc agrupado
   leaks emails entre destinatarios).
4. **Templating**: HTML + plain-text fallback. ¿Branding del email
   (logo de 4Reels, color primario)? ¿O minimal text-only?
5. **Re-render del reel**: si el agente regenera y vuelve a
   `pending_review`, ¿re-enviamos email? Default razonable: SÍ pero con
   una key distinta (no duplicate).
6. **Eventos adicionales futuros**: por ahora solo `review_requested`.
   ¿Más adelante `reel_published`, `reel_failed`?
7. **Path del editor en el admin**: `?site_id=&property_id=` vs
   `/reels/{site_id}/{property_id}` — confirmar con el frontend.
8. **Rate limiting**: si una agencia tiene 100 reels pending de golpe
   (después de un fallo), ¿spam 100×N emails? **Recomendado**:
   throttle en el worker (max 1 email/recipient/minute) o batch
   agrupado por agencia/hora.
9. **Validación de email**: ¿el back valida (regex + sintaxis)? ¿O
   confía en el frontend? **Recomendado**: validar ambos lados.

## 8. Gaps identificados (lo que falta para que la feature funcione)

| # | Gap | Impacto | Mitigación |
|---|-----|---------|------------|
| 1 | Sin `EMAIL_BACKEND` configurable + sin cliente SMTP/Resend | No se puede enviar nada | Nueva capa `shared/email/` con interfaz `EmailSender.send(message)` + 2 backends (`SmtpEmailSender`, `ConsoleEmailSender` para dev) |
| 2 | Sin `FRONTEND_BASE_URL` | No hay link en el email | Añadir env var + settings |
| 3 | Sin tabla `email_notifications` | Sin idempotencia ni audit | Nueva migración Alembic |
| 4 | Sin handler en worker para `kind='email_send'` | Worker no procesa el job | Añadir handler análogo a `reel_publish` |
| 5 | `reviewEmails` shape inconsistente (string CSV) | Parsing frágil | Migrar a `list[str]` con shim de retrocompat |
| 6 | Sin templates de email | Sin contenido | Carpeta `assets/email/templates/` con MJML/HTML + plain |
| 7 | Sin validación de email en payload Pydantic | Garbage in | Añadir validator en `automation.py` / `defaults.py` |
| 8 | Sin tests de integración del flujo | Sin cobertura | Suite nueva `tests/integration/notifications/` con `ConsoleEmailSender` |

## 9. Archivos clave referenciados (audit read-only)

- `modules/reels/application/use_cases/publish_reel.py:219-235` (trigger).
- `modules/reels/application/use_cases/regenerate_reel.py:142-148` (approve flow, descartado como trigger).
- `modules/configuration/transport/payloads/automation.py` (contrato `/automation`).
- `modules/configuration/transport/payloads/defaults.py` (contrato `/defaults`).
- `modules/delivery/infrastructure/job_repository.py` (cola de jobs).
- `tests/integration/configuration/test_automation_router.py:111` (placement de `review_emails` en defaults).
- `alembic/versions/20260501_0001_initial_schema.py` (schema baseline).
- `.env.example` (env vars actuales — ninguna de email/frontend).
