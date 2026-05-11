# Review — feature 6 (fix_frontend_backend_payload_contract)

## Verdict: APPROVED

## Re-execution results (post-fix)
- Back pytest: 434 passed, exit 0 (243.30s, 14 warnings non-bloqueantes
  — `InsecureKeyLengthWarning` en `tests/unit/apps_api/test_agency_token.py`,
  pre-existentes, no relacionadas con feature 6).
- Back `apps.api --check`: exit 0 (RUNTIME READY: Yes).
- Back `apps.worker --check`: exit 0 (kinds=reel_publish, scripted_render).
- Front lint: exit 0.
- Front build: exit 0 (`built in 1.67s`).
- Front smoke: exit 0 (40 passed, 2 skipped, 47.7s).
- Front playwright `tests/payload_contract.spec.js`: exit 0
  (6 passed across desktop/tablet/mobile, 19.4s).

## Post-fix verification
- BLOCKER previo (unmapped placeholder `ingestionSourceId`): **RESUELTO**.
  Línea añadida en `tests/integration/test_http_surface_contract.py:17`
  (`"ingestionSourceId": "ingestion_source_id"`), entre `agencyId` y
  `musicId`, manteniendo el orden alfabético del dict.
- Suite cross-repo verde end-to-end: el test
  `test_frontend_api_requests_target_existing_backend_routes` pasa,
  cerrando el contrato cross-repo establecido por feature 4 de Phase 3.

## Acceptance criteria — back (feature 6)
- [x] Pydantic estricto preservado (sin cambios en payloads/routers).
- [x] Tests de integración añadidos para `/sources` (POST legacy reject +
      PUT partial), `/brand` (legacy reject parametrizado), `/automation`
      (legacy reject parametrizado), `/defaults` (namespaced settings
      round-trip).
- [x] No se aceptan campos legacy; documentación de
      `defaults.settings` como bucket canónico para los 7 toggles huérfanos.
- [x] `docs/API.md` actualizado a las tablas tipadas reales (Tenancy +
      Configuration sections).
- [x] `docs/openapi.json` / `docs/http_surface.md` no regenerados — schemas
      sin diff.

## Acceptance criteria — front (feature 6)
- [x] Sources envía `name` y `status`, no `source_name`/`source_status`
      (verificado en `AgencyConfigDrawer.jsx:159-176`).
- [x] Editar Sources usa
      `PUT /v1/admin/agencies/{agency_id}/sources/{ingestion_source_id}`
      vía `adminApi.reconfigureAgencySource` (`api.js:30-36`).
- [x] Brand envía exactamente los 6 campos canónicos
      (`BrandConfig.jsx:54-61`).
- [x] Brand lee `font_family` (`BrandConfig.jsx:45`).
- [x] Automation PUT solo `approval_required` + window/days/trigger
      (`hooks.js:25-36`); `publishMode === 'review' → approval_required:true`.
- [x] Automation no envía los 9 campos legacy (verificado por el spec
      `payload_contract.spec.js`).
- [x] Platforms persistido por `/defaults` (`useAutomationSave.js:84-90`,
      `defaults/hooks.js:36-49`); UI sigue en Automation.
- [x] `tests/support/mock-backend.js` rechaza con 422 shape Pydantic-like.
- [x] DOCS.md / `.env.example` actualizados (LEGACY note en
      VITE_API_URL/USE_MOCK).
- [x] `npm run lint`, `npm run build`, `npm run test:smoke` verdes.

## Findings
- **MINOR — ruta del nuevo spec.** El leader especificó
  `tests/playwright/payload_contract.spec.js`; el implementer lo creó en
  `tests/payload_contract.spec.js`. Funciona porque la config glob-ea
  `tests/**/*.spec.js` y los demás specs viven directos bajo `tests/`,
  así que es de hecho coherente con la convención real del proyecto.
  Documentado como decisión consolidable; no bloquea.
- **MINOR — VITE_API_URL/VITE_USE_MOCK no eliminados.** Marcados LEGACY
  en `.env.example:16-22`. Aceptable según la desviación documentada por
  el implementer del front; no bloquea.

## Cross-repo coherence
- El front renombra correctamente todos los campos legacy en form state
  y body. Grep negativo verificado: las únicas residuales son `tagline=`
  (prop label de `ModeCard` en Automation, semántica UI no relacionada
  con Brand), `mode-card-tagline` (CSS class), `outroCard / outroEnabled
  / outroFile / outroDuration` en `defaults/initialState.js` (concepto
  Defaults independiente del `outro_*` que el back rechazaba), y
  `brand-watermark` (CSS class del LivePreview, decorativa). Ninguna
  productiva.
- El mock-backend reproduce correctamente el `extra_forbidden` de
  Pydantic (`mock-backend.js:371-413`); los handlers PUT/POST parsean el
  body. Los tests Playwright `payload_contract.spec.js` ejercitan el
  contrato real (Brand canonical body + Automation split entre
  `/automation` y `/defaults`).
- Los tests negativos del back (`test_brand_put_rejects_legacy_keys`
  parametrizado x6, `test_automation_put_rejects_legacy_keys`
  parametrizado x8, `test_sources_post_rejects_legacy_keys`
  parametrizado x2, `test_sources_put_persists_partial_update` x1,
  `test_defaults_put_persists_namespaced_automation_settings` x1)
  cubren exactamente las claves que el front retira. Total nuevo:
  18 casos. Baseline 416 + 18 = 434 passed observada y reproducida.
- El placeholder `ingestionSourceId` ya está registrado en
  `tests/integration/test_http_surface_contract.py:15-23`, blindando
  el contrato del nuevo `PUT /sources/{ingestion_source_id}` introducido
  por la feature.

## Recommendation
Cerrar feature 6 en ambos repos. La feature está completa, los tests
negativos del back blindan el contrato, el front consume exactamente
los campos canónicos, y el test de contrato cross-repo (feature 4 de
Phase 3) sigue verde. Phase 4 puede darse por terminada tras este cierre.
