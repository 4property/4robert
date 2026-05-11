# Spike — Feature 5 (back side): `frontend_admin_auth_lockstep`

> Read-only exploration. Mapea el contrato de auth admin actual del back y propone
> el contrato live para que el frontend pueda operar contra `/v1/admin/*` sin
> hardcodear el `ADMIN_API_TOKEN` en el bundle. Cross-repo: ver
> `4reels front/progress/explore_feature_5_admin_auth.md` (a abrir por el front).

## 1. Estado actual del back

### 1.1 Validación de `Authorization` en `/v1/admin/*`

- **Módulo central**: `apps/api/admin_auth.py`.
  - `AdminAccessPolicy` dataclass — `apps/api/admin_auth.py:23-31`.
  - `build_admin_access_policy(...)` — `apps/api/admin_auth.py:33-54`.
  - `extract_bearer_token(...)` — `apps/api/admin_auth.py:57-66`.
  - `authorize_admin_request(request, policy)` — `apps/api/admin_auth.py:83-193`.
- **Patrón de aplicación**: NO se usa como `Depends(...)` de FastAPI. Cada handler
  llama `authorization_error = authorize_admin_request(request, admin_access_policy);
  if authorization_error is not None: return authorization_error` al inicio.
  Ejemplo canónico: `modules/tenancy/transport/http/admin_agencies_router.py:73-75,94-96`.
- **Política actual**:
  - Si `policy.enabled` es `False` → 404 `ADMIN_API_DISABLED`.
  - Si `policy.disable_auth_for_testing` → bypass con WARNING (línea 105-121).
  - Si `policy.bearer_token == ""` → 503 `ADMIN_API_NOT_CONFIGURED`.
  - Si no llega `Authorization: Bearer …` → 401 `ADMIN_AUTH_REQUIRED`.
  - Si el token no matchea (`secrets.compare_digest`) → 401 `INVALID_ADMIN_TOKEN`.
- **Routers que usan la policy** (13, todos via `admin_access_policy=` en
  `apps/api/app_factory.py:288-362`):
  - `modules/tenancy/transport/http/admin_agencies_router.py`
    (`/v1/admin/agencies`, `/v1/admin/agencies/{agency_id}`).
  - `modules/publishing/transport/http/connections_router.py`
    (`/v1/admin/agencies/{agency_id}/gohighlevel/...`).
  - `modules/publishing/transport/http/social_accounts_router.py`
    (`/v1/admin/agencies/{agency_id}/social-accounts`).
  - `modules/ingestion/transport/http/sources_router.py`
    (`/v1/admin/agencies/{agency_id}/sources/...`).
  - `modules/ingestion/transport/http/wordpress_sources_router.py`
    (`/v1/admin/wordpress-sources` global).
  - `modules/configuration/transport/http/{brand,defaults,automation,music,reel_profile,social_templates}_router.py`
    (todos `/v1/admin/agencies/{agency_id}/...`).
  - `modules/reels/transport/http/admin_reels_router.py` (+ `admin_reels_assets.py`).

### 1.2 Settings involucradas

Definidas en `settings/app.py:212-227` y reexportadas por `settings/admin.py:5-8`:
- `ADMIN_API_ENABLED` (default `True`).
- `ADMIN_API_BASE_PATH` (default `/v1/admin`).
- `ADMIN_API_TOKEN` (default `""`; sin valor → 503).
- `ADMIN_API_DISABLE_AUTH_FOR_TESTING` (default `False`).

Inyectadas en la app via kwargs de `build_api_app(...)` (`apps/api/app_factory.py:113-200`)
y materializadas en `AdminAccessPolicy` (línea 195-200).

### 1.3 Endpoint de sesión GHL

- **Router**: `modules/publishing/transport/http/sessions_router.py` (sin
  `admin_access_policy`, prefix `/v1/sessions/gohighlevel`).
- **`POST /v1/sessions/gohighlevel/session`** — `sessions_router.py:138-164`.
  - Use case: `InspectSessionStatusUseCase`
    (`modules/publishing/application/use_cases/inspect_session_status.py:30-55`).
  - Lógica: dado `{location_id, user_id}`, busca en
    `provider_connections` por `(provider="gohighlevel", external_id=location_id)`.
  - Devuelve `{ok, location_id, user_id, connected, has_token, agency_id}`
    (`SessionStatus.to_dict` — línea 19-27).
  - **No persiste nada**: solo lee `provider_connections` (escritas vía OAuth/admin).
  - **No emite ningún token propio del back** — solo confirma si existe y a qué
    agencia pertenece la location.

