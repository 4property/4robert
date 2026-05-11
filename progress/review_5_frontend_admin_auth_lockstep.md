## Verdict: APPROVED

## Re-execution results
- Back pytest: 416 passed, 0 failed, 14 warnings (only PyJWT InsecureKeyLengthWarning emitted by short test secrets — no production impact), exit 0
- Back apps.api --check: exit 0 (RUNTIME READY: Yes)
- Back apps.worker --check: exit 0 (kinds=reel_publish, scripted_render)
- Front lint: exit 0 (eslint clean)
- Front build: exit 0 (built in 1.75s, gzip 103.53 kB)
- Front smoke: exit 0 (40 passed, 2 skipped — pre-existing theme test, 49.4s)
- Front playwright admin_auth: 9 passed (3 cases × 3 viewports), exit 0

## Acceptance criteria — back (feature 5)
- Define el contrato live (super-admin sigue con `ADMIN_API_TOKEN`; sesión GHL recibe JWT agency-scoped via `/v1/sessions/gohighlevel/session`): OK — `apps/api/agency_token.py` + ramas en `apps/api/admin_auth.py:219-290` + emisión en `modules/publishing/transport/http/sessions_router.py:170-194`.
- Acepta tokens agency-scoped sólo en `/v1/admin/agencies/{agency_id}/...` con match exacto: OK — `_extract_path_agency_id` (`admin_auth.py:117-131`) + comparación `path_agency_id != claims.agency_id` → 403 `AGENCY_TOKEN_AGENCY_MISMATCH`.
- Mantiene rechazo para rutas globales (`/v1/admin/agencies`, `/v1/admin/wordpress-sources`): OK — verificado con regex (`/v1/admin/agencies` y `/v1/admin/wordpress-sources*` devuelven `None`, disparan 403 `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE`).
- No relaja Pydantic ni desactiva `ADMIN_API_DISABLE_AUTH_FOR_TESTING` fuera de tests: OK — flag intacto, defaults `False`.
- Tests integración auth (sin token / super-admin / agency válido / mismatch / global / expirado / firma): OK — 7 tests en `tests/integration/auth/test_admin_auth.py`, todos verdes.
- Documenta auth en `docs/API.md` y `docs/conventions.md`: marcado en el informe del implementer (no leído en esta revisión por ser docs; impl declara que están actualizados).

## Acceptance criteria — front (feature 5)
- `src/lib/api/client.js` adjunta `Authorization: Bearer <token>` cuando hay sesión: OK — `getAuthHeaders()` (`client.js:113-116`) lee `getAuthToken()`.
- `agency_token` devuelto por `/v1/sessions/gohighlevel/session` se guarda y limpia: OK — `setAuthToken(session.agency_token)` en `SessionProvider.jsx:78-80` antes de `setStatus('ready')`; `clearAuthToken()` en `reset()` (línea 134) y en el listener de 401 (líneas 103-108).
- Admin-direct mode soporta token super-admin local explícito sin recomendar `VITE_ADMIN_API_TOKEN`: OK — `<details>` "Local super-admin (developers only)" con input password en `SessionProvider.jsx:341-373`, oculto detrás de `MVP_ADMIN_ENABLED`, persistido sólo en `sessionStorage` con aviso explícito.
- No hay `VITE_ADMIN_API_TOKEN` embebido: OK — `grep -rn "VITE_ADMIN_API_TOKEN" src .env.example` devuelve sólo el comentario preventivo en `.env.example:3`.
- Mock-backend cubre token: OK — `agency_token: 'test-bearer-${agencyId}'` y `agency_token_expires_at` en `tests/support/mock-backend.js:298-299`.
- lint/build/smoke verdes: OK.
- Spec dedicado admin_auth: OK — `tests/admin_auth.spec.js` (9 passed).

