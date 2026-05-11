# Feature 6 — Spike: fix_frontend_backend_payload_contract

Read-only cross-repo spike. Confirms Pydantic contracts on the back, the
exact field shapes the front sends today, and the diff/plan to align
them. Routes/verbs already match (feature 4 contract test verified);
this feature only fixes payload bodies.

Backend repo: `c:\Users\4pm\Desktop\4reels\4reels back`
Front repo:   `c:\Users\4pm\Desktop\4reels\4reels front`

---

## 1. Inventario back: contrato real aceptado por Pydantic

All four configuration/ingestion payloads use `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)` — any unknown key returns `422`.

### 1.1 `POST /v1/admin/agencies/{agency_id}/sources` → `IngestionSourceCreatePayload`
File: `modules/ingestion/transport/payloads/sources.py:8-43`
| Field | Type | Required |
|---|---|---|
| `site_id` | str (min 1) | yes |
| `name` | str (min 1) | yes |
| `kind` | str (default `"wordpress"`) | no |
| `site_url` | str \| None | no |
| `normalized_host` | str \| None | no |
| `status` | str \| None | no |
| `webhook_secret` | str \| None | no |

`extra='forbid'`: yes (line 12).

### 1.2 `PUT /v1/admin/agencies/{agency_id}/sources/{ingestion_source_id}` → `IngestionSourceUpdatePayload`
File: `modules/ingestion/transport/payloads/sources.py:46-71`. All fields optional: `name`, `site_url`, `normalized_host`, `status`, `webhook_secret`. `extra='forbid'`: yes (line 50). Router line `modules/ingestion/transport/http/sources_router.py:149` confirms PUT exists.

### 1.3 `PUT /v1/admin/agencies/{agency_id}/brand` → `BrandSettingsUpsertPayload`
File: `modules/configuration/transport/payloads/brand.py:8-59`. Accepted (all optional): `primary_color`, `secondary_color`, `logo_position`, `logo_object_key`, `intro_logo_object_key`, `font_family`. `extra='forbid'`: yes (line 18). No POST — the router upserts on PUT.

### 1.4 `PUT /v1/admin/agencies/{agency_id}/automation` → `AutomationRulesUpsertPayload`
File: `modules/configuration/transport/payloads/automation.py:8-56`. Accepted (all optional): `approval_required`, `publish_window_start`, `publish_window_end`, `publish_days`, `trigger_on_status`. `extra='forbid'`: yes (line 17). Doc-string at line 12 explicitly states `platforms` is owned by `/defaults`.

### 1.5 `PUT /v1/admin/agencies/{agency_id}/defaults` → `ReelDefaultsUpsertPayload`
File: `modules/configuration/transport/payloads/defaults.py:8-77`. Accepted (all optional): `platforms`, `duration_seconds` (5..180), `music_id`, `intro_enabled`, `caption_template`, `settings` (free-form dict, jsonb). `extra='forbid'`: yes (line 20). **Confirms `platforms` lives here** (line 47); `settings` is the canonical bucket for INITIAL_DEFAULTS.

---

## 2. Inventario front: campos enviados hoy

### 2.1 Sources — `src/features/admin/AgencyConfigDrawer.jsx`
- POST create body at lines 165-170: `{ site_id, source_name, site_url, source_status: 'active' }`.
- API helper: `src/features/admin/api.js:25-29` (`upsertAgencySource` → POST `/sources`).
- **No update path**: `startEdit` (line 147) just refills the form; `submit` always POSTs even when `editingId` is set, so editing is broken (creates a new resource or 422s on duplicate site_id).
- DELETE works: `src/features/admin/api.js:30-36`.

### 2.2 Brand — `src/features/brand/BrandConfig.jsx:53-65`
Body sent on save: `{ primary_color, secondary_color, logo_position, font, tagline, watermark_enabled, outro_enabled, outro_headline, outro_sub }`. Hook: `src/features/brand/hooks.js:19-26` passes body verbatim.

### 2.3 Automation — `src/features/automation/hooks.js:22-32`
Body sent: `{ publish_mode, platforms, review_window_enabled, review_window_hours, quiet_hours_enabled, skip_weekends, auto_captions, regen_on_update, review_emails }`. Built from state assembled in `AutomationConfig.jsx:55-67`.

### 2.4 Defaults — `src/features/defaults/hooks.js:25-32`
Body sent: `{ intro_enabled, duration_seconds, settings: <whole INITIAL_DEFAULTS state object> }`. State from `ReelDefaultsConfig.jsx:53-58`. **Does not currently send `platforms`** (despite back accepting it), and `settings` carries every UI key including outro/intro that BrandConfig also tries to persist.

---

## 3. Diff: front → back

