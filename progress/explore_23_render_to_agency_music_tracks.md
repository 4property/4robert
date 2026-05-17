# Explore — Feature 23: `wire_render_to_agency_music_tracks`

> Read-only investigation. NO implementation, NO migrations, NO state mutations.
> El implementer va a usar este documento como referencia primaria; cualquier
> bloque marcado ⚠️ requiere revalidación tras el cierre de feature 21.

## 1. Estado del repo al iniciar

- **Timestamp**: 2026-05-14T14:50:38+01:00
- **HEAD**: `1749e02 x` (autor `robert-server`, 2026-05-13). Trabajos posteriores
  están como tracked-modified o untracked, sin commitear.
- **`git status` resumen**: ~40 archivos modificados y 19 untracked (60 entradas
  totales). Convive feature 21 (`per_reel_description_override_endpoint`,
  paralela), hotfixes de Codex en `rendering/infrastructure/preparation.py` y
  `ffmpeg/filters.py` + `layout/panels.py`, y una migración `20260514_0003`
  todavía sin aplicar.
- **Última migración en disco**: `alembic/versions/20260514_0003_reels_descriptions_override.py`
  (revision `20260514_0003`, down `20260514_0002`). Feature 21 la introduce y
  sigue sin aplicarse — nuestra migración de feature 23 vendrá DESPUÉS, con
  rev_id `20260514_0004` (o el siguiente disponible cuando se implemente).

### Tabla zonas calientes vs frías

| Path | Caliente / Frío | En `git status`? | Acción para feature 23 |
|------|------------------|------------------|------------------------|
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | CALIENTE (feature 21) | M | Revalidar post-21; no detallar threading aquí |
| `modules/reels/application/use_cases/_ingest_property_assets.py` | CALIENTE | M | Revalidar post-21 |
| `modules/reels/application/use_cases/_ingest_property_planning.py` | CALIENTE | M | Revalidar post-21 |
| `modules/reels/application/use_cases/regenerate_reel.py` | CALIENTE (cercana) | (no aparece) | Releer al cierre de 21 |
| `modules/reels/application/content_generator.py` | CALIENTE | M | Revalidar post-21 |
| `modules/reels/domain/reel_state.py`, `types.py` | CALIENTE | M | Revalidar post-21 |
| `modules/reels/transport/http/admin_reels_router.py` | CALIENTE | M | Revalidar post-21 |
| `modules/reels/infrastructure/reel_state_repository.py` | CALIENTE | M | Revalidar post-21 |
| `modules/rendering/infrastructure/preparation.py` | CALIENTE (hotfix Codex) | M | Revalidar al commitear Codex |
| `modules/rendering/infrastructure/ffmpeg/filters.py` | CALIENTE (hotfix) | (Codex sin commitear; aparece M) | Revalidar |
| `modules/rendering/infrastructure/layout/panels.py` | CALIENTE (hotfix) | (idem) | Revalidar |
| `shared/db/orm.py` | CALIENTE (feature 21 añade `reels.descriptions_override`) | M | Revalidar post-21 |
| `alembic/versions/20260514_0003_*` | CALIENTE (rev_ids volátiles) | ?? (untracked) | Decidir `down_revision` al final |
| `modules/rendering/infrastructure/runtime/assets.py` | FRÍO | (no en `git status`) | Profundizar |
| `modules/rendering/infrastructure/runtime/branding.py` | FRÍO | (no en `git status`) | Profundizar |
| `modules/rendering/infrastructure/runtime/slides.py`, `__init__.py` | FRÍO | (no en `git status`) | Profundizar |
| `modules/rendering/infrastructure/manifest.py` | FRÍO | (no en `git status`) | Profundizar |
| `modules/configuration/infrastructure/music_track_repository.py` | FRÍO | (no en `git status`) | Profundizar |
| `modules/configuration/application/use_cases/list_music_tracks.py` | FRÍO | (no en `git status`) | Profundizar |
| `modules/configuration/application/use_cases/inspect_music_track.py` | FRÍO | (no en `git status`) | Profundizar |
| `modules/configuration/domain/agency_settings.py` | FRÍO (pero modificado por feature 20) | M | Diff revisado abajo |
| `assets/music/` | FRÍO | sin tracking de binarios | Profundizar |
| `modules/configuration/transport/http/brand_logo_router.py` | FRÍO | (no en `git status`) | Profundizar (analogía multipart) |
| `apps/api/app_factory.py` | LECTURA SOLO | M | Solo entender registro de routers |
| `shared/storage/site_layout.py` | FRÍO | (no en `git status`) | Profundizar (analogía branding) |
| `tests/integration/rendering/` y `tests/unit/rendering/` | FRÍO en general | algunos M | Detallar tests nuevos abajo |

**Conclusión**: este explore profundiza únicamente en zonas frías. Las zonas
calientes se dejan para revalidación post-merge de feature 21 (y, dependiente
de timing, post-commit de los hotfixes Codex en `preparation.py` /
`filters.py` / `layout/panels.py`).

---

