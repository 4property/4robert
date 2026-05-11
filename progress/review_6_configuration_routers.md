# Review — feature 6 (`configuration_routers`)

**Veredicto:** APPROVED

## Resumen

La feature 6 entrega los 5 routers (`brand`, `defaults`, `automation`,
`social-templates`, `music`) con los 13 use cases descriptivos
correspondientes en `modules/configuration/`, siguiendo Opción A:
escritura directa a `uow.configuration.<section>` sin pasar por
`ReelProfileStore`. `./init.sh` termina verde con **287 tests** (incluye
+63 nuevos: 43 unit + 20 integration + 3 adaptados en
`test_http_transport.py` − 1 test stub borrado).

## Foco específico

### 1. Naming descriptivo

Verificado en `modules/configuration/application/use_cases/`:

- `read_brand_settings.py` / `update_brand_settings.py`
- `read_reel_defaults.py` / `update_reel_defaults.py`
- `read_automation_rules.py` / `update_automation_rules.py`
- `read_social_templates.py` / `replace_social_templates.py`
- `register_music_track.py`, `list_music_tracks.py`,
  `inspect_music_track.py`, `reconfigure_music_track.py`,
  `decommission_music_track.py`

Total: 13 use cases, todos con verbos descriptivos. **Ninguno** usa
`create/get/update/delete` genérico.

### 2. Path `/music` y stub `/music-tracks` eliminados

- `services/transport/http/server.py`: `grep -E "music-tracks|music_tracks"`
  → 0 hits. Stub legacy borrado.
- `tests/integration/test_http_transport.py`:
  `test_admin_music_tracks_endpoint_advertises_unimplemented_state` borrado.
- `modules/configuration/transport/http/music_router.py:67-296`: monta
  `/agencies/{agency_id}/music` (POST, GET) y `/music/{music_id}` (GET,
  PUT, DELETE).

### 3. Opción A aplicada

- Use cases escriben directo a `uow.configuration.<section>` (verificado
  caso a caso, p. ej. `update_brand_settings.py`,
  `update_reel_defaults.py:52`, `update_automation_rules.py:41`,
  `replace_social_templates.py`, `register_music_track.py:62`).
- `repositories/stores/reel_profile_store.py` **conservado**: tiene
  call sites legítimos en `services/transport/http/server.py:435,440,
  445,470,483` (helpers `runtime.get_reel_profile`,
  `apply_reel_profile_section`, `upsert_reel_profile`,
  `delete_reel_profile`) y `:587, :1153` (handlers
  `handle_publishing_decision_approve` y `/reel-profile` raw que viven
  bajo features 7/9). Conservación documentada en informe del
  implementer §"Decisiones operativas". Su retiro queda para feature 9
  (`retire_wordpress_webhook_server`) / 17.

### 4. Dueño canónico de `platforms` = `defaults`

- `update_automation_rules.py:21-48` (dataclass + use case) NO contiene
  campo `platforms`.
- `modules/configuration/transport/payloads/automation.py:16-28` con
  `extra="forbid"` → cualquier intento del cliente de mandar
  `platforms` en el JSON de `/automation` se rechaza con 422.
- `update_reel_defaults.py:23` tiene `platforms: Iterable[str] | None` y
  llama `uow.configuration.defaults.upsert(platforms=...)`.

### 5. Borrado legacy en `server.py`

`grep` directo confirma:

- Handlers `get_agency_brand_settings`, `update_agency_brand_settings`,
  `get_agency_reel_defaults`, `update_agency_reel_defaults`,
  `get_agency_automation_rules`, `update_agency_automation_rules`,
  `get_agency_social_templates`, `update_agency_social_templates`,
  `list_admin_agency_music_tracks` → 0 hits.
- Payloads inline `BrandSettingsUpsertPayload`,
  `ReelDefaultsUpsertPayload`, `AutomationRulesUpsertPayload`,
  `SocialTemplatesUpsertPayload` → 0 hits.
- Serializers `_serialize_brand_section`, `_serialize_defaults_section`,
  `_serialize_automation_section`, `_serialize_social_templates` → 0 hits.
