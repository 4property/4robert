# Design: email notifications + brand colors/fonts customisation

> **Sesión leader Claude — 2026-05-14.** Documento de diseño cross-repo.
> NO se ha tocado código todavía. Próximo paso: confirmar decisiones
> pendientes con el usuario, registrar features `pending` en
> `feature_list.json` de ambos repos, lanzar implementers por feature
> respetando `one_feature_at_a_time`.

## 0. Scopes

Dos scopes independientes en este turno:

### A. Notificaciones por email — "reel listo para revisar"

Cuando un reel queda en `publish_status='pending_review'`, enviar un
email a 1..N destinatarios configurados por la agencia con un link al
editor del reel en el admin. Sin previsualización embebida. El agente
entra a la app si quiere aprobar.

Informes base:
- `progress/explore_email_notifications_back.md`
- `/opt/projects/4Reels-Frontend/progress/explore_email_notifications_front.md`

### B. Brand customisation — colores + fuente

En `/brand`, la agencia puede elegir color primario, color secundario
y familia tipográfica. Si la agencia no configura un valor, se usa el
fallback que venga en el JSON del webhook de WordPress por property.
Las fuentes se sirven desde un catálogo del backend (set de fuentes
instaladas en `assets/fonts/`); el frontend solo ofrece las disponibles
en un dropdown.

Informe base:
- `progress/explore_brand_colors_and_fonts.md`

---

## A. Email notifications — diseño

### A.1 Trigger único

`modules/reels/application/use_cases/publish_reel.py:219-235`. Ahí ya
se emite un `outbox_event` tipo `review_requested`. El nuevo módulo de
notificaciones se SUBSCRIBE a ese outbox, NO se cuelga inline (preserva
event-sourcing, no acopla email al pipeline crítico).

### A.2 Arquitectura propuesta

```
publish_reel.py (existente)
    ├─ emite outbox_event(type='review_requested', payload={…})
    │
    ▼
[NEW] modules/notifications/application/use_cases/dispatch_review_requested_email.py
    ├─ lee outbox event
    ├─ carga agency_reel_defaults.settings.automation.reviewEmails (list[str])
    ├─ si lista vacía → no-op, marca outbox como skipped
    ├─ INSERT (idempotente) en email_notifications por cada destinatario
    │   con status='queued'
    ├─ encola N jobs kind='email_send' (uno por destinatario)
    └─ marca outbox como dispatched

apps/worker/ (existente) — añade handler para kind='email_send'
    ├─ carga payload (recipient_email, subject, template_id, context)
    ├─ renderiza template (HTML + plain text)
    ├─ delega a EmailSender (interfaz nueva)
    ├─ EmailSender = SmtpEmailSender(prod) | ConsoleEmailSender(dev) | ResendEmailSender(opt)
    ├─ on success → UPDATE email_notifications SET status='sent', sent_at=NOW
    └─ on failure → UPDATE status='failed' con error_message; retry exponencial
```

### A.3 Datos: nueva tabla `email_notifications`

```sql
CREATE TABLE email_notifications (
    id UUID PRIMARY KEY,
    agency_id VARCHAR(36) NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    event_kind TEXT NOT NULL,          -- 'review_requested', etc.
    site_id TEXT NOT NULL,
    source_property_id INTEGER NOT NULL,
    recipient_email TEXT NOT NULL,
    status TEXT NOT NULL,              -- 'queued' | 'sent' | 'failed' | 'bounced'
    provider_message_id TEXT,
    error_message TEXT,
    sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE (agency_id, site_id, source_property_id, recipient_email, event_kind)
);
CREATE INDEX idx_email_notifications_status ON email_notifications(status);
```

Idempotencia: `INSERT ON CONFLICT DO NOTHING` por la UNIQUE. Si la
fila existe con `status='sent'`, skip. Si `status='failed'` y han
pasado >X minutos, reintentar.

### A.4 Persistencia de destinatarios

**Decisión recomendada**: migrar `defaults.settings.automation.reviewEmails`
de `string CSV` a `list[str]` normalizado en lowercase. Mantiene el
path actual; el back acepta ambos shapes con shim defensivo
(`split(',')` cuando llega string). El frontend manda `list[str]`
directamente.

Alternativa (cleaner pero más invasiva): mover a
`defaults.settings.notifications.email_recipients[]` siguiendo el
patrón de `settings.music.selection_rules` (feature 24).

