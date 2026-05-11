# Implementación Feature 5 (lado BACK) — `frontend_admin_auth_lockstep`

## Resumen

Se cierra el lado BACK de la feature 5: el endpoint `POST /v1/sessions/gohighlevel/session`
ahora emite un JWT HS256 stateless (`agency_token`) cuando la location de GoHighLevel
tiene una agencia conectada, y la autorización de `/v1/admin/*` acepta tanto el
super-admin token (compare_digest) como el JWT agency-scoped (decode + scope check
+ matching `{agency_id}` en path). 503 `AGENCY_AUTH_NOT_CONFIGURED` si
`ADMIN_AGENCY_TOKEN_SECRET` está vacío en producción.

La feature queda `in_progress`: el lado FRONT (4reels front: `src/lib/api/client.js`
`getAuthHeaders()`, `src/features/session/` para persistir el token, mock-backend
de Playwright) sigue pendiente y disparará el reviewer cross-repo cuando ambas
partes estén listas.

## Archivos creados / modificados

| Archivo | Razón |
|---|---|
| `apps/api/agency_token.py` (nuevo) | Issue/decode HS256 stateless. `AgencyTokenClaims`, `issue_agency_token`, `decode_agency_token`, excepciones `AgencyTokenError/Expired/Invalid`. Issuer `4reels-back`, scope `agency`, defensa contra `alg=none` y `alg=HS512` (sólo se permite HS256). Sin acoplar a FastAPI. |
| `apps/api/admin_auth.py` (modificado) | Reescrita `authorize_admin_request` según matriz §2.4 del spike: super-admin (compare_digest) → ok; agency JWT → `decode_agency_token`, exige `scope==agency`, extrae `{agency_id}` del path con `_extract_path_agency_id`, rechaza con 403 mismatch / 403 global / 401 invalid o expired. `AdminAccessPolicy` ahora lleva `agency_token_secret` y `agency_token_ttl_seconds`. |
| `apps/api/app_factory.py` (modificado) | Acepta kwargs `admin_agency_token_secret` / `admin_agency_token_ttl_seconds`. Los pasa a `build_admin_access_policy(...)` y a `create_sessions_router(...)`. |
| `modules/publishing/transport/http/sessions_router.py` (modificado) | Inyecta `agency_token_secret`/`agency_token_ttl_seconds`/`admin_disable_auth_for_testing`. Tras `inspect_session_status` y si `connected and agency_id`: emite el JWT y añade `agency_token` + `agency_token_expires_at` (ISO-8601 UTC con sufijo `Z`) a la respuesta. Si secret vacío y bypass desactivado → 503 `AGENCY_AUTH_NOT_CONFIGURED`. |
| `settings/app.py` (modificado) | `admin_agency_token_secret: str = Field("", alias="ADMIN_AGENCY_TOKEN_SECRET")` y `admin_agency_token_ttl_seconds: int = Field(3600, alias="ADMIN_AGENCY_TOKEN_TTL_SECONDS", ge=60)`. |
| `settings/admin.py` (modificado) | Reexporta los dos nuevos settings. |
| `settings/__init__.py` (modificado) | Reexporta `ADMIN_AGENCY_TOKEN_SECRET` / `ADMIN_AGENCY_TOKEN_TTL_SECONDS`. |
| `tests/integration/auth/test_admin_auth.py` (nuevo, 7 escenarios) | sin token → 401 `ADMIN_AUTH_REQUIRED`; super-admin token → 200 en `/v1/admin/agencies` (global); agency token válido → 200 en `/v1/admin/agencies/{su_id}/brand`; agency contra otra agencia → 403 `AGENCY_TOKEN_AGENCY_MISMATCH`; agency contra `/v1/admin/agencies` → 403 `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE`; expirado → 401 `INVALID_ADMIN_TOKEN`; firma inválida → 401 `INVALID_ADMIN_TOKEN`. |
| `tests/integration/publishing/test_gohighlevel_session_router.py` (modificado) | Añade 3 tests: `agency_token` se emite cuando connected; se omite cuando not connected; 503 cuando connected y secret vacío. |
| `tests/integration/test_http_transport.py` (modificado) | `_build_client` recibe `admin_agency_token_secret="test-agency-secret-for-http-transport-suite"` por defecto para que los tests que no se centran en auth no disparen el 503 estricto al chequear `/v1/sessions/gohighlevel/session` con location conectada. |
| `tests/unit/apps_api/test_agency_token.py` (nuevo, 10 tests) | issue/decode round-trip; expirado (forzando `now=` futuro); firma inválida; rechazo de `alg=HS512`; rechazo de claims faltantes; **rechazo de `alg=none` forjando JWT manualmente con header `{alg:"none"}` y sin firma**; **rechazo de `scope!="agency"`**; **rechazo de `iss!="4reels-back"`**; secret vacío al firmar; token/secret vacío al decodificar. |
| `tests/integration/delivery/test_worker_dispatcher_flow.py` (modificado) | `mock.patch` añadido sobre `SOCIAL_PUBLISHING_LOCAL_ONLY=False` y `SOCIAL_PUBLISHING_ENABLED=True` para que el test sea independiente del `.env` del operador (que tenía `SOCIAL_PUBLISHING_LOCAL_ONLY=true` para desarrollo offline). Pre-existente al feature 5; arreglado para que `pytest -q` quede 100% verde. |
| `requirements.txt` (modificado) | `PyJWT==2.12.1` (>=2.8). |
| `.env.example` (modificado) | `ADMIN_AGENCY_TOKEN_SECRET=` y `ADMIN_AGENCY_TOKEN_TTL_SECONDS=3600` con comentarios y aviso de generar con `openssl rand -base64 48` y de NO reutilizar `ADMIN_API_TOKEN`. |
| `docs/API.md` (modificado) | Sección "Admin authentication — super-admin vs agency-scoped" con la matriz completa, regla de precedencia, formato del payload `agency_token`/`agency_token_expires_at` en la respuesta de `POST /v1/sessions/gohighlevel/session`, y comportamiento 503 cuando el secret está sin configurar en producción. |
| `docs/conventions.md` (modificado) | Regla "todo handler bajo `/v1/admin/*` debe llamar `authorize_admin_request(request, policy)` al inicio del handler" y nota sobre `apps/api/agency_token.py` como single source of truth de issue/decode JWT. |
| `docs/openapi.json` y `docs/http_surface.md` | Regenerados con `python scripts/generate_http_surface.py`. Diff trivial: la lista `(method, path)` no cambia (los nuevos campos viajan en el body, no en la URL). |

