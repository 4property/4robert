# Review — feature 41 (`auto_subtitles_snapshot_for_editor`)

**Verdict: APPROVED**

Reviewer: Claude (rol reviewer) — 2026-05-17

---

## 1. Resumen ejecutivo

Feature 41 añade la columna `reels.auto_subtitles_snapshot JSONB NULL` con
los cues que la renderer autoCaptions produce, los persiste vía un
sentinel `_UNSET` que **preserva** el snapshot cuando el render consume
`subtitles_override`, y expone `publish_subtitles_snapshot` en
`GET /v1/admin/agencies/{id}/reels[/{site}/{prop}]`. El 6-point pattern
está completo y consistente con features 35/36/37. La migración
`20260517_0001` es reversible. El init.sh termina en el baseline
esperado (1063 passed + 3 flakes conocidos).

---

## 2. 6-point audit (file:line)

| # | Requirement | File:line | Verdict |
|---|---|---|---|
| 1 | Migración `20260517_0001_reels_auto_subtitles_snapshot.py`, `down_revision="20260515_0005"`, up/down/up clean | `alembic/versions/20260517_0001_reels_auto_subtitles_snapshot.py:32-51` | OK |
| 2 | `ReelORM.auto_subtitles_snapshot: Mapped[list \| None]` JSONB nullable | `shared/db/orm.py:228-241` | OK |
| 3 | `ReelState.auto_subtitles_snapshot: list[dict[str, Any]] \| None = None` (domain dataclass, sin SQLAlchemy) | `modules/reels/domain/reel_state.py:90-100` | OK |
| 4 | `_REEL_COLUMNS` + INSERT + `ON CONFLICT DO UPDATE` + bind + helpers preservando `existing.auto_subtitles_snapshot`; sentinel `_UNSET` en `save_local_artifacts` | `modules/reels/infrastructure/reel_state_repository.py:26-35` (sentinel), `:187-201` (param helper), `:249-251` (reader), `:262-273` (_REEL_COLUMNS), `:316` (INSERT), `:336` (ON CONFLICT), `:379-381` (bind), `:454` / `:510` (helpers forward), `:514-528` (kwarg + `_UNSET`), `:556-560` (resolve sentinel), `:598` (save) | OK |
| 5 | `_build_ingested_reel_state` propaga `state.auto_subtitles_snapshot` | `modules/reels/application/use_cases/_ingest_property_assets.py:238-244` | OK |
| 6 | Renderer computa cues vía `build_auto_subtitles_snapshot` cuando `subtitles_override is None`; `RenderedMediaArtifact.auto_subtitles_snapshot`; `PersistLocalArtifactsUseCase._persist_with_uow` forward a `save_local_artifacts(auto_subtitles_snapshot=...)` solo cuando el artifact carga cues (`None` → sentinel preserva) | Domain: `modules/reels/domain/types.py:303-356`. Renderer call: `modules/rendering/application/frame_composition.py:214-262`. Builder: `modules/rendering/infrastructure/layout/subtitles.py:253-327`. Persist forward: `modules/reels/application/use_cases/persist_local_artifacts.py:305-330`. | OK |

Sin `session.commit()` en repositorios; sin imports legacy
(`services.|application.|repositories.|core.|domain.`); sin cross-module
imports nuevos (las llamadas a `modules.rendering.infrastructure` y
`modules.publishing.infrastructure` desde reels son preexistentes — no
introducidas por esta feature). Composición intacta en
`apps/api/app_factory.py` y `apps/worker/runtime.py`.

---

## 3. Per-decision audit (leader's decisions)

