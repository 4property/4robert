# Implementer report — feature 24 (BACK) agency_music_selection_rules

- **Fecha:** 2026-05-14
- **Agente:** implementer (Claude Opus 4.7)
- **Estado:** entregado al reviewer — feature **no** marcada `done`.

## 1. Resumen

Persistencia y wiring de la regla `settings.music.selection_rules.fallback_to_full_library` en `agency_reel_defaults.settings` (JSONB). Reescribe `_resolve_agency_music_pool` para honrar el flag (deja de hardcodear `True` desde feature 23) y conecta el use case `ingest_property_into_reel` a la nueva fuente de verdad. No toca schema (la columna ya es JSONB).

## 2. Decisión: payload Pydantic — Opción A

He elegido **Opción A** del plan:

- `settings` sigue tipado como `dict | None` en `ReelDefaultsUpsertPayload` (no se reemplaza por un modelo Pydantic con `extra="allow"`).
- Validación parcial del sub-documento `music` via un `@field_validator("settings")` que parsea sólo `value["music"]` con `SettingsMusicPayload` y lo re-serializa con `model_dump(exclude_none=True)`.

Razón:
- El resto de claves de `settings` (frontend INITIAL_DEFAULTS: `currency`, `language`, `aspect`, `subFont`, `automation.quietHoursEnabled`, etc.) son de forma libre y el test `test_defaults_put_persists_namespaced_automation_settings` ya documenta el contrato verbatim. Cambiar `settings` a un modelo Pydantic — incluso con `extra="allow"` — habría obligado a documentar todas esas claves namespaced o aceptar que Pydantic las recoja en `__pydantic_extra__`, complicando el merge con `mapping_to_jsonb`.
- La Opción A aísla la validación al sub-arbol que realmente queremos restringir (`music.*` y `music.selection_rules.*`) sin perder forward-compat para el resto del payload.
- `model_dump(exclude_none=True)` preserva la ausencia de claves: si el cliente envía `selection_rules` con sólo `fallback_to_full_library`, el dict persistido no acumula otras keys default. Esto satisface el requisito "NO persistas el default si está ausente".

## 3. Shape exacto del PUT /defaults con sub-objeto

```http
PUT /v1/admin/agencies/{agency_id}/defaults
Content-Type: application/json

{
  "settings": {
    "music": {
      "selection_rules": {
        "fallback_to_full_library": false
      }
    }
  }
}
```

- `extra="forbid"` en `SettingsMusicPayload`: cualquier clave bajo `music.*` distinta de `selection_rules` → 422.
- `extra="forbid"` en `SettingsMusicSelectionRulesPayload`: cualquier clave bajo `selection_rules.*` distinta de `fallback_to_full_library` → 422.
- El raíz `settings` sigue siendo free-form, así que `settings.currency`, `settings.subFont`, etc. continúan funcionando exactamente igual que antes (preserva test `test_defaults_put_persists_namespaced_automation_settings`).
- El PUT preserva la ausencia: si el cliente no envía `settings.music`, no se inserta en la JSONB.
- El GET añade el default `{fallback_to_full_library: true}` en respuesta (vía `_settings_with_music_defaults`), pero no toca el storage.

## 4. Cómo `_resolve_agency_music_pool` carga el flag

### Firma actualizada

```python
def resolve_agency_background_audio_candidates(
    *,
    uow: "DatabaseUnitOfWork",
    agency_id: str,
    workspace_dir: Path,
    fallback_to_full_library: bool = True,
) -> tuple[Path, ...]:
```

- El default (`True`) preserva backwards-compat para callers/tests existentes.
- Si `default_tracks` no vacía → se usa esa pool (flag ignorado).
- Si vacía y `fallback_to_full_library=True` → usa la library completa.
- Si vacía y `fallback_to_full_library=False` → `raise PropertyReelError(code="MUSIC_NO_DEFAULT_TRACKS", stage="prepare", ...)` con hint apuntando a las dos formas de resolverlo (marcar un track como default o reactivar el flag).
- Si la library entera está vacía → mantiene el raise `MUSIC_NO_TRACKS` independientemente del flag.

### Caller (`IngestPropertyIntoReelUseCase`)

