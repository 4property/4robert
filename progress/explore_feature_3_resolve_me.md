# Spike — Feature 3 (Phase 3): resolve_session_me_endpoint

> Sub-task 0 obligatoria del feature 3 de Phase 3. Read-only sobre código.
> No edita `apps/`, `modules/`, `shared/`, `tests/` (back) ni `src/`,
> `tests/` (front). El único cambio cross-archivo es el flip
> `status: pending → in_progress` en `feature_list.json` exigido por
> AGENTS.md §4 paso 4.

## 1. Resumen ejecutivo

- El front llama a `GET /me` desde una única ruta (`sessionApi.getCurrentUser()`
  en `src/features/session/api.js:5`) y la consume sólo en
  `ApiSessionProvider` (`src/features/session/SessionProvider.jsx:58-74`).
- Esa rama (`ApiSessionProvider`) está **muerta en producción y en tests**:
  `GHL_MVP_ENABLED` se lee con `import.meta.env.VITE_GHL_MVP_ENABLED === 'true'`
  (`src/features/session/ghlMvpContext.js:25`) y el `.env.example`
  documenta `VITE_GHL_MVP_ENABLED=true` (`4reels front/.env.example:18`).
  El branch alternativo (`GhlMvpSessionProvider`) construye `user` localmente
  con `buildMvpUser` / `buildMvpAdminUser` y nunca toca `/me`.
- El back no expone `/me` ni tiene tabla `users` (verificado: `grep` sobre
  `modules/` no encuentra `me_router`, `inspect_current_session` ni
  `'/me'`/`"/me"`; el directorio `modules/tenancy/transport/http/` sólo
  contiene `admin_agencies_router.py`).
- **Decisión propuesta: Opción B (eliminar `getCurrentUser` del front).**
  `Why:` la única ruta que invoca `/me` es código muerto bajo el flag actual,
  el back no tiene identidad per-usuario para servir, y todos los campos
  consumidos downstream ya están disponibles vía `ghlMvpContext` /
  `buildMvpUser` / `buildMvpAdminUser`.

## 2. Inventario de usos del retorno de `getCurrentUser()` en el front

`getCurrentUser()` se invoca desde un único punto:

```js
// 4reels front/src/features/session/SessionProvider.jsx:58-74
function ApiSessionProvider({ children }) {
  const { data, loading, error } = useApi(() => sessionApi.getCurrentUser(), []);
  if (loading) return <div className="session-fallback loading">Loading…</div>;
  if (error || !data) return <div className="session-fallback error">Could not load session.</div>;
  return <SessionContext.Provider value={data}>{children}</SessionContext.Provider>;
}
```

`SessionContext` se expone vía cuatro hooks declarados al final del mismo
archivo (`SessionProvider.jsx:312-336`):

```js
export function useCurrentUser() { /* ctx */ }
export function usePermissions() { return useCurrentUser().permissions || {}; }
export function useGhlMvp()     { return useCurrentUser().ghlMvp || null; }
export function useCurrentAgency()  { /* AgencyContext, depende de user.agencyId / user.ghlMvp.agencyId */ }
export function useCurrentAgencyId(){ return useCurrentAgency().agencyId; }
```

### 2.1 Consumidores directos del objeto `user`

| Consumidor | Línea(s) | Campo(s) leídos |
|---|---|---|
| `SessionProvider.jsx` (`ActiveAgencyProvider`) | `:169`, `:200`, `:202` | `user?.agencyId`, `user?.ghlMvp?.agencyId` |
| `MobileNav.jsx` | `:13`, `:35`, `:37`, `:38` | `user.name`, `user.avatarHue`, `user.role` |
| `Topbar.jsx` (`Topbar`) | `:21`, `:87` | `user` completo (pasa a `<UserMenu>`) |
| `Topbar.jsx` (`UserMenu`) | `:104`, `:114`, `:120`, `:122`, `:123` | `user.id`, `user.name`, `user.avatarHue`, `user.role` |

Snippets relevantes:

```jsx
// 4reels front/src/app/MobileNav.jsx:13,33-39
const user = useCurrentUser();
...
<Avatar name={user.name} color={`hsl(${user.avatarHue ?? 215}, 55%, 55%)`} />
<div className="mnav-user-name">{user.name}</div>
<div className="mnav-user-role">{user.role}</div>
```

```jsx
// 4reels front/src/app/Topbar.jsx:101-124
function UserMenu({ user, ghlMvp }) {
  const userId = ghlMvp?.userId || user.id || 'Not set';
  ...
  <Avatar name={user.name} color={`hsl(${user.avatarHue ?? 215}, 55%, 55%)`} />
  ...
  <div className="topbar-user-popover-name">{user.name}</div>
  <div className="topbar-user-popover-role">{user.role}</div>
```

### 2.2 Consumidores de `permissions`

`usePermissions()` se consume en:

| Consumidor | Línea | Uso |
|---|---|---|
| `Shell.jsx` | `:22`, `:108-116` | `permissions` → `pickLandingPath(permissions)` (devuelve `/reels` o el primer path con `can()` ok) |
| `Shell.jsx` (varios `<RequirePermission>`) | `:40-96` | indirecto: `RequirePermission` → `useCan()` → `usePermissions()` |
| `Topbar.jsx` | `:23`, `:27-29` | filtrado de `PAGES` por `can(permissions, p.requires.module, level)` |
| `useCan.js` | `:11` | base de `<Can>` y `<RequirePermission>` |

```jsx
// 4reels front/src/app/Shell.jsx:22,108-116
const permissions = usePermissions();
...
function pickLandingPath(permissions) {
  for (const page of PAGES) {
    if (!page.requires?.module) return page.path;
    if (can(permissions, page.requires.module, page.requires.level)) return page.path;
  }
  return '/reels';
}
```

### 2.3 Consumidores de `ghlMvp`

`useGhlMvp()` sólo se usa en `Topbar.jsx:22, 87` (pasado a `UserMenu`).
`UserMenu` lee `ghlMvp?.locationId`, `ghlMvp?.userId`, `ghlMvp?.connected`,
`ghlMvp?.adminMode`, `ghlMvp?.source` (`Topbar.jsx:103-105, 128, 131-132`).

### 2.4 Consumidores de `agencyId`

- `SessionProvider.jsx:169` lee `user?.agencyId || user?.ghlMvp?.agencyId`
  como `initialAgencyId` para `ActiveAgencyProvider`.
- `useCurrentAgencyId()` se consume en hooks de feature
  (`features/{reels,music,brand,social,defaults,automation}/hooks.js`,
  todas las líneas marcadas como `const agencyId = useCurrentAgencyId();`)
  y en `app/providers/TenantProvider.jsx:47` (`useCurrentAgency()`).

### 2.5 Resumen de campos del objeto `user` consumidos

`name`, `role`, `avatarHue`, `id`, `permissions`, `ghlMvp`
(con sub-campos `locationId`, `userId`, `connected`, `adminMode`, `source`,
`agencyId`), `agencyId`. **Ningún consumidor lee** `email`, `status`,
`twoFA`, `sso`, `lastSeen`, `joined` aunque `buildMvpUser` /
`buildMvpAdminUser` los rellenen (`ghlMvpContext.js:96-129, 132-172`).

## 3. Mapping campo → fuente alternativa