| Decisión | Donde se cumple | OK |
|---|---|---|
| Columna `reels.auto_subtitles_snapshot JSONB NULL` hermana de `subtitles_override` | `alembic/versions/20260517_0001_reels_auto_subtitles_snapshot.py:39-47`; `shared/db/orm.py:239-241` | OK |
| Shape `[{index, text, in_seconds, out_seconds}]` igual que `subtitles_override` | Builder construye exactamente esa shape: `modules/rendering/infrastructure/layout/subtitles.py:302-326`. Payload reusa `ReelSubtitleCue` de feature 36: `modules/reels/transport/payloads/admin_reels.py:64`. | OK |
| Migración con `down_revision="20260515_0005"`; up/down/up clean | `alembic/versions/20260517_0001_reels_auto_subtitles_snapshot.py:32-33`; round-trip verificado en sección 7 | OK |
| Renderer integration: snapshot persiste cuando override NULL | `modules/rendering/application/frame_composition.py:224-241`; persistencia: `modules/reels/application/use_cases/persist_local_artifacts.py:323-330` | OK |
| Renderer integration: snapshot **preservado** cuando override IS NOT NULL (sentinel `_UNSET`) | `modules/reels/infrastructure/reel_state_repository.py:514-528` (firma con `_UNSET`), `:551-560` (resolve). Renderer emite `None` cuando hay override (`frame_composition.py:224-225`). Persist forward solo si `rendered_snapshot is not None` (`persist_local_artifacts.py:323-329`) → kwarg omitido → sentinel preserva. | OK |
| HTTP response: `AgencyReelItemPayload.publish_subtitles_snapshot` (snake_case) → front lo mapea a `publishSubtitlesSnapshot` | `modules/reels/transport/payloads/admin_reels.py:58-64`; serializer: `modules/reels/transport/http/admin_reels_assets.py:70-77` | OK |
| GET single endpoint surface | `GET /v1/admin/agencies/{id}/reels/{site}/{prop}` → `modules/reels/transport/http/admin_reels_router.py:330-369` (usa `_serialize_agency_reel(item)`). `InspectReelUseCase` reusa `list_recent_for_agency`, así que basta extender el SELECT una vez. | OK |
| GET list endpoint surface | `modules/reels/transport/http/admin_reels_router.py:316`; SELECT extendido: `modules/reels/infrastructure/reel_query.py:282` (columna), `:333-335` (mapping a `AgencyReelSummary.auto_subtitles_snapshot`) | OK |

---

## 4. Override-preservation test verdict

**Existe y prueba correctamente la preservación.**

`tests/integration/rendering/test_render_persists_auto_subtitles.py:495-623`
(`test_persist_local_artifacts_preserves_existing_snapshot_when_artifact_has_none`):

1. Pre-siembra un snapshot directamente en la columna (raw SQL).
2. Construye un `RenderedMediaArtifact(auto_subtitles_snapshot=None)`
   (escenario "render con override-set; renderer no emite cues").
3. Llama a `PersistLocalArtifactsUseCase.execute`.
4. Reabre la row vía repo → asserta que `state.auto_subtitles_snapshot
   == existing_snapshot` (lo pre-sembrado, no `None`).

Complementario: `test_renderer_emits_no_snapshot_when_override_is_set`
(`:277-297`) asserta que el artifact emite `auto_subtitles_snapshot is
None` cuando `subtitles_override` está set — el lado renderer del
contrato. Y los tests
`test_update_publish_status_preserves_auto_subtitles_snapshot`
(`tests/integration/reels/test_auto_subtitles_snapshot.py:319`) y
`test_update_workflow_state_preserves_auto_subtitles_snapshot` (`:364`)
cubren los otros dos helpers que tocan la row (`update_publish_status`
y `update_workflow_state`), garantizando que **ningún** path de
escritura clobere el snapshot accidentalmente.

Veredicto: **claim de preservación verificado en tests, no solo en
narración.**

---

## 5. Backfill recommendation

**Decisión: no-op (no backfill).**

Razones:

- Backfill genuino requeriría re-correr la pipeline Gemini contra los
  datos históricos de cada property — no-trivial y caro.
- Los reels existentes ya tienen `publish_target_snapshot.subtitles`
  almacenado en otro campo histórico (el front mapper actual
  `hooks.js:147` precisamente lee de ahí; ver sección 8 — Open items),
  así que la UI no se queda completamente sin fallback durante el
  período de transición.
- El path "natural" (manual regenerate via feature 40 o approve normal)
  popula el snapshot en cuanto el reel se re-renderiza.
- La migración mantiene la columna como `NULL` nullable, lo que es
  semánticamente correcto ("aún no se ha renderizado sin override").