## 2. Comportamiento actual del audio en el render

### 2.1 Definición y firma actual

`resolve_background_audio_paths` está en
`modules/rendering/infrastructure/runtime/assets.py:101-138` (archivo frío,
verificado fuera de `git status`):

```python
def resolve_background_audio_paths(
    workspace_dir: Path,
    settings: PropertyReelTemplate,
    *,
    shuffle_candidates: bool,
) -> tuple[Path, ...]:
    configured_audio_path = (
        workspace_dir / settings.assets_dirname / settings.background_audio_filename
    )
    audio_directory = configured_audio_path.parent
    ...
    candidates = [
        candidate
        for candidate in sorted(audio_directory.iterdir())
        if candidate.is_file()
        and candidate.suffix.lower() in SUPPORTED_BACKGROUND_AUDIO_EXTENSIONS
    ]
    ...
    if shuffle_candidates and len(candidates) > 1:
        ...
    return tuple(candidates)
```

- Construye la ruta a `workspace/<assets_dirname>/<background_audio_filename>`,
  toma su `parent` y lista los archivos cuya extensión esté en
  `SUPPORTED_BACKGROUND_AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg"}`
  (`assets.py:42-44`).
- `settings.assets_dirname` por defecto `"assets"`
  (`settings/reels.py:8`, expuesto en `PropertyReelTemplate.assets_dirname`
  en `modules/rendering/infrastructure/models.py:50`).
- `settings.background_audio_filename` por defecto `"music/ncs-music.mp3"`
  (`settings/reels.py:12` + `models.py:53`).
- Devuelve tupla; `shuffle_candidates=True` usa `random.SystemRandom`.

### 2.2 Call-graph (6 sitios confirmados via `grep -rn "resolve_background_audio_paths"`)

| # | File:line | Caller context | Hot/Cold |
|---|-----------|---------------|----------|
| 1 | `modules/rendering/infrastructure/preparation.py:37` | import | ⚠️ caliente (hotfix Codex) |
| 2 | `modules/rendering/infrastructure/preparation.py:186` | invocación dentro de `prepare_reel_render_assets`, `shuffle_candidates=True` — produce las candidates que terminan en `PreparedReelAssets.background_audio_path` (primera) y `.background_audio_candidates` (tupla completa) | ⚠️ caliente |
| 3 | `modules/rendering/infrastructure/runtime/__init__.py:8` | re-export | frío |
| 4 | `modules/rendering/infrastructure/runtime/__init__.py:41` | `__all__` | frío |
| 5 | `modules/rendering/infrastructure/manifest.py:36` | import | frío |
| 6 | `modules/rendering/infrastructure/manifest.py:180` | en `build_reel_manifest`: solo si `prepared_assets` es `None` o sin candidates, fallback con `shuffle_candidates=False` | frío |
| 7 | `modules/rendering/infrastructure/runtime/assets.py:101` | definición | frío |
| 8 | `modules/rendering/infrastructure/runtime/assets.py:285` | `__all__` | frío |
| 9 | `apps/api/readiness.py:200` (vía wrapper `_resolve_background_audio_paths`, def en `readiness.py:408-416`) | smoke-test del readiness: comprueba que el workspace tiene al menos un track. Construye `PropertyReelTemplate()` (defaults) y llama con `shuffle_candidates=False` | frío |
| 10 | `tests/unit/apps_api/test_readiness.py:37` | mocked en tests | frío |

### 2.3 Consumo de las candidates en `mux_audio_candidates`

En `modules/rendering/infrastructure/ffmpeg/render_reel.py:341-395`
(`mux_audio_candidates`) — archivo no modificado actualmente:

- Recibe `prepared_assets: PreparedReelAssets`.
- `audio_candidates = prepared_assets.background_audio_candidates if prepared_assets.background_audio_candidates else (prepared_assets.background_audio_path,)` (líneas 352-356).
- Itera con `enumerate(..., start=1)` y por cada candidate construye el ffmpeg
  command con `build_audio_mux_command(..., background_audio_path=...)` (línea 364).
- Si el ffmpeg falla, logea `"Background audio mux failed for property %s (%s) with %s. Trying the next track."` y borra el output (línea 393). Si era el último, hace `raise`.
- Cuando triunfa, escribe el path final en `prepared_assets.background_audio_path` y break (línea 380).

Disparador: `render_property_reel` (`render_reel.py:200-208`) llama
`mux_audio_candidates` tras `render_silent_reel`.

### 2.4 Decisión de `shuffle_candidates`

Solo dos call sites pasan el flag:

- `preparation.py:186` → `shuffle_candidates=True` (el render real).
- `manifest.py:180` → `shuffle_candidates=False` (preview/dry-run del manifiesto).
- `readiness.py:412-415` → `shuffle_candidates=False` (smoke).

Conclusión: `shuffle_candidates=True` solo se decide en el path real
(`preparation.py:186`, **⚠️ caliente**).

### 2.5 Modelo `PreparedReelAssets`

`modules/rendering/infrastructure/models.py:93-106` (frío):

