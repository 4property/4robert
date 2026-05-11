# AGENTS.md — Mapa de navegación para agentes de IA (`4reels back/`)

> Este archivo es el **punto de entrada** para cualquier agente que trabaje
> en el backend de 4reels. NO es una biblia de reglas: es un **mapa**. Lee
> solo lo que necesites cuando lo necesites (divulgación progresiva).

---

## 1. Antes de empezar (obligatorio)

### Nota Windows 11 / PowerShell

Este workspace se ejecuta normalmente en Windows 11 con PowerShell. En ese
entorno `./init.sh` es un script Bash y puede fallar aunque el repo este bien,
por ejemplo con `execvpe(/bin/bash) failed: No such file or directory` si no
hay WSL/Git Bash disponible. Si `bash ./init.sh` falla por falta de Bash, no
lo trates como fallo de producto: ejecuta este equivalente PowerShell desde
`4reels back/` y exige el mismo resultado verde antes de tocar codigo o cerrar
una feature:

```powershell
$ErrorActionPreference = "Stop"

$PYTHON = if (Test-Path ".\.venv\Scripts\python.exe") {
  ".\.venv\Scripts\python.exe"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  "python"
} else {
  throw "No hay python disponible"
}

& $PYTHON --version
& $PYTHON -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
& $PYTHON -c "import fastapi, pydantic, sqlalchemy, alembic"

$required = @(
  "AGENTS.md",
  "CLAUDE.md",
  "feature_list.json",
  "progress/current.md",
  "docs/architecture.md",
  "docs/conventions.md",
  "docs/verification.md",
  "CHECKPOINTS.md"
)
$missing = $required | Where-Object { -not (Test-Path $_) }
if ($missing) { throw "Faltan archivos base: $($missing -join ', ')" }

$data = Get-Content -Raw feature_list.json | ConvertFrom-Json
$valid = @("pending", "in_progress", "done", "blocked")
$invalid = @($data.features | Where-Object { $_.status -notin $valid })
if ($invalid.Count -gt 0) {
  throw "feature_list.json tiene estados invalidos: $($invalid.id -join ', ')"
}
$inProgress = @($data.features | Where-Object { $_.status -eq "in_progress" })
if ($inProgress.Count -gt 1) {
  throw "Hay mas de una feature en in_progress"
}

$legacyDirs = @("services", "application", "repositories", "core", "domain") |
  Where-Object { Test-Path $_ -PathType Container }
if ($legacyDirs) {
  throw "Directorios legacy reaparecidos: $($legacyDirs -join ', ')"
}

$legacyImportPattern = "^\s*(from|import)\s+(services|application|repositories|core|domain)\."
$legacyImports = Get-ChildItem apps, modules, shared, tests -Recurse -File -Filter "*.py" |
  Select-String -Pattern $legacyImportPattern
if ($legacyImports) {
  $legacyImports
  throw "Imports legacy encontrados"
}

& $PYTHON -m apps.api --check
& $PYTHON -m apps.worker --check
& $PYTHON -m pytest -q --no-header
```

1. Ejecuta `./init.sh` (o el equivalente PowerShell anterior si estas en
   Windows 11 sin Bash) y verifica que termina sin errores. Si falla por otra
   causa, **para** y resuelve el entorno antes de tocar código.
2. Lee `progress/current.md` para entender en qué estado quedó la última
   sesión.
3. Lee `feature_list.json` y elige **una** tarea con estado `pending`. No
   trabajes en más de una a la vez. **Phase 2 está cerrada (feature 18
   aprobada el 2026-05-06).** La fase activa es Phase 3 — URL rename
   closeout + frontend lockstep (4 features, alcance reducido; ver
   `REFACTOR_STATUS.md` § Phase 3).
4. Si la feature pertenece a Phase 3, lee también
   `docs/phase_3_operating_rules.md` (override autoritativo: si choca
   con `feature_list.json`, gana el doc).
   `docs/phase_2_operating_rules.md` queda como referencia histórica
   (no aplica como override).
5. Si la feature de Phase 3 ya tiene un spike en
   `progress/explore_feature_<id>_*.md`, léelo antes de tocar código.
   Las features 2 y 3 de Phase 3 son cross-repo: lee también
   `4reels front/feature_list.json` y abre la entrada equivalente en
   el front antes de modificar nada allí. (Los informes
   `progress/explore_router_<id>_*.md` son de Phase 2; ya cerrados.)

## 2. Mapa del repositorio

### Arnés (este conjunto de archivos)

| Archivo / carpeta            | Qué contiene                                              | Cuándo leerlo |
|------------------------------|-----------------------------------------------------------|---------------|
| `feature_list.json`          | Lista de tareas con estado (pending / in_progress / done) | Siempre, al empezar |
| `progress/current.md`        | Estado de la sesión actual                                | Siempre, al empezar |
| `progress/history.md`        | Bitácora append-only de sesiones anteriores               | Si necesitas contexto histórico |
| `docs/architecture.md`       | Estándar de arquitectura del back                         | Antes de implementar |
| `docs/conventions.md`        | Estilo Python, naming, errores                            | Antes de escribir código |
| `docs/verification.md`       | Cómo verificar que tu trabajo funciona                    | Antes de declarar `done` |
| `CHECKPOINTS.md`             | Criterios objetivos de "estado final correcto"            | Para auto-evaluarte |
| `.claude/agents/`            | Definiciones de subagentes (leader, implementer, reviewer) | Si orquestas trabajo |

