# Review — feature 11 (wire_automation_publish_window_to_ghl_schedule)

**Veredicto:** APPROVED

## Resumen ejecutivo

El implementer ejecutó la ruta minimalista exactamente como pidió el leader: solo `publish_window_start`/`publish_window_end`/`publish_days` se cablean al `scheduleDate` de GoHighLevel; `quiet_hours_*` y `skip_weekends` quedan documentados como TODO sin tocar ORM, payload ni dataclass. Sin alembic, sin dependencias nuevas. El use case `compute_next_publish_slot` es puro (sin UoW, sin I/O, sin side-effects). El response del `/approve` devuelve `scheduled_at` (snake_case, ISO8601 UTC | `null`) coherente con el contrato del front. El threading queda completo: `regenerate_reel` → `publish_context` (JSONB) → `SocialPublishContext` → `MultiPlatformPublishRequest` → `multi_publish` → `post_creation` → `social_service` (`json_body["scheduleDate"]` + `json_body["status"]="scheduled"`).

Replay idempotente correcto: `ActiveJob` ampliado con `publish_context_json`, `find_active_job_for_property` lo selecciona, y `_extract_scheduled_at` (defensivo: maneja `None`, JSON malformado, dict ausente) recupera el slot original. Tests pre-feature-11 sin la clave responden `null` sin romper.

`ingest_property_into_reel.py` queda fuera de scope (el diff existente es de feature 10, agency logo — no toca `publish_context` ni `scheduled_at`).

## Checkpoints

- C1 — Use case puro `compute_next_publish_slot` en `modules/configuration/application/use_cases/compute_next_publish_slot.py`: [x] Sin UoW, sin I/O, sin imports SQLAlchemy/Pydantic. Parseo defensivo (`_parse_hh_mm`, `_normalise_publish_days`) que colapsa input malformado a `None` sin crashear. Tipo de retorno `datetime | None`, ISO8601 lo emite el caller con `.isoformat()`.
- C2 — Tests del use case puro (`tests/unit/configuration/test_compute_next_publish_slot.py`): [x] 26 casos pasan, cubren los 5 escenarios canónicos del enunciado + 21 edge cases (HH:MM inválido, hora/minuto fuera de rango, día desconocido, tz naive, tz no-UTC, wrap-around 22→06, parametrize de los 7 días).
- C3 — `regenerate_reel.py` reemplaza `del automation` por `compute_next_publish_slot(automation, datetime.now(timezone.utc))`: [x] Líneas 236-241 (use case); línea 257 (`publish_context["scheduled_at"]`); línea 319 (`RegenerateReelResult.scheduled_at`).
- C4 — Replay idempotente recupera `scheduled_at` del job persistido: [x] `ActiveJob` ampliado con `publish_context_json: str | None` (`job_repository.py:36`). `find_active_job_for_property` lo selecciona y normaliza (str/bytes/jsonb → str). En el branch de replay (`regenerate_reel.py:205-220`), `_extract_scheduled_at` parsea el JSON con defensa total: vacío/None/no-dict/exception → `None`. Pre-feature-11 retorna `null` sin romper.
- C5 — `SocialPublishContext` lleva `scheduled_at: str | None = None` (`modules/reels/domain/types.py:59`) + cobertura en `to_dict` (línea 68) y `from_dict` (líneas 105-110, con strip + collapse a `None` si whitespace-only): [x]
- C6 — `MultiPlatformPublishRequest` lleva `scheduled_at: str | None` (`modules/publishing/infrastructure/adapters/gohighlevel/models.py:223`) + init manual `object.__setattr__` con normalización de whitespace (líneas 243, 321-326): [x] Respeta `frozen=True, slots=True, init=False`.
- C7 — `property_publisher.publish_property_media` forwardea `context.publish_context.scheduled_at` al construir el `MultiPlatformPublishRequest` (línea 104 de `property_publisher.py`): [x]
- C8 — `multi_publish.publish_media_to_platforms` forwardea `request.scheduled_at` a `_publish_platform_with_retry` (línea 253 de `multi_publish.py`): [x]
- C9 — `post_creation._publish_platform_with_retry` + `_create_post` añaden kwarg `scheduled_at` con default `None` y lo forwardean a `social_service.create_social_post` (líneas 39, 53, 73, 101 de `post_creation.py`). Log incluye `format_detail_line("Scheduled at", scheduled_at or "<immediate>")`: [x]
- C10 — `social_service.create_social_post` añade kwarg `scheduled_at`. Cuando no es None/empty/whitespace: `json_body["scheduleDate"] = normalized_scheduled_at` y `json_body["status"] = "scheduled"`. Cuando None: `json_body["status"]="published"` y la clave `scheduleDate` NO aparece (`social_service.py:100, 117-134`). `create_reel_post` también acepta y forwardea el kwarg (líneas 204, 217). [x]
- C11 — Handler del approve emite `body["scheduled_at"] = result.scheduled_at` cuando `publish_enqueued=True`, incluso con valor `null` (decisión documentada: incluir siempre cuando aplica para que el front pueda branch sin distinguir presencia/ausencia). `admin_reels_router.py:218-225`. [x]
- C12 — Tests `social_service` con MagicMock (`tests/unit/publishing/test_social_service_scheduling.py`, 5 casos): [x] (1) con `scheduled_at` ISO → body incluye `scheduleDate` + `status="scheduled"`; (2) `scheduled_at=None` → body sin `scheduleDate`, `status="published"`; (3) whitespace-only `"   "` → trata como inmediato; (4) kwarg omitido → default safe; (5) `create_reel_post` forwardea el kwarg.
- C13 — Tests `test_regenerate_reel.py` actualizado: [x] 6 tests nuevos cubren window-outside (slot ISO), window-inside (None), automation missing (None), replay con slot persistido, replay legacy sin scheduled_at, replay sin atributo (defensivo).
- C14 — Tests integration HTTP approve (`tests/integration/reels/test_admin_reels_router.py`): [x] 3 tests nuevos (700-859) verifican body incluye `scheduled_at`, persistencia en `jobs.publish_context_json` coherente con el response, replay recupera el slot original y replay legacy emite `null` sin romper.
- C15 — `docs/API.md` documenta `scheduled_at` en el response del approve (líneas 315-348) y la semántica del `scheduleDate` en el body GHL (líneas 350-359). Además aclara que `quiet_hours_*`/`skip_weekends` quedan fuera del contrato (líneas 361-364). [x]
- C16 — NO tocar `ingest_property_into_reel.py` para `scheduled_at`: [x] `grep -n "scheduled_at" modules/reels/application/use_cases/ingest_property_into_reel.py` → 0 hits. El diff existente es de feature 10 (agency_logo_local_path) — completamente ortogonal.
- C17 — NO tocar ORM, alembic, payload, dataclass para `quiet_hours`/`skip_weekends`: [x] `git diff modules/configuration/infrastructure/orm.py modules/configuration/infrastructure/automation_repository.py modules/configuration/transport/payloads/automation.py modules/configuration/domain/agency_settings.py` → todos sin cambios. `ls alembic/versions/` → solo `20260501_0001_initial_schema.py` (no hay nueva revision). `grep "quiet_hours\|skip_weekends" modules/` → solo aparece en el docstring del use case puro como documentación de no-soporte.
- C18 — Verificación local:
  - `.venv/bin/python -m pytest tests/unit/configuration/test_compute_next_publish_slot.py -q` → `26 passed`. [x]
  - `.venv/bin/python -m pytest tests/unit/publishing/test_social_service_scheduling.py -q` → `5 passed`. [x]
  - `.venv/bin/python -m pytest tests/unit/reels/test_regenerate_reel.py -q` → `13 passed`. [x]
  - `.venv/bin/python -m pytest tests/integration/reels/test_admin_reels_router.py -q` → `24 passed`. [x]
  - `.venv/bin/python -m pytest tests/unit/configuration/ tests/unit/publishing/ tests/unit/reels/ tests/integration/reels/ tests/integration/publishing/ -q` → `239 passed`. [x]
  - `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh` → `exit 0`. Solo los 2 fallos preexistentes de `test_http_transport` (campo `configured_worker_count` en `/health`), ajenos a feature 11. [x]
  - `.venv/bin/python -m apps.api --check` → `exit 0`, `RUNTIME READY: Yes`. [x]
  - `.venv/bin/python -m apps.worker --check` → `exit 0`, `Worker --check OK`. [x]