```python
@dataclass(slots=True)
class PreparedReelAssets:
    working_dir: Path
    slides: tuple[PreparedReelSlide, ...]
    cover_background_path: Path
    cover_logo_path: Path | None
    agent_image_path: Path
    ber_icon_path: Path | None
    background_audio_path: Path
    background_audio_candidates: tuple[Path, ...] = field(default_factory=tuple)
    reserve_agency_logo_space: bool = False
    ...
```

`background_audio_path` es el track elegido (siempre 1 Path). `_candidates`
es la pool a probar por `mux_audio_candidates` si la primera falla en ffmpeg.

---

## 3. Patrón de storage existente (analogía branding)

### 3.1 `shared/storage/site_layout.resolve_agency_branding_destination`

`shared/storage/site_layout.py:31-58` (frío):

```python
def resolve_agency_branding_destination(
    *,
    workspace_dir: Path,
    agency_id: str,
    filename: str,
) -> tuple[str, Path]:
    safe_agency = safe_site_dirname(agency_id)
    branding_dir = (
        workspace_dir
        / GENERATED_MEDIA_ROOT_DIRNAME      # "generated_media"
        / AGENCY_BRANDING_UPLOAD_DIRNAME    # "_agency_branding"
        / safe_agency
    )
    branding_dir.mkdir(parents=True, exist_ok=True)
    local_path = branding_dir / filename
    object_key = f"agencies/{safe_agency}/{filename}"
    return object_key, local_path
```

- **Firma**: keyword-only, devuelve `(object_key: str, local_path: Path)`.
- **Filesystem layout**: `workspace_dir/generated_media/_agency_branding/{safe_agency}/<filename>`.
  `safe_site_dirname` sanea: `_INVALID_SITE_DIR_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")` colapsa cualquier
  carácter inválido a `_` y luego strip `._-` (`site_layout.py:16,25-28`).
- **`object_key` shape**: `"agencies/<safe_agency>/<filename>"`. Diseñado para
  futuro backend S3 (`s3://...`) sin tocar callers.
- **Helper compañero** `resolve_agency_branding_local_path` (`site_layout.py:61-90`):
  toma un `object_key` y devuelve el `Path` local **solo si el archivo existe**;
  rechaza esquemas `://`, paths con `..` y prefijos distintos a `agencies/`.

### 3.2 `brand_logo_router.py` (frío) — patrón multipart con stdlib

Resumen de `modules/configuration/transport/http/brand_logo_router.py`:

- Endpoint `POST /v1/admin/agencies/{agency_id}/brand/logo` con multipart sin
  `python-multipart`. Parsea con `email.parser.BytesParser` + `email.policy.default`
  (`brand_logo_router.py:41-43,116-119`).
- Extrae boundary con regex `_MULTIPART_BOUNDARY_RE` (líneas 77, 91-95).
- Función `_extract_file_field(body, content_type_header)` (lines 98-142):
  envuelve el cuerpo con un header sintético `Content-Type: multipart/form-data; boundary=...`,
  itera `message.iter_parts()` y devuelve el primer part con `name=file`.
- Constantes inline (no hay convención previa de admin-upload):
  `BRAND_LOGO_MAX_UPLOAD_BYTES = 5 * 1024 * 1024`,
  `_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}`,
  `_SUFFIX_BY_CONTENT_TYPE = {"image/jpeg": ".jpg", "image/png": ".png"}`.
- Validaciones encadenadas: 415 si content-type wrong, 413 si body > max,
  422 si extension wrong, 422 si extension/content-type mismatch, 422 si empty.
- Filename del blob: `f"logo-{digest12}{suffix}"` con `digest = hashlib.sha1(field.body).hexdigest()[:12]`
  (líneas 310-312). El digest evita colisiones y hace el upload idempotente.
- Persistencia: `destination.write_bytes(field.body)` (línea 319). Sin
  `session.commit()` en el router; la fila se inserta más tarde via el
  PUT `/brand` que aplica el `logo_object_key`.
- Response JSON: `{"object_key": <key>, "url": <admin streaming url>}`
  (líneas 337-343).
- Hay un `GET /agencies/{agency_id}/brand/logo/file/{filename}` espejo que
  stream-ea el archivo (líneas 345-406), usando `resolve_agency_branding_local_path`
  para resolver el path.

### 3.3 `runtime/branding.py` (frío) — consumidor del cache helper

`modules/rendering/infrastructure/runtime/branding.py:45-117`:

- `prepare_cover_logo_image` prefiere `property_data.agency_logo_local_path`
  (inyectado por `ingest_property_into_reel.py` via `_resolve_agency_logo_local_path`,
  pero esto cae en zona caliente).
- Si no, recurre a `resolve_cached_branding_destination` (en `assets.py:206-220`)
  para decidir dónde cachear el logo descargado:
  `workspace_dir/"generated_media"/safe_site_dirname(site_id)/"_branding"/f"{slug}-{label}-{hash12}{suffix}"`.

