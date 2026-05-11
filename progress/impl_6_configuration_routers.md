# Implementation report — Feature 6 `configuration_routers`

> Estado: implementación completa, **revisión pendiente**.
> `feature_list.json` queda en `in_progress` (no marcamos `done` desde
> implementer).

## Decisiones operativas (Opción A confirmada)

- Los use cases escriben **directo** a `uow.configuration.<section>` (no
  pasan por `ReelProfileStore`).
- `runtime.get_reel_profile`, `runtime.apply_reel_profile_section` y
  `ReelProfileStore` se **conservan** porque tienen call sites fuera de
  esta feature:
  - `services/transport/http/server.py:835` (helper interno
    `handle_publishing_decision_approve`).
  - `services/transport/http/server.py:1401` y `:1437`
    (`/admin/agencies/{id}/reel-profile` raw — vive en feature 7/9).
  - `repositories/postgres/uow.py` (UoW legacy).
  - `application/persistence.py` (Protocol re-export).
  - Esos eliminadores los hace feature 9 (`retire_wordpress_webhook_server`)
    y feature 17 (`retire_property_store_and_repositories_stores`).
- Dueño canónico de `platforms` = **defaults**.
  `update_automation_rules` no tiene campo `platforms` (el dataclass lo
  prueba; el payload Pydantic lo rechaza con `extra="forbid"`).
- `/music-tracks` (stub) **eliminado**. Sustituido por `/music` con CRUD
  completo. El frontend deberá actualizar.

## Archivos creados

### Use cases (13) — `modules/configuration/application/use_cases/`

- `_agency_support.py` (helpers: `agency_not_found_error`,
  `music_track_not_found_error`, `ensure_agency_exists`).
- `read_brand_settings.py`, `update_brand_settings.py`.
- `read_reel_defaults.py`, `update_reel_defaults.py`.
- `read_automation_rules.py`, `update_automation_rules.py`.
- `read_social_templates.py`, `replace_social_templates.py`.
- `register_music_track.py`, `list_music_tracks.py`,
  `inspect_music_track.py`, `reconfigure_music_track.py`,
  `decommission_music_track.py`.

### Routers (5) — `modules/configuration/transport/http/`

- `brand_router.py` — `GET/PUT /v1/admin/agencies/{agency_id}/brand`.
- `defaults_router.py` — `GET/PUT /v1/admin/agencies/{agency_id}/defaults`.
- `automation_router.py` — `GET/PUT /v1/admin/agencies/{agency_id}/automation`.
- `social_templates_router.py` — `GET/PUT /v1/admin/agencies/{agency_id}/social-templates`.
- `music_router.py` — `POST/GET /music`, `GET/PUT/DELETE /music/{music_id}`.

Cada router lleva su serializer privado de respuesta (no se importa
nada desde `services/transport/http/server.py`).

### Payloads — `modules/configuration/transport/payloads/`

- `__init__.py`.
- `brand.py` — `BrandSettingsUpsertPayload`.
- `defaults.py` — `ReelDefaultsUpsertPayload` (incluye `platforms`).
- `automation.py` — `AutomationRulesUpsertPayload` (NO `platforms`,
  `extra="forbid"` lo rechaza).
- `social_templates.py` — `SocialTemplatesReplacePayload`.
- `music.py` — `MusicTrackPayload` (POST), `MusicTrackPatchPayload` (PUT).

### Tests (18 nuevos archivos)

Unit tests (13, 43 casos) — `tests/unit/configuration/`:
- `_uow_stubs.py` (helper compartido).
- `test_read_brand_settings.py`, `test_update_brand_settings.py`,
  `test_read_reel_defaults.py`, `test_update_reel_defaults.py`,
  `test_read_automation_rules.py`, `test_update_automation_rules.py`,
  `test_read_social_templates.py`, `test_replace_social_templates.py`,
  `test_register_music_track.py`, `test_list_music_tracks.py`,
  `test_inspect_music_track.py`, `test_reconfigure_music_track.py`,
  `test_decommission_music_track.py`.

