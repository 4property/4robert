# Implementación — Feature 5 `publishing_connections_router`

Estado: implementación completa, pendiente de revisión por `reviewer`.

## Archivos creados

| Tipo | Path |
|------|------|
| Payload Pydantic | `modules/publishing/transport/payloads/connections.py` |
| Use case | `modules/publishing/application/use_cases/attach_provider_connection.py` |
| Use case | `modules/publishing/application/use_cases/rotate_provider_credentials.py` |
| Use case | `modules/publishing/application/use_cases/inspect_provider_connection.py` |
| Use case | `modules/publishing/application/use_cases/detach_provider_connection.py` |
| Use case | `modules/publishing/application/use_cases/list_provider_connections.py` |
| Router | `modules/publishing/transport/http/connections_router.py` |
| Test unit | `tests/unit/publishing/test_attach_provider_connection.py` |
| Test unit | `tests/unit/publishing/test_rotate_provider_credentials.py` |
| Test unit | `tests/unit/publishing/test_inspect_provider_connection.py` |
| Test unit | `tests/unit/publishing/test_detach_provider_connection.py` |
| Test unit | `tests/unit/publishing/test_list_provider_connections.py` |
| Test integration | `tests/integration/publishing/test_connections_router.py` |

## Archivos modificados

| Tipo | Path | Cambio |
|------|------|--------|
| __init__ | `modules/publishing/application/use_cases/__init__.py` | Re-exports de los 5 use cases nuevos |
| App factory | `apps/api/app_factory.py` | Registra `create_connections_router` con la AdminAccessPolicy del runtime |
| God-file legacy | `services/transport/http/server.py` | Borra los 3 handlers `/ghl-connection*` (PUT/DELETE/POST .../test), el payload Pydantic `_AdminGhlConnectionUpsertPayload`, y los runtime methods `upsert_ghl_connection` / `delete_ghl_connection` (sin call sites tras la migración) |
| Test integration legacy | `tests/integration/test_http_transport.py` | Elimina import de `GoHighLevelConnectionStore`, registra el router nuevo en el builder, y el test `test_admin_upserts_and_reads_ghl_connection_for_an_agency` ahora hace `POST /ghl-connection` y verifica vía `uow.publishing.connections.get_with_secrets`. Sin `xfail`. |

## Endpoints expuestos por el router (`/v1/admin/agencies/{agency_id}/ghl-connection`)

| Método | Path | Use case |
|--------|------|----------|
| POST   | `/ghl-connection`          | `attach_provider_connection` |
| GET    | `/ghl-connection`          | `inspect_provider_connection` |
| PUT    | `/ghl-connection`          | `rotate_provider_credentials` |
| DELETE | `/ghl-connection`          | `detach_provider_connection` |
| POST   | `/ghl-connection/test`     | `probe_provider_connection` (reutiliza el use case de feature 2) |

`list_provider_connections` existe como use case sin endpoint dedicado, listo para que tenancy / cross-módulo lo invoque sin tocar el repo directamente.

## Cifrado / no fugas de tokens

- Los secrets cruzan la frontera del use case en plaintext únicamente durante la ejecución del request; el cifrado/descifrado vive **dentro de** `ProviderConnectionRepository` (`encrypt_text` en `upsert`, `decrypt_text` en `_row_to_connection`).
- `inspect`/`list` jamás llaman a `get_with_secrets` — devuelven `ProviderConnection` con `has_secret: bool` solamente.
- El serializador del router (`_serialize_connection`) emite `has_access_token` y `has_refresh_token` (booleans), nunca el plaintext. Los tests integration verifican `assert "secret-token" not in response.text` para attach y rotate.

## Compatibilidad backward con el frontend

El payload Pydantic (`ProviderConnectionUpsertPayload`) acepta el shape legacy `{location_id, user_id, access_token, refresh_token, expires_at, status}` plano. El router lo mapea a `(external_id, secrets, config)` antes de llamar al use case. **Cambio de contrato semántico**: el método HTTP cambia de `PUT (upsert)` a `POST (attach) + PUT (rotate, requires existing)` por descriptividad — el frontend que hoy hace PUT para crear necesita migrar a POST. Documentado en `progress/explore_router_5_publishing_connections.md` (riesgo E) y validado en el test legacy adaptado.

## Decisiones no obvias

- `repositories/stores/ghl_connection_store.py` **NO se borra**. Sigue usado por `repositories/postgres/uow.py` (legacy UoW factory) y por los runtime methods `get_ghl_connection_by_agency` / `require_ghl_connection_for_agency`, que siguen consumidos por endpoints fuera del scope de feature 5: `social-accounts` (server.py:~2475), `enqueue_reel_publish` (server.py:~860). Esos los limpia feature 7 (admin reels) o feature 9 (retiro god-file). En feature 5 solo eliminamos `upsert_ghl_connection` y `delete_ghl_connection`, que sí pierden todos los call sites con esta migración.
- `runtime.test_gohighlevel_connection` también se conserva: lo sigue usando `social-accounts`. El use case `probe_provider_connection` consume el cliente HTTP legacy a través de `_list_accounts_with_legacy_client` (ya existente desde feature 2). Bonus de mover los clients al módulo no aplicado — se hará en feature 9.
- Decisión sobre `/test`: movido al router nuevo (recomendación del operating rules). Carga la connection por agency_id y delega en `probe_provider_connection.execute(location_id=...)`, manteniendo la firma existente del probe use case.

## Verificación

`./init.sh` termina verde:

```
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
........................................................................ [ 32%]
........................................................................ [ 64%]
........................................................................ [ 96%]
.........                                                                [100%]
225 passed in 94.66s (0:01:34)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Baseline previa al feature 5: 207 tests verdes (feature 4 cerrada). Tras feature 5: 225 tests (+18: 13 unit + 5 integration nuevas; el test legacy adaptado se mantiene igual en cuenta).

## Schema

No se tocó. `provider_connections` ya soporta plenamente el flujo nuevo.