| Campo | Uso downstream | Fuente alternativa disponible en el front | Factibilidad | Nota |
|---|---|---|---|---|
| `name` | Avatar + label (Topbar/MobileNav) | `buildMvpUser()`/`buildMvpAdminUser()` lo derivan de `context.userName` o de env vars MVP (`ghlMvpContext.js:97, 136`) | Sí | Ya cubierto en el branch GHL_MVP del provider. |
| `role` | Etiqueta UI ("Admin"/"Super Admin"/...) | `buildMvpUser()` fija `'Admin'`; `buildMvpAdminUser()` fija `'Super Admin'` (`ghlMvpContext.js:99, 138`) | Sí | Es presentación, no autorización. La autorización va por `permissions`. |
| `avatarHue` | Color del avatar | `buildMvpUser()` fija 215; `buildMvpAdminUser()` fija 280 (`ghlMvpContext.js:103, 142`) | Sí | Cosmético. |
| `id` | Texto fallback en `UserMenu` (`ghlMvp?.userId || user.id || 'Not set'`) | `ghlMvp.userId` ya está disponible vía `useGhlMvp()` | Sí | El fallback `user.id` sólo dispara si `ghlMvp` es null, que no ocurre en el branch GHL_MVP. |
| `permissions` | `pickLandingPath`, `RequirePermission`, `Can`, filtrado de tabs | `buildMvpUser()` y `buildMvpAdminUser()` codifican el mapa hardcoded por modo (`ghlMvpContext.js:108-117, 150-158`) | Sí | El mapa per-modo ya es la fuente de verdad: agency_user `admin: 'none'`; super-admin sólo `admin: 'rw'` y `api: 'rw'`. |
| `ghlMvp.*` | UserMenu | Construido por `buildMvpUser()`/`buildMvpAdminUser()` desde `context` y `session` (`ghlMvpContext.js:118-128, 159-170`) | Sí | Idéntico hoy en branch GHL_MVP. |
| `agencyId` | `ActiveAgencyProvider` → `apiRequest('/v1/admin/agencies/{id}')` | `buildMvpUser()` lo lee de `session.agency_id` (`ghlMvpContext.js:106`) y `buildMvpAdminUser()` lo deja `null`. El POST `/v1/sessions/gohighlevel/session` ya devuelve `agency_id` (`mock-backend.js:286-294`, real back: `modules/tenancy/transport/http/admin_agencies_router.py` y `modules/sessions/...`) | Sí | Crítico. La cadena `connect → session → setUser(buildMvpUser(...))` ya rellena este campo. |
| `email`, `status`, `twoFA`, `sso`, `lastSeen`, `joined` | (ningún consumidor) | n/a | Sí | Se pueden eliminar de los builders sin tocar UI; o dejarlos como ruido inocuo. Ver "Riesgos / dudas abiertas". |

## 4. Análisis de Opción A vs Opción B

(Detalle del scope de cada opción ya está en
`feature_list.json` feature 3 → `scope.option_a_implement_back` y
`scope.option_b_remove_from_front`. Lo que sigue añade el delta del spike.)

### Opción A — Implementar `GET /v1/me` en el back

- **Archivos nuevos:** `modules/tenancy/transport/http/me_router.py`,
  `modules/tenancy/application/use_cases/inspect_current_session.py`
  (y posiblemente un `payloads.py` Pydantic). Modificar
  `apps/api/app_factory.py` para registrar el router.
- **Tests:** unit del use case (4 escenarios listados en feature_list)
  + integration del router. Smoke tests del front (`tests/smoke.spec.js`)
  necesitarían stub de `/me` en `tests/support/mock-backend.js`.
- **El use case sería casi vacío.** Tendría que clasificar la petición
  por presencia de bearer admin token vs headers de SSO de GHL, y devolver
  un objeto sintético derivado de los **mismos** datos que el front ya
  conoce. No hay tabla `users` ni `roles`; no hay capabilities almacenadas.
  El back es estado-puro de tenancy + ingestion + rendering.
- **Riesgo:** introducir un endpoint cuya única razón de existir es
  satisfacer un fetch del front que el front podría hacer localmente.
  Aumenta superficie HTTP que feature 4 (`http_surface_audit_and_contract_test`)
  tendrá que mantener.
- **Coste relativo:** 1 router + 1 use case + 4 tests + actualización
  del mock-backend. Bajo en LoC, alto en valor por LoC entregado.

### Opción B — Eliminar `getCurrentUser` del front

