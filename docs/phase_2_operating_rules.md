# Phase 2 — Operating Rules (god-file split)

> **Phase 2 cerrada el 2026-05-06 con feature 18.** Este documento queda
> como referencia histórica de las reglas de operación que regían
> Phase 2 mientras estaba activa. **No aplica a Phase 3 ni features
> posteriores.** Si arrancas una feature nueva, mira `AGENTS.md` y
> `REFACTOR_STATUS.md`; este archivo solo sirve para entender decisiones
> tomadas durante Phase 2 si necesitas contexto retrospectivo.

> Decisiones operativas tomadas con el usuario para el Phase 2 del refactor
> (`feature_list.json` features 2-8). Todo agente que arranque una feature de
> Phase 2 debe leer este archivo además de `AGENTS.md`,
> `feature_list.json` y el informe de exploración correspondiente bajo
> `progress/explore_router_<id>_*.md`.
>
> Si lo escrito aquí entra en conflicto con `feature_list.json`, **gana este
> archivo**: `feature_list.json` se redactó antes de la fase de exploración y
> tiene desfases factuales (paths, alcance) que se confirmaron después.

---

## 1. Modo de ejecución: serial estricto (modo A)

Las features 2-8 se ejecutan **una a una**, en orden de id, sin paralelismo.
Razones:

- Toda feature de Phase 2 toca dos archivos compartidos:
  - `apps/api/app_factory.py` (registra su router).
  - `services/transport/http/server.py` (borra sus rutas).
- Aunque los rangos de líneas a borrar son mayoritariamente disjuntos, los
  imports al tope de `server.py` y los registros en `app_factory.py` son
  puntos de fricción. Serializar elimina el riesgo de merge silencioso.

La paralelización sí se aplicó a la **fase de exploración previa**: hay 7
informes en `progress/explore_router_<id>_*.md` (uno por feature) que el
implementer debe leer antes de tocar código. Esos informes ahorran el grueso
del tiempo de comprensión.

## 2. Borrar todo lo legacy a medida que se mueve

**No hay bridges, no hay compat shims, no hay `xfail`.** Cada feature
elimina su propia huella legacy en el mismo PR/sesión donde mueve el código:

- Handlers en `services/transport/http/server.py` que la feature mueve.
- Payloads Pydantic inline (con prefijo `_`) que solo usaban esos handlers.
- Métodos en `WordPressWebhookApplication` que **solo** usa esta feature.
- Imports de `application/`, `core/`, `repositories/stores/` que dejan de
  tener call sites tras esta feature.
- Tests legacy bajo `tests/integration/test_http_transport.py` que apuntan
  a esas rutas: se adaptan a las rutas nuevas (mismo path HTTP, ahora
  servido por el router nuevo) o se sustituyen por los tests del router en
  `tests/integration/<bc>/test_<feature>_router.py`. **No se marcan
  `xfail`.**

**Excepción única:** legacy que otras features 2-8 todavía consumen NO se
borra hasta que la última call site desaparezca. Ejemplo concreto:
`WordPressWebhookApplication.test_gohighlevel_connection`
(`server.py:1296-1309`) lo usan features 2 y 5; feature 2 lo deja vivo,
feature 5 lo borra al cerrar.

**Cuando una feature deja un store legacy en `repositories/stores/` sin
call sites**, se borra en esa misma feature. La feature 17 deja de tener
trabajo conforme las features 2-8 limpian a su paso.

**Approach específico para use cases que hoy pasan por bridges legacy:**

- Feature 6 (configuration) usa **Opción A**: los use cases nuevos escriben
  directo a las tablas tipadas (`agency_brand_settings`,
  `agency_reel_defaults`, `agency_automation_rules`,
  `agency_social_templates`, `agency_music_tracks`) vía
  `uow.configuration.<section>.upsert(...)`. Borra `ReelProfileStore` en
  cuanto ningún caller queda (probable que sea esta feature misma).

## 3. Naming descriptivo en endpoints y use cases

Verbos descriptivos en lugar de CRUD genérico. Para cada recurso:

| Verbo HTTP | Use case style                              |
|------------|---------------------------------------------|
| POST       | `register_<resource>` (creación)            |
| GET (list) | `list_<resources>`                          |
| GET (one)  | `inspect_<resource>`                        |
| PUT/PATCH  | `reconfigure_<resource>` (o verbo que mejor describa la mutación) |
| DELETE     | `decommission_<resource>` (o `archive_<resource>`) |

Para endpoints que NO son CRUD, usa el verbo más descriptivo del dominio:

