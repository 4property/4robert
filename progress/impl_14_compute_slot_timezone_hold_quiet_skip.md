# Feature 14 — `compute_slot_honors_timezone_hold_quiet_skip`

## Resumen

Refactor de `compute_next_publish_slot` para que honre la zona horaria
de la agencia (kwarg `agency_timezone` IANA, fallback UTC con WARNING)
y aplique los tres toggles introducidos por feature 13
(`hold_window_seconds`, `quiet_hours_enabled`, `skip_weekends`) en
orden estricto: hold → skip_weekends → quiet_hours. Threading desde
`regenerate_reel.py`: el use case ahora carga la agencia con
`uow.tenancy.agencies.get_by_id(...)` y pasa su `timezone` al use case
puro.

Se preserva el contrato pre-feature-13 (todos los toggles off →
`None`, publicación inmediata). La semántica implícita de la feature
11 —donde `publish_window_start/end` actuaba como "horas permitidas"
por defecto— pasa a depender del flag `quiet_hours_enabled` (default
`False`); los tests legacy que asumían esa semántica fueron migrados
a `quiet_hours_enabled=True`, preservando cobertura. Documentado en
`docs/API.md`.

## Archivos tocados

- `modules/configuration/application/use_cases/compute_next_publish_slot.py`
  — refactor completo del algoritmo (firma + lógica).
- `modules/reels/application/use_cases/regenerate_reel.py` — carga
  `agency` desde `uow.tenancy.agencies.get_by_id(...)` y forwardea
  `agency_timezone`.
- `tests/unit/configuration/test_compute_next_publish_slot.py` —
  tests legacy migrados a `quiet_hours_enabled=True` para preservar
  cobertura; +13 casos nuevos para feature 14.
- `tests/unit/reels/_uow_stubs.py` — `StubAgencies` ahora expone
  `timezone` y registra las llamadas a `get_by_id`; `build_uow` acepta
  `agencies` / `agency_timezone`.
- `tests/unit/reels/test_regenerate_reel.py` — test legacy ahora
  habilita `quiet_hours_enabled=True`; +2 tests nuevos que asertan el
  forward del timezone al use case puro.
- `tests/integration/reels/_client.py` — `seed_automation_rules`
  acepta los nuevos campos (`hold_window_seconds`,
  `quiet_hours_enabled`, `skip_weekends`).
- `tests/integration/reels/test_admin_reels_router.py` — nuevo test
  end-to-end (skip_weekends + quiet_hours + Europe/Dublin cruzando UTC)
  con fake clock vía `patch` de `datetime`.
- `docs/API.md` — documentada la semántica nueva: comportamiento del
  toggle `quiet_hours_enabled`, fallback de timezone con WARNING,
  orden de los shifts.

## Algoritmo final de `compute_next_publish_slot`

