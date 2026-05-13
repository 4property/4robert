# Plan — Cablear "esperar antes de publicar" de Automation a GHL (v2)

> Plan persistido el 2026-05-13 por el leader, aprobado por el usuario.
> Sin implementación todavía. Las features se abren como `pending` en
> `feature_list.json` (entradas 13, 14, 15) y se ejecutarán en una
> próxima sesión, una a una, vía `implementer` + `reviewer`.

---

## 1. Contexto y diagnóstico

### 1.1 Síntoma reportado
El usuario configura un reel para que espere un tiempo antes de publicarse
desde la pestaña *Automation* del frontend y el reel se publica al
instante (no respeta el "wait").

### 1.2 Causa raíz
1. La **feature 11** (rama `ghl`, viva en `:8001`) ya cablea
   `compute_next_publish_slot` → `regenerate_reel.py` →
   `SocialPublishContext` → `MultiPlatformPublishRequest` →
   `social_service.create_social_post` con `json_body["scheduleDate"]` y
   `json_body["status"]="scheduled"`. El POST a
   `/social-media-posting/{locationId}/posts` ya sabe diferir.
2. **El front no envía los campos correctos** al PUT
   `/v1/admin/agencies/{id}/automation`. La pestaña *Automation* tiene
   tres toggles ("Hold window", "Quiet hours", "Skip weekends") que se
   persisten en `/v1/admin/agencies/{id}/defaults.settings` con claves
   namespaced (`automation.reviewWindowEnabled`,
   `automation.quietHoursEnabled`, `automation.skipWeekends`). El back
   **ignora** estas claves para calcular el slot — solo lee
   `publish_window_start/end` + `publish_days` de
   `agency_automation_rules`.
3. Sin PUT explícito a esos tres campos, el upsert de
   `automation_repository.py:44-77` aplica defaults `00:00–23:59` +
   `mon..fri`. La ventana cubre el día entero → el use case puro
   devuelve `None` (= "publicar inmediato") → GHL recibe
   `status:"published"` sin `scheduleDate` → publicación inmediata.
4. **Bug secundario de timezone**: `compute_next_publish_slot.py:131-140`
   compara `now_utc.timetz().replace(tzinfo=None)` contra
   `publish_window_start/end` parseados como `time(HH, MM)`, pero el
   usuario configura las horas en hora **local** de la agency.
   `agencies.timezone` ya existe (`shared/db/orm.py:55`) — solo falta
   threadearla.
5. El **flujo webhook auto-publish**
   (`modules/reels/application/use_cases/ingest_property_into_reel.py`)
   nunca llama a `compute_next_publish_slot` (decisión consciente
   documentada en `progress/impl_11_*.md` línea 47). El usuario ahora
   pide que también honre la ventana.

### 1.3 Outcome esperado
- Pestaña Automation persiste hold/quiet/skip en `/automation` (no en
  `/defaults.settings`).
- `compute_next_publish_slot` honra `agency.timezone`,
  `hold_window_seconds`, `quiet_hours_enabled`, `skip_weekends`.
- Approve manual **y** webhook auto-publish envían a GHL como
  scheduled cuando aplica.

---

## 2. Modelo de datos (acordado con el usuario)

Tres conceptos en la UI, tres efectos sobre el slot:

| UI control | Campo back (nuevo) | Efecto sobre slot |
|---|---|---|
| Hold window (toggle + chip 30m/1h/2h/4h/8h/24h + custom) | `hold_window_seconds INTEGER NOT NULL DEFAULT 0` | `target = now_utc + hold_window_seconds` |
| Quiet hours (toggle + time picker start/end) | `quiet_hours_enabled BOOLEAN NOT NULL DEFAULT FALSE` + reuso de `publish_window_start`/`publish_window_end` existentes | Si enabled y `target_local.time()` cae fuera de `[start, end]`, avanzar al próximo start |
| Skip weekends (toggle) | `skip_weekends BOOLEAN NOT NULL DEFAULT FALSE` + reuso de `publish_days` existente | Si enabled y `target_local.weekday() in (5,6)`, avanzar al próximo lunes a `start` |

`agencies.timezone` (IANA, ya existe en
`shared/db/orm.py:55`) se carga junto con la fila de automation y se
pasa al use case puro como kwarg explícito.