- `decode_session_context`, `inspect_session_status`,
  `probe_provider_connection`, `regenerate_reel`, `reject_reel`,
  `enqueue_scripted_render`, `ingest_wordpress_property`.

La regla "5 verbos" es **aspiracional, no obligatoria**: si un recurso
tiene solo GET+PUT (p. ej. `agency_brand_settings`), no fuerces 5 verbos
artificiales. Los nombres por defecto en ese caso son `read_<section>` y
`update_<section>`.

## 4. Sin commits por feature

Esto es una app en desarrollo. **No hagas commits intermedios** ni propongas
PRs por feature. Cierra la feature dejando el árbol limpio (sin
`__pycache__/`, sin `.tmp_*`) y deja al usuario decidir cuándo agrupar
commits.

## 5. Patches y alcance por feature (overrides sobre `feature_list.json`)

Lo siguiente sustituye lo escrito en `feature_list.json` cuando hay
desacuerdo. La lista refleja decisiones del usuario tras la exploración.

### Feature 2 — `publishing_sessions_router`

- **Path real:** `/v1/sessions/gohighlevel/*` (Phase 1 ya renombró
  `/mvp/gohighlevel/*`). No se cambia el contrato HTTP.
- 4 endpoints, 4 use cases descriptivos:
  - `GET /v1/sessions/gohighlevel/tokens` → `list_provider_sessions`
  - `POST /v1/sessions/gohighlevel/context` → `decode_session_context`
    (renombrar el archivo y la clase de
    `decode_gohighlevel_session.py / DecodeGoHighLevelSessionUseCase`).
  - `POST /v1/sessions/gohighlevel/session` → `inspect_session_status`
  - `POST /v1/sessions/gohighlevel/test` → `probe_provider_connection`
- Borra de `server.py`: `971-973` (`list_ghl_connections`),
  `967-969` (`get_ghl_connection_by_location`), `587-642` (payloads
  inline), `1461-1654` (handlers).
- **Conserva** `server.py:1296-1309` (`test_gohighlevel_connection`) —
  feature 5 lo necesita.

### Feature 3 — `tenancy_admin_agencies_router`

- 5 endpoints CRUD `/v1/admin/agencies` y `/v1/admin/agencies/{id}`:
  - `POST` → `register_agency`
  - `GET` (list) → `list_agencies`
  - `GET` (detalle) → `inspect_agency`
  - `PATCH` → `reconfigure_agency`
  - `DELETE` → `decommission_agency`
- El handler de `inspect_agency` hidrata `sources`, `ghl_connection`,
  `reel_profile` cross-módulo. El **router** (no el use case) consulta los
  repos de los otros módulos vía namespaces del UoW
  (`uow.ingestion.sources`, `uow.publishing.connections`,
  `uow.configuration.*`). Eso respeta la regla "transport puede orquestar
  varios repos" sin romper el aislamiento "no importes
  `<otro>.application` ni `<otro>.infrastructure`".
- Borra `server.py:167-206` (payloads), `1895-2082` (handlers),
  `4132-4143` (`_serialize_agency`), `4146-4162` (`_serialize_agency_summary`),
  `4165-4172` (`_slugify_admin`), `1036-1058` (runtime CRUD methods).
- `_serialize_wordpress_source_details` (`server.py:4175-4194`) la
  necesita feature 4 — DUPLICAR temporalmente en el router de tenancy
  con TODO; feature 4 unifica.
- Adapta `tests/integration/test_http_transport.py:346-...` para que sigan
  verdes contra el router nuevo.

### Feature 4 — `ingestion_routers`

- **Webhook path real:** `/v1/ingest/wordpress/property` (default
  `WEBHOOK_PATH`). NO `/webhooks/wordpress/property` como dice la
  feature description. El contrato externo con WordPress se preserva
  bit-a-bit.
- **Sources expandido a CRUD literal de 5 verbos** (la API actual solo
  tenía `POST upsert + DELETE`; aquí ampliamos a CRUD completo):
  - `POST /v1/admin/agencies/{id}/sources` → `register_ingestion_source`
  - `GET /v1/admin/agencies/{id}/sources` → `list_ingestion_sources`
  - `GET /v1/admin/agencies/{id}/sources/{source_id}` → `inspect_ingestion_source`
  - `PUT /v1/admin/agencies/{id}/sources/{source_id}` → `reconfigure_ingestion_source`
  - `DELETE /v1/admin/agencies/{id}/sources/{source_id}` → `decommission_ingestion_source`