Importante para feature 23: este helper es **per-site**, no per-agency. Es
el caché de descarga de URLs webhook. Para music NO sirve — necesitamos el
helper análogo per-agency tipo `resolve_agency_branding_destination`.

---

## 4. Diseño propuesto para feature 23 (sin código real)

### 4.1 Nuevo helper en `shared/storage/site_layout.py`

```text
resolve_agency_music_destination(
    *, workspace_dir: Path, agency_id: str, filename: str
) -> tuple[str, Path]
```

**Decisiones**:

- **Mismo backend-agnostic contract** que `resolve_agency_branding_destination`:
  devuelve `(object_key, local_path)`; el S3-future-proofing está heredado.
- **Sanitización**: `safe_site_dirname(agency_id)` (reusar el existente —
  ya colapsa `[^A-Za-z0-9._-]+` a `_` y strip de `._-`). `filename` debe
  pasarse YA sanitizado por el caller (el patrón brand_logo_router usa
  `hashlib.sha1(blob).hexdigest()[:12]` + suffix conocido); para feature 23
  proponer convención `f"<sha1_12>-<safe_basename>.mp3"` o similar — ver
  decisión #3 abajo.
- **Layout propuesto**: `workspace_dir / GENERATED_MEDIA_ROOT_DIRNAME / "_agency_music" / safe_agency / filename`.
  Razón: simetría exacta con branding (`_agency_branding/...`). Nueva constante
  `AGENCY_MUSIC_UPLOAD_DIRNAME = "_agency_music"`. **Alternativa rechazada**:
  bajo `property_media/` — los blobs no son per-site, son per-agency, y
  `property_media/` ya está reservado para imágenes filtradas (ver
  `settings/images.py:8-9`).
- **`object_key` shape**: `"agencies/{safe_agency}/music/{filename}"` —
  prefijo `agencies/.../music/` distinto del `agencies/.../<filename>`
  que usa el logo. Razón: que `resolve_agency_branding_local_path` no
  matchee accidentalmente los `object_key`s de música.
- **Helper compañero** `resolve_agency_music_local_path(workspace_dir, object_key) -> Path | None`:
  copia exacta del patrón branding (rechazo de `://`, `..`, esquema validado).
  Necesario para el render: dada una fila `agency_music_tracks` con su
  `object_key`, traducir a `Path` antes de pasarlo a ffmpeg.

**Nota a feature 22**: si feature 22 se merge primero (que es lo natural,
porque feature 22 ES el upload), el helper ya existe y feature 23 solo lo
consume. Ver Riesgos §5.

### 4.2 Refactor de `resolve_background_audio_paths`

**Propuesta de nueva firma**:

```text
resolve_background_audio_paths(
    workspace_dir: Path,
    settings: PropertyReelTemplate,
    *,
    music_tracks: tuple[Path, ...] | None = None,
    shuffle_candidates: bool,
) -> tuple[Path, ...]
```

