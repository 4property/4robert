# impl 25 — per_reel_music_override (BACK)

- **Inicio:** 2026-05-14
- **Agente:** implementer (Claude Opus 4.7 1M)
- **Estado al cierre:** feature **NO marcada `done`** (esperando reviewer).
- **Verificación final:** `bash ./init.sh` exit 0 con 3 failed baseline + 778 passed; `alembic upgrade head` ⇄ `downgrade -1` ⇄ `upgrade head` verde; `apps.api --check` y `apps.worker --check` verdes.

## Resumen ejecutivo

Backend de la última feature del bundle música. Añade override de pista
de fondo per-reel:

1. Columna `reels.music_id String(36) NULL` con FK `agency_music_tracks.id ON DELETE SET NULL`.
2. PATCH `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/music`
   con body `{music_id: str | null}`.
3. Use case que valida agencia/cross-agency/estado del reel, persiste y
   re-encola un `reel_publish` con `override_music_track_id` en el
   `publish_context_json` del job.
4. Worker `ingest_property_into_reel` aplica el override sustituyendo la
   pool resuelta por una tupla de 1 elemento; si la pista referida no
   resuelve, fallback al pool default con warning.
5. Tests integration (9) + unit (6); docs en `docs/API.md` y
   `docs/http_surface.md`.

## Decisiones de diseño relevantes

### 403 vs 404 cross-agency → 404 `ADMIN_MUSIC_TRACK_NOT_FOUND`

Tanto "music_id inexistente" como "music_id de otra agencia" se
colapsan en un único **404 `ADMIN_MUSIC_TRACK_NOT_FOUND`** (definido en
`update_reel_music_override._music_track_not_found_error`). Razón:
sigue la convención cross-tenant de feature 22 / endpoints de música
de configuración (no leak de existencia entre agencias). Devolver 403
permitiría a un agente externo aprender que un id concreto pertenece a
otra tenant.

### Path exacto del PATCH

```
PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/music
```

Mismo shape que el PATCH de descripciones (feature 21) — handler junto
en `modules/reels/transport/http/admin_reels_router.py` para reutilizar
auth, error handlers y serialización de `_serialize_agency_reel`.

### Cómo viaja `override_music_track_id` por el publish_context

1. `UpdateReelMusicOverrideUseCase` re-encola un job idéntico al que
   produce `RegenerateReelUseCase`, con un campo adicional en
   `publish_context`: `"override_music_track_id": <music_id|None>`.
2. El campo se persiste en `jobs.publish_context_json` (JSONB).
3. Al despachar el job, `modules/reels/application/orchestrator.py:272`
   ya parsea `publish_context_json` con `SocialPublishContext.from_dict`.
   Esa clase ahora tiene un nuevo slot `override_music_track_id: str | None`
   (default `None`, backward-compat con jobs viejos).
4. En `IngestPropertyIntoReelUseCase._execute_with_uow` añadimos una
   llamada a `_apply_music_track_override` después de resolver la pool
   de la agencia. El helper:
   * lee `publish_context.override_music_track_id`;
   * si está vacío → pass-through;
   * carga el track via `uow.configuration.music.get(music_id=…)`;
   * valida same-agency;
   * sustituye `background_audio_candidates` por
     `resolve_agency_music_local_paths(…, music_tracks=(track,))`.
5. La tupla resultante fluye por `PropertyContext.background_audio_candidates`
   tal cual antes — el renderer no necesita cambios (lo cubre feature 23).

Además, `RegenerateReelUseCase` ahora copia el `existing_state.music_id`
al `publish_context` que reencola al aprobar, así la ruta approve
preserva la elección del editor sin necesidad de re-PATCHear música.

### Comportamiento si la pista override fue borrada antes del render

Tres salvaguardas combinadas:

1. **A nivel DB**, la FK lleva `ON DELETE SET NULL`. Si la agencia
   borra el track via `DELETE /v1/admin/agencies/{id}/music/{music_id}`,
   `reels.music_id` se pone a NULL automáticamente, **pero** el job
   ya encolado mantiene el `override_music_track_id` en su
   `publish_context_json`.
2. **A nivel worker**, `_apply_music_track_override` re-consulta
   `agency_music_tracks` antes de aplicar el override. Si el `get`
   devuelve `None`, o si la `agency_id` no coincide, hace
   `logger.warning(...)` y devuelve la pool original sin tocar.
3. El render sigue completo con la pool default y queda traza en
   logs. NO se propaga `ResourceNotFoundError` desde
   `_apply_music_track_override` (a propósito — el dueño del reel
   acaba de quitarse el track en otra pestaña, no es un error
   recuperable manualmente y forzar fallo bloquearía render).