- Use case del webhook: `ingest_wordpress_property`. **Preserva la cadena
  de superseding** (`uow.delivery.jobs.supersede_queued_jobs` +
  `uow.delivery.webhook_events.update_event_status`) antes de encolar el
  job nuevo.
- Mueve `services/transport/http/security.py` (HMAC pure helpers) a
  `shared/http/webhook_signature.py`. La fórmula HMAC se preserva
  byte-a-byte (`location_id` y `access_token` siguen en el mensaje
  firmado, default `""`).
- Borra `services/transport/http/security.py` tras moverlo.
- Borra el `WordPressSourceAdminService` legacy
  (`application/admin/wordpress_source_management.py`) si esta feature
  deja sin call sites — verificar con `grep`.
- El bundle de secrets para el job: `provider_secret_bundle =
  json.dumps({"access_token": ghl.access_token, "provider": "gohighlevel"})`.
  Coordinar con feature 16 si la fórmula cambia.

### Feature 5 — `publishing_connections_router`

- 5 endpoints CRUD descriptivos sobre `/v1/admin/agencies/{id}/ghl-connection`:
  - `POST` → `attach_provider_connection`
  - `GET` (list) → `list_provider_connections` (ámbito del cliente:
    típicamente filtra por agency)
  - `GET` (one) → `inspect_provider_connection`
  - `PUT` → `rotate_provider_credentials` (más descriptivo que "update"
    porque la operación cambia tokens)
  - `DELETE` → `detach_provider_connection`
- **No incluye** `POST .../ghl-connection/test` (eso queda fuera del
  acceptance literal). Si feature 5 lo deja en `server.py`, feature 9 lo
  borra. Alternativamente, mover `/test` aquí también con use case
  `probe_provider_connection` (compartido con feature 2). **Decisión
  preferida: moverlo aquí** para no dejar un handler huérfano.
- Cifrado/descifrado con Fernet **dentro del repo
  `ProviderConnectionRepository`** (ya existente). El use case maneja
  plaintext local solo durante la ejecución, jamás lo persiste ni lo
  retorna en responses.
- Borra `repositories/stores/ghl_connection_store.py` cuando deje de
  tener call sites tras esta feature (typically con esto hecho).
- Acepta payload legacy del frontend
  (`{location_id, user_id, access_token, refresh_token, expires_at, status}`)
  por compatibilidad — el adaptador construye `secrets` y `config` por
  dentro.

### Feature 6 — `configuration_routers`

- **NO partir.** Una sola feature, un solo PR (puede ser grande).
- **Opción A:** los use cases nuevos escriben **directo a las tablas
  tipadas** vía `uow.configuration.<section>`. NO usa el bridge al
  `ReelProfileStore`. El store legacy se borra al cerrar la feature si
  ningún caller queda (probable).
- **5 routers**, 5 paths bajo `/v1/admin/agencies/{id}/`:
  - `/brand` → 2 endpoints: `read_brand_settings` / `update_brand_settings`
  - `/defaults` → 2 endpoints: `read_reel_defaults` / `update_reel_defaults`
  - `/automation` → 2 endpoints: `read_automation_rules` / `update_automation_rules`
  - `/social-templates` → 2 endpoints: `read_social_templates` /
    `replace_social_templates` (la PUT actual reemplaza el bloque
    completo, no merge — el verbo lo refleja)
  - `/music` → **CRUD por track**, 5 verbos descriptivos:
    - `POST /music` → `register_music_track`
    - `GET /music` → `list_music_tracks`
    - `GET /music/{music_id}` → `inspect_music_track`
    - `PUT /music/{music_id}` → `reconfigure_music_track`
    - `DELETE /music/{music_id}` → `decommission_music_track`
- **`/music-tracks` (path actual del stub) se elimina.** El frontend
  deberá apuntar a `/music`. El stub de "implemented: false" desaparece.
- Cuando un campo aparece en dos secciones (p. ej. `platforms` está hoy
  tanto en `defaults` como redirigido por el legacy a `automation`), el
  dueño canónico es **defaults**. `update_automation_rules` NO escribe
  `platforms`.
- `MusicUpsertPayload` (per-track):
  ```python
  class MusicTrackPayload(BaseModel):
      display_name: str
      object_key: str
      duration_seconds: int
      is_default: bool = False
  ```
- Tests legacy en `tests/integration/test_http_transport.py:451-...` se
  adaptan para verificar persistencia vía `uow.configuration.<section>`,
  no vía `ReelProfileStore`.

### Feature 7 — `reels_admin_router`