```python
def compute_next_publish_slot(
    rules: AutomationRules | None,
    now_utc: datetime,
    *,
    agency_timezone: str = "UTC",
) -> datetime | None:
    if rules is None:
        return None

    # Step 2: clamp hold window into [0, 86_400].
    hold_window_seconds = _coerce_hold_window_seconds(
        getattr(rules, "hold_window_seconds", 0)
    )

    # Step 3: ensure UTC, then apply hold.
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    target_utc = now_utc + timedelta(seconds=hold_window_seconds)

    quiet_hours_enabled = bool(getattr(rules, "quiet_hours_enabled", False))
    skip_weekends = bool(getattr(rules, "skip_weekends", False))

    # Step 8 (early): preserve pre-feature-13 "immediate" contract.
    if hold_window_seconds == 0 and not quiet_hours_enabled and not skip_weekends:
        return None

    # Step 4: resolve timezone (safe fallback to UTC with WARNING).
    tz = _resolve_timezone(agency_timezone)

    # Step 5: convert to agency local.
    target_local = target_utc.astimezone(tz)

    start_time = _parse_hh_mm(getattr(rules, "publish_window_start", "") or "")
    end_time = _parse_hh_mm(getattr(rules, "publish_window_end", "") or "")
    publish_day_indices = _normalise_publish_days(
        getattr(rules, "publish_days", ()) or ()
    )

    # Step 6: skip_weekends shift.
    if skip_weekends and target_local.weekday() in (5, 6):
        if start_time is None or not publish_day_indices:
            return None
        next_slot_local = _next_allowed_day_at_start(
            after_local=target_local,
            publish_day_indices=publish_day_indices,
            start_time=start_time,
            include_after=False,
        )
        if next_slot_local is None:
            return None
        target_local = next_slot_local

    # Step 7: quiet hours shift.
    if quiet_hours_enabled:
        if start_time is None or end_time is None or not publish_day_indices:
            return None
        if target_local.weekday() not in publish_day_indices:
            shifted = _next_allowed_day_at_start(
                after_local=target_local,
                publish_day_indices=publish_day_indices,
                start_time=start_time,
                include_after=False,
            )
            if shifted is None:
                return None
            target_local = shifted
        if not _is_inside_quiet_hours_window(
            moment=target_local.time().replace(microsecond=0),
            start_time=start_time,
            end_time=end_time,
        ):
            same_day_start = datetime.combine(
                target_local.date(), start_time, tzinfo=target_local.tzinfo
            )
            if (
                target_local.weekday() in publish_day_indices
                and same_day_start > target_local
            ):
                target_local = same_day_start
            else:
                shifted = _next_allowed_day_at_start(
                    after_local=target_local,
                    publish_day_indices=publish_day_indices,
                    start_time=start_time,
                    include_after=False,
                )
                if shifted is None:
                    return None
                target_local = shifted

    # Step 9: collapse to None if no wait was introduced.
    resolved_utc = target_local.astimezone(timezone.utc)
    if resolved_utc == now_utc:
        return None
    return resolved_utc
```

Helpers nuevos:

- `_resolve_timezone(agency_timezone)` — `try/except (ZoneInfoNotFoundError, ValueError, TypeError)` con WARNING al log y fallback a UTC.
- `_coerce_hold_window_seconds(raw)` — clamp defensivo `[0, 86400]`.
- `_next_allowed_day_at_start(...)` — walks 1..7 días buscando el próximo en `publish_day_indices`.
- `_is_inside_quiet_hours_window(...)` — soporta wrap-around (start > end).

## Diff conceptual de `regenerate_reel.py`

Antes:

```python
scheduled_slot = compute_next_publish_slot(
    automation, datetime.now(timezone.utc)
)
```

Después:

```python
agency = uow.tenancy.agencies.get_by_id(normalized_agency_id)
agency_timezone = (
    agency.timezone
    if agency is not None and getattr(agency, "timezone", "")
    else "UTC"
)
scheduled_slot = compute_next_publish_slot(
    automation,
    datetime.now(timezone.utc),
    agency_timezone=agency_timezone,
)
```

(`get_by_id` es el nombre real del método en `AgencyRepository`, no
`get` — verificado en `modules/tenancy/infrastructure/agency_repository.py`.)

## Tests nuevos

**Unit — `tests/unit/configuration/test_compute_next_publish_slot.py`:**

- `test_all_toggles_off_returns_none_immediate_publish` — preserva
  contrato pre-feature-13: sin toggles, slot=None aunque la hora actual
  caiga fuera de `publish_window_*`.
- `test_hold_window_only_returns_now_plus_delta_utc` — `hold=3600` con
  todo lo demás off → `now+1h` UTC.
- `test_hold_window_capped_at_24h` — `hold=10_000_000` se clamp en 86400.
- `test_hold_window_exactly_24h_is_honoured` — `hold=86400` produce
  `now+24h`.
- `test_quiet_hours_dublin_evening_defers_to_next_morning` — Tue 23:30
  Dublin BST + ventana 07:00-22:00 → próximo Wed 07:00 Dublin → UTC.