### 1.4 ¿Existe noción de "agency-scoped token"?

**No**. El back hoy solo conoce dos modos:
1. Bearer token global = `ADMIN_API_TOKEN` (super-admin, sin scoping).
2. Bypass total via `ADMIN_API_DISABLE_AUTH_FOR_TESTING` (solo tests).

El concepto se diseña desde cero. No hay tabla `agency_sessions`, ni JWT, ni
ningún campo en `provider_connections` que sirva como token de sesión emitida
por el back. La identidad agency se deriva implícitamente del SSO de GHL pero
no se materializa en un token de back.

## 2. Diseño propuesto del contrato live

### 2.1 Emisión del token tras sesión GHL válida

**Recomendación: JWT firmado HS256 con secret server-side, stateless, TTL corto.**

| Opción | Pros | Contras |
|---|---|---|
| **A. JWT HS256** stateless | Sin tabla nueva ni round-trip a DB; revocación implícita por TTL corto; payload auto-contenido (`agency_id`, `location_id`, `user_id`, `exp`); librería estándar (`PyJWT`). | Revocación inmediata imposible sin denylist; secret key management. |
| B. Token opaco + `agency_sessions` | Revocación trivial (DELETE row); auditoría natural. | Requiere migración Alembic; round-trip a DB en cada request `/v1/admin/*`; más superficie operativa. |
| C. Reutilizar el bearer GHL | Cero código nuevo. | El back tendría que llamar al provider GHL para validar **cada** request → latencia y dependencia externa; expone secretos GHL al cliente. **Descartada**. |

**Why (A):** la sesión GHL ya es de duración corta (iframe), el TTL de 30-60 min
encaja, no hace falta revocación inmediata por agencia (super-admin sigue
siendo el camino de emergencia), y evita migración Alembic en una feature
ortogonal. Si en el futuro se necesita revocación, se añade tabla `revoked_jtis`
con (jti, expires_at) sin romper el contrato.

**Payload sugerido (claims)**:
```
{
  "sub": "<user_id GHL>",
  "agency_id": "<uuid>",
  "location_id": "<location GHL>",
  "scope": "agency",            // distingue de un eventual super-admin futuro
  "iat": 1730000000,
  "exp": 1730003600,            // TTL 60 min
  "jti": "<uuid4>",             // para denylist futura
  "iss": "4reels-back"
}
```

### 2.2 Almacenamiento y expiración

- **Stateless**: no se guarda en DB. El back reconstruye la identidad del JWT
  en cada request validando firma + `exp`.
- **TTL**: 60 minutos (configurable via nuevo setting `ADMIN_AGENCY_TOKEN_TTL_SECONDS`).
- **Rotación**: el front pide un nuevo token llamando otra vez a
  `POST /v1/sessions/gohighlevel/session` cuando faltan <5 min para `exp` o tras 401.
- **Secret**: nuevo setting `ADMIN_AGENCY_TOKEN_SECRET` (env var). Sin default;
  si está vacío, el back NO emite tokens (responde sin `agency_token` o 503 según
  decisión del implementer; recomendado: 503 `AGENCY_AUTH_NOT_CONFIGURED` para no
  silenciar mal config en producción).

### 2.3 Propagación al frontend

- `POST /v1/sessions/gohighlevel/session` extiende su respuesta:
  ```
  {
    "ok": true, "location_id": "...", "user_id": "...",
    "connected": true, "has_token": true, "agency_id": "<uuid>",
    "agency_token": "<jwt>",           // NUEVO, solo si connected=true
    "agency_token_expires_at": "2026-05-07T15:00:00Z"  // NUEVO
  }
  ```
- El front lo guarda en memoria (preferido) o `sessionStorage`, lo añade como
  `Authorization: Bearer <jwt>` en `getAuthHeaders()` y lo limpia al reset/logout.
- Para el modo super-admin local del front: el usuario pega el `ADMIN_API_TOKEN`
  en una pantalla local (no env var del bundle) y el front lo persiste en
  `sessionStorage` aparte. NO se mezclan los dos tokens.

### 2.4 Validación back: matriz super-admin / agency