- Incluye `/reject` además de los 3 listados en feature_list. No deja
  handlers huérfanos en `server.py`. Endpoints + use cases:
  - `GET /v1/admin/agencies/{id}/reels` → `list_reels`
  - `GET /v1/admin/agencies/{id}/reels/{site_id}/{property_id}` →
    `inspect_reel`
  - `POST /v1/admin/agencies/{id}/reels/{site_id}/{property_id}/approve`
    → `regenerate_reel` (la URL mantiene `/approve` por compatibilidad
    frontend; el use case se llama `regenerate_reel` por ser más
    descriptivo del comportamiento real).
  - `POST /v1/admin/agencies/{id}/reels/{site_id}/{property_id}/reject`
    → `reject_reel`
- Los 4 GET de assets (`video`, `images`, `images/{pos}/file`, `manifest`)
  se mueven al router como **helpers de transport** (sin use case
  dedicado — son lectura plana de fichero local).
- `regenerate_reel` escribe `jobs` directo vía `uow.delivery.jobs` +
  `uow.delivery.webhook_events`, NO via `WebhookAcceptanceService`
  legacy. Replica el supersede + create_event + enqueue como una sola
  transacción del UoW.
- `SocialPublishContext` (hoy en `application/types.py`): construir el
  `publish_context_json` como dict literal en el use case. La
  conversión a dataclass la hace el bridge consumer del worker.

### Feature 8 — `rendering_scripted_router`

- **Cambio sync→async confirmado.** La response cambia:
  - Antes: `201` con `{render_id, video_path, manifest_path, ...}`.
  - Después: `202` con `{status: "accepted", job_id, event_id}`.
- Use case en el módulo rendering: `enqueue_scripted_render` (en
  `modules/rendering/application/use_cases/`). El use case **no
  importa** `RenderScriptedVideoUseCase` de `modules/reels/`. Solo
  encola el job; el worker ya tiene el handler registrado en
  `apps/worker/runtime.py:271-278`.
- Tenant resolution **inline en el use case** vía
  `uow.ingestion.sources.get_by_kind_external_id(kind="wordpress",
  external_id=site_id)`. NO importar `TenantResolver` legacy.
- `webhook_events.source_kind = "scripted_api"` (verificar que la
  columna no tiene CHECK constraint).
- Actualiza/borra `services/transport/http/openapi_docs.py:359-454`
  (`_decorate_scripted_render_operation`) para reflejar el 202.

## 6. Tests

- Mantén **116+ tests verdes** como baseline (post-feature-1: 146 verdes
  porque feature 1 sumó 30 unit tests para los helpers).
- Cada feature **suma** tests, nunca quita.
- Tests legacy bajo `tests/integration/test_http_transport.py` se
  **adaptan**, no se eliminan ni se marcan `xfail`. Los que importan de
  `repositories/stores/...` migran a `uow.<bc>.<repo>` o a SQL directo
  contra el engine de prueba.
- Cada feature crea:
  - `tests/unit/<bc>/test_<verbo>_<recurso>.py` — uno por use case.
  - `tests/integration/<bc>/test_<feature>_router.py` — cubre los
    endpoints reales del router.
- Sin mocks de Postgres: usar `tests/support/postgres.py`
  (`temporary_postgres_schema`, `seed_*` helpers).

## 7. Subagentes en este harness

El harness del usuario tiene `general-purpose` disponible (no carga
`.claude/agents/{implementer,reviewer}.md` como subagent_type nativo).
Cuando el leader necesita lanzar un implementer/reviewer:

- Usa `subagent_type: "general-purpose"`.
- En el prompt, dile que **lea `.claude/agents/implementer.md` (o
  `reviewer.md`) como primera acción** y que respete su protocolo al pie
  de la letra.
- Pídele respuesta **una sola línea** (`done -> ...` / `blocked -> ...` /
  `APPROVED -> ...` / `CHANGES_REQUESTED -> ...`) — sin diff, sin
  resumen extenso. Los detalles van a `progress/impl_<id>_*.md` o
  `progress/review_<id>_*.md`.

Para el cierre administrativo (marcar `done`, mover summary a
`history.md`, vaciar `current.md`), lanzar otro `general-purpose` con
instrucción explícita "modo cierre" (CLAUDE.md prohíbe al leader marcar
`done` directamente).

## 8. Bloqueo si las premisas cambian

Si el implementer descubre que un supuesto de este doc o del
`explore_router_<id>_*.md` ya no es cierto (p. ej. una ruta que se
movió antes, un repo que cambió de firma), **para y reporta `blocked`**.
No improvises. El leader re-decide y eventualmente actualiza este
archivo.
