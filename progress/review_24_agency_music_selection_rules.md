# Reviewer report — feature 24 (BACK) agency_music_selection_rules

- **Fecha:** 2026-05-14
- **Agente:** reviewer (Claude Opus 4.7, 1M)
- **Veredicto:** **APROBADO** — listo para marcar `done` cuando el leader lo decida.
- **Plan de origen:** `progress/current.md` §"Trabajo en paralelo — feature 24 BACK"
- **Implementer:** `progress/impl_24_agency_music_selection_rules.md`

## 1. Resumen ejecutivo

Verificada la persistencia y wiring de `settings.music.selection_rules.fallback_to_full_library` end-to-end. Los seis acceptance criteria de `feature_list.json` (id 24) se cumplen. El alembic head sigue siendo `20260514_0005` (sin migración nueva, como prometía el plan). `bash ./init.sh` cierra en verde con la baseline preexistente de 3 fallos no relacionados (`test_http_surface_contract`, `test_http_transport`×2). No detecto regresiones ni violaciones de capa.

## 2. Acceptance criteria — punto por punto

| # | Criterio | Estado | Evidencia |
|---|----------|--------|-----------|
| 1 | PUT con `fallback_to_full_library=false` round-trips | OK | `tests/integration/configuration/test_defaults_router.py::test_defaults_put_persists_music_selection_rules_false` PUT 200 → GET 200 → DB `saved.settings == {"music": {"selection_rules": {"fallback_to_full_library": False}}}` |
| 2 | Unknown key bajo `music.*` → 422 | OK | `extra="forbid"` en `SettingsMusicPayload` y `SettingsMusicSelectionRulesPayload`. Tests: `test_defaults_put_rejects_unknown_music_key`, `test_defaults_put_rejects_unknown_selection_rules_key`. El 422 lo emite FastAPI con `extra_forbidden` (la acceptance literal pide "SETTINGS_UNKNOWN_KEY *or equivalent*"; `extra_forbidden` es el equivalente Pydantic estándar). |
| 3 | Default pool vacía + flag=false → MUSIC_NO_DEFAULT_TRACKS; flag=true → usa library | OK | Unit: `test_no_defaults_with_fallback_false_raises_music_no_default_tracks` y `test_no_defaults_with_fallback_true_uses_library`. Integration: `test_ingest_raises_when_fallback_false_and_no_defaults` (asserta `exc_info.value.code == "MUSIC_NO_DEFAULT_TRACKS"`) y `test_ingest_uses_library_when_fallback_true_and_no_defaults`. |
| 4 | Tests cubren ambos paths del flag y default cuando `settings.music` ausente | OK | 5 integration en `test_defaults_router.py` + 3 integration en `test_music_selection_rules_flow.py` + 3 unit nuevos en `test_resolve_agency_music_pool.py`. `test_defaults_get_surfaces_music_selection_rules_default` cubre explícitamente el caso "PUT sin `settings.music` → GET surface `fallback_to_full_library=true` → DB conserva la ausencia". |
| 5 | `docs/API.md` documenta la clave y su default | OK | `docs/API.md:138-166` documenta la sub-clave, el default `true`, el comportamiento `false`, la validación `extra="forbid"`, y el shape verbatim del JSON (incluye el detalle "el default NO se persiste en PUT, sólo se surface en GET"). |
| 6 | `pytest -q` verde, `--check` verde | OK con baseline | `pytest -q` → 763 passed, 3 failed. Los 3 fallos coinciden 1:1 con la baseline declarada en `progress/current.md` (HOTFIX `side_banner_footer_radius` los lista en su bitácora). `apps.api --check` y `apps.worker --check` verdes. |

## 3. Decisiones del implementer verificadas

### 3.1 Opción A del payload — confirmada

`modules/configuration/transport/payloads/defaults.py`:
- `settings: dict | None` se mantiene free-form (línea 142).
- `@field_validator("settings")` (línea 152) extrae sólo el sub-árbol `music`, lo parsea con `SettingsMusicPayload.model_validate(raw_music)` (línea 177) y re-emite con `model_dump(exclude_none=True)` (línea 178) para preservar la ausencia de defaults.
- `SettingsMusicPayload` y `SettingsMusicSelectionRulesPayload` ambos con `model_config = ConfigDict(extra="forbid")` (líneas 28, 50).
- El resto de claves de `settings` (currency, language, automation.*, etc.) siguen siendo free-form → preserva el test `test_defaults_put_persists_namespaced_automation_settings` que vi corriendo en verde.

**No hay regresión** del comportamiento pre-feature-24 para `settings.{currency, automation.*, etc.}`.

### 3.2 Read/write asimétrico — confirmado