Modificar `authorize_admin_request` para aceptar **dos** tipos de token. Pseudo:

```
provided = extract_bearer_token(...)
if compare_digest(provided, ADMIN_API_TOKEN):
    return None  # super-admin: todo permitido
try:
    claims = jwt.decode(provided, AGENCY_SECRET, algorithms=["HS256"])
except (InvalidSignature, ExpiredSignature, ...):
    return 401 INVALID_ADMIN_TOKEN
if claims["scope"] != "agency":
    return 401 INVALID_ADMIN_TOKEN
# scope=agency: sólo /v1/admin/agencies/{agency_id}/...
path_agency_id = extract_agency_id_from_path(request.url.path)
if path_agency_id is None:
    return 403 AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE  # /v1/admin/agencies, /v1/admin/wordpress-sources
if path_agency_id != claims["agency_id"]:
    return 403 AGENCY_TOKEN_AGENCY_MISMATCH
request.state.agency_id = claims["agency_id"]   # opcional, para logging
return None
```

Matriz:

| Token enviado | Path | Resultado |
|---|---|---|
| ninguno | cualquiera | 401 `ADMIN_AUTH_REQUIRED` |
| `ADMIN_API_TOKEN` | cualquier `/v1/admin/*` | 200 |
| JWT agency válido | `/v1/admin/agencies/{su_agency_id}/...` | 200 |
| JWT agency válido | `/v1/admin/agencies/{otra_agency}/...` | 403 `AGENCY_TOKEN_AGENCY_MISMATCH` |
| JWT agency válido | `/v1/admin/agencies` (lista) | 403 `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE` |
| JWT agency válido | `/v1/admin/wordpress-sources` (global) | 403 `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE` |
| JWT expirado/firma inválida | cualquiera | 401 `INVALID_ADMIN_TOKEN` |

`ADMIN_API_DISABLE_AUTH_FOR_TESTING` se mantiene **solo** como hoy: bypass para
pytest. El nuevo flujo de agency token NO se prueba con ese flag activo.

## 3. Cambios concretos en el back

1. **`apps/api/admin_auth.py`** — refactor de `authorize_admin_request` (línea 83-193):
   - Extraer helper `_extract_path_agency_id(path: str, base_path: str) -> str | None`
     (regex sobre `/v1/admin/agencies/{uuid}/...`).
   - Añadir rama JWT tras fallar `compare_digest` con el super-admin token.
   - Nuevos errores: `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE`,
     `AGENCY_TOKEN_AGENCY_MISMATCH`. Mantener `INVALID_ADMIN_TOKEN`/`ADMIN_AUTH_REQUIRED`.
2. **Nuevo módulo `apps/api/agency_token.py`** (read-only para los routers):
   - `issue_agency_token(*, agency_id, location_id, user_id, secret, ttl_seconds) -> tuple[str, datetime]`.
   - `decode_agency_token(token, *, secret) -> AgencyTokenClaims` (dataclass).
   - Sin acoplar a FastAPI; tests unit triviales.
3. **`settings/app.py`** y **`settings/admin.py`**:
   - Añadir `admin_agency_token_secret: str = Field("", validation_alias="ADMIN_AGENCY_TOKEN_SECRET")`.
   - Añadir `admin_agency_token_ttl_seconds: int = Field(3600, validation_alias="ADMIN_AGENCY_TOKEN_TTL_SECONDS", ge=60)`.
   - Reexport en `settings/admin.py` y en `settings/__init__.py`.
4. **`apps/api/app_factory.py`** (línea 109-200):
   - Aceptar kwargs `admin_agency_token_secret`, `admin_agency_token_ttl_seconds`.
   - Pasar el secret al `AdminAccessPolicy` (extender el dataclass con
     `agency_token_secret: str`, `agency_token_ttl_seconds: int`).
5. **`modules/publishing/transport/http/sessions_router.py`** (línea 138-164):
   - Inyectar `agency_token_secret` y `agency_token_ttl_seconds` al
     `create_sessions_router(...)`.
   - Tras `inspect_session_status.execute(...)`, si `connected and agency_id`:
     emitir el JWT y añadirlo a la respuesta como `agency_token` +
     `agency_token_expires_at`.
   - Si `agency_token_secret == ""`: omitir los dos campos (o devolver 503; ver §2.2).