- **Archivos tocados (front, fase de implementación posterior):**
  `src/features/session/api.js` (borrar `getCurrentUser`),
  `src/features/session/SessionProvider.jsx` (borrar `ApiSessionProvider`,
  `useApi` import si queda huérfano, y la condicional `if (GHL_MVP_ENABLED)`
  → siempre renderizar `GhlMvpSessionProvider`),
  `src/features/session/session.css` (borrar reglas
  `.session-fallback{,*}` y la nota inicial del comentario; reglas
  `.ghl-mvp-screen` y siguientes se conservan porque
  `GhlMvpSessionProvider` las usa).
- **Archivos NO tocados:** los 4 hooks expuestos
  (`useCurrentUser`, `usePermissions`, `useGhlMvp`, `useCurrentAgency`,
  `useCurrentAgencyId`) y todos sus consumidores. El contrato del
  contexto se mantiene igual; sólo desaparece la rama que lo construía
  desde `/me`.
- **Tests:** los smoke tests de Playwright ya pasan por el branch
  GHL_MVP (todos los tests siembran `seedAgencyLocalStorage` o usan
  `?admin=1`, ver `tests/routes.js:17` y `tests/flows.spec.js:19,38,117`).
  Tras la limpieza, sólo hay que verificar que ningún test referencia
  el selector `.session-fallback` (verificado: `grep` no encuentra
  ocurrencias en `4reels front/tests/`).
- **Riesgo:** que existan ramas de despliegue donde
  `VITE_GHL_MVP_ENABLED !== 'true'`. Verificación: el `.env.example`
  documenta `=true` y los tests Playwright no setean el flag explícitamente
  (heredan el default). Si en el deploy de producción se quitase
  `VITE_GHL_MVP_ENABLED`, hoy ya estaría roto el shell (caería al
  `ApiSessionProvider` que llama a `/me` 404 → fallback de error). No
  hay evidencia de un escenario de despliegue alternativo en el repo.
- **Coste relativo:** ~30 LoC borradas en front, 0 nuevos endpoints,
  0 nuevos tests. Reduce superficie.

### Coste relativo neto

Opción B ahorra ~1 router + ~1 use case + ~4 unit tests + 1 integration
test + 1 stub del mock-backend, a cambio de borrar ~30 LoC.

## 5. Decisión final

**Opción B — eliminar `getCurrentUser` del front.**

**Why:**
1. El branch que llama a `/me` (`ApiSessionProvider`) está muerto bajo
   el flag `VITE_GHL_MVP_ENABLED=true` que documenta `.env.example` y
   que los smoke tests de Playwright suponen activo (no lo override-an).
2. El back no tiene fuente de verdad para servir `/me`: no hay tabla
   `users`, no hay capabilities almacenadas, no hay autenticación
   per-usuario. Cualquier `/me` sería un wrapper sintético sobre
   `Authorization` y headers SSO de GHL — datos que el front ya tiene
   localmente vía `ghlMvpContext` y `buildMvpUser`/`buildMvpAdminUser`.
3. Todos los campos consumidos downstream (`name`, `role`, `avatarHue`,
   `permissions`, `ghlMvp.*`, `agencyId`) tienen fuente alternativa
   ya implementada en el mismo módulo (`features/session/ghlMvpContext.js`).

## 6. Consecuencias para la implementación posterior

### 6.1 Tests E2E (Playwright)

- `tests/smoke.spec.js` y `tests/flows.spec.js` ya operan asumiendo
  el branch GHL_MVP (siembran `localStorage` o usan `?admin=1`). No
  requieren cambios de aserción; sí conviene verificar tras la
  implementación que ningún test usa el selector `.session-fallback`
  (ya verificado: `grep` no lo encuentra en `tests/`).
- `tests/support/mock-backend.js` no necesita un stub para `/me`
  (no lo tiene). En Opción A habría que añadirlo; en Opción B se
  evita el cambio.

### 6.2 Comentario residual de `/me` en `session.css`

`session.css:1` dice
`/* Session provider fallbacks (shown while /me is loading or errored). */`.
Las reglas `.session-fallback{,.loading,.error}` (`session.css:3-11`)
quedan huérfanas tras eliminar `ApiSessionProvider`. La implementación
debe **borrar la línea de comentario y las reglas `.session-fallback*`**.
Las reglas `.ghl-mvp-*` (`session.css:13-` en adelante) las usa
`GhlMvpSessionProvider` y `GhlMvpConnectScreen` y se conservan tal cual.