**Semántica de "publish window":** sigue representando **horas
permitidas**. La UI del front almacena `quietHoursStart=22:00,
quietHoursEnd=07:00` y al guardar invierte a
`publish_window_start=07:00, publish_window_end=22:00`. El flag
`quiet_hours_enabled` decide si se aplica esa ventana o si el slot
ignora las horas (24 h libres).

---

## 3. Trabajo cross-repo

### 3.1 Backend — 3 features (ids 13, 14, 15)

#### **Feature 13 — back-A: extender `agency_automation_rules`**

**Schema:** sí (migración Alembic).

**Archivos a tocar:**
- `alembic/versions/20260513_0003_automation_hold_quiet_skip.py` *(nuevo)*
  — añadir 3 columnas a `agency_automation_rules`:
  - `hold_window_seconds INTEGER NOT NULL DEFAULT 0`
  - `quiet_hours_enabled BOOLEAN NOT NULL DEFAULT FALSE`
  - `skip_weekends BOOLEAN NOT NULL DEFAULT FALSE`
- `modules/configuration/infrastructure/orm.py:116-143` —
  `AgencyAutomationRulesORM` (+3 columnas con `server_default`).
- `modules/configuration/domain/agency_settings.py:45-54` — dataclass
  `AutomationRules` (+3 campos al final).
- `modules/configuration/transport/payloads/automation.py:8-59` —
  `AutomationRulesUpsertPayload` (+3 campos opcionales,
  `extra='forbid'` se mantiene).
- `modules/configuration/infrastructure/automation_repository.py:44-77`
  — defaults silenciosos (`hold_window_seconds=0`,
  `quiet_hours_enabled=False`, `skip_weekends=False`).
- `modules/configuration/application/use_cases/update_automation_rules.py`
  — input DTO + use case forwardan los nuevos campos.
- `modules/configuration/application/use_cases/read_automation_rules.py`
  — sin cambios funcionales; sólo refleja el dataclass ampliado.
- Tests: extender
  `tests/integration/configuration/test_automation_router.py` y
  `tests/unit/configuration/test_update_automation_rules.py` +
  `test_read_automation_rules.py` para asertar round-trip de los nuevos
  campos.

**Validación payload:** `hold_window_seconds` ∈ [0, 86400]
(24 h máx). `publish_window_start/end` siguen sin regex en Pydantic;
la validación HH:MM defensiva queda en
`compute_next_publish_slot._parse_hh_mm` (no se cambia).

**No tocar `agencies`:** la columna `timezone` ya existe.

**Backward-compat:** los nuevos campos llegan como `None` →
upsert aplica defaults → comportamiento legacy (publicar inmediato)
preservado para agencies que no actualicen.

**Acceptance:**
- `alembic upgrade head` y `alembic downgrade -1` verdes en DB limpia.
- `pytest -q tests/integration/configuration tests/unit/configuration`
  100 %.
- PUT `/automation` con los 3 nuevos campos persiste y GET los devuelve.
- PUT que omite los campos NO los altera (`existing.<x>` se preserva
  via repository merge).

---

#### **Feature 14 — back-B: honrar timezone + hold + quiet + skip en `compute_next_publish_slot`**

**Schema:** no.

**Depende de:** feature 13 (`AutomationRules` debe tener los 3 nuevos
campos).

**Archivos a tocar:**
- `modules/configuration/application/use_cases/compute_next_publish_slot.py`
  — refactor de la firma y del algoritmo.
- `modules/reels/application/use_cases/regenerate_reel.py:236-264` —
  cargar `agency = uow.tenancy.agencies.get(agency_id)` (repo ya
  existe), pasar `agency_timezone=agency.timezone` al use case puro.
- Tests:
  - `tests/unit/configuration/test_compute_next_publish_slot.py` —
    extender (los 26 casos existentes deben seguir verdes; añadir casos
    de `hold_window_seconds > 0`, `quiet_hours_enabled=true` con
    `agency_timezone="Europe/Dublin"`, `skip_weekends=true` un sábado).
  - `tests/unit/reels/test_regenerate_reel.py` — ajustar
    `StubAutomation` (ya existe) y añadir
    `StubTenancyAgency.get_timezone`.
  - `tests/integration/reels/test_admin_reels_router.py:700-859` —
    extender los 3 tests añadidos por feature 11 con casos de hold +
    skip_weekends que crucen frontera de zona horaria.

**Firma nueva del use case puro:**

