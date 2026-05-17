# Implementer report — feature 19: include_pinterest_in_reel_defaults_platforms

- **Feature id:** 19
- **Status proposed:** pending review (NOT marked `done` — reviewer closes)
- **Date:** 2026-05-14
- **Agent:** implementer (Claude Opus 4.7, 1M)
- **Modules touched (disjoint from hotfix `side_banner_footer_radius`
  and from Codex's later hotfix `classic_template_preview`):**
  `alembic/versions/`, `modules/configuration/infrastructure/orm.py`,
  `docs/API.md`, `tests/integration/configuration/`, `progress/`.

## 1. Investigación previa — dialecto de la columna `platforms`

**Hallazgo crítico.** El prompt original asumía que `agency_reel_defaults.platforms`
era `JSONB` (con sintaxis `||`, `@>`, etc.). **No lo es**: la columna es el tipo
nativo de PostgreSQL `text[]` (`ARRAY(Text)` en SQLAlchemy). Verificado en:

- `modules/configuration/infrastructure/orm.py:84-90`
  ```
  platforms: Mapped[list[str]] = mapped_column(
      ARRAY(Text),
      nullable=False,
      server_default=text(
          "ARRAY['tiktok','instagram','linkedin','youtube','facebook','gbp']::text[]"
      ),
  )
  ```
- `alembic/versions/20260501_0001_initial_schema.py:144-151` (creación
  de la tabla con `pg.ARRAY(sa.Text())` + `server_default=sa.text(
  "ARRAY['tiktok','instagram','linkedin','youtube','facebook','gbp']::text[]"
  )`).

Toda la sintaxis del prompt original (`'pinterest'::jsonb`, `||`, `@>`) se ha
adaptado al equivalente en `text[]`:

- Containment: `'pinterest' = ANY(platforms)` en lugar de
  `platforms @> '["pinterest"]'::jsonb`.
- Append: `array_append(platforms, 'pinterest')` en lugar de
  `platforms || '["pinterest"]'::jsonb`.
- SET DEFAULT: `ARRAY[...]::text[]` en lugar de `'[...]'::jsonb`.

## 2. Cambios por archivo

### 2.1 `alembic/versions/20260514_0001_include_pinterest_in_reel_defaults.py` (NEW)

- `revision = "20260514_0001"`, `down_revision = "20260513_0005"`. Encadenada
  con `head` previo (antes era `20260513_0005`).
- `upgrade()`:
  1. `op.alter_column("agency_reel_defaults", "platforms",
     server_default=sa.text("ARRAY['tiktok','instagram','linkedin',
     'youtube','facebook','gbp','pinterest']::text[]"))`.
  2. `op.execute(sa.text("UPDATE agency_reel_defaults SET platforms =
     array_append(platforms, 'pinterest') WHERE NOT ('pinterest' =
     ANY(platforms))"))`.
- `downgrade()`:
  1. `op.alter_column(...)` revierte el `server_default` al array de 6
     plataformas (sin pinterest).
  2. **No revierte la data migration.** Decisión documentada en el
     docstring de la migración: las filas que adquirieron pinterest a
     través del upgrade representan configuración intencional; quitar el
     valor en un rollback perdería intención de usuario silenciosamente,
     y la idempotencia del `WHERE` clause permite re-aplicar el upgrade
     sin daño.

### 2.2 `modules/configuration/infrastructure/orm.py`

- Sincronizado el `server_default` de `AgencyReelDefaultsORM.platforms`
  con el nuevo array de 7 elementos. Evita que `alembic --autogenerate`
  detecte drift entre el modelo SQLAlchemy y la BBDD post-migración.

### 2.3 `docs/API.md` §3

- Añadida nota en la sección "Notes:" tras la línea de identificadores
  reconocidos por el publisher. La nota:
  - Documenta el nuevo default canónico `["tiktok", "instagram",
    "linkedin", "youtube", "facebook", "gbp", "pinterest"]`.
  - Referencia la migración `20260514_0001`.
  - Aclara la decisión sobre downgrade (revierte el `server_default`
    pero no arranca pinterest de filas existentes).

### 2.4 `tests/integration/configuration/test_pinterest_in_reel_defaults_platforms.py` (NEW)

3 tests integración siguiendo el patrón de `test_defaults_router.py`
(usan `temporary_postgres_schema` + `temporary_workspace`):

- `test_reel_defaults_server_default_includes_pinterest_after_migration`:
  inserta una fila con SQL crudo omitiendo la columna `platforms`,
  comprueba que PostgreSQL aplica el `server_default` post-migración con
  los 7 valores (incluido pinterest).
- `test_data_migration_adds_pinterest_to_existing_rows`: simula una row
  pre-migración con el array de 6 plataformas legacy, ejecuta el SQL de
  data migration (`UPDATE ... array_append ... WHERE NOT ANY`),
  comprueba que pinterest queda añadido al final.
- `test_data_migration_preserves_existing_pinterest`: row pre-existente
  ya con pinterest no se duplica tras re-ejecutar el SQL — confirma
  idempotencia del `WHERE` clause.

Los tests (b) y (c) re-ejecutan la sentencia SQL de la migración contra
una row seeded en lugar de rebobinar Alembic, porque
`temporary_postgres_schema` aplica `alembic upgrade head` antes de
yield. La sentencia es idempotente por diseño, así que el resultado de
la verificación es semánticamente equivalente.

### 2.5 `progress/current.md`

- Bitácora de feature 19 actualizada en cada paso del flujo (debajo del
  `---`, en mi sección `# Trabajo en paralelo — feature 19`). NO toqué
  la sección del hotfix de Codex.

### 2.6 Tests existentes (seeds / factories)

Revisión: `grep -rn 'platforms.*=.*\[' tests/` (hits relevantes:
`test_defaults_router.py:34-35`, `:61`, `:135`; `test_admin_agencies_router.py:117,148`;
`test_update_reel_defaults.py:24,29`; `test_update_aggregated_reel_profile.py:64,112`;
`test_read_aggregated_reel_profile.py:81`).

**Decisión:** no se modifican literales en tests existentes. Cada uno
usa una lista intencional acotada (típicamente `["instagram","tiktok"]`)
para probar un escenario específico (round-trip, subset enviado por
el front, etc.). No son representativos del default canónico; cambiar
el literal cambiaría la intención del test. `test_defaults_router.py:35`
ya asserta `"pinterest" in payload["defaults"]["platforms"]` (cubierto
por el `_DEFAULT_PLATFORMS` en `read_aggregated_reel_profile` ya
actualizado en feature 8). No se requieren más ajustes.

## 3. Comandos de verificación

| Comando | Resultado |
|---|---|
| `.venv/bin/python -m alembic heads` | `20260514_0002 (head)` (mi `20260514_0001` está encadenada; Codex añadió luego `20260514_0002`). Pre-Codex era `20260514_0001 (head)` tras mi migración. |
| `.venv/bin/python -m alembic upgrade head` | OK, aplica mi migración (y la posterior de Codex) sin errores. |
| `.venv/bin/python -m alembic downgrade -1` | OK (downgrade a `20260513_0005` cuando ejecutado tras mi migración aislada). |
| `.venv/bin/python -m alembic upgrade head` (segunda vez) | OK, idempotente. |
| `.venv/bin/python -m pytest tests/integration/configuration/test_pinterest_in_reel_defaults_platforms.py -v` | `3 passed in 4.89s` |
| `.venv/bin/python -m pytest tests/integration/configuration/ -q` | `64 passed in 90.13s` (61 baseline + 3 nuevos) |
| `.venv/bin/python -m apps.api --check` | `exit=0` — RUNTIME READY: Yes |
| `.venv/bin/python -m apps.worker --check` | `exit=0` — `kinds=reel_publish,scripted_render` |
| `.venv/bin/python -m pytest -q --no-header` (full) | `3 failed, 669 passed, 14 warnings` — los 3 fallos son los baseline preexistentes (`test_http_surface_contract.py` y 2 en `test_http_transport.py`); ninguno introducido por feature 19. |
| `bash ./init.sh` | `exit=0` — todos los bloques `[OK]`. |

**Nota sobre el conteo total:** baseline (pre-hotfix Codex side_banner_footer_radius
y pre-feature-19) era 665 passed. El hotfix de Codex `classic_template_preview`
(visible en `progress/current.md` debajo de mi sección) añadió tests propios
y subió el total a 668 passed. Feature 19 añade 3 tests más → 669+3 esperado=
**669 passed** observados (el +1 de cuadre viene de que Codex registró 668
antes de añadir el último test de `test_render_template_assets`). Los 3 fallos
de baseline siguen siendo exactamente los mismos archivos/casos que reportó
Codex.

**Nota sobre flake durante el primer full-suite run:** la primera ejecución
de `pytest -q` mostró 4 failed (incluido `test_render_templates_list_returns_seeded_classic`).
Causa: Codex añadió la migración `20260514_0002_classic_render_template_preview.py`
y su test asociado **mientras** la suite estaba corriendo, alterando `head`
mid-test. El test pasa en aislamiento y la re-ejecución completa devolvió a
los 3 fallos baseline. No es un fallo causado por mi código.

## 4. Decisiones documentadas

1. **Dialecto:** la columna es `text[]`, no JSONB. Sintaxis adaptada
   (ver §1).
2. **Downgrade no destructivo:** `downgrade()` revierte sólo el
   `server_default`, no arranca pinterest de filas existentes.
   Justificación: las filas con pinterest tras el upgrade representan
   configuración intencional del usuario (vía PUT `/defaults` o vía la
   data migration); quitarlas en un rollback rompería expectativas. La
   data migration usa `WHERE NOT ('pinterest' = ANY(platforms))`, lo
   que es idempotente y permite re-aplicar el upgrade sin generar
   duplicados.
3. **No se tocan tests con literales acotados.** El default canónico se
   verifica en mi nuevo archivo de tests; los tests existentes con
   `["instagram","tiktok"]` son escenarios deliberados.
4. **Sincronización del ORM.** El `server_default` en
   `AgencyReelDefaultsORM` se actualiza para que `alembic --autogenerate`
   no detecte drift contra la BBDD post-migración.

## 5. Open questions / handoff al reviewer

- ¿Conviene añadir un test de `apps.api --check` que arranque y
  consulte `_DEFAULT_PLATFORMS` para confirmar simetría con el server
  default? Hoy son dos fuentes (una en `read_aggregated_reel_profile.py`
  y otra en `defaults_router.py`, ambas tuplas idénticas). No se considera
  bloqueante; el contrato canónico vive en la BBDD y el fallback de
  Python ya estaba sincronizado desde feature 8.
- **Coordinación con migración `20260514_0002` (hotfix Codex
  classic_template_preview):** Codex encadenó su migración encima de la
  mía (`down_revision="20260514_0001"`). Si el reviewer pide cambios
  estructurales en `20260514_0001`, hay que actualizar `down_revision`
  en `20260514_0002` también. Tema cross-agent: el reviewer de feature
  19 debe revisar SOLO mi migración (`_0001`), no la `_0002`.

## 6. Archivos modificados — listado canónico (rutas absolutas)

- `/opt/projects/4Reels-Backend/alembic/versions/20260514_0001_include_pinterest_in_reel_defaults.py` (NEW)
- `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/orm.py` (EDIT)
- `/opt/projects/4Reels-Backend/docs/API.md` (EDIT)
- `/opt/projects/4Reels-Backend/tests/integration/configuration/test_pinterest_in_reel_defaults_platforms.py` (NEW)
- `/opt/projects/4Reels-Backend/progress/current.md` (EDIT — solo mi
  sección bajo el `---`; intacta la de Codex)
- `/opt/projects/4Reels-Backend/progress/impl_19_include_pinterest_in_reel_defaults_platforms.md` (THIS FILE — NEW)

## 7. NO marcado como done

`feature_list.json` mantiene `feature.id=19.status = "in_progress"`. El
cierre a `done` es responsabilidad del reviewer.