- `test_hold_window_plus_quiet_hours_dublin_BST` — hold de 1h sumado a
  quiet hours, ambos respetando timezone Europe/Dublin.
- `test_skip_weekends_saturday_morning_dublin_advances_to_monday` — Sat
  10:00 Dublin → Mon 09:00 Dublin → UTC.
- `test_skip_weekends_friday_evening_plus_hold_lands_on_monday` — Fri
  23:00 Dublin + hold 2h → Sat 01:00 local → Mon 09:00 Dublin → UTC.
- `test_quiet_hours_enabled_with_empty_publish_days_returns_none` —
  publish_days vacío → None (preserva semántica feature 11).
- `test_invalid_agency_timezone_falls_back_to_utc_with_warning` — IANA
  inválida → cae a UTC, calcula slot, registra WARNING. Verificado vía
  `caplog`.
- `test_dst_spring_forward_ambiguous_local_time_is_safe` — target que
  cae en el "gap" de DST Dublin 2026-03-29 01:30 local no crashea; el
  resultado es un datetime UTC válido. Documentación: el comportamiento
  exacto depende de la política de ZoneInfo de CPython (suma el offset
  DST), no se pinea el valor para no acoplar al runtime.
- `test_skip_weekends_with_empty_publish_days_returns_none` —
  skip_weekends sin anchor (`publish_window_start=""`) retorna None.
- `test_quiet_hours_inside_window_at_local_noon_returns_none` — 12:00
  Dublin local (11:00 UTC) dentro de la ventana → None.

**Unit — `tests/unit/reels/test_regenerate_reel.py`:**

- `test_regenerate_reel_forwards_agency_timezone_to_compute_slot` —
  spy del use case puro, asserta `kwargs == {"agency_timezone":
  "Europe/Dublin"}` y verifica que `agencies.get_by_id` se llamó.
- `test_regenerate_reel_falls_back_to_utc_when_agency_timezone_missing`
  — `agency.timezone=""` colapsa a `"UTC"` en el caller.

**Integration — `tests/integration/reels/test_admin_reels_router.py`:**

- `test_approve_skip_weekends_quiet_hours_dublin_lands_on_monday_utc` —
  seed completo (agency Dublin + automation con
  `skip_weekends=True, quiet_hours_enabled=True, 09:00-18:00`), fake
  clock Sat 09:00 UTC (= Sat 10:00 Dublin BST), aprueba reel, verifica
  que `scheduled_at` en respuesta == persisted en
  `jobs.publish_context_json` == Mon 09:00 Dublin → UTC.

## Salida de `pytest -q` (últimas 30 líneas)

```
tests/unit/apps_api/test_agency_token.py::test_decode_rejects_token_with_non_agency_scope
tests/unit/apps_api/test_agency_token.py::test_decode_rejects_token_with_wrong_issuer
  /opt/projects/4Reels-Backend/.venv/lib64/python3.12/site-packages/jwt/api_jwt.py:365: InsecureKeyLengthWarning: The HMAC key is 11 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
    decoded = self.decode_complete(

tests/unit/apps_api/test_agency_token.py::test_decode_raises_invalid_when_signature_does_not_match
  /opt/projects/4Reels-Backend/.venv/lib64/python3.12/site-packages/jwt/api_jwt.py:365: InsecureKeyLengthWarning: The HMAC key is 12 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
    decoded = self.decode_complete(

tests/unit/apps_api/test_agency_token.py::test_decode_rejects_tokens_signed_with_different_algorithm
  /opt/projects/4Reels-Backend/.venv/lib64/python3.12/site-packages/jwt/api_jwt.py:147: InsecureKeyLengthWarning: The HMAC key is 11 bytes long, which is below the minimum recommended length of 64 bytes for SHA512. See RFC 7518 Section 3.2.
    return self._jws.encode(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 632 passed, 14 warnings in 246.39s (0:04:06)
```