### A.5 Provider de email

**Capa nueva** `shared/email/` con interfaz `EmailSender`:

```
class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> SentEmail: ...
```

Backends:
- `ConsoleEmailSender`: imprime el mail a stdout (dev y tests).
- `SmtpEmailSender`: stdlib `smtplib` + `email.message.EmailMessage`.
- `ResendEmailSender` (opcional, feature futura).

Selección via env var `EMAIL_BACKEND` (`console` por defecto en dev,
`smtp` en prod).

### A.6 Configuración del frontend (UI)

UI en `/automation` → `ReviewModeDetails`, sustituye el `<input>` CSV
plano por un `EmailListInput` (chips, basado en el patrón
`HashtagsEditor` de feature 20). Validación cliente con
`isValidEmail` en `src/lib/utils/email.js`.

### A.7 URL del editor para el link del email

Nueva env var del back `FRONTEND_BASE_URL` (p.ej.
`https://4reelsfront-test.4property.com` en test). El template del
email construye `{FRONTEND_BASE_URL}/reels?site_id={site_id}&property_id={property_id}`
(confirmar path final con el frontend; el routing actual de `/reels`
no soporta deeplink a un reel concreto — quizá requiera un cambio
pequeño en el frontend, ver §A.9 gap 2).

### A.8 Contenido del email (text-only por defecto)

Asunto: `Reel ready for review — {property_title}`.

Cuerpo (plain text):
```
Hi,

A new reel is awaiting your approval at {agency_name}.

Property: {property_title}
Address:  {property_address}

Review and approve here: {reel_url}

— 4Reels
```

HTML opcional con el mismo contenido + un botón "Review reel". Sin
imágenes ni MP4 embebido.

### A.9 Gaps a resolver en implementación

1. **Sin `FRONTEND_BASE_URL`**: añadir a `.env.example`, `settings/`.
2. **`/reels` no soporta deeplink** a reel concreto: confirmar con el
   frontend si `/reels?site_id=&property_id=` selecciona la card
   automáticamente. Si no, añadir esa lógica en el frontend.
3. **Sin handler `email_send` en el worker**: registrar nuevo kind.
4. **Sin validación de email en Pydantic**: validar en payload de
   `/defaults`.
5. **Sin tests integración del flujo completo**: suite nueva con
   `ConsoleEmailSender`.

### A.10 Features propuestas (registrar como `pending`)

- **back #26 `email_notification_infrastructure`**: capa
  `shared/email/` + `EmailSender` interfaz + 2 backends (console+smtp)
  + env vars + tabla `email_notifications` + migración.
- **back #27 `email_notification_review_requested`**: subscriber del
  outbox `review_requested` + handler worker `email_send` + templates
  + tests integración con `ConsoleEmailSender`.
- **front #26 `review_emails_chip_editor`**: chip editor en
  `/automation` + helper `lib/utils/email.js` + mock-backend valida
  `list[str]` + spec E2E. (Frontend solo necesita una feature; el
  back tiene 2 por separación de capas).

---

## B. Brand customisation — diseño

### B.1 Hallazgo crítico

El frontend YA tiene UI funcional para los 3 campos
(`primary_color`, `secondary_color`, `font_family`). El backend YA los
acepta y persiste. PERO:

- **`font_family` es dead-end**: persiste en BBDD, NUNCA llega al
  renderer (Inter hardcodeado).
- **Solo Inter está en `assets/fonts/`**: las otras 4 opciones del
  dropdown (Söhne, Manrope, Plus Jakarta Sans, Helvetica) son ficticias.
- **`secondary_color` es inerte**: persistido pero no consumido por el
  render (solo se usa `primary_color`).

Esto significa que el usuario hoy **cree que está configurando** colores
y fuente, pero realmente solo `primary_color` tiene efecto.

### B.2 Arquitectura propuesta

**Backend**:

1. **Catálogo de fuentes** programático:
   - Carpeta `assets/fonts/` con sub-carpeta por familia
     (`Inter/`, `Roboto/`, …) cada una con `Regular.ttf` y `Bold.ttf`
     (paths estandarizados).
   - Helper `modules/configuration/domain/font_catalog.py` con
     constante `AVAILABLE_FONTS = (FontDescriptor(...), ...)` que
     define `family`, `display_name`, `regular_path`, `bold_path`.
   - **Endpoint `GET /v1/admin/fonts`** (admin scope, sin agency_id —
     el catálogo es global): devuelve
     `{items: [{family, display_name, available: true}], count: N}`.

