# Review: feature 19 — include_pinterest_in_reel_defaults_platforms (2026-05-14)

## Veredicto

APPROVED

## Cumplimiento de acceptance criteria

- [x] **AC1 — Nueva migración Alembic con revision_id único, downgrade reversible.**
  `alembic/versions/20260514_0001_include_pinterest_in_reel_defaults.py:50-51`
  declara `revision = "20260514_0001"` (único en `alembic/versions/`),
  `down_revision = "20260513_0005"` (encadenada tras el head anterior).
  `downgrade()` definido en `:84-91`.
- [x] **AC2 — Tras `alembic upgrade head` en BBDD limpia, un upsert de
  defaults inserta `'pinterest'` en `platforms`.**
  Verificado en `tests/integration/configuration/test_pinterest_in_reel_defaults_platforms.py:130-142`
  (`test_reel_defaults_server_default_includes_pinterest_after_migration`)
  → 3 passed en la ejecución aislada. Adicionalmente, `\d agency_reel_defaults`
  contra la BBDD post-upgrade muestra `column_default = ARRAY['tiktok'::text,
  'instagram'::text, 'linkedin'::text, 'youtube'::text, 'facebook'::text,
  'gbp'::text, 'pinterest'::text]`.
- [x] **AC3 — Data migration añade pinterest a rows legacy sin duplicar.**
  `alembic/versions/20260514_0001_include_pinterest_in_reel_defaults.py:75-81`:
  `UPDATE ... SET platforms = array_append(platforms, 'pinterest') WHERE NOT
  ('pinterest' = ANY(platforms))`. Cubierto por
  `test_data_migration_adds_pinterest_to_existing_rows` (`:145-180`) y
  `test_data_migration_preserves_existing_pinterest` (`:183-213`), ambos
  passed.
- [x] **AC4 — `alembic downgrade -1` funciona y revierte el default.**
  Ejecutado manualmente: `alembic downgrade -1` desde head pasó por
  `20260514_0001 -> 20260513_0005`, dejando el default de columna como
  el array de 6 plataformas (sin pinterest). `alembic upgrade head`
  posterior re-aplica y deja el default de 7 incluido pinterest.
  Verificado leyendo `information_schema.columns.column_default` tras
  cada paso.
- [x] **AC5 — `docs/API.md §3` lista pinterest como plataforma del default.**
  `docs/API.md:122-132`: nota nueva con el default canónico
  `["tiktok","instagram","linkedin","youtube","facebook","gbp","pinterest"]`,
  referencia a migración `20260514_0001` y explicación del downgrade.
- [x] **AC6 — `pytest -q` verde (modulo baseline).**
  `bash ./init.sh` (que incluye `pytest -q`) cerró con
  `3 failed, 669 passed, 14 warnings`. Los 3 fallos coinciden 1:1 con los
  baseline documentados por Codex (`test_http_surface_contract.py` y 2 en
  `test_http_transport.py`); ninguno introducido por feature 19.
- [x] **AC7 — `apps.api --check` y `apps.worker --check` exit 0.**
  `apps.api --check` reporta `RUNTIME READY: Yes`; `apps.worker --check`
  `kinds=reel_publish,scripted_render worker_count=1`.

## Verificación ejecutada

- `bash ./init.sh` → exit 0; `3 failed, 669 passed, 14 warnings`
  (fallos = baseline preexistente).
- `.venv/bin/python -m alembic heads` → `20260514_0002 (head)` (única
  head; `20260514_0001` queda encadenada por `20260514_0002` cuyo
  `down_revision = "20260514_0001"`).
- `.venv/bin/python -m alembic history --verbose` → cadena ordenada:
  `<base> → 20260501_0001 → 20260513_0002 → 20260513_0003 → 20260513_0004
  → 20260513_0005 → 20260514_0001 → 20260514_0002 (head)`.
- `.venv/bin/python -m alembic downgrade -1` → bajó a `20260513_0005`;
  inspección de `information_schema` confirmó que el `column_default`
  volvió al array de 6 plataformas.
- `.venv/bin/python -m alembic upgrade head` → re-aplicó
  `20260514_0001` y luego `20260514_0002`; `column_default` ahora tiene
  los 7 elementos incluyendo `pinterest`.
- `.venv/bin/python -m pytest tests/integration/configuration/test_pinterest_in_reel_defaults_platforms.py -v`
  → 3 passed.
- `.venv/bin/python -m apps.api --check` → exit 0, `RUNTIME READY: Yes`.
- `.venv/bin/python -m apps.worker --check` → exit 0.
- `grep -rnE '::jsonb|@>|platforms \|\|' alembic/versions/20260514_0001_*`
  → 0 hits (sin sintaxis JSONB residual).