## Cambios por archivo (back-only)

### Schema / persistencia

| Archivo | Cambio |
|---|---|
| `alembic/versions/20260514_0006_reels_music_id_override.py` | **Nuevo.** Añade columna + FK ON DELETE SET NULL. Downgrade dropa FK + columna. |
| `shared/db/orm.py` | `ReelORM.music_id` `String(36)` nullable + FK. |
| `modules/reels/domain/reel_state.py` | Nuevo campo `music_id: str \| None = None`. |
| `modules/reels/infrastructure/reel_state_repository.py` | SELECT/INSERT/UPDATE incluyen `music_id`; `update_publish_status`/`update_workflow_state`/`save_local_artifacts` re-emiten el campo igual que ya hacen con `descriptions_override`. |

### Transport / use case

| Archivo | Cambio |
|---|---|
| `modules/reels/transport/payloads/reel_music_override.py` | **Nuevo.** `ReelMusicOverridePayload {music_id: str \| None}` con `extra='forbid'`. |
| `modules/reels/application/use_cases/update_reel_music_override.py` | **Nuevo.** Use case con validaciones (agencia, reel, estado editable, cross-agency) + re-enqueue (mirror de `RegenerateReelUseCase`) con `override_music_track_id` en publish_context. |
| `modules/reels/transport/http/admin_reels_router.py` | Inyecta el use case nuevo y registra el handler `patch_admin_agency_reel_music`. |

### Worker

| Archivo | Cambio |
|---|---|
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | Llama a `_apply_music_track_override` justo después del pool resolver; el método nuevo está en la misma clase, defensivo frente a stubs sin `configuration.music`. |
| `modules/reels/application/use_cases/regenerate_reel.py` | El publish_context del approve emite ahora `override_music_track_id` desde `existing_state.music_id`. |
| `modules/reels/domain/types.py` | `SocialPublishContext` añade `override_music_track_id`; `to_dict` lo emite; `from_dict` lo lee (tolera la clave ausente para backward-compat con jobs viejos). |

### Docs / tests

| Archivo | Cambio |
|---|---|
| `docs/API.md` | Nueva fila en la tabla + sección "`PATCH .../music` (feature 25)" con shape de request/response y matriz de errores. |
| `docs/http_surface.md` | Nueva fila para el PATCH. |
| `tests/integration/reels/test_admin_reels_music_override.py` | **Nuevo.** 9 tests (happy, null clear, prereqs-missing, 404 unknown id, 404 cross-agency, 404 unknown reel, 404 unknown agency, 409 published, 422 extra keys). |
| `tests/unit/reels/test_ingest_applies_music_override.py` | **Nuevo.** 6 tests sobre `_apply_music_track_override` (swap, fallback-on-missing, fallback-on-cross-agency, noop sin override, noop sin publish_context, noop sin music repo). |
| `tests/integration/configuration/test_seed_existing_agencies_music.py` | Ajustado: 3 llamadas `alembic downgrade -1` ahora apuntan a la revisión explícita `20260514_0004` para seguir reproduciendo el data-path del seed migration (que es `20260514_0005`) ahora que `20260514_0006` está en head. |

## Verificación

```
.venv/bin/python -m alembic heads          # → 20260514_0006 (head)
.venv/bin/python -m alembic upgrade head   # verde
.venv/bin/python -m alembic downgrade -1   # verde (vuelve a 20260514_0005)
.venv/bin/python -m alembic upgrade head   # verde
.venv/bin/python -m pytest tests/unit/reels/test_ingest_applies_music_override.py -q
  → 6 passed
.venv/bin/python -m pytest tests/integration/reels/test_admin_reels_music_override.py -q
  → 9 passed
.venv/bin/python -m pytest tests/integration/reels/ tests/unit/reels/ tests/integration/rendering/ tests/unit/rendering/ -q
  → 283 passed
.venv/bin/python -m pytest -q
  → 3 failed (baseline pre-existente: test_http_surface_contract.py y dos de test_http_transport.py),
    778 passed
.venv/bin/python -m apps.api --check       # OK
.venv/bin/python -m apps.worker --check    # OK
```

`bash ./init.sh` final: exit 0; mantiene los 3 fallos de baseline.

## Pendiente fuera del scope back

- Front cross-repo: tarea `#30. Feature 25 — implementer front`.
- Reviewer back: tarea `#29. Feature 25 — reviewer back`.
- NO se marca `done` en `feature_list.json` desde aquí (per instrucciones).
