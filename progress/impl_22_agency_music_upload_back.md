# impl 22 — agency_music_upload (backend)

Sesión: 2026-05-14 — implementer Claude (rol delegado por leader).
Branch: trunk (sin worktree separado).

## Resumen ejecutivo

`POST /v1/admin/agencies/{id}/music` (metadata-only) está retirado a 405.
El nuevo flujo es:

- `POST /v1/admin/agencies/{id}/music/upload` (multipart, <=20MB) →
  persiste el blob bajo `workspace/generated_media/_agency_music/{safe_agency}/`,
  probea duración con `ffprobe`, registra fila en `agency_music_tracks` y
  responde 201 con el `music_track` completo.
- `GET /v1/admin/agencies/{id}/music/{music_id}/file/{filename}` →
  streamea el blob de vuelta. Scope-checked contra el JWT de la agencia.

Cero cambios de schema (la tabla ya existía desde la migración inicial).

## Shape exacto del response (importante para cross-repo)

`POST /upload` (201):

```json
{
  "status": "created",
  "agency_id": "<uuid de la agencia>",
  "music_track": {
    "music_id": "<uuid>",
    "agency_id": "<uuid de la agencia>",
    "display_name": "Sunset Drive",
    "object_key": "agencies/<safe_agency>/music/<filename>.mp3",
    "duration_seconds": 28,
    "is_default": false,
    "created_at": "2026-05-14T17:00:00+00:00"
  }
}
```

Coincide con el mock del frontend (nota #S1 del reviewer front cumplida —
`agency_id` está DENTRO de `music_track`).

`GET .../file/{filename}` (200) devuelve los bytes con
`Content-Type` derivado del suffix (`audio/mpeg`, `audio/mp4`, `audio/wav`)
y `Cache-Control: private, max-age=600`.

## Archivos modificados

### Código

- `apps/api/app_factory.py` — import + `app.include_router(create_music_upload_router(...))`.
- `modules/configuration/transport/http/music_router.py` —
  - `POST /agencies/{id}/music` ahora devuelve 405
    `METHOD_NOT_ALLOWED` con `details.use_endpoint` apuntando al nuevo
    upload. Auth sigue requerida (no leakea existencia del endpoint).
  - `PUT` ya no pasa `payload.object_key` ni `payload.duration_seconds`
    (los pasa como `None`) — el use case `reconfigure_music_track` ya
    los trata como "no tocar".
  - `register_music_track` kwarg se mantiene en la firma (compat) pero
    se descarta (`del`) porque el router ya no instancia POST directo.
- `modules/configuration/transport/payloads/music.py` —
  `MusicTrackPatchPayload` reducido a `display_name` + `is_default`.
  `extra='forbid'` ya estaba → 422 automático si llega `object_key` o
  `duration_seconds`.
- `shared/storage/site_layout.py` —
  - Constante `AGENCY_MUSIC_UPLOAD_DIRNAME = "_agency_music"`.
  - `resolve_agency_music_destination(workspace_dir, agency_id, filename)`
    → `(object_key, local_path)`. Mismo patrón que la versión branding
    para que un futuro adapter S3 enchufe sin cambios HTTP.
  - `resolve_agency_music_local_path(workspace_dir, object_key)` →
    `Path | None`, defiende contra `..`, paths con `://`, y formas
    desconocidas.

### Código nuevo

- `modules/configuration/application/use_cases/upload_music_track.py` —
  `UploadMusicTrackUseCase`. Orquesta:
  1. Write atomic (`tempfile.mkstemp` + `os.fsync` + `os.replace`) bajo
     la carpeta de la agencia. Si el proceso muere a mitad nunca queda
     un archivo parcial bajo el nombre final.
  2. `ffprobe -show_entries format=duration -of default=...` (subprocess
     directo, NO importa `modules/rendering`; resolución de binario vía
     `shutil.which`). Timeout 30s.
  3. `RegisterMusicTrackUseCase` para la fila DB.
  4. **Cleanup-on-fail**: cualquier excepción posterior al write del
     blob (ffprobe fail, duration > 600s, persistencia fail) borra el
     blob antes de propagar el error.