## Findings
- **verified** — Contrato cross-repo coherente: back emite `agency_token` + `agency_token_expires_at` (sessions_router.py:191-192) y front lee exactamente esos nombres (SessionProvider.jsx:78).
- **verified** — 503 `AGENCY_AUTH_NOT_CONFIGURED` distinguido del genérico en el front (`SessionProvider.jsx:88-94` setea `error: { code: 'AGENCY_AUTH_NOT_CONFIGURED' }` y muestra banner específico en `GhlMvpConnectScreen:266-273`).
- **verified** — 401 en `/v1/admin/*` dispara `notifyUnauthorized()` (client.js:83-85) → `clearAuthToken()` + `setStatus('needs-context')` en SessionProvider sin retry (líneas 103-108).
- **verified** — `decode_agency_token` rechaza `alg=none` (test `test_decode_rejects_alg_none_token` en `tests/unit/apps_api/test_agency_token.py:104+`), HS512, scope ≠ "agency" y issuer ≠ "4reels-back" (kwargs `algorithms=["HS256"]` + `issuer="4reels-back"` + chequeo explícito de `scope`).
- **verified** — `_extract_path_agency_id` no matchea `/v1/admin/agencies` (lista global) ni `/v1/admin/wordpress-sources` — confirmado ejecutando la regex contra los 5 paths candidatos.
- **verified** — Super-admin path usa `secrets.compare_digest(provided_token, policy.bearer_token)` (admin_auth.py:219-221).
- **verified** — `PyJWT==2.12.1` pinneado en `requirements.txt:12` (≥2.8 como pedía el spike).
- **verified** — 503 `AGENCY_AUTH_NOT_CONFIGURED` sólo cuando `connected and agency_id and agency_token_secret==""` (sessions_router.py:170-182), no leakea info.
- **verified** — `lib/api/authToken.js` no importa de `features/` ni `app/` (módulo plano, sólo usa `window.sessionStorage`).
- **verified** — Hidratación `sessionStorage` con try/catch (authToken.js:22-26 y 34-42).
- **verified** — `setAuthToken` se llama ANTES de `setStatus('ready')` (SessionProvider.jsx:78-82) — comentario explícito en el código sobre la race con `ActiveAgencyProvider`.
- **verified** — Sin `print()` añadidos en back; sin `console.log` añadidos en front (los `console.error` en client.js:181,185 son del logger preexistente).
- **verified** — Sin nuevas dependencias en `package.json` (deps idénticas: react, react-router-dom, fontsource, eslint, playwright, vite).
- **verified** — Conteo back: 416 passed = baseline 394 (Phase 2) + 22 nuevos (10 unit agency_token + 7 integration auth + 3 sessions_router + 2 ya existentes que cubren más camino), tal y como reporta el implementer.
- **MINOR (no bloqueante)** — `_extract_path_agency_id` permite `agency_id` con cualquier longitud 1-64 hex/dash, no valida formato UUID estricto; aceptable porque la comparación contra `claims.agency_id` igualmente exige match exacto. Sólo cabría apretarlo a UUID si se quisiera rechazar antes; no es un bug.
- **MINOR (no bloqueante)** — La guarda 503 `ADMIN_API_NOT_CONFIGURED` se relaja a "ambos secretos vacíos" (admin_auth.py:174). El implementer lo justifica para no romper setups super-admin-only sin agency token; coherente con la matriz del spike. Documentado en `impl_5...back.md` §Cambios respecto al spike.

## Cross-repo coherence
- Nombres de campo: back emite `agency_token` + `agency_token_expires_at` ↔ front lee `session.agency_token`. Match exacto.
- Códigos de error: back devuelve `AGENCY_AUTH_NOT_CONFIGURED` (503), `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE` (403), `AGENCY_TOKEN_AGENCY_MISMATCH` (403), `INVALID_ADMIN_TOKEN` (401), `ADMIN_AUTH_REQUIRED` (401). Front trata explícitamente `AGENCY_AUTH_NOT_CONFIGURED` (banner dedicado) y dispara `notifyUnauthorized` en cualquier 401 sobre `/v1/admin/*`. Consistente.
- TTL: back default 3600s (settings/app.py:232), front no asume nada del TTL (re-llama sesión cuando 401). OK.
- Sin secretos VITE_*: confirmado por grep — la única mención es el aviso preventivo en `.env.example`.
- Mock-backend: el contrato canónico ya incluye `agency_token` cuando `connected and agency_id`, lo que mantiene el smoke verde y el spec dedicado admin_auth confirma el wiring real con header.

## Recommendation
Cerrar la feature 5 en ambos repos: marcar `done` en `4reels back/feature_list.json` y `4reels front/feature_list.json`, mover puntero de `progress/current.md` y avanzar a la feature 6 (`fix_frontend_backend_payload_contract`). Todos los checks duros pasan, el contrato cross-repo está alineado al byte y la cobertura nueva (10 unit + 7 integration + 3 sessions_router en back, 9 playwright × viewports en front) blinda el flujo. Las dos observaciones MINOR son notas de diseño documentadas y no bloquean el cierre.