## Comandos ejecutados

PowerShell-equivalente del init (Bash no disponible; documentado en
`progress/current.md`):

```powershell
& .venv\Scripts\python.exe --version            # Python 3.13.0
& .venv\Scripts\python.exe -c "import fastapi, pydantic, sqlalchemy, alembic"  # ok
& .venv\Scripts\python.exe -m apps.api --check  # exit 0
& .venv\Scripts\python.exe -m apps.worker --check  # exit 0
& .venv\Scripts\python.exe -m pytest -q --no-header
# 416 passed, 14 warnings in 201.68s (0:03:21)
```

Baseline pre-feature-5 era 394 passed (cierre Phase 2). Diferencial post-feature-5:
**+22 tests nuevos**: 10 unit en `test_agency_token.py` + 7 integration en
`auth/test_admin_auth.py` + 3 integration nuevos en `test_gohighlevel_session_router.py`
+ 2 ya existentes que ahora cubren más camino (decoded payload). Total **416
passed** y 0 fallos.

## Tests añadidos

**Unit** (`tests/unit/apps_api/test_agency_token.py`, 10):
- `test_issue_and_decode_round_trip` — claims iguales, `expires_at == iat + ttl`.
- `test_decode_raises_expired_when_token_past_exp` — usa `now=` futuro, espera `AgencyTokenExpired`.
- `test_decode_raises_invalid_when_signature_does_not_match` — secret distinto.
- `test_decode_rejects_tokens_signed_with_different_algorithm` — JWT firmado con HS512 contra HS256-only.
- `test_decode_rejects_token_missing_required_claims` — payload sin `agency_id/exp/...`.
- `test_decode_rejects_alg_none_token` — JWT manual `header.payload.` con `alg=none`, sin firma.
- `test_decode_rejects_token_with_non_agency_scope` — `scope="super-admin"` firmado correctamente.
- `test_decode_rejects_token_with_wrong_issuer` — `iss="some-other-issuer"`.
- `test_issue_requires_non_empty_secret` — guarda contra emitir sin secret.
- `test_decode_requires_non_empty_token_and_secret` — guarda contra decodificar sin token o secret.