- `grep -rn 'pinterest' modules/configuration/infrastructure/orm.py`
  → hit en `:89`, confirmando ORM sincronizado con la migración.

## Cadena alembic

- Estado: **una sola head** (`20260514_0002`). No hay branches.
- Orden correcto: `20260513_0005 → 20260514_0001 (feature 19) →
  20260514_0002 (hotfix Codex classic_render_template_preview)`.
- `20260514_0001.down_revision = "20260513_0005"` (correcto, encadena
  tras el head pre-feature-19).
- `20260514_0002.down_revision = "20260514_0001"` (correcto, Codex
  encadenó su hotfix encima sin romper la migración de feature 19).
- Upgrade/downgrade/upgrade roundtrip ejercitado en vivo sin errores.

## Hallazgos

1. **(fyi)** El implementer adaptó correctamente la sintaxis: la
   columna `agency_reel_defaults.platforms` es `ARRAY(Text)` (text[]),
   no JSONB. La migración usa `array_append(...)` y `'pinterest' =
   ANY(platforms)`. Sin operadores JSONB residuales (`@>`, `||`,
   `::jsonb`). Decisión correcta y bien documentada en el docstring
   de la migración.
2. **(fyi)** El `server_default` del ORM
   (`modules/configuration/infrastructure/orm.py:84-90`) coincide
   exactamente con el nuevo default de la migración: el array de 7
   plataformas incluyendo `pinterest`. Esto evita que
   `alembic --autogenerate` proponga un revert. Bien hecho.
3. **(fyi)** El docstring de la migración explica explícitamente por
   qué `downgrade()` revierte solo el `SET DEFAULT` y NO arranca
   `pinterest` de filas existentes (preservar intención de usuario;
   idempotencia del `WHERE NOT ANY` permite re-aplicar). Razonamiento
   sólido y documentado in-place (líneas 35-41 del archivo).
4. **(fyi)** Los 3 tests cubren los escenarios pedidos: server_default
   post-migración, fila legacy sin pinterest (data migration la
   actualiza), fila legacy con pinterest (no-op, sin duplicado). Los
   tests (b) y (c) re-ejecutan el SQL de la data migration en lugar de
   rebobinar Alembic — workaround razonable y semánticamente
   equivalente porque `WHERE NOT ANY` es idempotente.
5. **(fyi)** El hotfix concurrente de Codex
   (`20260514_0002_classic_render_template_preview.py`) NO pisa el
   trabajo de feature 19: encadena `down_revision = "20260514_0001"`,
   sin tocar `agency_reel_defaults` ni mover el revision id de feature
   19. La cadena alembic queda lineal con una única head.
6. **(fyi)** Los 3 fallos de pytest baseline
   (`test_http_surface_contract.py` y 2 en `test_http_transport.py`)
   son exactamente los reportados por Codex en su hotfix
   `side_banner_footer_radius`; no son regresión de feature 19.
   Conteo total `669 passed` = `665 baseline + 1 del último test de
   render_template_assets de Codex + 3 nuevos de feature 19`.
7. **(nit)** Open question del implementer (sección 5 del impl
   report): la simetría entre el server_default de la BBDD y el
   `_DEFAULT_PLATFORMS` de Python (`read_aggregated_reel_profile.py` y
   `defaults_router.py`) hoy se mantiene a mano. No es bloqueante —
   ambas tuplas ya están alineadas y la BBDD es el owner canónico —
   pero podría plantearse en una futura mini-feature un test de
   smoke que compare ambas para evitar drift silencioso. **No
   bloquea cierre de feature 19.**
8. **(fyi)** Verificación de no-tocados (mtime + grep): los archivos
   de feature 19 se editaron entre 12:36:38 y 12:37:45; `apps/api/
   app_factory.py` y los archivos de `modules/rendering/*` tienen
   mtime ≥ 12:40, consistente con que feature 19 NO los tocó (esos
   cambios corresponden a los dos hotfixes de Codex). Conforme al
   prompt original que prohibía solapamientos.

## Recomendación de cierre

- **APPROVED.** El implementer puede ahora:
  1. Marcar `feature.id=19.status = "done"` en
     `feature_list.json`.
  2. Archivar la sección "# Trabajo en paralelo — feature 19 (leader
     Claude)" de `progress/current.md` moviéndola a
     `progress/history.md`. La sección del hotfix `classic_template_preview`
     de Codex queda fuera del alcance de feature 19 — su cierre lo
     decide quien coordine la siguiente sesión.
  3. No hay pendientes técnicos. La open question sobre simetría
     ORM/Python-fallback queda como nota informativa para futura
     consolidación, no como pre-requisito de cierre.