### Documentación del proyecto (autoritativa, anterior al arnés)

| Archivo                      | Qué contiene                                              |
|------------------------------|-----------------------------------------------------------|
| `ARCHITECTURE.md`            | Capas reales, módulos, schema, UoW, API/worker split.     |
| `REFACTOR_STATUS.md`         | Estado de la migración Phase 1 → Phase 2 → Phase 3.       |
| `README.md`                  | Setup, comandos, runtime folders.                         |
| `.env.example`               | Variables de entorno documentadas.                        |

Si `docs/architecture.md` (arnés) y `ARCHITECTURE.md` (proyecto) entran en
conflicto, **gana `ARCHITECTURE.md`**: el arnés es un resumen operativo, el
documento del proyecto es la fuente de verdad.

### Código

| Carpeta                      | Qué contiene                                                   |
|------------------------------|----------------------------------------------------------------|
| `apps/api/`                  | Proceso FastAPI (HTTP only, sin loop de worker).               |
| `apps/worker/`               | Proceso worker (job dispatcher, `SELECT … FOR UPDATE SKIP LOCKED`). |
| `modules/<bc>/domain/`       | Value objects puros, sin SQLAlchemy.                           |
| `modules/<bc>/application/`  | Use cases, un verbo-recurso por archivo.                       |
| `modules/<bc>/infrastructure/` | Repositorios SQLAlchemy + clientes externos.                 |
| `modules/<bc>/transport/`    | Routers FastAPI + payloads Pydantic.                           |
| `shared/db/`                 | `engine`, `session`, `uow`, `repository_base`, `security`.     |
| `shared/{errors,observability,locking,crypto,storage,media_cleanup}/` | Cross-cutting. |
| `settings/`                  | Config dividida por concern.                                   |
| `alembic/versions/`          | Migraciones (hoy una sola: `20260501_0001_initial_schema.py`). |
| `tests/{unit,integration,support}/` | Tests + helpers de Postgres.                            |

### Código legacy en transición

**Phase 2 cerrada el 2026-05-06.** Los directorios `services/`,
`application/`, `repositories/`, `core/`, `domain/` se eliminaron por
completo. Toda la lógica vive en `apps/`, `modules/<bc>/` y `shared/`.
Cualquier import legacy `from services.|from application.|from
repositories.|from core.|from domain.` es una regresión a corregir.

## 3. Reglas duras (no negociables)

- **Una sola feature a la vez.** No mezcles cambios de varias tareas en la
  misma sesión.
- **No declares una tarea `done` sin pruebas verdes.** Ejecuta `./init.sh`
  y asegúrate de que `pytest -q` pasa al 100%. La baseline tras Phase 2 es
  394 tests verdes (post-feature-18; ver `REFACTOR_STATUS.md`). Cualquier
  feature nueva debe añadir tests, no quitar. Si introduces un fallo
  intermitente, no lo marques como flake — repróduce y corrige.
- **Respeta las reglas inter-módulo:** un módulo puede importar de
  `shared/` y de `<otro_módulo>.domain`, **nunca** de `<otro_módulo>.application`
  ni `<otro_módulo>.infrastructure`. La composición vive en
  `apps/api/app_factory.py` o `apps/worker/runtime.py`.
- **No edites el schema sin migración.** Si tocas `shared/db/orm.py`,
  añade la `alembic revision --autogenerate -m "<msg>"` y revisa el SQL.
- **Documenta lo que haces** en `progress/current.md` mientras trabajas,
  no al final.
- **Deja el repositorio limpio** antes de cerrar la sesión (ver §5).
- **Si no sabes algo, busca en `ARCHITECTURE.md`, `docs/` o
  `REFACTOR_STATUS.md`** antes de inventarlo.

## 4. Cómo elegir una tarea

```
1. Abre feature_list.json
2. Filtra por status == "pending"
3. Coge la de menor "id" (o la marcada como prioritaria por el leader)
4. Cambia su status a "in_progress" y guarda
5. Anota en progress/current.md: feature, hora de inicio, plan breve
```

## 5. Cierre de sesión (lifecycle)

Antes de terminar:

1. Ejecuta `./init.sh` — todo verde. En Windows 11 sin Bash, ejecuta el
   equivalente PowerShell de la nota inicial y documenta en
   `progress/current.md` que `init.sh` no pudo arrancar por falta de Bash.
2. Si la tarea está acabada y aprobada por el `reviewer`: marca
   `status: "done"` en `feature_list.json`.
3. Mueve el resumen de `progress/current.md` al final de
   `progress/history.md`.
4. Vacía `progress/current.md` dejando solo la plantilla.
5. No dejes archivos temporales (`.tmp_*`, `.tmp_test_cases/`,
   `__pycache__/` fuera del `.gitignore`), ni `print()` de debug, ni
   TODOs sin contexto.
6. Si añadiste una migración Alembic: comprueba que `alembic upgrade head`
   y `alembic downgrade -1` funcionan en una DB limpia.

## 6. Si te bloqueas

- Relee la sección relevante de `ARCHITECTURE.md` o `docs/`.
- Si la herramienta no hace lo que esperas, **no inventes un workaround**:
  documenta el bloqueo en `progress/current.md` con estado `blocked` en
  `feature_list.json` y para la sesión.