Integration tests (5, 20 casos) — `tests/integration/configuration/`:
- `_client.py` (helper compartido del TestClient).
- `test_brand_router.py` (4), `test_defaults_router.py` (4),
  `test_automation_router.py` (4), `test_social_templates_router.py` (4),
  `test_music_router.py` (4).

Sin `__init__.py` en los directorios de tests (consistente con la
convención del repo: `tests/unit/publishing/` y demás tampoco lo tienen
— pytest usa rootdir-based discovery).

## Archivos modificados

### `modules/configuration/infrastructure/`

- `music_track_repository.py` — añadidos `get(music_id)` y
  `update(...)`. Mantiene `list_for_agency`, `add_track`, `delete`.
- `social_template_repository.py` — añadidos `delete_all_for_agency`
  y `replace_all_for_agency` (bulk replace consumido por
  `replace_social_templates`).

### `apps/api/app_factory.py`

- Importa `create_brand_router`, `create_defaults_router`,
  `create_automation_router`, `create_social_templates_router`,
  `create_music_router`.
- Registra los 5 routers en `build_api_app` después de
  `create_sources_router` y antes del webhook router.

### `services/transport/http/server.py`

Borrado:
- 4 payloads inline (`BrandSettingsUpsertPayload`,
  `ReelDefaultsUpsertPayload`, `AutomationRulesUpsertPayload`,
  `SocialTemplatesUpsertPayload`) — ~234 LoC.
- 8 handlers (GET+PUT × 4 secciones) — ~430 LoC.
- 1 stub handler `list_admin_agency_music_tracks` y su decorator —
  ~38 LoC.
- 4 serializers (`_serialize_brand_section`,
  `_serialize_defaults_section`, `_serialize_automation_section`,
  `_serialize_social_templates`) y 3 constantes
  `_DEFAULT_BRAND_PRIMARY_COLOR`/`_DEFAULT_BRAND_SECONDARY_COLOR`/
  `_DEFAULT_LOGO_POSITION` — ~70 LoC.
- Cross-references docstring en `_AdminReelProfileUpsertPayload`
  ajustadas para no apuntar a clases borradas.

Conservado a propósito:
- `runtime.get_reel_profile`, `runtime.apply_reel_profile_section`,
  `runtime.upsert_reel_profile`, `runtime.delete_reel_profile` (call
  sites en feature 7/9).
- Handlers `/admin/agencies/{id}/reel-profile` (GET/PUT) — feature 7/9.

### `tests/integration/test_http_transport.py`

- Quitado el import de `ReelProfileStore` (no se usa en este fichero
  tras la migración).
- Registrados los 5 routers nuevos en `_build_client`.
- 3 tests adaptados (brand, automation, social-templates) para
  verificar persistencia vía `uow.configuration.<section>`:
  - `test_brand_endpoint_only_touches_its_section` ahora pre-popula la
    sección `automation` vía `uow.configuration.automation.upsert(...)`
    y verifica que la PUT de brand no la toca.
  - `test_automation_endpoint_drives_approval_required` ahora envía el
    payload tipado nuevo (`approval_required`/window/days en vez de
    `publish_mode`/`platforms`) y verifica `uow.configuration.automation`.
  - `test_social_templates_endpoint_persists_per_network_templates`
    verifica los rows en `agency_social_templates` vía
    `uow.configuration.social_templates.list_for_agency(...)`.
- `test_admin_music_tracks_endpoint_advertises_unimplemented_state`
  **borrado** (el stub ya no existe).

## Cambios contractuales (frontend impact)

1. **Endpoint cambia: `/music-tracks` → `/music`.** El frontend de
   admin tendrá que actualizar la URL y, si quiere CRUD, los nuevos
   verbos POST/GET-detail/PUT/DELETE.
