# Implementación feature 21 — `per_reel_description_override_endpoint` (backend)

- **Fecha:** 2026-05-14
- **Agente:** implementer (backend), invocado por leader Claude
- **Concurrencia:** otra sesión trabaja la feature 22 (música). Esta entrega
  no toca `modules/configuration/infrastructure/music_track_repository.py`,
  `assets/music/`, ni `modules/rendering/*` (hotfixes Codex archivados sin
  cerrar). Tampoco modifico `progress/current.md` fuera de mi sección
  `# Trabajo en paralelo — feature 21 (leader Claude)`.

## Resumen

Cierra el bucle de descripciones por agencia (features 18/19/20 ya cerradas)
añadiendo la capacidad de **editar la caption de un reel concreto antes de
publicarlo**. La edición se persiste en una nueva columna JSONB nullable
sobre `reels` y el worker la honra al ensamblar el `PropertyContext` antes
de invocar `PublishReelUseCase`.

## Cambios por archivo

### Schema + ORM

- **`alembic/versions/20260514_0003_reels_descriptions_override.py`** (nuevo)
  - `revision = "20260514_0003"`, `down_revision = "20260514_0002"`
    (encadenada tras el hotfix de Codex `classic_render_template_preview`).
  - `upgrade()`: `op.add_column('reels', sa.Column('descriptions_override',
    postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=None))`.
  - `downgrade()`: `op.drop_column('reels', 'descriptions_override')`.
  - Idempotente para arriba y reversible para abajo. Probada manualmente
    con `alembic upgrade head` / `downgrade -1` / `upgrade head`.
- **`shared/db/orm.py`** — añade `descriptions_override: Mapped[dict | None]`
  inmediatamente después de `publish_target_snapshot`. Tipo `JSONB` (mismo
  dialecto que el resto de columnas JSONB del modelo) con `nullable=True`
  y `server_default=None`.

### Dominio + persistencia

- **`modules/reels/domain/reel_state.py`** — añade el campo
  `descriptions_override: Mapping[str, Any] | None = field(default=None)`
  al `ReelState` (después de `render_template_id`). El docstring explica
  que `None` y `{}` significan "no override". `build_empty_reel_state`
  conserva la firma posicional, así que no rompe call-sites existentes.
- **`modules/reels/infrastructure/reel_state_repository.py`**
  - Nuevas helpers `_override_to_jsonb_param` y `_jsonb_to_optional_mapping`.
    `_override_to_jsonb_param` mapea `None` / `{}` a `None` (SQL NULL) y el
    resto a JSON compacto; `_jsonb_to_optional_mapping` decodifica la
    columna preservando el sentinel `None`. Con esto el `WHERE
    descriptions_override IS NULL` sigue siendo idéntico a "no override".
  - `_REEL_COLUMNS` incluye `descriptions_override`. El INSERT castea el
    parámetro con `CAST(:descriptions_override AS jsonb)` (el cast trata
    el parámetro `None` como literal NULL, no como string `"null"`).
  - El `ON CONFLICT DO UPDATE SET` también propaga la columna.
  - `update_publish_status`, `update_workflow_state`, `save_local_artifacts`
    reciclan `existing.descriptions_override` al reconstruir el `ReelState`
    (preservación del override a través de transiciones de workflow).

### Aplicación

