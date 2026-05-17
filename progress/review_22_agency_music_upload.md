# review 22 — agency_music_upload (backend)

Sesión: 2026-05-14 — reviewer Claude (rol delegado por leader).
Branch: trunk (sin worktree separado).

## Veredicto

**APPROVED**

Feature 22 back cumple los 10 acceptance bullets. La verificación local
(`./init.sh` + suite targeted + sweep integration + readiness checks) sale
verde, los 3 fallos baseline preexistentes se preservan (no aumenta el
rojo), el shape del response casa campo-por-campo con el mock del
frontend, no hay migraciones nuevas (head sigue siendo `20260514_0004`),
y los greps duros sobre layer rules y `session.commit()` salen vacíos.

## Cumplimiento de acceptance criteria

1. **POST `/music/upload` 201 con shape correcto + blob persistido +
   duration coherente** —
   `modules/configuration/transport/http/music_upload_router.py:438-445`
   (response 201, `status='created'`, `agency_id` + `music_track`),
   `_serialize_track` en `music_upload_router.py:548-557` (incluye
   `agency_id` DENTRO de `music_track`).
   Persistencia atomic write en
   `modules/configuration/application/use_cases/upload_music_track.py:86-91`
   (`resolve_agency_music_destination` → `_write_atomic`). Duration via
   ffprobe en `upload_music_track.py:172-212`. Test
   `tests/integration/configuration/test_music_upload_router.py:60-124`
   verifica response, blob en disco (`generated_media/_agency_music/...`),
   round-trip GET sirviendo los mismos bytes.

2. **MIME inválido → 400 MUSIC_TRACK_AUDIO_INVALID; >20MB → 413; sin
   display_name → 422; ffprobe fail → 400 con code + hint** —
   `music_upload_router.py:346-356` (MIME no permitido, code +
   `details.allowed_content_types`),
   `music_upload_router.py:307-316` y `:364-376` (413, double-check
   envelope + parte interna),
   `music_upload_router.py:328-343` (422 missing/blank display_name +
   422 too-long),
   `upload_music_track.py:107-117` (ffprobe fail → ValidationError
   `MUSIC_TRACK_AUDIO_INVALID` con `hint` "Re-encode the audio…").
   Tests: `test_music_upload_router.py:127-147` (MIME),
   `:150-168` (>20MB), `:171-211` (display_name missing + blank),
   `:238-267` (ffprobe fail + cleanup).

3. **GET `/file/{filename}` admin auth scope-checked; cross-agency →
   403/404** — `music_upload_router.py:466-468` (authorize_admin_request
   antes de tocar nada), `:478-492` (inspect use case verifica el
   `agency_id` vía `InspectMusicTrackUseCase`, que en
   `modules/configuration/application/use_cases/inspect_music_track.py:27-29`
   filtra cross-agency devolviendo `MUSIC_TRACK_NOT_FOUND`).
   Cross-agency 404 (no 403) es consistente con el patrón del repo —
   `modules/configuration/transport/http/brand_logo_router.py:368,387`
   también devuelve 404 `BRAND_LOGO_FILE_NOT_FOUND` sin distinguir entre
   "no existe" y "no eres el dueño". Acceptance pedía "403/404 según
   política existente" → 404 es la elección correcta.
   Test `test_music_upload_router.py:324-351` cubre cross-agency.

4. **POST metadata-only retirado a 405** —
   `modules/configuration/transport/http/music_router.py:69-102`. El
   handler exige auth primero (`:85-87`) para no leakar existencia, y
   responde 405 `METHOD_NOT_ALLOWED` con `details.use_endpoint` apuntando
   al upload. Acceptance permitía 405 o 404; 405 es mejor semántica HTTP
   (el recurso existe, el método no se acepta).
   Test `test_music_router.py:50-72`.

5. **PUT rechaza `object_key` Y `duration_seconds` con 422** —
   `modules/configuration/transport/payloads/music.py:47-65`
   (`MusicTrackPatchPayload` con `model_config(extra='forbid')`,
   campos = solo `display_name | is_default`). Tests
   `test_music_router.py:177-201` y `:204-224` cubren ambos casos
   explícitamente. El handler PUT
   (`music_router.py:200-201`) pasa siempre `object_key=None,
   duration_seconds=None` al use case, así el cliente no puede
   sobrescribirlos via PUT aunque rompan la validación.

6. **`resolve_agency_music_destination` devuelve `(object_key, Path)`
   determinista** —
   `shared/storage/site_layout.py:94-120` (firma + layout
   `workspace_dir/generated_media/_agency_music/{safe_agency}/`,
   `object_key = "agencies/{safe_agency}/music/{filename}"`).
   Compañero defensivo `resolve_agency_music_local_path` en
   `:123-161` (rechaza `..`, `://`, formas distintas). Mismo patrón que
   `resolve_agency_branding_*` (líneas 32-91), lo que deja la puerta
   abierta a adaptador S3 sin tocar HTTP.

7. **`alembic upgrade head` sin cambios** — `alembic heads` =
   `20260514_0004 (head)` (singleton, sin migración nueva). Confirmado
   por `feature 22` sin entry posterior en `alembic/versions/`.