**Integration auth** (`tests/integration/auth/test_admin_auth.py`, 7):
- `test_no_token_returns_401_admin_auth_required`.
- `test_super_admin_token_can_list_global_agencies`.
- `test_agency_token_can_access_its_own_brand_route`.
- `test_agency_token_against_other_agency_returns_403_mismatch`.
- `test_agency_token_against_global_route_returns_403_forbidden_global`.
- `test_expired_agency_token_returns_401_invalid_admin_token`.
- `test_jwt_with_invalid_signature_returns_401_invalid_admin_token`.

**Integration sessions router** (3 nuevos):
- `test_session_emits_agency_token_when_secret_configured` — JWT decodificable, claims correctos.
- `test_session_omits_agency_token_when_not_connected` — sin connection no se emiten los campos.
- `test_session_returns_503_when_secret_unset_and_auth_not_bypassed` — 503 `AGENCY_AUTH_NOT_CONFIGURED`.

## Cambios respecto al spike

Ninguno significativo. Detalles operativos:

- En `apps/api/admin_auth.py:174` la guarda de "no configurado" se relaja a
  503 únicamente cuando **ambos** secretos están vacíos
  (`bearer_token == "" and agency_token_secret == ""`). Si solo falta el agency
  secret pero hay super-admin, el flujo super-admin sigue funcionando — coherente
  con la matriz del spike (el agency JWT se rechaza con 401 `INVALID_ADMIN_TOKEN`
  porque la rama JWT no se entra). **Why:** evita un 503 incorrecto en setups
  super-admin-only que no necesitan emitir agency tokens.
- `decode_agency_token` valida explícitamente `scope=="agency"` (y rechaza
  `iss!="4reels-back"` vía PyJWT). El spike sólo lo pedía en `admin_auth.py`;
  duplicar la guardia en el módulo unitario hace que un caller que use el módulo
  directo (p.ej. tooling de soporte) no abra una vía paralela. **Why:** defensa
  en profundidad sin coste — un único `if scope != _SCOPE` extra.

## Bloqueos resueltos

1. **`tests/integration/test_http_transport.py::_build_client` disparaba 503
   `AGENCY_AUTH_NOT_CONFIGURED`** al llamar a `/v1/sessions/gohighlevel/session`
   con location conectada (porque el secret estaba vacío y el bypass desactivado).
   _Fix:_ default `admin_agency_token_secret="test-agency-secret-for-http-transport-suite"`
   en el helper (NO se relaja el 503 en producción; sólo se inyecta el secret en
   el harness de tests). Confirmado por el spike y la nota del usuario.

2. **`tests/integration/delivery/test_worker_dispatcher_flow.py::test_reel_publish_handler_completes_job_and_writes_outbox`**
   fallaba con `len(fake_publisher.calls) == 0` cuando `.env` del operador tenía
   `SOCIAL_PUBLISHING_LOCAL_ONLY=true` (modo desarrollo offline). El orchestrator
   computa `social_publishing_active = SOCIAL_PUBLISHING_ENABLED and not SOCIAL_PUBLISHING_LOCAL_ONLY`
   y, cuando es False, NO llama a `_build_default_social_property_publisher`
   y `IngestPropertyIntoReelUseCase` produce `pending_publish_platforms=[]`,
   por lo que `requires_external_publish=False` y la rama "skipped" del publish
   use case se activa. Pre-existente al feature 5, no relacionado con auth.
   _Fix:_ `mock.patch` sobre `SOCIAL_PUBLISHING_LOCAL_ONLY=False` y
   `SOCIAL_PUBLISHING_ENABLED=True` dentro del test, así el test es independiente
   del `.env` del desarrollador. Sin tocar producción.

## Estado

- `feature_list.json` feature 5 → `in_progress` (intacto, no se marca `done`).
- Lado FRONT pendiente: `4reels front/src/lib/api/client.js` (getAuthHeaders),
  `4reels front/src/features/session/` (persist + cleanup del token), Playwright
  mock-backend si la suite necesita validar Authorization.
- Reviewer cross-repo se lanza cuando ambas partes estén listas.