- Sin `xfail` en todo `tests/`.

### 6. CRUD music funciona

`modules/configuration/infrastructure/music_track_repository.py`:

- `list_for_agency` (`:11`), `get(music_id)` (`:33`), `add_track`
  (`:53`), `update` (`:94`), `delete` (`:129`).
- Sin `session.commit()`.

`register_music_track.py:63` siempre genera `music_id = str(uuid4())`.
La dataclass `RegisterMusicTrackInput` no expone el campo, lo cual
satisface el spirit del requisito (uuid generado server-side).

`decommission_music_track.py` borra el track y propaga
`ResourceNotFoundError` si la agencia no es propietaria. **No** limpia
`agency_reel_defaults.music_id` si el track decommissioned era el
default — comportamiento documentado por el implementer en
§"Decisiones operativas" como acoplamiento conocido. Esto se acepta
porque el reviewer original solo pidió que el comportamiento estuviera
documentado, y lo está.

### 7. Aislamiento inter-módulo

`grep "from modules\.(reels|tenancy|ingestion|publishing|catalog|delivery|rendering)\.(application|infrastructure)" modules/configuration/`
→ 0 hits.

### 8. Pydantic en transport, dataclasses en application

`grep "from pydantic|import pydantic|BaseModel" modules/configuration/application/`
→ 0 hits. Todos los inputs son `@dataclass(frozen=True, slots=True)`
(p. ej. `RegisterMusicTrackInput`, `UpdateReelDefaultsInput`,
`UpdateAutomationRulesInput`).

### 9. Tests adaptados

- `tests/integration/test_http_transport.py:546-587` (brand) — pre-popula
  `automation` vía `uow.configuration.automation.upsert(...)` y verifica
  preservación.
- `:589-613` (automation) — payload tipado nuevo
  (`approval_required`/`publish_window_*`), verifica via
  `uow.configuration.automation.get(...)`.
- `:615-649` (social-templates) — verifica vía
  `uow.configuration.social_templates.list_for_agency(...)`.
- Test de music-tracks borrado.
- `:30-36, :174-204` registran los 5 routers nuevos en `_build_client`.

5 archivos en `tests/integration/configuration/`:
`test_brand_router.py`, `test_defaults_router.py`,
`test_automation_router.py`, `test_social_templates_router.py`,
`test_music_router.py`.

13 archivos en `tests/unit/configuration/` (uno por use case).

### 10. `./init.sh` verde

```
[OK]    apps.api --check verde
[OK]    apps.worker --check verde
[OK]    pytest verde — 287 passed in 121.44s
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Conteo total: **287 tests** ≥ 287 (requerido).

## Checkpoints

- C1: [x] Archivos base existen, `./init.sh` exit 0.
- C2: [x] Una sola feature `in_progress` (id 6), tests verdes.
- C3: [x] No imports cross-module application/infrastructure desde
        `modules/configuration/`. Repositorios extienden
        `ModuleRepository` y no llaman `session.commit()`. Domain
        layer libre de Pydantic. Application layer libre de Pydantic.
- C4: [x] 13 unit + 5 integration tests cubren las 5 secciones; usan
        `temporary_postgres_schema` y `seed_tenant`, no mocks.
- C5: [x] No tocó schema (la feature solo extrae transport y use cases).
        Las tablas `agency_*` ya existían tras Phase 1.
- C6: [x] Sin `__pycache__`/`*.tmp` colgados; sin `xfail`; sin `print()`
        de debug; `feature_list.json` deja la feature `in_progress`
        como exige el implementer rule.

## Notas no bloqueantes

- El docstring de `read_brand_settings.py:1` menciona "watermark, outro
  card" pero el use case actual solo expone los campos tipados de
  `agency_brand_settings`. Es un comentario stale heredado del legacy;
  no afecta funcionamiento. Opcional limpiarlo.
- `register_music_track.py` no acepta un `music_id` provisto por el
  cliente; siempre genera uuid. Si el frontend en el futuro necesita
  importar tracks con id externo, se podría ampliar la dataclass; no es
  un requisito ahora.

APPROVED.