```python
def compute_next_publish_slot(
    rules: AutomationRules | None,
    now_utc: datetime,
    *,
    agency_timezone: str = "UTC",
) -> datetime | None:
```

(`hold_window_seconds`, `quiet_hours_enabled`, `skip_weekends` se leen
de `rules`. `agency_timezone` es kwarg porque vive en otra tabla.)

**Algoritmo nuevo (orden estricto):**
1. Si `rules is None` ⇒ `None`.
2. `target_utc = now_utc + timedelta(seconds=rules.hold_window_seconds)`.
3. `tz = ZoneInfo(agency_timezone)` con `try/except` → fallback a
   `ZoneInfo("UTC")` si la cadena no es IANA válida (log
   `warnings-errors.log` con `traceId`).
4. `target_local = target_utc.astimezone(tz)`.
5. Si `rules.skip_weekends` y `target_local.weekday() in (5, 6)`:
   avanzar al próximo lunes a `publish_window_start` en local.
6. Si `rules.quiet_hours_enabled` y `target_local.time()` cae fuera de
   `[publish_window_start, publish_window_end]` (soporta wrap-around):
   avanzar al próximo `publish_window_start` válido (respetando
   `publish_days` y el shift de skip_weekends ya aplicado).
7. Si `rules.quiet_hours_enabled=False` y `rules.skip_weekends=False` y
   `rules.hold_window_seconds == 0` ⇒ `None`.
8. Si tras todos los shifts `target_utc == now_utc` ⇒ `None` (preserva
   contrato actual: `null` = inmediato).
9. Else ⇒ `target_local.astimezone(timezone.utc)`.

**Caller del approve:** `regenerate_reel.py` ya carga `automation`;
añadir carga de `agency` y pasar kwarg.

**No breaking change** en el JSON enviado a GHL.

**Acceptance:**
- `tests/unit/configuration/test_compute_next_publish_slot.py` cubre
  ≥ 35 casos (26 actuales + ≥ 9 nuevos).
- `tests/integration/reels/test_admin_reels_router.py` extendido pasa
  100 %.
- Tz inválida (`agency_timezone="garbage"`) no rompe el approve; cae a
  UTC y registra warning.

---

#### **Feature 15 — back-C: wire `scheduled_at` al webhook auto-publish**

**Schema:** no.

**Depende de:** feature 14 (usa la nueva firma del use case puro).

**Archivos a tocar:**
- `modules/reels/application/use_cases/ingest_property_into_reel.py:137-176`
  — cargar `automation = uow.configuration.automation.get(agency_id)`
  + `agency = uow.tenancy.agencies.get(agency_id)`, llamar
  `compute_next_publish_slot(automation, datetime.now(timezone.utc),
  agency_timezone=agency.timezone)`, añadir `"scheduled_at": iso_or_none`
  al `publish_context`.
- `modules/reels/application/use_cases/_ingest_property_planning.py`
  (si existe el helper privado) — propagar `scheduled_at` por el dict.
- Tests:
  - Nuevo
    `tests/unit/reels/test_ingest_property_includes_scheduled_at.py`
    siguiendo el patrón de `test_regenerate_reel.py`.
  - Extender
    `tests/integration/ingestion/test_wordpress_webhook.py` (si
    existe) con un caso `approval_required=false` que sembra
    automation rules con quiet hours y verifica que
    `jobs.publish_context_json` tiene `scheduled_at` poblado.

**Decisión documentada:**
- Si `approval_required=true`, el flujo del webhook NO publica
  (espera approve manual). Sin cambios.
- Si `approval_required=false` y `compute_next_publish_slot` devuelve
  un slot, el job se enqueue con `scheduled_at` en el JSON;
  `social_service.create_social_post` enviará `status:"scheduled"` a
  GHL.
- Idempotent-replay no aplica al webhook (no hay retry humano).

**Acceptance:**
- Job persistido tras webhook con automation activa lleva
  `scheduled_at` en `jobs.publish_context_json`.
- Test integration mockea GHL y verifica `json_body["scheduleDate"]`.

---

### 3.2 Frontend — 1 feature (id 16 del front)

Ver `/opt/projects/4Reels-Frontend/progress/plan_automation_scheduling_ui.md`
y feature 16 del `feature_list.json` del front.

**Depende de:** feature 13 del back (sin schema desplegado, los PUT
explotan con 422 por `extra='forbid'`).

---

## 4. Orden de ejecución