2. **Validación enum** en `BrandSettingsUpsertPayload`:
   - `font_family: str | None` se valida contra `AVAILABLE_FONTS`.
   - `null` o ausente → "usa default" (Inter fallback).
   - Valor fuera del catálogo → 422 `UNKNOWN_FONT_FAMILY`.

3. **Inyección en el render**:
   - Añadir `font_family: str | None` a `PropertyReelTemplate`
     (`models.py`).
   - En `ingest_property_into_reel.py`, tras cargar
     `brand = uow.configuration.brand.get(agency_id)`, resolver el
     path de la fuente:
     ```
     font_descriptor = font_catalog.resolve(brand.font_family or 'Inter')
     template.font_path = font_descriptor.regular_path
     template.bold_font_path = font_descriptor.bold_path
     ```
   - El renderer ya consume `template.font_path` (no requiere cambios).

4. **Inyección de `secondary_color`** (decisión a confirmar):
   - Hoy se persiste pero no se usa. Si el render lo necesita (p. ej.
     para color del panel inferior del template classic), inyectarlo
     análogamente a `primary_color`.

5. **Política "null = usa default"**:
   - El frontend manda `null` cuando el usuario "limpia" un campo.
   - El use case persiste `NULL` (no string vacío).
   - El resolver de render usa la cascada:
     `brand_field` → `webhook_field` (para colores) → `hardcoded_default`.

**Frontend**:

1. Reemplazar el `FONTS` hardcodeado por una llamada a
   `GET /v1/admin/fonts` que pueble el dropdown dinámicamente.
2. Añadir botón "Reset to webhook default" junto a cada selector
   (colores y fuente) que mande `null` en el PUT.
3. UX: mostrar visualmente "Using webhook fallback" cuando el campo
   esté en `null`.

### B.3 Catálogo inicial de fuentes (a confirmar con el usuario)

El frontend hoy ofrece (ficticias salvo Inter):
- Inter ✅ (ya en disco).
- Söhne ❌ (de pago, requiere licencia).
- Manrope ❌ (Google Fonts, OFL — bajable).
- Plus Jakarta Sans ❌ (Google Fonts, OFL — bajable).
- Helvetica ❌ (Apple/Linotype, no redistribuible libre).

**Recomendación**: catálogo MVP con fuentes Google OFL (free, redistribuibles):
- Inter (ya).
- Manrope.
- Plus Jakarta Sans.
- Montserrat.
- Poppins.
- Roboto.

Quitar Söhne y Helvetica del dropdown (no se pueden distribuir
legalmente con el repo).

### B.4 Cascada de fallback (colores)

```
PARA cada color (primary, secondary):
  resolved_color =
    BrandSettings.{color} de la agencia    if not null
    ELSE property.wppd_accent_{color}     if válido en webhook
    ELSE hardcoded default                 (#0F172A para primary, #FFFFFF para secondary)
```

Por consistencia, lo mismo para `font_family`:
```
resolved_font =
  BrandSettings.font_family de la agencia    if not null y en catálogo
  ELSE 'Inter'  (default global)
```

(El webhook NO trae font, así que la cascada de font es de 2 niveles
no 3).

### B.5 Cleanup de scope (independiente del usuario)

Los 2 hotfixes recientes en `/brand`:
- HOTFIX 1: quitó `LivePreview`.
- HOTFIX 2: quitó `LogoPlacementCard` pero preservó `logo_position`
  en state + body (para no cambiar el contrato Pydantic).

**Decisión pendiente**: ¿deprecar `logo_position` también del contrato
del back? Si nunca se va a tocar desde la UI, podría dejar de enviarse
y el back podría tener un default fijo. **Recomendación**: dejarlo
como está (no introducir un cambio de contrato sin necesidad).

### B.6 Gaps a resolver en implementación

1. **`font_family` dead-end** (descrito).
2. **4 fuentes ficticias en el dropdown**.
3. **Sin catálogo programático**.
4. **Sin endpoint `GET /fonts`**.
5. **Sin validación enum del payload**.
6. **`secondary_color` posiblemente inerte** (decisión).
7. **Política de `null` no documentada**: payload acepta `null`, pero
   no hay tests de cómo el use case lo trata vs string vacío.

### B.7 Features propuestas (registrar como `pending`)