8. **`pytest -q` verde (baseline + nuevos)** — 731 passed, 3 baseline
   failures preservados (los 3 mismos: `test_http_surface_contract` y 2
   en `test_http_transport`). Suite targeted:
   `tests/integration/configuration/test_music_upload_router.py` +
   `test_music_router.py` + `tests/unit/configuration/` = **134
   passed** (incluye 11 + 7 + 5 = 23 tests directos de feature 22).
   Sweep `tests/integration/configuration/ tests/integration/tenancy/` =
   **89 passed**.

9. **`apps.api --check` y `apps.worker --check` exit 0** — ambos
   verdes:
   - `apps.api --check`: `RUNTIME READY: Yes`, `FFMPEG: /usr/bin/ffmpeg`,
     exit 0.
   - `apps.worker --check`: `Worker --check OK: kinds=reel_publish,
     scripted_render worker_count=1 lease=900s poll=0.50s`, exit 0.

10. **`docs/API.md` + `docs/http_surface.md` + `docs/openapi.json`
    reflejan el endpoint** —
    - `docs/API.md:405` (POST), `:408` (GET), `:428-466` (descripción
      detallada con campos + códigos de error).
    - `docs/http_surface.md:36` (POST upload_admin_agency_music_track),
      `:40` (GET stream_admin_agency_music_track), módulo
      `modules.configuration.transport.http.music_upload_router`.
    - `docs/openapi.json:2294` (POST retirado 405),
      `:2333` (POST upload), `:2528` (GET file).

## Verificación ejecutada

| comando | resultado |
|---|---|
| `bash ./init.sh` | exit 0 — 731 passed, 3 baseline failed, mismo trío preexistente |
| `.venv/bin/python -m alembic heads` | `20260514_0004 (head)` (singleton) |
| `.venv/bin/python -m pytest tests/integration/configuration/test_music_upload_router.py tests/integration/configuration/test_music_router.py tests/unit/configuration/ -v` | **134 passed in 28.16s** (11 upload + 7 router + 5 unit + resto suite configuration) |
| `.venv/bin/python -m pytest tests/integration/configuration/ tests/integration/tenancy/ -q` | **89 passed in 128.61s** |
| `.venv/bin/python -m apps.api --check` | exit 0 (`RUNTIME READY: Yes`) |
| `.venv/bin/python -m apps.worker --check` | exit 0 (`Worker --check OK`) |

Greps duros:

- `grep -rn 'from modules.rendering' modules/configuration/` → **0
  hits** (layer rules OK, ffprobe vía `subprocess`+`shutil.which` local
  al use case, ver `upload_music_track.py:172-212`).
- `grep -rnE 'session\.commit\(\)' modules/configuration/infrastructure/` →
  **0 hits** (UoW respetado).
- `grep -rn 'resolve_agency_music_destination\|resolve_agency_music_local_path' shared/ modules/ tests/` →
  2 helpers en `site_layout.py`, 2 callers (use case + stream handler) y
  exports en `__all__`. Ningún caller huérfano fuera del nuevo módulo.

Fixture: `tests/integration/configuration/_fixtures/tiny.mp3` 4510
bytes, `file` reporta `Audio file with ID3 version 2.4.0 ... MPEG ADTS
layer III v2 56 kbps 22.05 kHz Monaural`. ffprobe lo procesa
correctamente (test happy path verifica `duration_seconds >= 1`).

## Cross-repo: shape comparado con el mock frontend

Mock frontend (`tests/support/mock-backend.js`):

```js
{ status: 'created', agency_id, music_track: { music_id, agency_id, display_name, object_key, duration_seconds, is_default, created_at } }
```

Back (`music_upload_router.py:438-445` + `_serialize_track` :548-557):

```python
{ "status": "created", "agency_id": agency_id, "music_track": {
    "music_id", "agency_id", "display_name", "object_key",
    "duration_seconds", "is_default", "created_at",
}}
```