### Sources POST `/sources`
| Campo front actual | Campo back esperado | Acción |
|---|---|---|
| `site_id` | `site_id` | keep |
| `source_name` | `name` | rename |
| `site_url` | `site_url` | keep |
| `source_status` | `status` | rename |

### Sources PUT `/sources/{ingestion_source_id}` (no existe en front)
Front debe **añadir** `reconfigureSource(agencyId, ingestionSourceId, body)` que envía `{ name, site_url?, status? }`. El id viene de `source.wordpress_source_id` (back lo devuelve duplicado bajo ambas claves: `sources_router.py:225-226, 248-249`).

### Brand PUT `/brand`
| Campo front actual | Campo back esperado | Acción |
|---|---|---|
| `primary_color` | `primary_color` | keep |
| `secondary_color` | `secondary_color` | keep |
| `logo_position` | `logo_position` | keep |
| `font` | `font_family` | rename |
| `tagline` | — | drop (back no acepta) |
| `watermark_enabled` | — | drop |
| `outro_enabled` | — | drop |
| `outro_headline` | — | drop |
| `outro_sub` | — | drop |
| (none) | `logo_object_key` | optional, no usado por UI hoy |
| (none) | `intro_logo_object_key` | optional, no usado por UI hoy |

GET de brand también debe leer `font_family` (BrandConfig.jsx:41 lee `brand?.font` — el back devuelve `font_family`).

### Automation PUT `/automation`
| Campo front actual | Campo back esperado | Acción |
|---|---|---|
| `publish_mode` | — | drop (UI-only; deriva de `approval_required`) |
| `platforms` | — | drop (mover a `/defaults`) |
| `review_window_enabled` | — | drop |
| `review_window_hours` | — | drop |
| `quiet_hours_enabled` | — | drop |
| `skip_weekends` | — | drop |
| `auto_captions` | — | drop |
| `regen_on_update` | — | drop |
| `review_emails` | — | drop |
| (none) | `approval_required` | add (mapear desde `publishMode === 'review'`) |
| (none) | `publish_window_start` | add (UI no lo expone aún — placeholder o mover a /defaults UI) |
| (none) | `publish_window_end` | add |
| (none) | `publish_days` | add |
| (none) | `trigger_on_status` | add |

### Defaults PUT `/defaults`
| Campo front actual | Campo back esperado | Acción |
|---|---|---|
| `intro_enabled` | `intro_enabled` | keep |
| `duration_seconds` | `duration_seconds` | keep |
| `settings` (INITIAL_DEFAULTS blob) | `settings` (jsonb passthrough) | keep |
| (none) | `platforms` | **add** (owner canónico, valor recibido desde UI Automation) |
| (none) | `music_id`, `caption_template` | optional, sin owner UI hoy |

**Decisión a tomar (señalada):** `feature_list.json` afirma que back acepta los nombres listados. Verificación contra schema: ✅ todos los nombres que el JSON menciona como "campos buenos" existen en Pydantic. **Ningún rename adicional necesario.**

---

## 4. Plan front (archivos:línea)

### 4.1 Sources — `src/features/admin/`
- `api.js:25-36` — añadir `reconfigureAgencySource(agencyId, ingestionSourceId, body)` con PUT a `/v1/admin/agencies/{id}/sources/{ingestion_source_id}`. Mantener `upsertAgencySource` POST (renombrarlo a `registerAgencySource` opcional).
- `AgencyConfigDrawer.jsx:132-200` — en `SourcesPanel`:
  - state form: renombrar `source_name` → `name` (lines 132-145, 156-159). Cambiar UI labels en line 244 ("Display name") sigue ok; sólo es el key del form state.
  - `submit` (lines 156-182): cuando `editingId`, llamar `reconfigureAgencySource(agencyId, editingId, { name, site_url || undefined, status: 'active' })`; cuando no, POST con `{ site_id, name, site_url, status: 'active' }`. Quitar `source_name`/`source_status`.
  - `startEdit` (line 147): sigue rellenando `name` (renombrado), pero ahora el flujo de edición funciona.
- Mensaje de validación (line 159): cambiar `'site_id and source_name are required.'` → `'site_id and name are required.'`.

### 4.2 Brand — `src/features/brand/`
- `BrandConfig.jsx:53-65` — body send: dejar `primary_color, secondary_color, logo_position`, renombrar `font` → `font_family`, **eliminar** `tagline, watermark_enabled, outro_enabled, outro_headline, outro_sub`.
- `BrandConfig.jsx:41` — leer `brand?.font_family` en lugar de `brand?.font`.
- Recomendación UX para campos huérfanos:
  - **Recomendado:** opción (a) — eliminar `tagline`/`watermark_enabled`/`outro_enabled`/`outro_headline`/`outro_sub` de la UI de Brand. **Why:** son cosméticos del preview, no tienen storage en back, y `outro` ya está cubierto por `defaults.settings.outroCard`/`introCard`. La cita del agency (`tagline`) se puede sustituir por `agency?.name` (que ya hace fallback en line 44).
  - **Abierta:** opción (c) — mover los 5 campos a `defaults.settings` con keys libres (`brand.tagline`, etc.) si el usuario insiste en persistirlos.

