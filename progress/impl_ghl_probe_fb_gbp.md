# Impl report — feature 7 `ghl_probe_fb_gbp`

- Status: **blocked** (no code changes applied).
- Date: 2026-05-11.
- Agent: implementer (Opus 4.7 1M).
- Module touched: `modules/publishing/` (investigation only — no edits).
- Schema?: No.

## TL;DR

El endpoint `POST /v1/admin/agencies/{agency_id}/ghl-connection/test` se queda
en 4 cuentas porque el token de GoHighLevel guardado para la location
`v8H1XNB3YCQmVHRhqDoM` (Location API key de 40 caracteres) **no tiene scope**
para invocar `GET /social-media-posting/oauth/{platform}/accounts`. La ruta
existe (devuelve `401 "The token is not authorized for this scope."`, no 404),
pero el resto de variantes que harían visibles Facebook Pages y Google Business
Profile devuelven 404 con cualquier token. Sin un token nuevo (OAuth
Marketplace App con los scopes `socialplanner/oauth.readonly` o equivalentes)
no hay forma de listar estas cuentas desde la API. **No se modifica código;
la solución pasa por reemplazar el token o ajustar el contrato del frontend.**

## Investigación API (rutas probadas, 2026-05-11)

Base URL: `https://services.leadconnectorhq.com`. Header `Version: 2021-07-28`.
Token: Location API key (`pit-...`-style, 40 chars) extraído de
`provider_connections.secrets_encrypted` para
`location_id=v8H1XNB3YCQmVHRhqDoM`.

### Endpoints accesibles con el token actual

| Método | Ruta | Resultado |
|--------|------|-----------|
| GET | `/social-media-posting/{locationId}/accounts` | 200 — 4 cuentas (Instagram, LinkedIn, TikTok, YouTube). `results.groups` vacío. |
| GET | `/social-media-posting/{locationId}/accounts?platform=facebook` | 200 — `results.accounts: []`. |
| GET | `/social-media-posting/{locationId}/accounts?platform=google` | 200 — `results.accounts: []`. |
| GET | `/social-media-posting/{locationId}/categories` | 200 — `{categories: [], count: 0}`. |
| GET | `/social-media-posting/{locationId}/tags` | 200 — sin tags. |
| GET | `/locations/{locationId}` | 200 — perfil de location. |
| POST | `/social-media-posting/{locationId}/posts/list` | 200 — lista de posts ya publicados (incluye `platform: instagram`). |

### Endpoints que existen pero requieren scope distinto (401, no 404)

Todas con `?locationId=v8H1XNB3YCQmVHRhqDoM` y método `GET`. Respuesta:
`{"statusCode":401,"message":"The token is not authorized for this scope."}`.

- `/social-media-posting/oauth/facebook/accounts`
- `/social-media-posting/oauth/google/accounts`
- `/social-media-posting/oauth/instagram/accounts`
- `/social-media-posting/oauth/tiktok/accounts`
- `/social-media-posting/oauth/linkedin/accounts`
- `/social-media-posting/oauth/youtube/accounts`

El patrón `/social-media-posting/oauth/{platform}/accounts` es el canónico para
listar todas las cuentas/pages/locations OAuth disponibles para ese tenant.
Como el token no acepta este scope, *no* podemos enumerar Facebook Pages ni
Google Business Profile locations desde la API en este momento.

### Endpoints que NO existen (404)

Probados para cerrar incertidumbre:

- `/social-media-posting/{locationId}/groups`
- `/social-media-posting/{locationId}/posts`
- `/social-media-posting/{locationId}/statistics`
- `/social-media-posting/{locationId}/oauth-accounts`
- `/social-media-posting/{locationId}/all-accounts`
- `/social-media-posting/oauth/{locationId}/{platform}/accounts` (y variantes)
- `/social-media-posting/oauth/{platform}/pages`, `.../locations` para
  `platform in {facebook, google, instagram, tiktok, linkedin, youtube}`
- `/social-media-posting/oauth/{platform}` (sin sub-recurso)
- `/social-media-posting/accounts/oauth/{platform}`
- `/oauth/facebook/accounts`
- `/locations/{locationId}/integrations`
- `/integrations?locationId={locationId}`

### Parámetros adicionales

- `GET /social-media-posting/{locationId}/accounts?includeAll=true` → 422
  Unprocessable Entity. Idem con `includeGroups=true` / `all=true`. La API no
  soporta filtros para ampliar el listado.

## Causa raíz

`GET /social-media-posting/{locationId}/accounts` devuelve únicamente las
cuentas que el composer de GHL marca como "selected" para postear desde la
suite de Social Planner. Facebook Page y Google Business Profile, aunque
conectadas a la location, no aparecen en este endpoint con el token Location
API key. El endpoint que sí las listaría
(`/social-media-posting/oauth/{platform}/accounts`) está protegido por el
scope `socialplanner/oauth.readonly` (o equivalente Marketplace OAuth), y el
token guardado no lo posee. No es un bug del backend ni del adapter actual:
es un techo del contrato `API key` ↔ scopes.

## Workarounds posibles (decisión del leader)

1. **Recomendado (correcto)**: emitir un Access Token OAuth desde la app
   Marketplace de 4Reels (flujo `/oauth/chooselocation` →
   `/oauth/token`) con los scopes `socialplanner/account.readonly` +
   `socialplanner/oauth.readonly` (y los de post si no se tienen ya).
   Persistirlo en `provider_connections` y reemplazar el flujo de
   `attach_provider_connection`. Esto desbloquea no sólo el probe sino
   cualquier listado OAuth futuro (refresh tokens, expiry tracking real).
   Coste: requiere SSO/OAuth UI en el admin del front y un cliente OAuth
   registrado en Marketplace.

2. **Mitigación rápida (frontend)**: cambiar el copy en
   `AgencyConfigDrawer.jsx:407` de "social accounts available" a
   "social accounts ready for direct publishing" para que el `account_count`
   no se interprete como inventario total. El usuario podrá ver Facebook y
   Google directamente en la UI de GHL.

3. **Alternativa híbrida**: parsear el sub-account profile en
   `/locations/{locationId}` por si lleva metadata de páginas conectadas.
   Verificado: el payload de `/locations/{locationId}` no expone esa lista,
   sólo datos demográficos del sub-account. Descartado.

## Por qué no toco código

El comportamiento actual es coherente con lo que devuelve la API para el
token disponible. Añadir llamadas a `/social-media-posting/oauth/{platform}/accounts`
sería ruido: devolverán 401 igual y degradarían la UX (probe lento + errores).
Si el leader aprueba la ruta (1), el cambio de adapter es trivial y se cubre
en una feature posterior tras el rollout del flujo OAuth Marketplace.

## Verificación (no se ejecuta pytest porque no hay cambios)

- `./init.sh`: no relevante para esta feature (no edits en `apps/`, `modules/`,
  `shared/`, `tests/`).
- Estado entorno (heredado de `progress/current.md`): API y worker `--check`
  exit 0; `pytest -q --ignore=tests/integration/test_http_surface_contract.py`
  → 433 passed.

## Archivos tocados

- `feature_list.json`: nueva entrada `id: 7`, status `blocked`.
- `progress/current.md`: bitácora actualizada.
- `progress/impl_ghl_probe_fb_gbp.md`: este informe.

Sin cambios en `modules/publishing/` ni en tests.

## Próximo paso

Decisión del leader entre opciones 1 (OAuth scopes) y 2 (copy del front).
Si se elige (1), abrir feature nueva `ghl_marketplace_oauth_token` antes de
retomar este probe.