- `modules/configuration/transport/http/music_upload_router.py` —
  `create_music_upload_router`. Multipart parser stdlib (`email`/
  `policy`), mismo patrón que `brand_logo_router.py` para no añadir la
  dependencia `python-multipart`. Validaciones HTTP:
  - 415 si Content-Type no es multipart.
  - 413 si body > 20 MB (chequeo doble: envelope + parte interna).
  - 422 si parser falla o `display_name` está ausente / vacío / > 200 ch.
  - 400 `MUSIC_TRACK_AUDIO_INVALID` si MIME no es uno de
    `audio/mpeg`, `audio/mp4`, `audio/wav`, `audio/x-wav`, `audio/wave`.
  - 400 `MUSIC_TRACK_AUDIO_INVALID` si magic-bytes no concuerdan con el
    Content-Type declarado (ID3/MPEG frame para mp3, `ftyp` atom para
    m4a, `RIFF...WAVE` para wav).
  - Sanitiza filename: NFKD normalize → `[^A-Za-z0-9._-]+` → strip → cap
    a 96 chars → fallback `track-<sha1>` si nada usable sobrevive. El
    suffix lo deriva del Content-Type (no del filename), así un
    "audio.exe" no se guarda con `.exe` aunque pase el primer guard.

### Tests

- **Unit** (`tests/unit/configuration/test_upload_music_track.py`,
  nuevo, 5 tests):
  - happy path (write + register + duration intacta).
  - ffprobe fail → ValidationError `MUSIC_TRACK_AUDIO_INVALID` + blob
    limpiado.
  - duration > MAX (600s) → ValidationError + cleanup.
  - persistencia (RegisterMusicTrackUseCase) lanza `PipelineError` →
    blob limpiado + error propagado.
  - duration 0 → ValidationError + cleanup.

- **Integration** (`tests/integration/configuration/test_music_upload_router.py`,
  nuevo, 11 tests): happy path + MIME inválido + > 20 MB + display_name
  missing/blank + magic-byte mismatch + ffprobe failure + agency
  desconocida + auth requerida + cross-agency stream → 404 + filename
  mismatch → 404 + stream sin track → 404.

- **Integration** (`tests/integration/configuration/test_music_router.py`,
  REESCRITO porque dependía del POST metadata-only retirado, 7 tests):
  POST → 405, list seed-direct, inspect/PUT/delete round-trip (PUT
  ahora con `display_name` + `is_default` solo y verifica que
  `object_key`/`duration_seconds` permanecen intactos), PUT con
  `object_key` → 422, PUT con `duration_seconds` → 422, cross-agency
  inspect → 404. (Helper local `_seed_music_track` siembra via UoW.)

- **Fixture** `tests/integration/configuration/_fixtures/tiny.mp3` —
  MP3 silencioso de 1 segundo (~4.4 KiB) generado con
  `ffmpeg -f lavfi anullsrc -t 1 -c:a libmp3lame -b:a 32k`. Lo bastante
  pequeño para git, lo bastante real para que `ffprobe` extraiga
  duración.

### Docs

- `docs/API.md` — sección Música reescrita: upload + stream + reconfigure
  + endpoints retirados, todos los códigos de error nuevos.
- `docs/http_surface.md` — regenerado vía
  `scripts/generate_http_surface.py --write`. Aparecen `POST .../music/upload`
  y `GET .../music/{music_id}/file/{filename}` (handlers en el módulo
  nuevo `music_upload_router`).
- `docs/openapi.json` — regenerado por el mismo script.

## Decisiones tomadas

1. **`duration_seconds` no editable post-upload**. El plan lo proponía
   como decisión y lo confirmo: `ffprobe` es la única fuente de verdad,
   permitir override desconectaría la duración de la realidad del blob
   en disco. Cliente que quiera "cambiar duración" → re-upload.
2. **`object_key` no editable post-upload** (mismo razonamiento — apunta
   al blob persistido, cambiarlo a mano huerfanaría archivos). El
   `PatchPayload` con `extra='forbid'` lo bloquea como 422 gratis,
   pero hay tests integrationales explícitos para que el contrato
   quede documentado.
3. **`register_music_track` use case se mantiene intacto**. El upload lo
   reusa (no duplica INSERT). Si en el futuro vuelve un endpoint de
   "registrar con object_key externo" (p. ej. importación batch) la
   capa de application sigue lista.