6. **Nueva dependencia**: `pyjwt` en `requirements.txt` /
   `pyproject.toml`. Razón: estable, mantenido, suficiente para HS256.
   Alternativa `python-jose` rechazada por superficie excesiva.
7. **No hace falta migración Alembic** (stateless). Si en el futuro se añade
   denylist de `jti`, será una feature aparte.
8. **Tests de integración** (en `tests/integration/auth/test_admin_auth.py` nuevo):
   - `sin token → 401 ADMIN_AUTH_REQUIRED`.
   - `super-admin token → 200 en /v1/admin/agencies (list global)`.
   - `agency token válido → 200 en /v1/admin/agencies/{su_agency_id}/brand`.
   - `agency token contra otra agencia → 403 AGENCY_TOKEN_AGENCY_MISMATCH`.
   - `agency token contra /v1/admin/agencies (global) → 403 AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE`.
   - Bonus: `agency token expirado → 401 INVALID_ADMIN_TOKEN`,
     `JWT firma inválida → 401 INVALID_ADMIN_TOKEN`.
9. **Tests unit** del módulo `apps/api/agency_token.py` (issue/decode round-trip,
   exp, firma).
10. **Tests del sessions router** ampliados: respuesta de `POST /v1/sessions/gohighlevel/session`
    incluye `agency_token` cuando hay connection con `agency_id`, lo omite cuando
    no, y NO lo incluye si `ADMIN_AGENCY_TOKEN_SECRET == ""`.
11. **Documentación**:
    - `docs/API.md`: nueva sección "Admin authentication — super-admin vs agency-scoped";
      ampliar la entrada de `POST /v1/sessions/gohighlevel/session` con los dos
      campos nuevos.
    - `docs/conventions.md`: regla "todo router admin debe llamar `authorize_admin_request`
      al inicio del handler" (ya implícita; documentarla).
    - Regenerar `docs/openapi.json` y `docs/http_surface.md` (script de feature 4).
    - `.env.example`: documentar `ADMIN_AGENCY_TOKEN_SECRET` y `ADMIN_AGENCY_TOKEN_TTL_SECONDS`.

## 4. Riesgos y decisiones abiertas

- **Confirmar con el usuario antes de codear**:
  1. ¿JWT HS256 stateless o tabla `agency_sessions` con tokens opacos? Recomiendo
     A; si el usuario pide revocación inmediata, B (con migración Alembic).
  2. TTL de 60 min — confirmar.
  3. Si `ADMIN_AGENCY_TOKEN_SECRET` no está configurado: ¿503 (estricto) u omitir
     el campo en la respuesta y dejar que el front degrade a "solo super-admin"?
     Recomiendo 503 en producción, omitir solo si `ADMIN_API_DISABLE_AUTH_FOR_TESTING`.
- **Compatibilidad con feature 4 (test de contrato cross-repo)**: el test de
  `tests/integration/test_http_surface_contract.py` solo verifica
  `(verbo, path)`, no auth. **No hace falta ampliar el mapping de placeholders**.
  Sí hay que validar que la feature 4 no añadió aserciones implícitas sobre
  201/200 sin Authorization: revisar el test cuando se implemente esta feature.
- **JWT lib**: `pyjwt` ≥ 2.8. Secret management: env var `ADMIN_AGENCY_TOKEN_SECRET`,
  generado con `openssl rand -base64 48`. Documentar que NO debe coincidir con
  `ADMIN_API_TOKEN` (auditoría más limpia si se filtran logs).
- **Front (cross-repo, fuera del alcance del implementer del back)**:
  - `4reels front/src/lib/api/client.js:105 getAuthHeaders()` debe leer del
    `SessionProvider` el `agency_token` o el `super_admin_token` local.
  - El front NO debe enviar ambos a la vez; precedencia: super-admin > agency.
  - El front debe limpiar el token al reset/logout y al recibir 401.
- **Routers globales que NO deben aceptar agency token**: `/v1/admin/agencies` (list/create),
  `/v1/admin/wordpress-sources*`. El helper `_extract_path_agency_id` debe
  devolver `None` para estos paths, disparando 403 explícito.
- **Logging**: `log_persistent_event("admin.authorization_failed", reason="agency_mismatch", ...)`
  para distinguir los nuevos rechazos en el log persistente. Mantener el formato
  actual (no hace falta nuevo schema).