## Cambios requeridos

Ninguno.

## Fuera de scope (correctamente NO tocado)

- `modules/reels/application/use_cases/ingest_property_into_reel.py` — flujo webhook auto-publish. El `publish_context` del webhook sigue publicando inmediato. Documentado en `impl_11_*.md` como decisión consciente, alineado con la regla del leader.
- `AutomationRules` dataclass (`modules/configuration/domain/agency_settings.py:45`) — sin nuevos campos. Sigue exponiendo solo `publish_window_start`, `publish_window_end`, `publish_days`, `trigger_on_status`, `approval_required`.
- `agency_automation_rules` ORM (`modules/configuration/infrastructure/orm.py:80-106`) — sin columnas nuevas. No hay alembic revision.
- Payload Pydantic (`modules/configuration/transport/payloads/automation.py`) — sin cambios.
- Pinterest, decodeHtmlEntities, social-templates, brand-logo, idempotencia previa — fuera de scope, sus diffs corresponden a features anteriores (8/9/10/12) sin interferencias con feature 11.

## Notas adicionales

- Decisión del implementer de incluir siempre `scheduled_at` en el body (con `null` cuando aplica) en vez de omitirlo: coherente con la observación del leader sobre coherencia (`idempotent_replay` se omite cuando False; `scheduled_at` se incluye siempre con `publish_enqueued=True` para que el front branche sin distinguir presencia vs ausencia). Documentado en `docs/API.md` y aceptado.
- Whitespace-only `scheduled_at` se trata como inmediato (collapse a `None`) en `social_service` (línea 117) y en `SocialPublishContext.from_dict` (línea 109) y en `MultiPlatformPublishRequest.__init__` (línea 325) — defensa coherente en toda la cadena.
- El ISO8601 que emite `regenerate_reel` viene de `datetime.isoformat()` con tz UTC (`+00:00`), coherente con el resto de timestamps del proyecto. Sin sufijo `Z` exótico.

**Una sola línea para chat**:

```
APPROVED -> progress/review_11_wire_automation_publish_window_to_ghl_schedule.md
```