```
back-13 (schema + payload)  ←─┐
                               ├──> back-14 (compute_slot tz/hold/flags)
                               │       └─ depende de back-13
                               │
                               └──> back-15 (webhook scheduled)
                                       └─ depende de back-14
front-16 (UI + mock + hydration)
        └─ depende de back-13
```

**Modo serial estricto** (regla del leader): back-13 ⇒ back-14 ⇒
back-15 ⇒ front-16. Sin commits intermedios. Cada feature se cierra
con `pytest -q` verde + `init.sh` verde + `apps.api --check` +
`apps.worker --check` + reviewer APPROVED.

**Coordinación cross-repo:** al cerrar back-13, el implementer del
front debe abrir su feature 16; al cerrar front-16, validar contra el
back live `:8001` antes de marcar done.

---

## 5. Reuso de utilidades existentes

- `compute_next_publish_slot` — use case puro existe con helpers
  `_parse_hh_mm`, `_normalise_publish_days`. Solo se extiende.
- `SocialPublishContext.scheduled_at` (`modules/reels/domain/types.py:59`),
  `MultiPlatformPublishRequest.scheduled_at`
  (`modules/publishing/infrastructure/adapters/gohighlevel/models.py:223`),
  `json_body["scheduleDate"]` + `json_body["status"]="scheduled"` en
  `social_service.py:117-134` — toda la cadena post-`regenerate_reel`
  está cableada. Cero cambios.
- `uow.tenancy.agencies.get(...)` — ya existe el repo de agency, sólo
  se invoca desde dos use cases (regenerate_reel y
  ingest_property_into_reel).
- `agencies.timezone` (`shared/db/orm.py:55`) — columna ya existe; no
  hace falta migración.

---

## 6. Verificación end-to-end

**Tests automatizados:**
- `pytest tests/unit/configuration/test_compute_next_publish_slot.py
   tests/unit/reels/ tests/integration/reels/
   tests/integration/configuration/ tests/integration/ingestion/ -q`
   → 100 %.
- `python -m apps.api --check` exit 0.
- `python -m apps.worker --check` exit 0.
- `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh`
  → exit 0 (con los 2 fallos preexistentes de `test_http_transport`
  que ya documentó feature 11).

**Smoke manual contra el host live (`:8001` → `https://4reelsback-test.4property.com`):**
1. Tras desplegar, `alembic upgrade head` en `miapp_test` (puerto
   5433, BBDD `miapp_test`, ver `reference_4reels_backend_runtime.md`).
2. Reiniciar API (`logs/test-api-8001.pid`).
3. Desde el admin panel: ir a *Automation*, configurar hold = 1 h,
   quiet hours 22:00–07:00 (hora local Dublin), skip weekends. Save.
4. Aprobar un reel un sábado 10:00 local. Banner debe decir
   "Publicará el lunes a las 07:00".
5. Verificar en GHL Social Planner que aparece como **Scheduled** (no
   Published) con la fecha y hora correctas en hora local de la agency.
6. Trigger del webhook WordPress con `approval_required=false`: el
   reel debe encolarse y aparecer en GHL como scheduled con la misma
   regla.

**Rollback:** cada feature es un commit lógico independiente;
`alembic downgrade -1` revierte el schema de back-13. Sin migraciones
destructivas (sólo `ADD COLUMN` con `DEFAULT`).

---

## 7. Fuera de scope (explícito)

- Validación IANA del input de timezone en `CreateAgencyModal.jsx` /
  `AgencyConfigDrawer.jsx`. La UI sigue siendo input text libre.
- Preview "próximo slot calculado" en la pestaña Automation.
- Migrar `auto_captions` / `regen_on_update` fuera de
  `defaults.settings` (no afectan al `scheduleDate`).
- Override del timezone por job al approve. Se lee siempre de
  `agencies.timezone`.

---

## 8. Notas para la próxima sesión

- El leader debe arrancar leyendo este archivo + las entradas 13, 14,
  15 del `feature_list.json`.
- Las 3 features son **secuenciales** (cada una depende de la
  anterior). No se pueden paralelizar entre `implementer`s.
- La sesión de "DB-backed render templates" registrada en
  `progress/current.md` el 2026-05-13 era un handoff aparte y NO está
  en este plan; si sigue abierta, cerrarla antes de arrancar back-13.
- Verificar que la rama desplegada en `:8001` esté limpia tras
  back-13 antes de lanzar el front (sin schema, el front explota con
  422).