Si `music_tracks` viene poblado (camino normal post-23), la función ignora
el escaneo de `assets/music/` y solo ordena/shuffle-a la tupla recibida.
Si viene `None` o vacío, mantiene el comportamiento legacy (escanea
`workspace/assets/music/`) — esto sirve como fallback de emergencia
para readiness y para modo dev sin BBDD (acceptance criteria de la
feature 23: "El directorio assets/music/ queda como fallback de emergencia
solo si la migración no ha corrido").

**Call sites a actualizar** (lockstep, 6 reales + 1 re-export + 1 `__all__`):

| File:line | Caller | Cómo se actualiza | Hot? |
|-----------|--------|-------------------|------|
| `preparation.py:186` | `prepare_reel_render_assets` | Recibe `music_tracks` por nuevo argumento desde `frame_composition.DefaultMediaRenderer` (que las cargó del UoW antes del render). ⚠️ Threading concreto se deja como TODO hasta cierre de feature 21. | ⚠️ caliente |
| `manifest.py:180` | `build_reel_manifest` | Idem (también necesita las tracks; en preview mode acepta `None` y cae al fallback). | frío |
| `readiness.py:412-416` | smoke | Llama con `music_tracks=None` explícito — escanea fs igual que hoy. Sin DB en readiness. | frío |
| `runtime/__init__.py:8, 41` | re-export | sin cambio funcional | frío |
| `runtime/assets.py:101, 285` | def + `__all__` | la propia función + `__all__` | frío |
| `tests/unit/apps_api/test_readiness.py:37` | mocking | Solo update si el monkeypatch cambia la signatura. | frío |

**Helper auxiliar nuevo en `runtime/assets.py`**:

```text
resolve_agency_music_local_paths(
    *, workspace_dir: Path, music_tracks: Iterable[MusicTrack]
) -> tuple[Path, ...]
```

- Itera `MusicTrack.object_key` (`modules/configuration/domain/agency_settings.py:87-94`,
  `MusicTrack(music_id, agency_id, display_name, object_key, duration_seconds, is_default, created_at)`).
- Para cada `object_key`, llama `resolve_agency_music_local_path` (helper §4.1).
- Si falta un blob: `raise ResourceNotFoundError(code="MUSIC_BLOB_MISSING", ...)`.
- Devuelve tupla de `Path`s para alimentar `resolve_background_audio_paths`.

**Acceptance criterion alineado** (de feature 23): "Tests unit del helper
resolve_agency_music_local_paths: blob ausente → ResourceNotFoundError con
código exacto."

### 4.3 Carga de la pool por agencia

Repositorio existente: `MusicTracksRepository`
(`modules/configuration/infrastructure/music_track_repository.py:10`, frío).
Método relevante: `list_for_agency(self, agency_id: str) -> tuple[MusicTrack, ...]`
(líneas 11-31), `ORDER BY display_name ASC`. **No** filtra por `is_default`.

**Lógica de carga propuesta** (use case wrapper, frío hasta que se decida
dónde plugar):

1. `all_tracks = uow.configuration.music.list_for_agency(agency_id)`.
2. `default_tracks = tuple(t for t in all_tracks if t.is_default)`.
3. Si `default_tracks`: usar esa lista.
4. Else, fallback a `all_tracks` (regla "fallback_to_full_library=true"
   hardcoded; feature 24 lo hace configurable).
5. Si vacío → `raise PropertyReelError(code="MUSIC_NO_TRACKS", ...)`.

**Where to plug**: aquí entramos en zona caliente. Los call sites candidatos
son:

- `modules/reels/application/use_cases/ingest_property_into_reel.py` ⚠️
- `modules/reels/application/use_cases/regenerate_reel.py` ⚠️
- `modules/rendering/application/frame_composition.py` (DefaultMediaRenderer)
- `modules/rendering/application/scripted_video/render_service.py` (al
  aceptar `music_tracks` por el camino largo según scope explícito de
  feature 23).

**TODO al implementer**: confirmar el punto de inyección **tras cierre de
feature 21**. La elección entre "use case de reels" vs "DefaultMediaRenderer"
depende del shape final del `PropertyContext`/`PreparedMediaAssets` post-21.
Hipótesis razonable: el use case de reels carga las tracks y las pasa por
`PropertyContext` (junto al `agency_logo_local_path`), y `DefaultMediaRenderer`
las propaga a `prepare_reel_render_assets` y `build_reel_manifest`.

### 4.4 Migración Alembic seed

**Inventario actual de `assets/music/`** (`ls /opt/projects/4Reels-Backend/assets/music/`):

| Archivo | Bytes | NCS? |
|---------|------:|------|
| `N3b, Extra Terra - Silence [NCS Release].mp3` | 8,268,333 | Sí |
| `ncs-music.mp3` | 5,975,492 | (genérico, es el `background_audio_filename` default — duplicado de uno de los 4? confirmar con el implementer) |
| `New Light.wav` | 43,619,066 | No |
| `sumu - apart [NCS Release].mp3` | 5,689,468 | Sí |
| `Sunny Lukas, Zushi & Vanko - Underrated (Feat. Sunny Lukas) [NCS Release].mp3` | 8,872,145 | Sí |

**Nota**: el directorio tiene **5** archivos, no los 4 que asume la task.
Hay un `New Light.wav` (43 MB) y un `ncs-music.mp3` (5.9 MB) además de los
3 tracks NCS con nombre largo. Hay que decidir qué 4 entran al seed:

- Opción A: los **3** NCS con nombre largo + `ncs-music.mp3` (= 4 archivos NCS).
- Opción B: los 3 NCS + `New Light.wav` (= 4 archivos).
- Opción C: los 5 archivos (incoherente con la spec "4 .mp3 NCS").

**Recomendación**: opción A — la spec dice "4 .mp3 NCS hardcoded" y
`background_audio_filename` apunta a `music/ncs-music.mp3` por defecto, así
que `ncs-music.mp3` SÍ está en uso. Ver decisión #1.

**Display-name mapping propuesto** (transformación: strip `[NCS Release]`,
strip extensión, reordenar `"Artista - Título"` → `"Título (Artista)"`):

| Archivo | display_name propuesto |
|---------|------------------------|
| `N3b, Extra Terra - Silence [NCS Release].mp3` | `Silence (N3b, Extra Terra)` |
| `sumu - apart [NCS Release].mp3` | `Apart (sumu)` |
| `Sunny Lukas, Zushi & Vanko - Underrated (Feat. Sunny Lukas) [NCS Release].mp3` | `Underrated (Sunny Lukas, Zushi & Vanko)` |
| `ncs-music.mp3` | `NCS Default` (o `Default Backing Track`) |

**Esquema upgrade**:

1. `bind = op.get_bind()`.
2. Listar agencias: `SELECT id FROM agencies`.
3. Para cada `agency_id`:
   a. `SELECT COUNT(*) FROM agency_music_tracks WHERE agency_id = :agency_id`.
      Si > 0 → skip (idempotente).
   b. Para cada uno de los 4 archivos seed:
      - `object_key, local_path = resolve_agency_music_destination(
        workspace_dir=<workspace>, agency_id=agency_id,
        filename=f"_seed_ncs_{slugified_basename}.mp3")`
      - **Marker en filename**: `_seed_ncs_` prefix para que el downgrade
        sepa qué borrar sin confundirse con uploads del usuario.
      - `shutil.copy(<repo>/assets/music/<orig>, local_path)`.
      - `duration_seconds`: ffprobe sobre el archivo origen
        (la migración es lenta pero solo se corre una vez).
      - `INSERT INTO agency_music_tracks (id, agency_id, display_name,
        object_key, duration_seconds, is_default, created_at) VALUES (...)`
        con `is_default=TRUE` y `id=uuid4()`.

**Esquema downgrade**:

- `DELETE FROM agency_music_tracks WHERE object_key LIKE 'agencies/%/music/_seed_ncs_%'`.
- Borrar los blobs físicos `workspace/generated_media/_agency_music/*/_seed_ncs_*.mp3`
  con un `glob` + `unlink(missing_ok=True)`.

**Idempotencia y safety**:

- Skip por agencia si ya tiene tracks (acceptance criterion explícito).
- El marker `_seed_ncs_` permite distinguir blobs creados por la migración
  vs uploads (feature 22), incluso si el usuario hace upload tras correr el
  seed.

**`down_revision`**: `TBD — depende del rev_id final tras cierre de feature 21
(actualmente alembic head es 20260514_0002, pero feature 21 introduce
20260514_0003 sin aplicar; nuestra migración sería 20260514_0004 o el
siguiente disponible). Decidir al final de la implementación.`

**Trigger al crear agencia nueva**: `RegisterAgencyUseCase`
(`modules/tenancy/application/use_cases/register_agency.py:30-73`,
frío). La inserción ocurre en línea 48-54 (`uow.tenancy.agencies.create(...)`)
y luego `uow.tenancy.agencies.get_by_id(agency_id)`. Después de eso, antes
del `return agency`, conviene disparar la lógica de seed (reutilizando una
función compartida entre la migración y este use case — por ejemplo
`seed_agency_default_music_tracks(uow, agency_id, workspace_dir)`).
**Atención**: este use case no recibe `workspace_dir` actualmente; habrá
que inyectarlo por constructor/parámetro. Es zona "fría" pero del bounded
context tenancy, no del rendering. Ver decisión #5.

### 4.5 Riesgos del seed binario en migración

Copiar 4 .mp3 (~5-9 MB cada uno = ~28 MB por agencia) en una migración
data es **feo pero no inviable**:

- Pro: simple, idempotente, atomic dentro de la migración.
- Contra: lento si hay muchas agencias, ffprobe en migración requiere
  ffmpeg en el entorno donde se corre el alembic.

**Alternativa propuesta**: la migración solo registra **filas** apuntando
a `object_key`s con un prefijo bootstrap `"bootstrap/ncs/<filename>"`,
y un script separado (`scripts/bootstrap_music_seed.py`) copia los
blobs por fuera de la migración. Razón: separa schema-data de blob-storage,
y permite re-correr el bootstrap si el workspace cambia (S3, otro disco,
restore desde backup) sin tocar la BBDD.

**Recomendación**: Opción A (migración data completa con copia + ffprobe)
para esta feature, porque:

- El seed es one-shot (migración solo aplica si la agencia no tiene tracks).
- El número de agencias es bajo en producción.
- Mantiene la atomicidad con la creación de filas.

Pero **decisión final del leader** (ver decisión #4).

### 4.6 Tests

**Integration nuevos** (en `tests/integration/rendering/` y
`tests/integration/configuration/`):

1. `tests/integration/rendering/test_render_uses_agency_music_pool.py`
   (nuevo):
   - Setup: agencia con 1 default track, render reel → verificar que el
     filter graph de `mux_audio_candidates` referencia un Path bajo
     `resolve_agency_music_destination(agency_id, ...)` (no `assets/music/`).
   - Setup: agencia con 4 default tracks → shuffle entre las 4 (con
     `random.SystemRandom` patched o aceptando cualquier orden).
   - Setup: agencia con 0 default + 2 library tracks → usa esas 2.
   - Setup: agencia con 0 tracks (ni default ni library) → render falla
     con `code="MUSIC_NO_TRACKS"`; el reel job marca `publish_status="failed"`
     o equivalente (depende de feature 21 cuando cierre).
   - Cross-agency: agencia A no puede usar tracks de B (validar que el use
     case filtra por `agency_id`).

2. `tests/integration/configuration/test_register_agency_seeds_music.py`
   (nuevo): crear una agencia → verificar que aparecen 4 tracks `is_default=TRUE`
   bajo su `agency_id`.

3. `tests/integration/alembic/test_seed_existing_agencies_ncs_music.py`
   (nuevo, si existe la convención `tests/integration/alembic/`; si no,
   colocar en `tests/integration/configuration/`):
   - Pre-condición: agencia preexistente sin tracks.
   - `alembic upgrade head` → 4 filas, 4 blobs.
   - `alembic downgrade -1` → 0 filas, 0 blobs con prefijo `_seed_ncs_`,
     uploads del usuario intactos.

**Unit nuevos** (en `tests/unit/rendering/`):

4. `tests/unit/rendering/test_resolve_agency_music_local_paths.py` (nuevo):
   - Happy path: lista de `MusicTrack` con object_keys válidos → tupla de
     Paths existentes.
   - Blob ausente → `ResourceNotFoundError` con `code="MUSIC_BLOB_MISSING"`.
   - Object_key con esquema `://` → rechazado (consistencia con
     `resolve_agency_branding_local_path`).

5. `tests/unit/configuration/test_resolve_agency_music_destination.py`
   (nuevo, en `tests/unit/configuration/` o `tests/unit/shared/` según
   convención):
   - Sanitización de `agency_id` con caracteres inválidos.
   - `object_key` shape correcto.
   - `local_path` bajo `workspace_dir/generated_media/_agency_music/`.

**Tests existentes a modificar**:

6. `tests/unit/apps_api/test_readiness.py` (frío): si la nueva firma
   de `resolve_background_audio_paths` añade el kwarg `music_tracks=None`
   con default, el monkeypatch existente sigue válido. Si forzamos kwarg
   sin default, hay que adaptarlo.

7. `tests/integration/rendering/test_side_banner_render.py` (frío): este
   test parchea las primitivas con `_patch_primitives` (líneas 38ss),
   así que probablemente no necesita ajustes si `music_tracks` se inyecta
   por el `PropertyContext` y no rompe la firma del patch.

8. `tests/test_reel_render_command.py` línea 27 (`background_audio_path=Path("music.mp3")`)
   — fixture, no toca la pool real. No cambia.

**Tests existentes a revalidar**:

- Cualquier test bajo `tests/integration/reels/` que dispare un render
  E2E va a romper si la BBDD del test no tiene música seedeada. Habrá
  que añadir fixture `agency_with_default_music_tracks` reutilizable.

---

## 5. Riesgos y dependencias

### 5.1 Feature 21 paralela (CRÍTICO)

El threading del nuevo `music_tracks` debe revalidarse cuando feature 21
cierre. Releer **obligatoriamente** antes de implementar:

- `modules/reels/application/use_cases/ingest_property_into_reel.py` ⚠️
- `modules/reels/application/use_cases/_ingest_property_assets.py` ⚠️
- `modules/reels/application/use_cases/_ingest_property_planning.py` ⚠️
- `modules/reels/application/use_cases/regenerate_reel.py` (precaución, cerca)
- `modules/reels/application/content_generator.py` ⚠️
- `modules/reels/domain/reel_state.py`, `types.py` ⚠️
- `modules/reels/transport/http/admin_reels_router.py` ⚠️
- `modules/reels/infrastructure/reel_state_repository.py` ⚠️
- `shared/db/orm.py` ⚠️ (nueva columna `reels.descriptions_override`)
- `alembic/versions/20260514_0003_reels_descriptions_override.py` ⚠️

### 5.2 Dependencia con feature 22 (back)

Feature 22 introduce el upload multipart de pistas y `resolve_agency_music_destination`
(según su scope explícito en `feature_list.json`). El orden natural es:

1. Feature 22 introduce el helper en `shared/storage/site_layout.py`.
2. Feature 23 lo consume + reorienta el render.

Si feature 22 NO se mergea antes de 23 (posible si los frontends se desincronizan),
esta explore propone que **feature 23 incluya también el helper**
`resolve_agency_music_destination` + `resolve_agency_music_local_path` —
son ~30 líneas y son neutrales para el upload-future. La spec de la feature
23 ya lo asume parcialmente: `"helper nuevo en modules/rendering/infrastructure/runtime/assets.py: resolve_agency_music_local_paths"`.

### 5.3 Hotfix Codex pendientes de archivar

`modules/rendering/infrastructure/preparation.py`, `ffmpeg/filters.py` y
`layout/panels.py` están con cambios sin commitear de Codex (ver `git status`
+ diff en §1). Si Codex commitea, `preparation.py:186` (donde se llama
`resolve_background_audio_paths`) puede cambiar. Anotar para revalidar
en cuanto Codex archive.

### 5.4 Riesgo del seed binario en migración

Cubierto en §4.5. Decisión por el leader (decisión #4).

### 5.5 Mismatch del inventario `assets/music/`

La task asume 4 .mp3 NCS pero hay 5 archivos (`ncs-music.mp3` + 3 NCS
nombre-largo + `New Light.wav`). Decidir cuáles entran al seed.
Ver decisión #1.

### 5.6 `MusicTracksRepository.list_for_agency` no filtra por `is_default`

El filtro es responsabilidad del use case (`(t for t in all_tracks if t.is_default)`).
Alternativa: añadir método `list_default_for_agency` al repo. Ver decisión #2.

### 5.7 Trigger del seed en agencia nueva requiere workspace_dir

`RegisterAgencyUseCase` actualmente no conoce el `workspace_dir`. Para
disparar la copia de blobs necesita inyectarlo (constructor o argumento
del `execute`). Esto cruza el bounded context tenancy → rendering/storage,
lo cual no es trivial. Ver decisión #5.

---

## 6. Decisiones a tomar antes de implementar

1. **Qué archivos de `assets/music/` entran al seed** (4 obligatorios según
   spec): ¿`ncs-music.mp3` + los 3 NCS nombre-largo? ¿O excluir `ncs-music.mp3`
   por ser el default y meter `New Light.wav`?

2. **`MusicTracksRepository.list_for_agency`**: ¿añadir método
   `list_default_for_agency` o filtrar en use case con comprehension?
   Recomendación: filtrar en use case (más simple, repo queda intacto).

3. **Convención de filename para los blobs seed**: ¿`_seed_ncs_<slug>.mp3`?
   ¿O `seed/<slug>.mp3` (subdirectorio)? Afecta el `LIKE` del downgrade.
   Recomendación: prefijo `_seed_ncs_` plano (más simple para `LIKE`).

4. **Migración monolítica vs script separado de bootstrap**: ¿la migración
   alembic copia los blobs (opción A) o solo inserta filas y un script
   externo copia los blobs (opción B)? Recomendación: A (atomicidad >
   limpieza).

5. **Punto de inyección del seed en `RegisterAgencyUseCase`**: ¿añadir
   `workspace_dir` por constructor en feature 23 (rompiendo callers existentes
   que instancian `RegisterAgencyUseCase()` sin args), o registrar un
   event-handler post-creación? Recomendación: inyección por constructor
   con default `Path(".")` para no romper unit tests sin workspace; en
   producción `app_factory.py` lo pasa explícito.

6. **Fallback en readiness check**: ¿el endpoint readiness debe llamar
   `resolve_background_audio_paths(music_tracks=None)` (legacy scan de
   `assets/music/`) o intentar contar tracks en BBDD? Recomendación:
   mantener legacy scan — readiness no requiere conexión a BBDD por
   diseño actual.

7. **Comportamiento si `MUSIC_NO_TRACKS`**: ¿qué hace el use case del reel?
   ¿marca `publish_status='failed'`? ¿bloquea ya en la fase de planning
   antes de gastar ffmpeg? Depende del shape post-feature-21.

8. **Migración de prod**: validar con el usuario que se puede correr la
   migración data en prod (28MB × N agencias por workspace) — se ejecuta
   una sola vez pero requiere que ffmpeg/ffprobe estén disponibles en el
   container donde corre `alembic upgrade head`.

---

## 7. Apéndice: comandos exactos para revalidar antes de implementar

Ejecutar (en orden) cuando feature 21 cierre, antes de empezar feature 23:

```bash
# 1. Confirmar estado del repo
cd /opt/projects/4Reels-Backend
git status --short
git log --oneline -10

# 2. Re-grep de call sites (deben coincidir con §2.2 o reflejar el nuevo árbol)
grep -rn "resolve_background_audio_paths" modules/ apps/ tests/ shared/
grep -rn "background_audio_candidates\|background_audio_path" modules/ apps/ tests/

# 3. Verificar que el contrato de PreparedReelAssets sigue igual
grep -n "class PreparedReelAssets" modules/rendering/infrastructure/models.py
# Leer las 15 líneas siguientes para confirmar background_audio_path/candidates

# 4. Confirmar el head de alembic actual y el next rev_id
ls alembic/versions/ | sort | tail -10
grep -E "^(revision|down_revision)" alembic/versions/202605*.py | tail -20

# 5. Confirmar que el helper resolve_agency_branding_destination sigue siendo
#    la única analogía válida (feature 22 puede haber introducido ya
#    resolve_agency_music_destination)
grep -n "resolve_agency_music_destination\|resolve_agency_branding_destination" shared/storage/site_layout.py shared/storage/__init__.py

# 6. Confirmar inventario de assets/music/
ls -la assets/music/

# 7. Confirmar el shape de MusicTrack + MusicTracksRepository
grep -n "class MusicTrack\b" modules/configuration/domain/agency_settings.py
grep -n "list_for_agency\|add_track\|is_default" modules/configuration/infrastructure/music_track_repository.py

# 8. Confirmar el flow de mux_audio_candidates
grep -n "mux_audio_candidates" modules/rendering/infrastructure/ffmpeg/render_reel.py

# 9. Re-leer el diff de las zonas calientes (debe estar limpio post-feature-21)
git diff HEAD -- modules/reels/application/use_cases/ingest_property_into_reel.py
git diff HEAD -- modules/rendering/infrastructure/preparation.py

# 10. Confirmar que readiness check sigue funcionando contra fs (no DB)
grep -n "_resolve_background_audio_paths\|background_audio" apps/api/readiness.py

# 11. Smoke baseline antes de modificar nada
python -m apps.api --check
# (NO pytest --create-db, NO alembic upgrade — solo --check)
```

Si cualquiera de los comandos 2-8 revela una diferencia respecto a este
explore, **detener y re-investigar** la zona afectada antes de continuar.