- **`modules/reels/application/use_cases/update_reel_descriptions_override.py`** (nuevo)
  - `UpdateReelDescriptionsOverrideUseCase.execute(...)` con la secuencia:
    1. `ensure_agency_exists(uow, agency_id)` → 404 `ADMIN_AGENCY_NOT_FOUND`.
    2. `uow.reels.states.get(...)` → 404 `ADMIN_REEL_NOT_FOUND` si no existe.
    3. Si `existing.publish_status not in {needs-approval, pending_review, pending, ''}`
       lanza `ReelNotEditableError` → mapeado a **409 `REEL_NOT_EDITABLE`**
       por el router.
    4. Carga `agency_reel_defaults.platforms`; cualquier clave fuera de esa
       lista (case-insensitive) → `ValidationError(code='PLATFORM_NOT_ENABLED')`
       → mapeado a **422** por el router.
    5. Reconstruye un `ReelState` nuevo con `descriptions_override=coerced or None`
       y lo persiste. La UoW commitea (no se llama `session.commit()` desde
       el repositorio).
  - **Decisión de error codes** (motivada en el prompt):
    - **409** + código `REEL_NOT_EDITABLE` para reel ya aprobado/publicado.
      Prefiero el código semántico (`REEL_NOT_EDITABLE`) en vez del genérico
      `RESOURCE_LOCKED` porque le da al frontend una pista accionable
      (deshabilitar el editor con un mensaje "reel ya publicado/aprobado"),
      coherente con `ADMIN_REEL_NOT_FOUND` que ya existe.
    - **422** + código `PLATFORM_NOT_ENABLED` (en vez de `UNKNOWN_PLATFORM`)
      porque el problema es de *configuración del tenant*, no de tipo: la
      plataforma puede existir en el catálogo global y aun así no estar
      habilitada para esta agency.
  - Acepta también `publish_status='pending'` y `''` además de los dos
    valores del prompt — son estados de transición legítimos del worker
    en los que el editor sigue siendo relevante (la override queda dormante
    hasta el siguiente ingest pass del worker).
- **`modules/reels/application/use_cases/ingest_property_into_reel.py`**
  - Después de calcular `publish_descriptions_by_platform` (línea ~222) y
    *antes* de construir `publish_target_snapshot`, hago un `peek` del
    `ReelState` existente y aplico el override con el helper nuevo
    `_apply_descriptions_override` (módulo-level). El peek se reusa unas
    líneas más abajo (`existing_state = _peeked_existing_state`), evitando
    un segundo round-trip a Postgres.
  - Lógica del merge:
    ```text
    for platform, override_text in dict(override).items():
        if override_text is None: continue
        if not str(override_text).strip(): continue
        publish_descriptions_by_platform[str(platform)] = str(override_text)
    ```
    Per-platform y defensivo: un `None` o blank no machaca la caption
    auto-generada. El resultado fluye tanto al
    `PropertyContext.publish_descriptions_by_platform` (que es lo que
    consume `property_publisher.py` en el adapter GHL) como al
    `publish_target_snapshot.descriptions_by_platform` persistido en
    `reels.publish_target_snapshot` — así un restart del worker re-lee un
    estado consistente.
- **`modules/reels/application/use_cases/_ingest_property_assets.py`** —
  `_build_ingested_reel_state` propaga `state.descriptions_override` al
  nuevo `ReelState` que escribe el ingest. Sin esto el override se perdería
  en cada re-ingest del mismo reel.

### Transport

- **`modules/reels/transport/payloads/reel_descriptions_override.py`** (nuevo)
  - `ReelDescriptionsOverridePayload(BaseModel)` con
    `model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)`.
  - Único campo: `descriptions_by_platform: dict[str, str]` (default vacío).
  - El docstring explica que **no se valida sintaxis `{{ vars }}`** — el
    cliente manda el texto ya renderizado. Si en el futuro permitimos
    re-templating, se añade un endpoint separado.
- **`modules/reels/transport/http/admin_reels_router.py`**
  - Nuevo endpoint `PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/descriptions`.
  - Mapeo de errores en el router (en este orden):
    - `ResourceNotFoundError` → `_resource_not_found_response` (404 con
      el `code` del propio error).
    - `ReelNotEditableError` → `json_error(409, ..., code='REEL_NOT_EDITABLE')`.
    - `ValidationError` → `json_error(422, ..., code=error.code)` (en lugar
      del 400 que usan `approve`/`reject`; la convención HTTP para
      validación semántica es 422 cuando el cuerpo es sintácticamente
      correcto pero viola reglas de negocio, mientras que 400 lo deja
      para validation errors atajados por Pydantic).
  - Inyección por DI: el constructor del router acepta un
    `update_descriptions_override: UpdateReelDescriptionsOverrideUseCase | None`
    (default `None` → se construye un use case nuevo), siguiendo el patrón
    de los otros use cases del router.

### Documentación

- **`docs/API.md`** — añade subsección `PATCH .../descriptions` debajo de
  "Reel approval and publish status" con request/response/error matrix.