Los **3 fallos son preexistentes** y están documentados en
`progress/review_13_automation_hold_quiet_skip.md` (Windows path en
`FRONTEND_REPO_ROOT` y `test_health_endpoints` no resueltos en
features previas). Antes de feature 14: **583 passed**; ahora: **632
passed** (+49 nuevos tests).

## Verificación

```
$ .venv/bin/python -m apps.api --check ; echo $?
0
$ .venv/bin/python -m apps.worker --check ; echo $?
0
$ .venv/bin/python -m pytest tests/unit/configuration/test_compute_next_publish_slot.py tests/unit/reels/test_regenerate_reel.py tests/integration/reels/test_admin_reels_router.py -q
79 passed in 36.72s
```

## Confirmaciones de coordinación

- **NO tocado** `modules/catalog/**`, `modules/rendering/**`,
  `modules/configuration/transport/http/render_templates_router.py`,
  `modules/configuration/application/use_cases/list_render_templates.py`,
  `modules/configuration/application/use_cases/select_render_template.py`,
  `modules/configuration/infrastructure/render_template_repository.py`,
  `modules/configuration/transport/payloads/render_templates.py` —
  scope exclusivo de feature 16.
- **NO tocado**
  `modules/reels/application/use_cases/ingest_property_into_reel.py` —
  scope de feature 15.
- **NO escritas migraciones** — no hay schema change en esta feature.
- **NO modificado** `progress/current.md` (la otra sesión de feature
  16 escribe ahí).
- **NO marcado `status:"done"`** en `feature_list.json` — sigue en
  `in_progress` hasta que el reviewer apruebe.
- **NO commits** ejecutados (repo sucio por features previas).

## Caveats / decisiones

- **Contrato implícito de feature 11.** Antes, `publish_window_*` con
  `publish_days` actuaba como "horas permitidas" en cualquier caso. Con
  feature 14 esa semántica requiere `quiet_hours_enabled=True`. Las
  filas existentes (creadas antes de la migración de feature 13)
  tienen el flag en `False` por defecto, lo que silencia el
  deferimiento por horas hasta que el usuario lo habilite desde la UI.
  **Esto es intencional** y está documentado en `docs/API.md`. Tests
  legacy migrados a `quiet_hours_enabled=True` para preservar cobertura.
- **DST gap (Dublin 2026-03-29 01:30).** CPython's `ZoneInfo` resuelve
  el local "no existe" sumando el offset DST de manera deterministica
  (PEP 495). El test no asserta el valor exacto post-DST porque ese
  contrato es del runtime, no del use case; sí verifica que **no
  crashea** y devuelve un UTC válido.
- **Fallback de timezone con WARNING.** Usado el patrón
  `logging.getLogger(__name__).warning(...)` — la configuración global
  de `shared/observability/persistent_log.py` ya enrota los WARNINGs a
  `warnings-errors.log` cuando el workspace está configurado. Sin
  `traceId` (no hay un correlation ID a mano en el use case puro); el
  caller (`regenerate_reel`) podría enriquecerlo en una iteración
  futura si la observabilidad lo demanda.
- **`include_after=False` en `_next_allowed_day_at_start`.** Decisión
  deliberada: cuando `skip_weekends` dispara con un sábado/domingo, no
  queremos quedarnos el mismo día (sigue siendo fin de semana); cuando
  `quiet_hours_enabled` dispara por estar fuera de la ventana, ya
  manejamos el caso "mismo día más tarde" inline antes de llamar al
  helper. Mantiene el helper simple y libre de ambigüedad.
- **Repo method `get_by_id`, no `get`.** El plan v2 escribía
  `uow.tenancy.agencies.get(...)`, pero el repo real expone
  `get_by_id`. Verificado en
  `modules/tenancy/infrastructure/agency_repository.py:40`.

(Revisión pendiente.)