- `defaults_router._serialize_defaults` (líneas 165-197) llama `_settings_with_music_defaults` tanto en el branch `record is None` (agencia nueva) como en el branch con registro existente. El helper delega en `resolve_music_selection_rules(settings)` para calcular el dict definitivo.
- `_settings_with_music_defaults` (líneas 200-217) NO escribe en DB; sólo construye el dict de respuesta.
- `update_reel_defaults.execute` (línea 67) sigue haciendo merge shallow sin inyectar defaults: `merged_settings = {**existing_settings, **dict(data.settings)}`. El validador de payload ya re-serializó `music` sin defaults vía `exclude_none=True`, así que la JSONB queda exactamente como la mandó el cliente.
- Round-trip frontend (GET → modificar `music.selection_rules.fallback_to_full_library` → PUT) NO se rompe: el GET trae el sub-objeto explícito, el frontend lo mantiene/cambia, y el PUT lo envía verbatim. **Caveat** (no bloqueante, ver §4) sobre el merge shallow del nivel `music.*` por si en el futuro se añaden hermanas a `selection_rules`.

### 3.3 `_resolve_agency_music_pool` — firma y semántica verificadas

`modules/reels/application/use_cases/_resolve_agency_music_pool.py:47-122`:
- Nueva kwarg `fallback_to_full_library: bool = True` (línea 52). El default preserva backwards-compat para callers/tests existentes.
- Branching idéntico a lo descrito en el plan:
  - `all_tracks` vacío → `PropertyReelError(code="MUSIC_NO_TRACKS")` (independiente del flag, línea 86).
  - `default_tracks` no vacío → usa default (línea 96-97).
  - Vacío + `fallback_to_full_library=True` → library completa (línea 98-99).
  - Vacío + `fallback_to_full_library=False` → `PropertyReelError(code="MUSIC_NO_DEFAULT_TRACKS", stage="prepare")` (línea 104-117). El `hint` apunta a las dos rutas de fix (marcar default o reactivar flag).
- Code string `MUSIC_NO_DEFAULT_TRACKS` coincide con lo que pide acceptance #3 y con lo que asertan los tests.

### 3.4 `ingest_property_into_reel` — wiring del flag

`modules/reels/application/use_cases/ingest_property_into_reel.py`:
- Nuevo helper `_resolve_music_selection_rules` (líneas 590-620) lee defensivamente `uow.configuration.defaults.get(agency_id)` y delega en `resolve_music_selection_rules` (export público de `read_aggregated_reel_profile`). Cualquier eslabón ausente (no agency_id, no configuration namespace, no defaults repo, no row) cae al default `{fallback_to_full_library: true}`.
- Llamada en `execute` (líneas 170-181): el flag se resuelve antes de `resolve_agency_background_audio_candidates` y se forwardea con `bool(music_selection_rules.get("fallback_to_full_library", True))`.

### 3.5 `regenerate_reel.py` sin cambios — confirmado

`grep -n 'music\|resolve_agency_background_audio_candidates\|fallback_to_full_library' modules/reels/application/use_cases/regenerate_reel.py` → 0 hits. Este use case sólo encola un `reel_publish` job y no resuelve la pool de audio. El worker termina invocando `ingest_property_into_reel` para el re-render, así que el flag se aplica downstream sin tocar este archivo. La nota del implementer es correcta.

### 3.6 Schema sin cambios — confirmado

`.venv/bin/python -m alembic heads` → `20260514_0005 (head)`. Sin migración nueva, sin `down_revision` retocada. La JSONB `agency_reel_defaults.settings` ya existe; la sub-clave es transparente al schema.

### 3.7 Layer rules — sin violaciones nuevas

- `grep -rn 'from modules.configuration' modules/rendering/` → 2 hits, ambos de `modules.configuration.domain` (tipos `RenderTemplate`, `MusicTrack`). Cero imports de `modules.configuration.application` o `modules.configuration.infrastructure` desde rendering. Esa frontera está intacta.
- `ingest_property_into_reel` (modules/reels/application) importa `resolve_music_selection_rules` de `modules.configuration.application.use_cases.read_aggregated_reel_profile` — `modules/reels/application` YA importaba de `modules.configuration.application` (e.g. `compute_next_publish_slot`, `read_aggregated_reel_profile`), así que esta dependencia no es nueva ni rompe nada.
- El flag se resuelve **antes** de invocar el runtime (`resolve_agency_background_audio_candidates` vive en `modules/reels/application`, no en `modules/rendering`). El renderer recibe un `tuple[Path, ...]` ya filtrado; nunca pregunta a configuración.

## 4. Caveats no bloqueantes