4. **Magic-bytes check antes de ffprobe**. Sería redundante dejar que
   ffprobe rechazara basura genérica, pero el primer guard ahorra el
   subprocess + write atomic para los casos triviales (cliente buggy
   subiendo `application/octet-stream` mal declarado, etc.). El detalle
   incluye `magic_prefix` en el `details` para ayudar al debugging.
5. **MIME tolerancia**. Acepto `audio/x-wav` y `audio/wave` además del
   canónico `audio/wav` — Safari y algunos navegadores envían los dos
   sinónimos. El frontend feature 22 normaliza a `audio/wav`, pero el
   back los acepta los tres.
6. **`audio/mp4` también aceptado** porque la `.m4a` mainstream lo
   declara con ese MIME (no `audio/aac`). El magic-byte check exige
   `ftyp` atom en offset 4 — bloquea video/mp4 puro porque no comparte
   el codec descriptor a esa altura.
7. **Filename sanitization defensiva**. NFKD + regex deja un stem
   ASCII; los `.` internos se reemplazan por `-` para no confundir el
   suffix derivado del Content-Type. El cap a 96 caracteres no es
   arbitrario: ext4 acepta 255 bytes, pero algunos FS legacy se
   atascan más allá de 100.
8. **Cleanup-on-fail explícito en el use case**. El test unitario
   inyecta un `RegisterMusicTrackUseCase` que lanza `PipelineError`
   tras el write y verifica que el directorio de la agencia queda
   vacío. Sin este branch un fallo de DB dejaría blobs huérfanos.
9. **`del register_music_track`** en `create_music_router` —
   conservamos el kwarg en la firma (compat) pero descartamos el valor
   porque ya no se usa dentro del router. Evita un warning de
   variable-no-usada sin romper a nadie.

## Comandos de verificación ejecutados

```bash
cd /opt/projects/4Reels-Backend
bash ./init.sh                                  # entorno verde
.venv/bin/python -m pytest tests/integration/configuration/test_music_router.py \
  tests/integration/configuration/test_music_upload_router.py \
  tests/unit/configuration/test_upload_music_track.py -q   # 23 passed
.venv/bin/python -m pytest -q                   # 731 passed, 3 baseline failed
.venv/bin/python -m apps.api --check            # exit 0
.venv/bin/python -m apps.worker --check         # exit 0
.venv/bin/python scripts/generate_http_surface.py --write  # docs regen
```

Resultados:

- pytest baseline: 712 passed → ahora 731 passed (19 nuevos), mismos 3
  fallos pre-existentes (`test_http_surface_contract` +
  2 `test_http_transport`); no aumenta el conteo de rojo.
- `apps.api --check`: `RUNTIME READY: Yes`.
- `apps.worker --check`: `Worker --check OK`.
- `docs/openapi.json`: 3 matches para `music/upload`/`music/{music_id}/file`
  (POST + GET stream entries).

## Manual quick check (sugerido al reviewer)

```bash
# Levantar la API en :8001 (configuración local existente)
# Subir el fixture:
curl -F file=@tests/integration/configuration/_fixtures/tiny.mp3 \
     -F 'display_name=Local Test' \
     -F is_default=false \
     -H 'Authorization: Bearer <admin-token>' \
     http://127.0.0.1:8001/v1/admin/agencies/<agency-id>/music/upload
# Descargar:
curl -OJ \
     -H 'Authorization: Bearer <admin-token>' \
     http://127.0.0.1:8001/v1/admin/agencies/<agency-id>/music/<music-id>/file/<filename>.mp3
```

## Pendiente (no scope feature 22)

- Feature 23 (`wire_render_to_agency_music_tracks`) sigue dependiendo
  de este cierre: cuando se enchufe, `resolve_background_audio_paths`
  pasará a leer `agency_music_tracks` en lugar de escanear
  `assets/music/`. El explore previo
  (`progress/explore_23_render_to_agency_music_tracks.md`) ya identificó
  los 3 call sites a actualizar.
- Cierre cross-repo del frontend 22 (espera deploy del back).

## NO marca `done`

`feature_list.json` sigue mostrando feature 22 back en `in_progress`.
El reviewer es quien marca `done` tras revisar este informe.