- **`docs/http_surface.md`** — añade una línea para el PATCH en la tabla
  de superficie HTTP.

### Tests

- **`tests/integration/reels/test_admin_reels_descriptions_override.py`** (nuevo)
  - 7 tests cubriendo:
    - Happy path PATCH → 200 + override persistido en `reels.descriptions_override`.
    - PATCH con `{}` → resetea la columna a SQL NULL.
    - 404 `ADMIN_REEL_NOT_FOUND` para reel inexistente.
    - 404 `ADMIN_AGENCY_NOT_FOUND` para agency inexistente.
    - 409 `REEL_NOT_EDITABLE` cuando el reel está `publish_status='published'`.
    - 422 `PLATFORM_NOT_ENABLED` cuando el payload referencia una platform
      fuera de `agency_reel_defaults.platforms`.
    - 422 (Pydantic) cuando llega un campo extra al body.
  - Reutiliza `tests/integration/reels/_client.py` y `tests/support/postgres.py`.
    Añade un helper local `_seed_reel_defaults` para sembrar
    `agency_reel_defaults`.
- **`tests/unit/reels/test_ingest_applies_descriptions_override.py`** (nuevo)
  - 5 tests cubriendo:
    - Helper `_apply_descriptions_override` con override per-platform.
    - Helper defensivo contra `None`/`""`/whitespace.
    - Helper no-op con `override=None` o `override={}`.
    - **Worker end-to-end con override**: existing state con
      `descriptions_override={'instagram': '...'}` →
      `context.publish_descriptions_by_platform['instagram']` == override,
      el resto de plataformas conservan la caption auto-generada, el
      snapshot persistido refleja el merge.
    - **Worker end-to-end sin override**: regression guard, las captions
      auto-generadas pasan sin tocar y `state.descriptions_override is None`.

## Verificación

- `bash ./init.sh` → exit 0. Mismos 3 fallos preexistentes documentados
  en la baseline (`test_http_surface_contract.py` por ausencia del repo
  frontend en este host, y 2 en `test_http_transport.py` por health
  endpoints sin dispatcher pausado). 711 passed (eran 699; +12 tests
  nuevos).
- `python -m alembic heads` → `20260514_0003 (head)`.
- `python -m alembic upgrade head` → corre la migración nueva limpio.
- `python -m alembic downgrade -1` → revierte sin errores (drop_column).
- `python -m alembic upgrade head` → re-aplica idempotente.
- `python -m pytest tests/integration/reels/ tests/unit/reels/ -q` → 123 passed.
- `python -m pytest -q` (global) → 3 failed (baseline), 711 passed, 14 warnings.
- `python -m apps.api --check` → OK.
- `python -m apps.worker --check` → OK (kinds=reel_publish, scripted_render).

## Notas para el reviewer

- El override se aplica en `IngestPropertyIntoReelUseCase` (no en
  `PublishReelUseCase` como sugería literalmente el prompt) porque el
  worker reasambla `PropertyContext` en cada job y `publish_reel.py`
  consume `context.publish_descriptions_by_platform` set por el ingest.
  Hacer el merge en el ingest mantiene la separación de capas y deja
  `publish_reel.py` intacto. El efecto observable es idéntico al descrito
  en el prompt: per-platform replace, fallback al snapshot si no hay
  override.
- El use case **no** ejecuta `session.commit()` ni opens su propia UoW:
  el router pasa la UoW que abre con `unit_of_work_factory()` y el
  context-manager commitea en el `__exit__` (regla dura "No
  `session.commit()` dentro de un repositorio" respetada).
- `_EDITABLE_PUBLISH_STATUSES` incluye `'pending'` y `''` además de
  `'needs-approval'` y `'pending_review'`. Esto cubre el caso de un reel
  recién ingestado (publish_status='pending') o de un reel sin publish
  context (publish_status=''). Si el reviewer cree que solo se deben
  aceptar `needs-approval`/`pending_review`, el cambio es trivial: ajustar
  el `frozenset` en
  `modules/reels/application/use_cases/update_reel_descriptions_override.py`.
- La feature **no marca `done`** en `feature_list.json`; eso queda para
  el reviewer + cross-repo (frontend).