Si producto quisiera repintar los snapshots históricos
inmediatamente, la vía limpia es un script one-off que itere reels con
`subtitles_override IS NULL AND render_status='completed'` y reuse
`build_auto_subtitles_snapshot` (mismo helper, sin tocar ffmpeg). No
es bloqueante; **propuesta no incluida en esta feature**.

---

## 6. Acceptance checklist

- [x] Render sin `subtitles_override` → `reels.auto_subtitles_snapshot`
      populated. (`test_renderer_emits_auto_subtitles_snapshot_when_no_override` + `test_persist_local_artifacts_writes_snapshot_when_artifact_carries_one`).
- [x] Re-ingest preserva el snapshot.
      (`test_auto_subtitles_snapshot_survives_re_ingest`).
- [x] GET single devuelve `publish_subtitles_snapshot`.
      (`test_get_reel_returns_publish_subtitles_snapshot_when_populated`,
      `test_get_reel_publish_subtitles_snapshot_is_null_when_unset`).
- [x] GET list devuelve `publish_subtitles_snapshot` por item.
      (`test_list_reels_returns_publish_subtitles_snapshot`).
- [x] Render con `subtitles_override` set → snapshot **preservado**, no
      recomputado. (`test_persist_local_artifacts_preserves_existing_snapshot_when_artifact_has_none`,
      `test_renderer_emits_no_snapshot_when_override_is_set`).
- [x] Tests integration verdes; baseline 1050 → 1063 (+13).
- [x] `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
      clean.

---

## 7. Verification re-run output tail

### Migration round-trip

```
$ .venv/bin/alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 20260515_0005 -> 20260517_0001, ...
$ .venv/bin/alembic current
20260517_0001 (head)
$ .venv/bin/alembic downgrade -1
INFO  [alembic.runtime.migration] Running downgrade 20260517_0001 -> 20260515_0005, ...
$ .venv/bin/alembic current
20260515_0005
$ .venv/bin/alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 20260515_0005 -> 20260517_0001, ...
$ .venv/bin/alembic current
20260517_0001 (head)
```

> Nota operativa: un `alembic downgrade base` directo desde head fallo
> con `ForeignKeyViolation` en una migración previa
> (`render_templates` / `agency_reel_defaults`), independiente de la
> feature 41. Reset completo del schema (`DROP SCHEMA public CASCADE`)
> seguido de `alembic upgrade head` aplicó limpio (siguiendo la regla
> de MEMORY.md "reset completo preferido sobre parches"). El up/down/up
> de la migración de feature 41 quedó verificado en la BD ya migrada.

### Targeted tests

```
$ .venv/bin/python -m pytest tests/integration/reels/test_auto_subtitles_snapshot.py \
    tests/integration/rendering/test_render_persists_auto_subtitles.py \
    tests/integration/reels/test_reel_subtitles_override.py -q
..............................                                           [100%]
30 passed in 40.24s
```

### Apps checks

```
$ .venv/bin/python -m apps.api --check
RUNTIME READY: Yes
exit=0
$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
exit=0
```

### init.sh

```
$ bash ./init.sh
...
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 1063 passed, 14 warnings in 582.01s (0:09:42)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

1063 = 1050 baseline + 13 nuevos (7 + 6). Los 3 fallos coinciden con
el set documentado como baseline-flake en reviews previos (features
32-40).

---

## 8. Issues found

### Blocking
- Ninguna.

### Non-blocking (apunta el equipo, no aplazar feature)

- **Drift de mapper en frontend.** El backend ahora ship
  `publish_subtitles_snapshot` como campo top-level en `/v1/admin/agencies/{id}/reels/...`.
  El frontend ya tiene el consumer `ReelEditor.jsx:614`
  (`reel.publishSubtitlesSnapshot`), pero el mapper en
  `/opt/projects/4Reels-Frontend/src/features/reels/hooks.js:147-151`
  hoy lee `publishSubtitlesSnapshot` desde
  `raw.publish_target_snapshot.subtitles` (un campo histórico) en vez
  de `raw.publish_subtitles_snapshot`. Hasta que el front actualice el
  mapper a leer el nuevo campo (3 líneas de cambio en `hooks.js`), el
  editor no usará los snapshots refrescados por esta feature — seguirá
  leyendo del campo histórico. La afirmación del implementer "no front
  changes are required" es **inexacta** en ese aspecto. Acción
  recomendada: abrir feature equivalente en
  `4Reels-Frontend/feature_list.json` para alinear el mapper. Backend
  no se bloquea por esto — la columna queda persistida y disponible.