### 6.3 Otros sitios a tocar en la implementación

- `SessionProvider.jsx:42-56` → la condicional `if (GHL_MVP_ENABLED)`
  pasa a ser incondicional: siempre `GhlMvpSessionProvider`. Decisión
  ortogonal: ¿se borra también la constante `GHL_MVP_ENABLED` del
  export (`ghlMvpContext.js:25`)? Recomendación: dejarla por si vuelve
  a usarse, pero documentar que ya no controla un branch de provider.
- `SessionProvider.jsx:19` (`import { sessionApi } from './api.js';`)
  se mantiene: `sessionApi.createGhlMvpSession` y
  `sessionApi.testGhlMvpConnection` siguen vivos.
- `api.js:5` se borra; `api.js:6-19` se mantienen.
- `SessionProvider.jsx:18` (`import { useApi } from '../../lib/hooks/useApi.js';`):
  comprobar si queda huérfano tras borrar `ApiSessionProvider` (sí, lo es;
  borrar el import).

### 6.4 Documentación

- `docs/API.md` (back): añadir nota en sección Sessions: "el back NO
  expone `GET /me`. La identidad efectiva la deriva el front desde
  el bearer admin token (modo super-admin) o desde el SSO context de
  GHL (modo agency_user). Ver `4reels front/src/features/session/`."
- `REFACTOR_STATUS.md` (back): la línea de auditoría 2026-05-06
  (`REFACTOR_STATUS.md:267-278`) que enumera `/me` como pendiente puede
  actualizarse al cierre de la feature.

## 7. Riesgos / dudas abiertas

1. **¿Hay un entorno de despliegue real donde
   `VITE_GHL_MVP_ENABLED !== 'true'`?** Si lo hay, hoy ya está roto
   (cae al fallback de error de `ApiSessionProvider`). El repo no tiene
   evidencia de tal entorno. Acción sugerida: el leader confirma con el
   usuario antes de implementar Opción B; si existe, puede aún preferirse
   Opción B + simplificación del `if (GHL_MVP_ENABLED)` (es decir, hacer
   el provider GHL incondicional y aceptar que el modo "API session"
   muere de forma explícita).

2. **Limpieza opcional de campos no consumidos en `buildMvpUser` /
   `buildMvpAdminUser`** (`email`, `status`, `twoFA`, `sso`, `lastSeen`,
   `joined`): no es necesaria para cerrar feature 3 y aumenta el
   alcance del PR. Recomendación: NO tocar en esta feature; abrir
   issue separado en `4reels front/feature_list.json` si se decide
   limpiar.

3. **`ApiError` en consola para llamadas previas a `/me`.** Hasta que
   la feature se implemente, cualquier despliegue accidental sin
   `VITE_GHL_MVP_ENABLED=true` mostraría la pantalla "Could not load
   session." y un error en consola. Es estado actual, no introducido
   por el spike. La implementación de Opción B lo elimina por
   construcción.

4. **Coordinación cross-repo.** La implementación de la decisión es
   front-only (Opción B) y el back queda intacto. La regla de Phase 3
   §3 obliga a abrir entrada equivalente en
   `4reels front/feature_list.json` antes de tocar `src/`. El leader
   debe lanzar el implementer del front con esa instrucción explícita.
   Detalle observado: `4reels front/feature_list.json` actualmente
   sólo contiene la entrada de feature 2 (cerrada); habrá que añadir la
   nueva entrada para feature 3 al iniciar la implementación.

5. **Tentación de "arreglar de paso" detectada y NO aplicada.** En
   `ghlMvpContext.js:16-23` el array `USER_PARAM_NAMES` repite
   `'user_id'` dos veces (líneas 17 y 22). Es un bug menor (no cambia
   comportamiento porque `readParam` toma el primer match). Anotado
   aquí; no editado por la regla read-only del spike.