- **back #28 `font_catalog_endpoint`**: bajar fuentes Google OFL al
  `assets/fonts/`, helper `font_catalog.py`, endpoint
  `GET /v1/admin/fonts`, validador enum del payload `/brand`,
  inyección en `PropertyReelTemplate.font_path`.
- **back #29 `brand_colors_cascade_complete`**: cablear
  `secondary_color` en el render (si scope), formalizar la cascada
  webhook→agencia→default, tests de los 3 escenarios. Opcional según
  decisión.
- **front #28 `brand_dynamic_fonts_and_reset`**: dropdown poblado por
  `GET /fonts`, botón "Reset to default" en colores + fuente, UI
  visual de "Using webhook fallback".

---

## C. Plan de ejecución (orden propuesto)

1. **Decisiones pendientes**: pregunto al usuario las 6 críticas (ver
   §D abajo).
2. **Registro features** en `feature_list.json` de ambos repos con
   ids 26-29 (continuando desde el 25 ya done).
3. **Email** primero (más independiente): back #26 → back #27 →
   front #26 → reinicio + verificación cross-repo.
4. **Brand** después: back #28 → front #28 → reinicio + verificación.
5. **Brand #29** (cascada completa) si decisión del usuario lo activa.

`one_feature_at_a_time` se respeta porque las cierro secuencialmente.
Las features de back y front del mismo id pueden trabajarse en
paralelo solo si el contrato está sellado tras el implementer del
back.

## D. Decisiones tomadas (2026-05-14, respondidas por el usuario)

### Email
1. **Provider**: SMTP genérico (stdlib `smtplib`). Env vars
   `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
   `SMTP_USE_TLS`, `SMTP_FROM_ADDRESS`, `SMTP_FROM_NAME`. Backend
   `EMAIL_BACKEND=smtp` en prod, `console` en dev/tests.
2. **De-from** (a confirmar al implementar): `notifications@4reels.ie`
   por defecto, configurable via `SMTP_FROM_ADDRESS`/`SMTP_FROM_NAME`.
3. **Multi-recipient**: **Un solo email con varios `To:` visibles**
   (los destinatarios se ven entre sí, simpler, menos requests).
   Implica:
   - 1 envío al SMTP por (agency, site, property, event_kind), pero
     **N filas** en `email_notifications` (una por destinatario) con
     el MISMO `provider_message_id` para tracking granular.
   - Si el envío falla en bloque, todas las N filas pasan a `failed`.
4. **Re-render**: si regenera y vuelve a `pending_review` (transición
   nueva), se manda un email nuevo. La key idempotente es la tupla
   `(agency, site, property, event_kind)`; si necesitas re-mandar tras
   regenerate, se emite con `event_kind='review_requested_resent'`.
   Decisión por defecto: SÍ re-mandar (más útil que silencio).
5. **Throttling**: en el worker añadiremos un guard de máx 1 envío
   por (agency, recipient) por minuto. Default suave; si se necesita
   tunear se sube/baja por env var.

### Brand
6. **Catálogo de fuentes**: MVP Google OFL. Final:
   - Inter (ya en disco).
   - Manrope.
   - Plus Jakarta Sans.
   - Montserrat.
   - Poppins.
   - Roboto.

   Quitamos Söhne y Helvetica del dropdown actual del frontend (no
   redistribuibles libres). El catálogo se ofrece via
   `GET /v1/admin/fonts` y el frontend lo popula dinámicamente.

7. **`secondary_color` en el render**: **SÍ se usa**. Específicamente
   sustituye al amarillo hardcoded `#FECF4D` del template `side_banner`
   (feature 17 del backend). El template `classic` NO lo usa (no se
   toca). Plantillas futuras decidirán caso a caso.

   Cascada: `BrandSettings.secondary_color` → `property.wppd_accent_*`
   (si webhook trae secundario; verificar) → `#FECF4D` (fallback
   global SOLO para side_banner; otras plantillas tienen su propio
   default si lo usan).

## E. Estado del repo al cerrar este turno

- Cero código tocado.
- 3 informes de exploración nuevos:
  - `progress/explore_email_notifications_back.md`
  - `4Reels-Frontend/progress/explore_email_notifications_front.md`
  - `progress/explore_brand_colors_and_fonts.md`
- 1 documento de diseño consolidado (este).
- `feature_list.json` SIN modificar (registro features `pending`
  cuando el usuario apruebe el diseño).