2. **`/automation` cambia el payload.**
   - Antes (god-store): `publish_mode` (`auto`/`review`),
     `platforms`, `review_window_*`, `quiet_hours_*`, `auto_captions`,
     `regen_on_update`, `review_emails`. Persistía a
     `extra_settings.automation` (jsonb) + columnas `approval_required`
     y `platforms` en `agency_reel_defaults`.
   - Ahora: `approval_required`, `publish_window_start`,
     `publish_window_end`, `publish_days`, `trigger_on_status`. Persiste
     a la tabla tipada `agency_automation_rules`. `platforms` se manda
     a `/defaults` (canonical owner).
   - El frontend admin tendrá que mapear `publish_mode === "review"` →
     `approval_required: true` antes de mandar la PUT, y mover el
     campo `platforms` al `/defaults` PUT.
3. **`/brand` cambia el shape.** Antes mezclaba columnas tipadas
   (`primary_color`, `secondary_color`, `logo_position`) con
   `extra_settings.brand` (`font`, `tagline`, `watermark_enabled`,
   `outro_enabled`, `outro_headline`, `outro_sub`). Ahora solo expone
   los campos tipados de `agency_brand_settings`: `primary_color`,
   `secondary_color`, `logo_position`, `logo_object_key`,
   `intro_logo_object_key`, `font_family`. Los campos
   "watermark/outro/tagline" del legacy quedan **fuera del scope**;
   migrarlos requiere una feature de schema aparte.
4. **`/defaults` cambia el shape.** Antes: `intro_enabled`,
   `duration_seconds`, `settings` (free-form). Ahora añade `platforms`,
   `music_id`, `caption_template`. `settings` sigue siendo free-form y
   merge-shallow con la versión guardada.
5. **`/social-templates` el contrato HTTP es estable** (`{templates:
   {platform: descripción}}`) pero ahora persiste a la tabla tipada
   `agency_social_templates` (un row por plataforma) en lugar de un
   blob jsonb. La GET añade ahora `items[]` con la forma rica
   (`description_template`, `title_template`, `hashtags`) por si el
   frontend quiere migrar.

Estos cambios son **deliberados** — Opción A los exige y el doc
operativo los acepta. Coordinación con el frontend queda fuera del
scope de este PR (los tests del repo no cubren al frontend).

## Verificación

```
$ ./init.sh
[OK]    Usando Python del venv: .venv/Scripts/python.exe
[OK]    Python 3.13.0
[OK]    Dependencias clave importables (fastapi, pydantic, sqlalchemy, alembic)
... (archivos base)
[OK]    feature_list.json válido (18 features)
[WARN]  Se han modificado 30 archivo(s) en directorios legacy en las últimas 24h.
        (es esperado: borrados handlers/payloads/serializers en server.py)
[OK]    apps.api --check verde
[OK]    apps.worker --check verde
[OK]    pytest verde — 287 passed in 122.03s
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Conteo de tests: 287 totales (tests del repo). Antes de la feature
había 224 (28 ingestion + 25 publishing + 18 tenancy + 5
worker_runtime_adapter + ... ). Esta feature aporta 63 nuevos
(43 unit + 20 integration). El total subió en +63 — borramos 1 test
del stub `music-tracks` y migramos 3 tests existentes en
`test_http_transport.py`.

## Notas no obvias

- `MusicTracksRepository.get(...)` y `update(...)` se añaden como
  métodos puros SQL (SELECT/UPDATE) sin tocar schema. La tabla
  `agency_music_tracks` ya existía.
- `SocialTemplatesRepository.replace_all_for_agency(...)` borra todos
  los rows del agency y reinsserta vía `upsert(...)`. Mapea el contrato
  flat (`{platform: string}`) a (`description_template = string`,
  `title_template = ""`, `hashtags = ()`). Migrar a un payload rico
  queda como feature aparte.
- `update_reel_defaults` hace **shallow merge** del `settings` jsonb
  para preservar valores escritos por otra pestaña del frontend (mismo
  comportamiento que el legacy).
- Los routers no comparten un `_serializers.py` — cada uno lleva su
  serializer privado. Para 5 routers de tamaño moderado eso es más
  legible que un módulo compartido cross-cutting.
- En tests de integración la persistencia se verifica reabriendo un
  `DatabaseUnitOfWork` después del request — patrón consistente con
  `tests/integration/publishing/test_connections_router.py`.