**Coincide campo por campo.** El `agency_id` se duplica
intencionadamente en el envelope y dentro de `music_track` (el front
prefería esta redundancia, ver nota #S1 del reviewer front). El test
integration `test_music_upload_happy_path_returns_201_and_persists_blob`
verifica el `set(track)` exacto (lines 87-95).

## Concurrencia: ¿feature 22 tocó algún path ajeno?

No. Feature 22 modifica solo:

- `apps/api/app_factory.py` — añade `create_music_upload_router(...)`
  include (sin tocar otros wirings).
- `modules/configuration/transport/http/music_router.py` — retira POST
  metadata-only (cambia el handler a 405), elimina deps no usadas.
- `modules/configuration/transport/http/music_upload_router.py` —
  archivo nuevo.
- `modules/configuration/transport/payloads/music.py` —
  `MusicTrackPatchPayload` reducido.
- `modules/configuration/application/use_cases/upload_music_track.py` —
  archivo nuevo.
- `shared/storage/site_layout.py` — añade
  `AGENCY_MUSIC_UPLOAD_DIRNAME` + 2 helpers + entries en `__all__`,
  sin alterar la lógica de branding existente (diff es aditivo puro).
- `tests/integration/configuration/test_music_router.py` — reescritura
  (depende de POST retirado).
- `tests/integration/configuration/test_music_upload_router.py` —
  archivo nuevo.
- `tests/unit/configuration/test_upload_music_track.py` — archivo nuevo.
- `tests/integration/configuration/_fixtures/tiny.mp3` — fixture nuevo.
- `docs/API.md`, `docs/http_surface.md`, `docs/openapi.json` —
  regeneración.

El `git status` muestra otros archivos modificados (rendering, ingestion,
social_templates, social_service, etc.) — todos son trabajo concurrente
ajeno (Codex hotfixes + hotfix de leader Claude previo). El diff de
`shared/storage/site_layout.py` se inspeccionó completo (líneas 1-198):
solo añade `AGENCY_MUSIC_UPLOAD_DIRNAME` y las 2 funciones nuevas, sin
tocar `resolve_agency_branding_*` ni `resolve_site_storage_layout`.

## Hallazgos numerados

### 1. fyi — Blob se escribe ANTES de verificar agencia (cleanup compensa)

`UploadMusicTrackUseCase.execute` ejecuta el orden:

1. `resolve_agency_music_destination` + `_write_atomic` (escribe blob)
2. `ffprobe_runner(destination)` (probe duration)
3. `RegisterMusicTrackUseCase.execute(...)` ← aquí dentro está
   `ensure_agency_exists`

Para una `agency_id` desconocida, el blob se persiste, ffprobe corre,
y el `register` levanta `ResourceNotFoundError` (subclase de
`ApplicationError`). El `except ApplicationError:` en
`upload_music_track.py:150-154` limpia el blob antes de propagar, así
que en la práctica el folder de la agencia queda vacío. El test
`test_music_upload_returns_404_for_unknown_agency` no asserta cleanup
explícito, pero el código está cubierto por el paralelo
`test_upload_cleans_blob_when_persistence_fails`.

**Recomendación**: opcionalmente mover `ensure_agency_exists` al
inicio del `UploadMusicTrackUseCase.execute` (antes del write), no
sería costoso y evita el shell-out a ffprobe + write atomic en el
caso "agency unknown". No blocker — el cleanup-on-fail lo cubre.

### 2. fyi — Doble 413 (envelope + parte interna)

El handler chequea `len(body) > max_upload_bytes` ANTES de parsear
(`music_upload_router.py:307-316`) y otra vez sobre `fields.body`
después del parse (`:364-376`). Es defensa-en-profundidad legítima
(un atacante podría inflar la parte interna manteniendo el envelope
pequeño con compresión). Documentado en el comentario inline. Sin
acción.

### 3. fyi — `agency_id` duplicado en envelope + `music_track`

El response 201 incluye `agency_id` dos veces: una en el envelope y
otra dentro de `music_track`. Es intencional para que el front pueda
consumir `music_track` aislado sin perder el contexto de agencia
(coincide con el mock del frontend). No es drift.

### 4. nit — `register_music_track` kwarg "muerto" en `create_music_router`

`music_router.py:47, 61` mantiene el kwarg `register_music_track`
para compat backward y lo descarta con `del register_music_track`.
Funciona, pero deja el contrato un poco ruidoso: cualquiera que lea
la firma sin leer el body asumirá que el handler POST lo usa. El
implementer lo justificó (decisión 9 en `impl_22_*.md`) por compat
con callers externos. Aceptable, pero podría limpiarse en una
feature posterior cuando se verifique que ningún caller externo lo
pasa.

### 5. fyi — `MusicTrackPayload` legacy sigue existiendo en payloads/music.py

`MusicTrackPayload` (líneas 8-44) ya no tiene handler que lo consuma
(el POST metadata-only se retiró). Sin embargo, sigue exportado en
`__all__` y se mantiene como referencia documental. Para mantener el
diff acotado a feature 22 está bien dejarlo; si en feature 23+
nadie lo referencia, candidato a borrado en una limpieza posterior.

### 6. fyi — `Cache-Control: private, max-age=600` en GET stream

10 minutos de cache navegador para el blob de música. Razonable
(los blobs son inmutables por `music_id`+`filename`). No es
acceptance criterion, solo lo dejo registrado.

## Recomendación de cierre

**Aprobar y cerrar feature 22 back.**

1. Mover feature 22 (back) a `done` en `feature_list.json`.
2. Anotar en `progress/current.md` que feature 22 back cierra; el
   frontend 22 (code-complete awaiting back deploy) puede pasar a
   verificación cross-repo / cierre.
3. (Opcional, no blocker para esta feature) considerar mover
   `ensure_agency_exists` al inicio del use case en una feature
   posterior (hallazgo #1).

Sin blockers ni changes-requested. El trabajo respeta layer rules
(zero `from modules.rendering` en configuration), zero
`session.commit()` en infrastructure, no añade migración, el shape
casa con el mock del frontend, y las verificaciones automatizadas
ejecutadas confirman lo que el implementer reportó.
