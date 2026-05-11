# Phase 4 — Operating Rules (frontend/backend live contract hardening)

> **Phase 4 cerrada el 2026-05-07** con las features 5 y 6. Este documento
> es post-mortem ligero: scope final, lecciones aprendidas y backlog
> candidate para una eventual Phase 5 (no aprobada).
>
> Para contexto retrospectivo de Phase 3, ver
> `docs/phase_3_operating_rules.md`.

---

## 1. Scope final

Phase 4 fueron **2 features cross-repo**, ambas APPROVED en review (la
feature 6 con un único fix mecánico post-review trivial sobre el
placeholder `ingestionSourceId` en `tests/integration/test_http_surface_contract.py`).

| # | Feature | Repos | Resultado |
|---|---|---|---|
| 5 | `frontend_admin_auth_lockstep` | back + front | done (APPROVED) |
| 6 | `fix_frontend_backend_payload_contract` | back + front | done (APPROVED tras fix mecánico) |

**Lo que cambió:**

- `apps/api/admin_auth.py` acepta dos modos de auth para `/v1/admin/*`:
  super-admin token (`ADMIN_API_TOKEN`) y agency-scoped JWT HS256
  stateless emitido por `POST /v1/sessions/gohighlevel/session` (scope
  `agency`, issuer `4reels-back`). Rechazo cross-tenant probado.
- Frontend adjunta `Authorization: Bearer <token>` desde
  `src/lib/api/authToken.js` (sessionStorage `4reels.adminBearer`).
  Admin-direct mode con input local oculto detrás de `MVP_ADMIN_ENABLED`
  (sin `VITE_ADMIN_API_TOKEN` ni secretos en el bundle).
- Pydantic estricto (`extra='forbid'`) preservado en `/sources`,
  `/brand`, `/automation`, `/defaults`. El frontend envía exactamente
  los campos canónicos; los 7 toggles huérfanos de Automation +
  `platforms` se persisten en `defaults.settings` con keys namespaced
  (`automation.<key>`) vía un hook compuesto (`useAutomationSave`) que
  dispara PUT `/automation` + PUT `/defaults` con shallow-merge previo.
- 18 tests negativos parametrizados nuevos en el back blindan los
  campos legacy retirados.

**Verificación final:**
- Back `pytest -q` 434 passed (baseline Phase 2 394 + 22 feature 5 + 18
  feature 6); `apps.api --check` y `apps.worker --check` exit 0.
- Front `npm run lint` verde, `npm run build` verde, `npm run test:smoke`
  40 passed/2 skipped, `tests/admin_auth.spec.js` 9 passed,
  `tests/payload_contract.spec.js` 6 passed.

---

## 2. Lecciones aprendidas

### 2.1 Cross-repo coordination en serie es viable y barato

Phase 4 ejecutó las 2 features en modo serial estricto (mismo modelo que
Phase 3). Cada feature tenía dos lados (back + front) que el implementer
producía dentro de la misma sesión de trabajo, y un único reviewer
validaba ambos. El coste de orquestación fue bajo porque:

- Ambos repos comparten `feature_list.json` con id alineado (id 5 y 6 en
  los dos).
- Cada implementer escribe `progress/impl_<id>_<name>_{back,front}.md`
  separados, y el review unifica con un `progress/review_<id>_<name>.md`
  en el back.
- El test de contrato cross-repo (`tests/integration/test_http_surface_contract.py`,
  feature 4 de Phase 3) detecta drift entre `apiRequest(...)` del front
  y rutas FastAPI vivas; sirve de safety net automático en cada cierre.

### 2.2 JWT HS256 stateless es suficiente para el alcance actual

La feature 5 evaluó (back) emitir tokens en una tabla `agency_sessions`
vs. JWT stateless. Se eligió JWT HS256 con scope `agency` + issuer
`4reels-back` + TTL configurable. Razón: no hay revocación per-sesión
necesaria (el TTL corto + reset del cliente es suficiente), y evita una
tabla nueva con su migración. Si en Phase 5 aparece un caso de
revocación selectiva (logout forzado de una sesión específica), habrá
que migrar a stateful.

