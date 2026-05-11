# Feature 6 — Implementation report (BACK side)

## Resumen

El back ya tenía Pydantic estricto (`extra="forbid"`) en los 4 endpoints
involucrados (Brand, Automation, Sources POST/PUT, Defaults), tal y como
documentaba el spike `progress/explore_feature_6_payload_contract.md` §1. La
implementación back-side de la feature 6 es por tanto puramente defensiva:
añade tests de integración que documentan el contrato (rechazo 422 de los
campos legacy que el frontend retira en su lado de la feature, y persistencia
del PUT parcial de Sources que el front empezará a usar) y actualiza
`docs/API.md` § Tenancy model + § Configuration sections para reflejar las
tablas tipadas reales (`agency_brand_settings`, `agency_reel_defaults`,
`agency_automation_rules`, `agency_social_templates`) en lugar del antiguo
`reel_profiles` con `extra_settings_json`. Cero cambios en routers, schemas,
use cases, repositorios u ORM.

## Archivos modificados

| Archivo | Tipo | Cambio |
|---|---|---|
| `feature_list.json` | metadata | feature 6 → `in_progress` |
| `progress/current.md` | tracking | plan + bitácora real-time |
| `tests/integration/configuration/test_brand_router.py` | test | +`test_brand_put_rejects_legacy_keys` (parametrizado, 6 casos: `font`, `tagline`, `watermark_enabled`, `outro_enabled`, `outro_headline`, `outro_sub`) |
| `tests/integration/configuration/test_automation_router.py` | test | +`test_automation_put_rejects_legacy_keys` (parametrizado, 8 casos: `publish_mode`, `review_window_enabled`, `review_window_hours`, `quiet_hours_enabled`, `skip_weekends`, `auto_captions`, `regen_on_update`, `review_emails`) |
| `tests/integration/ingestion/test_sources_router.py` | test | +`test_sources_post_rejects_legacy_keys` (parametrizado, 2 casos: `source_name`, `source_status`) y +`test_sources_put_persists_partial_update` (1 caso) |
| `tests/integration/configuration/test_defaults_router.py` | test | +`test_defaults_put_persists_namespaced_automation_settings` (documenta el bucket `defaults.settings` para los 7 toggles huérfanos de Automation, decisión cerrada del usuario) |
| `docs/API.md` | docs | § Tenancy model + § Configuration sections actualizadas a las tablas tipadas reales y a los campos canónicos por endpoint; añadida nota explícita de qué keys el back rechaza con 422 |

Sin cambios en `apps/`, `modules/<bc>/`, `shared/`, `settings/`, `alembic/`,
`docs/openapi.json`, `docs/http_surface.md`. No se ejecutó `alembic`. No se
hizo `git commit`.

## Tests añadidos

- Brand: 6 casos parametrizados (1 nueva función).
- Automation: 8 casos parametrizados (1 nueva función). El test pre-existente
  `test_automation_put_rejects_platforms_field` se mantiene como caso aparte
  para preservar la documentación explícita del owner canónico de
  `platforms`.
- Sources POST: 2 casos parametrizados (1 nueva función).
- Sources PUT partial update: 1 caso (1 nueva función).
- Defaults namespaced settings: 1 caso (1 nueva función).

**Total casos de test nuevos:** 18 (4 archivos modificados, 5 funciones de
test nuevas).

**Conteo final:** 416 (baseline post-feature-5) + 18 = **434 passed**.

## Comandos ejecutados

```
$ bash ./init.sh
[OK]   Python 3.13.0
[OK]   apps.api --check verde
[OK]   apps.worker --check verde
434 passed, 14 warnings in 259.61s (0:04:19)
[OK]   Entorno listo.
```

(`init.sh` corrió en Bash; no hizo falta el equivalente PowerShell. Los 14
warnings son `InsecureKeyLengthWarning` pre-existentes de tests JWT, no
introducidos por esta feature.)

## Decisiones no obvias

1. **Test `test_defaults_put_persists_namespaced_automation_settings`**:
   añadido aunque el spike sólo lo exigía si no existía `platforms_and_settings`
   (que sí existe). Lo añado igual porque documenta explícitamente la
   decisión cerrada del usuario (Automation 7 toggles huérfanos van a
   `defaults.settings` con keys namespaced). Cobertura de regresión barata
   y autoexplicativa.
2. **Actualización de `docs/API.md` más allá de § Configuration**: la sección
   § Tenancy model también describía el modelo `reel_profiles` +
   `extra_settings_json`, que ya no existe (la migración a tablas tipadas
   ocurrió en Phase 2). Lo dejé alineado para que un lector nuevo no se
   confunda; cambio puramente documental, no toca contrato HTTP.
3. **`docs/openapi.json` y `docs/http_surface.md` no regenerados**: ningún
   schema cambia, así que no debería haber drift. Si el reviewer detecta
   diff lo discutimos; no lo regenero preventivamente.

## Estado

`in_progress`. NO marcado `done` (a la espera de revisor).

## Post-review fix

El reviewer (`progress/review_6_fix_frontend_backend_payload_contract.md`)
reportó UN solo BLOCKER: el test cross-repo
`tests/integration/test_http_surface_contract.py` fallaba con
`Unsupported apiRequest expressions: src\features\admin\api.js:31: unmapped placeholder 'ingestionSourceId'`
porque el dict `PLACEHOLDER_NAMES` no contemplaba el placeholder
`ingestionSourceId` que el front introdujo en `reconfigureAgencySource`
(`4reels front/src/features/admin/api.js:30-36`, PUT con
`${encodeURIComponent(ingestionSourceId)}`).

**Fix aplicado:** añadida una entrada al dict, manteniendo orden
alfabético.

| Archivo | Línea | Cambio |
|---|---|---|
| `tests/integration/test_http_surface_contract.py` | 17 | `+    "ingestionSourceId": "ingestion_source_id",` |

**Conteo final post-fix:** `434 passed, 14 warnings in 221.74s` (era
433 passed + 1 failed antes del fix). `python -m apps.api --check`
exit 0. `python -m apps.worker --check` exit 0.

Cierre formal pendiente del agente de cierre (no marco `done` yo).