1. **Merge shallow a nivel `settings.*`, no `settings.music.*`** — `update_reel_defaults.py:67` hace `{**existing_settings, **dict(data.settings)}`. Si una agencia tuviera persistido `settings.music = {"selection_rules": {...}, "future_other_key": {...}}` y el frontend mandara un PUT con sólo `settings.music.selection_rules`, el merge a nivel `settings.*` reemplazaría completamente `music` (perdería `future_other_key`). Hoy no hay riesgo porque `music.*` sólo contiene `selection_rules` y el `extra="forbid"` lo blinda. Recomendación: cuando la feature 25 (per_reel_music_override) o cualquier feature posterior añada otra hermana bajo `music.*`, valorar un deep merge a nivel `music.*`. No es bloqueante para la 24.

2. **Mensaje 422 sin code custom** — la acceptance dice "422 SETTINGS_UNKNOWN_KEY o equivalente". Hoy Pydantic emite `{"type": "extra_forbidden", "loc": ["body", "settings", "music", "unknown_key"], ...}`, que es el equivalente estructurado. Si el front quisiera leer un `code` discriminador, habría que envolver con un handler custom; no es estrictamente necesario porque la `loc` ya identifica el campo y el `type` ya identifica la causa. El implementer eligió no añadir handler — coherente con el resto del repo (no existe handler global de `RequestValidationError` que añada un `code: "SETTINGS_UNKNOWN_KEY"`).

3. **`SettingsMusicPayload.selection_rules: ... | None`** — el sub-objeto se declara `Optional` con default `None`, y la validación lo permite explícitamente. Eso significa que `PUT settings.music = {}` (música presente sin selection_rules) **se acepta y se persiste como `{"music": {}}`**. No es un problema funcional (`resolve_music_selection_rules` devuelve el default en ese caso), pero es información residual en la JSONB. No bloquea — es coherente con la decisión "preservar la ausencia, no inyectar defaults".

## 5. Comandos ejecutados (todos verdes / acordes a baseline)

```bash
cd /opt/projects/4Reels-Backend
bash ./init.sh
# → exit 0, 3 failed (baseline preexistente), 763 passed, 14 warnings

.venv/bin/python -m alembic heads
# → 20260514_0005 (head)

.venv/bin/python -m pytest \
  tests/integration/configuration/test_defaults_router.py \
  tests/integration/reels/test_music_selection_rules_flow.py \
  tests/unit/reels/ tests/unit/configuration/ -v
# → 224 passed in 20.38s

.venv/bin/python -m apps.api --check       # → verde
.venv/bin/python -m apps.worker --check    # → verde
```

Greps clave:
- `grep -rn 'fallback_to_full_library\|MUSIC_NO_DEFAULT_TRACKS' modules/ tests/ docs/` → todas las apariciones esperadas, código + tests + docs alineados.
- `grep -rn 'SettingsMusicPayload\|SettingsMusicSelectionRulesPayload' modules/ tests/` → declaración + uso en validator + `__all__`.
- `grep -rn 'from modules.configuration' modules/rendering/` → 2 hits, ambos a `.domain` (tipos), 0 hits a `.application`/`.infrastructure`. Frontera rendering ↛ configuration intacta.
- `grep -n 'resolve_agency_background_audio_candidates\b' modules/ -r` → 1 callsite real (ingest_property_into_reel:174) + 1 definición + 1 `__all__`. Todos los callsites forwardean el flag correctamente.

## 6. Verificación cruzada contra :8001

No ejecutada (instrucciones explícitas del plan: el runtime de :8001 no tiene aún el código de feature 24; tests integration cubren el contrato). El plan también prohibía `alembic upgrade` desde el reviewer — confirmado no ejecutado.

## 7. Recomendaciones para el leader

1. Marcar feature 24 BACK `done` cuando archives `progress/current.md` (no antes — front feature 24 todavía pending).
2. Lanzar implementer del front (feature 24) — el contrato GET/PUT está estable; el toggle puede conectarse leyendo `settings.music.selection_rules.fallback_to_full_library` del GET y enviándolo de vuelta en el PUT.
3. Apuntar el caveat §4.1 (merge shallow a nivel `music.*`) en el plan de feature 25 (`per_reel_music_override`) por si esa feature añade hermanas bajo `music.*` que conviva con `selection_rules`.

## 8. Conclusión

Implementación **aprobada**. Cumple los seis acceptance criteria, mantiene la frontera arquitectónica rendering ↛ configuration, no introduce migración, y los 8 tests nuevos (5 integration + 3 unit) cubren los happy paths y los failure paths declarados. Los 3 fallos de `pytest -q` son baseline preexistente y están documentados en `progress/current.md`.