Nuevo helper `_resolve_music_selection_rules` en la misma clase. Lee `uow.configuration.defaults.get(agency_id)` defensivamente (cualquier eslabón ausente → cae al default) y delega en `resolve_music_selection_rules(settings)` (helper exportado desde `read_aggregated_reel_profile`).

El uso queda:
```python
music_selection_rules = self._resolve_music_selection_rules(uow=uow, agency_id=...)
background_audio_candidates = resolve_agency_background_audio_candidates(
    uow=uow,
    agency_id=...,
    workspace_dir=self.workspace_dir,
    fallback_to_full_library=bool(
        music_selection_rules.get("fallback_to_full_library", True)
    ),
)
```

### `regenerate_reel.py`

No requiere cambios para esta feature: ese use case encola un `reel_publish` job pero **no** resuelve la pool de audio aquí; el worker termina ejecutando `ingest_property_into_reel` (o el equivalente downstream) que ya queda parcheado. El feature_list lo mencionaba como sospechoso, pero al revisarlo confirmo que sólo lee `defaults.platforms` y `defaults.render_template_id`, no la sub-clave música.

## 5. Archivos modificados

```
modules/configuration/transport/payloads/defaults.py
modules/configuration/application/use_cases/read_aggregated_reel_profile.py
modules/configuration/transport/http/defaults_router.py
modules/reels/application/use_cases/_resolve_agency_music_pool.py
modules/reels/application/use_cases/ingest_property_into_reel.py
tests/integration/configuration/test_defaults_router.py     (+5 tests)
tests/integration/reels/test_music_selection_rules_flow.py  (nuevo, 3 tests)
tests/unit/reels/test_resolve_agency_music_pool.py          (+3 tests)
docs/API.md                                                  (sub-clave documentada en §3)
progress/current.md                                          (bitacora actualizada)
```

## 6. Resultados de verificación

```
.venv/bin/python -m pytest tests/integration/configuration/test_defaults_router.py \
    tests/integration/rendering/ tests/integration/reels/ \
    tests/unit/reels/ tests/unit/configuration/ -q
→ 272 passed in 82.22s

.venv/bin/python -m pytest -q
→ 763 passed, 3 failed in 329s
   FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
   FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
   FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
   (Los 3 fallos coinciden con la baseline declarada en el plan.)

.venv/bin/python -m apps.api --check
→ verde

.venv/bin/python -m apps.worker --check
→ verde
```

## 7. Notas para el reviewer

- **Layer rules:** ni `_resolve_agency_music_pool` ni `defaults_router.py` importan código de `modules/rendering/{application,infrastructure}` que rompa la frontera. `_resolve_agency_music_pool` sigue importando `resolve_agency_music_local_paths` desde `modules/rendering/infrastructure/runtime/assets` (esa relación ya existía pre-feature, está documentada en el módulo doc-string). El nuevo import `resolve_music_selection_rules` en `ingest_property_into_reel` viene de `modules/configuration/application/use_cases/read_aggregated_reel_profile.py` — `modules/reels/application` ya importa de `modules/configuration/application` (e.g. `compute_next_publish_slot`), así que no hay nueva dependencia cross-bounded-context.
- **No commits en repos:** `defaults_repository.upsert` ya hacía el INSERT/UPDATE bajo el contexto del UoW; no se han añadido `session.commit()` extras.
- **Migration:** ninguna; el feature_list lo aclaraba ("settings ya es JSONB").
- **GET vs PUT asimétrico (intencional):** el GET surface `{fallback_to_full_library: true}` cuando la sub-clave está ausente; el PUT preserva esa ausencia en disco. Documento esto explícitamente en `_serialize_defaults` y en el test `test_defaults_get_surfaces_music_selection_rules_default`. Si el reviewer prefiere "persistir el default en el primer write", se puede cambiar en `update_reel_defaults` pero pierde la propiedad de "una agencia migrada nunca tiene state implícito" — preferí dejarlo simétrico con cómo se trata `render_template_id` (default `"classic"` aplicado on-read en `to_public_dict`, no persistido).
- **Test integration con FFmpeg:** `test_music_selection_rules_flow` arma blobs MP3 stub (`b"stub-mp3-bytes"`) en disco. Ingest sólo necesita resolver paths; no renderiza, así que el contenido del MP3 no importa para que el test pase.

## 8. Próximo paso

Reviewer back → cierre cross-repo (front feature 24).
