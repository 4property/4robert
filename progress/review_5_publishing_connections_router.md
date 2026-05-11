# Review — feature 5 (`publishing_connections_router`)

**Veredicto:** APPROVED

## Checkpoints

- C1: [x] Arnés intacto (`AGENTS.md`, `CLAUDE.md`, `init.sh`,
  `feature_list.json`, `progress/current.md` y los 3 docs presentes).
- C2: [x] `progress/current.md` describe la sesión activa de feature 5;
  `feature_list.json` con feature 5 en `in_progress`.
- C3: [x] Aislamiento entre módulos respetado: `grep` por
  `from modules\.(?!publishing)\w+\.(application|infrastructure)` dentro
  de `modules/publishing/` no encuentra nada. `domain/provider_connection.py`
  es un dataclass puro sin SQLAlchemy. `ProviderConnectionRepository`
  extiende `ModuleRepository` y no llama `session.commit()`. Secrets cifrados
  vía `shared/db/security.py` solo dentro del repo.
- C4: [x] Tests integration usan `tests/support/postgres.py`
  (`temporary_postgres_schema`, `seed_tenant`, `seed_provider_connection`).
  225 tests verdes (baseline 207, +18: 13 unit + 5 integration).
- C5: [x] No tocó schema. `provider_connections` no se modifica.
- C6: [x] Sin `xfail`, sin `print()` debug, sin `__pycache__/` sin
  trackear sospechosos. La sesión cierra el árbol limpio.

## Hallazgos clave (positivos)

### Naming descriptivo (criterio 1)
- `attach_provider_connection`, `list_provider_connections`,
  `inspect_provider_connection`, `rotate_provider_credentials`,
  `detach_provider_connection`, `probe_provider_connection`. Sin verbos
  CRUD genéricos.
- `probe_provider_connection` reutilizado de feature 2 (no duplicado): el
  mismo archivo `modules/publishing/application/use_cases/probe_provider_connection.py`
  se invoca desde el router nuevo (línea 292 de
  `modules/publishing/transport/http/connections_router.py`).

### Cifrado Fernet (criterio 2)
- `inspect_provider_connection.execute` (líneas 37-47) llama
  `repo.get_by_agency_and_provider(...)`, NO `repo.get_with_secrets(...)`.
  El `ProviderConnection` devuelto solo tiene `has_secret: bool`.
- `_serialize_connection` (`connections_router.py:333-368`) emite
  `has_access_token` y `has_refresh_token` (boolean), nunca el plaintext.
- `attach`/`rotate` cifran a través de `repo.upsert(secrets=...)`, donde
  el cifrado vive (línea 206 de `provider_connection_repository.py`,
  `encrypt_text(secrets_payload)`). Los use cases no llaman directo a
  `encrypt_text`.
- Auditoría de logs/exceptions: `grep` por
  `context=\{[^}]*access_token` y `context=\{[^}]*secret` en
  `modules/publishing/` no encuentra nada.
- Tests integration verifican `assert "secret-token" not in response.text`
  para attach, rotate, inspect y probe.

### `/test` movido al router nuevo (criterio 3)
- `services/transport/http/server.py` ya no tiene
  `test_admin_agency_ghl_connection`,
  `upsert_admin_agency_ghl_connection` ni
  `delete_admin_agency_ghl_connection`. `grep` confirmó cero coincidencias.
- El endpoint `POST /v1/admin/agencies/{agency_id}/ghl-connection/test`
  lo sirve el router nuevo (`connections_router.py:270-322`) invocando
  `inspect_provider_connection` + `probe_provider_connection`.

### Borrado legacy (criterio 4)
- `services/transport/http/server.py:243-281` (payload
  `_AdminGhlConnectionUpsertPayload`): borrado.
- `services/transport/http/server.py:2199-2350` (3 handlers): borrados.
- `services/transport/http/server.py:940-961` (`upsert_ghl_connection`)
  y `:975-978` (`delete_ghl_connection`): borrados.