### 2.3 Hook compuesto en automation funcionó, pero requiere disciplina

`useAutomationSave` dispara dos PUTs (`/automation` + `/defaults`) con
shallow-merge previo del `settings` blob para no pisar keys de otros
tabs. Funcionó porque:

- El front nunca calcula `settings` desde cero; siempre lee el
  `defaults.settings` actual antes de mergear.
- Las keys namespaced (`automation.<key>`) hacen que cada tab "posea"
  su slice del blob sin colisiones.

Riesgo latente: si alguien añade una key huérfana sin namespacing, va a
chocar. La convención está documentada en `docs/API.md` § Configuration.

### 2.4 Mock-backend riguroso es la única defensa de los specs Playwright

`tests/support/mock-backend.js` ahora reproduce el `extra_forbidden` de
Pydantic con shape exacto (`{detail:[{loc:['body',<field>],
msg:'Extra inputs are not permitted', type:'extra_forbidden'}]}`).
Lección: si el mock acepta laxo lo que el back rechaza estricto, los
specs pasan en CI y rompen en producción. Cada vez que el front retira
un campo, el mock debe rechazarlo en el handler correspondiente.

### 2.5 Spike previo paga la deuda en una iteración

Las dos features tuvieron spike previo (`progress/explore_feature_5_back_auth.md`,
`progress/explore_feature_6_payload_contract.md`) que mapeó el estado
actual del código antes de tocar nada. Resultado: feature 6 descubrió
que Pydantic ya tenía `extra='forbid'` en los 4 endpoints relevantes y
el lado back se redujo a tests negativos + docs (cero cambio de
schemas/routers/use cases).

---

## 3. Backlog candidate para Phase 5 (NO aprobado)

Estos items quedaron fuera del scope de Phase 4 y son razonables como
arranque de Phase 5 si el usuario aprueba alcance. Ninguno es bloqueante.

- **Multi-provider real en `provider_connections`.** Hoy sólo
  `gohighlevel`; el schema (`provider` discriminator) lo permite.
  Validar la abstracción añadiendo un segundo adaptador (Meta, otra
  integración CRM).
- **Multi-source de ingestión.** Hoy sólo `wordpress`. Validar el
  `kind` discriminator de `ingestion_sources` con un segundo adapter
  (CSV upload, feed RSS, API REST de un CRM inmobiliario).
- **Dashboard operativo de jobs/outbox.** Visibilidad de qué pasa en el
  worker (`pending`/`processing`/`failed`, retries, outbox pendiente).
  Endpoint `/v1/admin/ops/*` + UI en el front.
- **Hardening de observabilidad.** Métricas Prometheus, traces
  OpenTelemetry, alertas sobre `outbox_events.status='failed'` y
  `jobs.status='failed' AND attempts >= max_attempts`.
- **Migración `WEBHOOK_*` → `INGEST_*`.** Renombrar las env vars del
  webhook de WordPress (`WEBHOOK_PATH`, `WEBHOOK_HOST`,
  `WEBHOOK_SITE_SECRETS`, etc.) a `INGEST_*` para alinear con el rename
  `WEBHOOK_WORKER_*` → `WORKER_*` ya hecho en Phase 1.
- **Eliminar `VITE_API_URL` / `VITE_USE_MOCK`** del `.env.example` del
  front (hoy marcados LEGACY tras feature 6). Requiere migrar el
  fallback de `BASE_URL` en `src/lib/api/client.js` a `VITE_MVP_API_URL`
  exclusivamente y dar aviso a entornos locales.
- **Revocación selectiva de agency JWT.** Si aparece la necesidad de
  forzar logout de una sesión sin cambiar `ADMIN_AGENCY_TOKEN_SECRET`
  global, migrar a stateful con tabla `agency_sessions`.

**Cualquier item que el usuario apruebe se mueve a `feature_list.json`
con scope ejecutable y se cubre con un nuevo spike previo.**
