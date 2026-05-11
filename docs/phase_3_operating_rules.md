# Phase 3 — Operating Rules (URL rename closeout + frontend lockstep)

> **Phase 2 cerrada el 2026-05-06 con feature 18.** Este documento es la
> referencia operativa **vigente** para Phase 3. Si lo escrito aquí entra
> en conflicto con `feature_list.json`, **gana este archivo**:
> `feature_list.json` se redactó antes del spike por feature.
>
> Para contexto retrospectivo de Phase 2, ver
> `docs/phase_2_operating_rules.md` (no aplica como override).

---

## 1. Alcance

Phase 3 son **4 features pequeñas** que cierran trabajo residual de
Phase 2 y alinean el contrato HTTP entre `4reels back/` y
`4reels front/`. NO es un refactor de arquitectura; el código del
backend ya está limpio post-Phase 2 (todos los archivos ≤ 495 LoC,
0 imports legacy).

| # | Feature | Repos tocados |
|---|---|---|
| 1 | `rename_scripted_render_to_v1` | back |
| 2 | `align_music_endpoint_front_to_back` | back (docs/test smoke) + **front** |
| 3 | `resolve_session_me_endpoint` | front (Opción B) o back+front (Opción A) |
| 4 | `http_surface_audit_and_contract_test` | back (lee front en read-only) |

Tras cerrar las 4, Phase 3 se da por terminada y Phase 4 abre con
backlog de producto (ver `REFACTOR_STATUS.md` § Phase 4 backlog
candidates). NO arrancar Phase 4 sin aprobación explícita del usuario.

## 2. Modo de ejecución: serial estricto

Una feature a la vez, en orden de id. Las 4 son ortogonales (cada una
toca un router/módulo distinto), pero el orden serial garantiza que
tras cada cierre el repo está trivialmente verificable y la baseline
de tests es estable.

La feature 4 (`http_surface_audit_and_contract_test`) **debe ser la
última**: su test de contrato sería ruidoso si se ejecuta antes de
cerrar 1, 2 y 3.

## 3. Cross-repo: front + back coordinados

Phase 3 cruza ambos repos. Reglas:

- Las features 2 y 3 modifican `4reels front/`. El implementer del back
  abre la entrada equivalente en `4reels front/feature_list.json`
  **antes** de cambiar ningún archivo del front, y la cierra coordinada.
- El front tiene su propio `leader` con sus propios subagentes
  (ver `4reels front/CLAUDE.md`). El leader del back NO edita el front
  directamente: lanza un `general-purpose` con la consigna "lee
  `4reels front/.claude/agents/implementer.md` y aplica el cambio".
- La verificación de cierre incluye `pytest -q` en back **y** las
  suites del front (`./init.sh` en cada repo).

## 4. Sin commits intermedios

Heredado de Phase 2. App en desarrollo, PRs grandes aceptables. **No
hagas `git commit` automático** ni propongas cierres por feature. El
usuario decide cuándo agrupar commits.

Cierre de feature = árbol limpio (sin `__pycache__/`, sin `.tmp_*`,
sin `print()` de debug) + tests verdes + reviewer APPROVED. El leader
no marca `done` (CLAUDE.md lo prohíbe): se lanza un `general-purpose`
en "modo cierre" para tocar `feature_list.json` y mover el resumen de
`progress/current.md` a `progress/history.md`.

## 5. Naming descriptivo (heredado)

Mismo estándar que Phase 2:

| Verbo HTTP | Use case style |
|------------|----------------|
| POST       | `register_<resource>` |
| GET (list) | `list_<resources>` |
| GET (one)  | `inspect_<resource>` |
| PUT/PATCH  | `reconfigure_<resource>` (o el verbo que mejor describa) |
| DELETE     | `decommission_<resource>` |

Para no-CRUD, verbo del dominio (`probe_provider_connection`,
`enqueue_scripted_render`, `inspect_current_session`).

## 6. Tests

- Baseline al arrancar Phase 3: **394 tests verdes** (post-feature 18).
- Cada feature **suma** tests, no quita. Si una feature no añade
  cobertura nueva (caso típico de feature 1, que es solo rename),
  documentar la razón en `progress/impl_<id>_*.md`.
- Sin mocks de Postgres: `tests/support/postgres.py`
  (`temporary_postgres_schema`, `seed_*` helpers).
- Las suites del front (`4reels front/tests/`) usan Playwright +
  `tests/support/mock-backend.js`. El mock-backend debe servir el
  **mismo contrato** que el back real — esa es la regla que feature 2
  está cerrando para el caso `/music`.

## 7. Patches por feature

### Feature 1 — `rename_scripted_render_to_v1`

- Cambio mínimo: `prefix=\"/v1\"` en `APIRouter(...)` de
  `modules/rendering/transport/http/scripted_router.py:49`.