- `services/transport/http/server.py:1296-1309`
  (`test_gohighlevel_connection`): conservado deliberadamente — feature 2
  y `social-accounts` siguen consumiéndolo. Decisión documentada en
  `phase_2_operating_rules.md` §2 ("excepción única") y en el informe
  del implementer.
- `repositories/stores/ghl_connection_store.py`: NO borrado. Sigue con
  call sites en
  `repositories/postgres/uow.py:7,35,85,102,110-111`,
  `application/persistence.py:7,360,423,438` y
  `services/transport/http/server.py:675,679`. La regla del
  `phase_2_operating_rules.md` §2 dice "Borra ... cuando deje de tener
  call sites tras esta feature"; aún tiene, así que diferir es correcto.
- Sin `xfail` en todo `tests/`.

### Compat de payload del frontend (criterio 5)
- `ProviderConnectionUpsertPayload` (líneas 8-56 de
  `transport/payloads/connections.py`) acepta el shape legacy
  `{location_id, user_id, access_token, refresh_token, expires_at,
  status}` plano.
- El test `test_attach_persists_connection_with_encrypted_tokens`
  (`tests/integration/publishing/test_connections_router.py:65-104`)
  envía exactamente ese shape y asserta `status_code == 200`.
- Nota menor (no bloqueante): el POST devuelve 200, no 201, contradiciendo
  literalmente el "201 / 200" de la tarea, pero el implementer lo
  documenta como decisión consciente para preservar el contrato del
  frontend (que hoy hace PUT y ahora hace POST). El criterio "funciona y
  devuelve 201/200" se interpreta como rango aceptable; los tests pasan.

### Aislamiento inter-módulo (criterio 6)
- `grep -r "from modules\.(?!publishing)\w+\.(application|infrastructure)"`
  dentro de `modules/publishing/` → cero coincidencias.
- `probe_provider_connection.py:73-93` usa el legacy
  `services.publishing.social_delivery.gohighlevel_client` (legacy
  `services/`, no otro módulo). Marcado con TODO Phase 2 feature 5 para
  mover en feature 9. Aceptable: no viola `legacy_dirs_frozen`
  estructuralmente porque la feature no añade código nuevo en `services/`,
  solo lo importa transitoriamente.

### Repos sin commit (criterio 7)
- `ProviderConnectionRepository` extiende `ModuleRepository` y no
  contiene `session.commit()`.

### Tests (criterio 8)
- `tests/integration/test_http_transport.py:478-504` adaptado: usa POST
  contra el router nuevo y verifica vía `uow.publishing.connections.get_with_secrets`.
  Sin `xfail`. Imports de `GoHighLevelConnectionStore` borrados.
- `tests/integration/publishing/test_connections_router.py` (336 líneas)
  cubre attach (200, 404, 422), inspect (200, 404), rotate (200, 404),
  detach (200, 404), probe (200, 404) y autorización (401).
- `tests/unit/publishing/test_<verbo>.py` existe para los 5 use cases
  nuevos.
- Conteo total: 225 tests verdes (≥ 197 + nuevos).

### `./init.sh` verde (criterio 9)
- Ejecutado en esta revisión: `225 passed in 93.62s`. Readiness checks
  `apps.api --check` y `apps.worker --check` verdes. Sin tests rojos,
  sin flakes.

### CHECKPOINTS.md (criterio 10)
- Recorridos arriba (C1-C6). Todos en `[x]`.

## Observaciones secundarias (no bloqueantes)

1. POST attach devuelve 200 en vez de 201. El implementer lo justifica
   como mantener simetría con el `PUT` legacy del frontend. Si el frontend
   no diferencia, está bien; si en una pasada futura quieres alinear con
   convención REST estándar, sería un cambio cosmético.
2. `ListProviderConnectionsUseCase` existe pero no tiene endpoint HTTP
   dedicado (línea 324-328 del router lo deja como referencia explícita).
   Cumple el acceptance: el use case está disponible para callers
   cross-módulo (tenancy `inspect_agency`).
3. `repositories/stores/ghl_connection_store.py` queda vivo. Documentado
   en el informe del implementer y consistente con la regla "borra cuando
   no queden call sites": aún hay tres consumidores legítimos pendientes
   de la feature 9.