### 4.3 Automation — `src/features/automation/`
- `hooks.js:22-32` — body nuevo: `{ approval_required: state.publishMode === 'review', trigger_on_status: state.triggerOnStatus, publish_window_start, publish_window_end, publish_days }`. **Eliminar** todos los demás campos.
- `AutomationConfig.jsx:18-44, 51-77` — quitar state de `reviewWindow*`, `quietHours`, `skipWeekends`, `captions`, `regenOnUpdate`, `reviewEmails` salvo que se persistan vía /defaults (ver siguiente bullet).
- `AutoPublishDetails.jsx`, `ReviewModeDetails.jsx`, `ModeCard.jsx` — los toggles que dejen de persistirse:
  - **Recomendado:** opción (c) — mover `quiet_hours_enabled`, `skip_weekends`, `auto_captions`, `regen_on_update`, `review_emails`, `review_window_*` a `defaults.settings` bajo keys propias (`automation.quietHoursEnabled`, etc.) y leer/guardar desde el hook de defaults o un nuevo hook compuesto. **Why:** eliminarlos de la UI rompería funcionalidad visible y `defaults.settings` es jsonb libre por contrato (`defaults.py:71-77`); coste mecánico bajo, evita perder UX.
  - **Abierta:** opción (a) — eliminar de la UI. Solo viable si se confirma que ningún flujo de producto los necesita.
- `platforms`: leer/escribir en `useReelDefaults` (no en automation). Pasar la lista al toggle de redes en `AutoPublishDetails.jsx` desde el hook de defaults.

### 4.4 Defaults — `src/features/defaults/`
- `hooks.js:25-32` — añadir `platforms: state.platforms || []` al body. Asegurarse de que `state.platforms` se pueble desde `defaults.platforms` en `ReelDefaultsConfig.jsx:33-49`.
- `initialState.js` — añadir `platforms: ['instagram','tiktok','facebook','gbp']` y, si se acepta opción (c) de §4.3, las claves de automation (`automation.quietHoursEnabled`, etc.).
- Si el spike acepta que la UI de Automation sea el editor visible de `platforms`, entonces el componente `AutoPublishDetails` debe disparar un `useSaveReelDefaults({ ..., platforms })` además del save de automation, o (más limpio) refactor para que ambas pantallas compartan un mismo hook compuesto.

### 4.5 `tests/support/mock-backend.js`
- El mock actual (lines 210-226) responde con `{ brand:null, defaults:null, automation:null, ... }` en GET y nunca valida POST/PUT bodies (cae al fallback). **Acción mínima:** ampliar el handler para validar que el body NO contiene los campos retirados (`source_name`, `source_status`, `font`, `tagline`, `watermark_enabled`, `outro_*`, `publish_mode`, `platforms` en /automation, etc.) y devolver `422` con `{detail:[...]}` realista. Esto previene que el front "se acostumbre" a payloads que el back real rechazaría.
- Añadir handler POST/PUT explícito para `/sources` (regex `\/v1\/admin\/agencies\/[^/]+\/sources(\/[^/]+)?$`) que sólo acepte `{ site_id, name, ... }` / `{ name, site_url?, status? }`.

### 4.6 `DOCS.md` y `.env.example`
- `DOCS.md:121` — eliminar la línea `Real backend — everything mocked.` (ya no aplica desde features 2–5; el live cliente es la fuente real). Reemplazar por nota de qué módulos siguen sin endpoint real (ninguno crítico tras feature 6).
- `DOCS.md:47-48` — la frase de Brand menciona "watermark, outro card" como funciones; si se aplica opción (a) de §4.2, reescribir para eliminar esas dos. Si se aplica (c), reescribir para indicar que viven en defaults.
- `DOCS.md:53-58` — Automation: actualizar la lista de toggles si se eliminan o se mueven a defaults.
- `.env.example` — clarificar `VITE_API_URL` vs `VITE_MVP_API_URL`. Hoy: `VITE_API_URL=/api` para el mock legacy, `VITE_MVP_API_URL` para el live. Tras feature 6, `VITE_API_URL` ya no se usa para nada productivo (sólo el path de mocks vacíos). Recomendado: eliminar `VITE_API_URL` y `VITE_USE_MOCK` o documentar explícitamente que sólo cuentan en tests.

---

## 5. Plan back (cambios mínimos)

El back NO relaja Pydantic. Acciones:

- **No hay cambios de schema requeridos.** Ya cubre todos los campos canónicos (sources Create+Update, brand 6 campos, automation 5 campos, defaults 6 campos + jsonb).
- **Tests integración existentes:**
  - `tests/integration/configuration/test_brand_router.py` — GET defaults + PUT persists. ❌ NO valida que `extra='forbid'` rechace `font`/`tagline`/`outro_*`.
  - `tests/integration/configuration/test_automation_router.py:67` — `test_automation_put_rejects_platforms_field` ya cubre `platforms`. ❌ Faltan rejects para `publish_mode`, `review_window_*`, `quiet_hours_enabled`, `skip_weekends`, `auto_captions`, `regen_on_update`, `review_emails`.
  - `tests/integration/configuration/test_defaults_router.py` — existe, verificar que tenga happy-path con `platforms`.
  - `tests/integration/ingestion/test_sources_router.py` — existe (`test_sources_router_rejects_duplicate_site_id`); ❌ falta caso negativo `extra='forbid'` para `source_name`/`source_status`.
- **Tests a añadir** (uno por endpoint, parametrizado):
  - `test_brand_put_rejects_legacy_keys` con `font`, `tagline`, `watermark_enabled`, `outro_enabled`, `outro_headline`, `outro_sub` → 422.
  - `test_automation_put_rejects_legacy_keys` con `publish_mode`, `review_window_enabled`, `review_window_hours`, `quiet_hours_enabled`, `skip_weekends`, `auto_captions`, `regen_on_update`, `review_emails` → 422.
  - `test_sources_post_rejects_legacy_keys` con `source_name`, `source_status` → 422.
  - `test_sources_put_persists_partial_update` para documentar el contrato del PUT que el front empezará a usar.
  - `test_defaults_put_persists_platforms_and_settings` (si no existe) — verifica el roundtrip de `platforms`.
- **Docs:** `docs/API.md`, `docs/openapi.json`, `docs/http_surface.md` — el contrato no cambia (ya estaba así desde Phase 2/3). **No regenerar a menos que** el reviewer detecte drift; documentar en el cierre que `pytest -q` pasa sin tocar artefactos de contract.

---

## 6. Decisiones abiertas para el usuario

1. **Brand: campos huérfanos (tagline, watermark, outro).** Recomiendo eliminarlos de la UI (§4.2 opción a). Alternativa: persistir en `defaults.settings` (opción c). Decidir antes de tocar `BrandConfig.jsx`.
2. **Automation: 7 toggles huérfanos.** Recomiendo moverlos a `defaults.settings` con keys namespaced (§4.3 opción c). Alternativa: eliminarlos. La eliminación es más limpia pero supone pérdida de UX visible.
3. **Platforms: dueño visual.** Hoy el slider de redes vive en Automation (`AutoPublishDetails`). Tras la feature, ¿la UI sigue mostrándolo en Automation guardando vía `/defaults`, o se mueve la UI a la pantalla Defaults? Recomiendo mantener el slider donde está (UX) y guardar contra `/defaults` desde un hook compuesto.
4. **Renombrado de identificadores en form state.** ¿Renombrar también `form.source_name` → `form.name` en `AgencyConfigDrawer.jsx` (consistencia) o sólo el key del body? Recomiendo renombrar todo para que `grep -n source_name` quede en cero.
5. **Mock-backend más estricto.** ¿El mock debe rechazar 422 los campos retirados (riguroso) o simplemente ignorarlos (laxo)? Recomiendo riguroso para que los tests Playwright detecten regresión; eso requiere parsear el body y emular Pydantic en JS.

---

## 7. Riesgos

- **Tests Playwright:** `tests/flows.spec.js`, `tests/admin_auth.spec.js`, `tests/smoke.spec.js` no parsean payloads (el mock ignora bodies). No deberían romperse por el rename de campos. Verificar tras los cambios que ningún assert lee `source_name`/`source_status`/`font`/`publish_mode` desde state global.
- **Mock-backend** (line 211, 264): si se endurece para rechazar 422, los tests de smoke que provoquen un save desde Brand/Automation/Sources empezarán a fallar en rojo hasta migrar el front. Migración debe ser un solo PR (front + mock).
- **`docs/openapi.json` regen:** no debería diff-ear (no cambia ningún schema). Si cambia, sólo aceptar el diff que añada/quite ejemplos en `json_schema_extra`.
- **Front: edición de Sources rota hoy.** El `editingId` actual reusa `upsertAgencySource` (POST), que con el mismo `site_id` choca con el unique constraint del back. Esta feature lo arregla colateralmente al introducir el PUT.
- **`/defaults` settings shape:** el back hace merge shallow del jsonb (`defaults.py:73-76`). Si se mueven 7 keys de Automation a `settings`, hay que confirmar que el merge no las pierde al guardar parcialmente desde Defaults UI.