- Adaptar 6 tests en `tests/integration/rendering/test_scripted_router.py`.
- `grep -rn '/videos/scripted/render' .` debe quedar en 0 hits
  (excluyendo `progress/history.md`, `docs/phase_2_operating_rules.md`
  y este `phase_3_operating_rules.md`).
- **No publicar alias legacy.** El contrato externo de scripted_render
  no estaba estabilizado (cambió de sync a async en feature 8 de
  Phase 2). Documentar el rename en `docs/API.md` y dejar nota en el
  cierre para que el usuario avise a integradores conocidos.

### Feature 2 — `align_music_endpoint_front_to_back`

- **Back: cambios mínimos.** El CRUD de música ya existe completo
  desde Phase 2 feature 6. Solo se documenta el contrato en
  `docs/API.md` y, opcionalmente, se añade un smoke test si la suite
  actual no garantiza el shape per-track.
- **Front: trabajo principal.** El `musicApi` actual solo tiene
  `listTracks`. Hay que ampliarlo a 5 verbos y adaptar las pantallas
  (`MusicLibrary.jsx`, `MusicRules.jsx`) al shape `{music_id,
  display_name, object_key, duration_seconds, is_default,
  created_at}`. El identificador es `music_id`, NO `id` ni
  `track_id`.
- **mock-backend.js: actualización obligatoria.** La regex
  `/music-tracks` debe pasar a `/music` y devolver el contrato
  canónico (no `{implemented: false}`).
- **Decisión sobre alias legacy.** El back no expone `/music-tracks`
  desde Phase 2 feature 6; no se reintroduce. La feature confirma
  que ningún cliente externo lo consume (es API admin, solo lo usa
  el dashboard front).

### Feature 3 — `resolve_session_me_endpoint`

- **Spike obligatorio antes de elegir opción.** Documentar en
  `progress/explore_feature_3_resolve_me.md`:
  - Qué campos del retorno de `getCurrentUser()` consume realmente la
    UI (rol, agency_id, capacidades, email, etc.).
  - Mapping de cada uso a la fuente alternativa disponible en el front
    (`ghlMvpContext`, presencia del bearer token, props del shell).
  - Decisión final con `Why:`.
- **Recomendación a priori: Opción B (eliminar `getCurrentUser`).** El
  proyecto no tiene tabla `users` ni autenticación per-usuario. La
  identidad efectiva es `super_admin` (presencia de bearer token) o
  `agency_user` (SSO context de GHL). `/me` sería un wrapper sintético
  sobre datos que el front ya tiene.
- **Si el spike justifica Opción A**, implementar `GET /v1/me` en
  `modules/tenancy/transport/http/me_router.py` con use case puro
  `inspect_current_session` que recibe headers normalizados (no
  `Request`).
- En cualquier caso: borrar el comentario residual de `/me` en
  `4reels front/src/features/session/session.css`.

### Feature 4 — `http_surface_audit_and_contract_test`

- **Cierre de Phase 3.** Solo arranca cuando 1, 2 y 3 están `done`.
- Generar `docs/http_surface.md` y `docs/openapi.json` desde la app
  real (`build_api_app(...)` con flags de testing). NO hardcodear la
  tabla.
- El test de contrato lee el front en **read-only**. La ubicación del
  front se configura vía env var `FRONTEND_REPO_ROOT` con default
  a `c:/Users/4pm/Desktop/4reels/4reels front`. Si la env var apunta
  a una ruta inexistente, el test debe fallar con mensaje claro
  (no skipear silenciosamente).
- El mapping de placeholders front → back vive en el propio test
  (≤30 entradas). Cuando el front añade un placeholder nuevo, se
  amplía el mapping en el mismo PR que introduce el endpoint.
- El test falla con mensaje accionable que incluye archivo+línea del
  front: `Front llama a GET /v1/admin/agencies/{id}/music-tracks
  pero back solo expone GET /v1/admin/agencies/{id}/music — corregir
  4reels front/src/features/music/api.js:5`.

## 8. Bloqueo si las premisas cambian

Mismo protocolo que Phase 2: si el implementer descubre que un supuesto
de este doc o del spike correspondiente ya no es cierto (p. ej. el back
tiene un endpoint que se asumió ausente, o el front tiene callers
ocultos a un path que se asumió huérfano), **para y reporta `blocked`**.
El leader re-decide y eventualmente actualiza este archivo.

## 9. Subagentes en este harness

Igual que Phase 2: el harness expone `general-purpose`, no carga
`.claude/agents/{implementer,reviewer}.md` como `subagent_type` nativo.
El leader instruye al `general-purpose` a leer el protocolo
correspondiente como primera acción y a responder en una sola línea
(`done -> ...` / `APPROVED -> ...` / `blocked -> ...`).

Para el cierre administrativo (marcar `done`, mover summary a
`history.md`, vaciar `current.md`), un `general-purpose` adicional
en "modo cierre".