- **Inconsistencia docstring vs comportamiento en `build_auto_subtitles_snapshot`.**
  El docstring del helper
  (`modules/rendering/infrastructure/layout/subtitles.py:267-272`) dice
  "we keep the raw text rather than the truncated / uppercased variant
  the renderer paints onscreen so the editor sees what the Gemini
  captioner produced verbatim", pero la implementación llama a
  `_resolve_subtitle_caption` (`:313`) → `normalize_caption` (`:43`),
  que **sí** normaliza (quita comillas, prefijos "Key features:",
  añade punto final). La decisión del implementer (sección 6.2 del
  impl_41.md) — "snapshot stores the normalised caption, not the raw
  Gemini output" — es la **correcta** para mantener la consistencia
  visual con lo que el renderer pinta. Pero el docstring del helper
  contradice eso. Limpieza no-bloqueante: ajustar el docstring para
  reflejar que se guarda el texto normalizado, no el raw.

### Nit

- Comentario `# pragma: no cover — defensive` en `_Unset.__repr__`
  (`reel_state_repository.py:31`) está bien; idem en el try/except
  defensivo de `frame_composition.py:233-242`.
- El sentinel `_UNSET` está privado al módulo
  (`reel_state_repository.py`); buen aislamiento. No expuesto.

---

## 9. Open items (verdicts on the 4 flagged by implementer)

### 9.1 Backfill
**Veredicto: no-op.** Ver sección 5. La columna queda NULL para reels
históricos; se popula naturalmente al próximo render. Si producto
prioriza repintar, abrir feature dedicada con script one-off (no
bloqueante).

### 9.2 Normalised vs raw caption text
**Veredicto: normalizado, correcto.** Coincide con lo que el renderer
pinta onscreen → el editor ve el mismo texto que la audiencia. La
asimetría (raw Gemini en otro lado, normalizado aquí) sería más
confusa. Acción: ajustar el docstring del helper (nit, sección 8) para
no contradecir la implementación.

### 9.3 Override-set preservation
**Veredicto: probado.** Ver sección 4. El claim correctness key de la
feature está cubierto por tests integration end-to-end.

### 9.4 `compute_segment_timing` edge-case drift
**Veredicto: drift aceptable.** En fps=30, el drift máximo por cue es
≤33ms (1 frame), bounded por la lógica de
`compute_segment_timing:281-289` que distribuye el remainder de frames
entre los slides (≤1 frame extra por slide en el peor caso). El
snapshot usa el `slide_duration` nominal del template, que es lo mismo
que el renderer-side `compose_subtitle_segments` consume para pintar
subtítulos onscreen → snapshot y video timing coinciden en cue boundaries.
La divergencia es entre snapshot/video y el **muxed audio fade**, no
entre snapshot y subtítulos pintados. 33ms está por debajo del umbral
de percepción humana para sincronización audio/visual de texto. **No
hay acción requerida.**

---

## 10. Cierre

Feature 41 cumple con todos los acceptance criteria del spec y respeta
el 6-point pattern de features 35/36/37. La preservación del snapshot
bajo render con override está sólidamente cubierta por tests
integration. El init.sh termina en baseline + 13 nuevos tests verdes
(1063 passed) con los 3 fallos pre-existentes ya documentados como
flakes.

**Verdict: APPROVED.**

Acciones de follow-up (no bloquean cierre):
1. Frontend: actualizar `4Reels-Frontend/src/features/reels/hooks.js:147`
   para leer `raw.publish_subtitles_snapshot` (top-level) en vez de
   `raw.publish_target_snapshot.subtitles`. Abrir feature equivalente
   en el feature_list del frontend.
2. Cleanup: ajustar el docstring de `build_auto_subtitles_snapshot`
   para reflejar que se persiste el caption normalizado, no el raw
   Gemini output.

Estos dos puntos no requieren reabrir feature 41. Se anotan aquí para
trazabilidad y se pueden abrir como features nuevas si producto las
prioriza.
