# AGENTS.md — Mapa de navegación para agentes de IA (`/opt/projects/4Reels-Backend`)

> Este archivo es el **punto de entrada** para cualquier agente que trabaje
> en el backend de 4Reels. NO es una biblia de reglas: es un **mapa**. Lee
> solo lo que necesites cuando lo necesites (divulgación progresiva).
>
> **Repos en disco:**
> - Backend (este): `/opt/projects/4Reels-Backend`
> - Frontend: `/opt/projects/4Reels-Frontend`
> - Producción legacy en :8000 (otro código fuente): `/opt/reels` — ver §7.

---

## 1. Antes de empezar (obligatorio)

### Nota Windows 11 / PowerShell (legado, host actual = Linux)

Este repo se desarrolló inicialmente en Windows 11 con PowerShell. En ese
entorno `./init.sh` es un script Bash y puede fallar aunque el repo este bien,
por ejemplo con `execvpe(/bin/bash) failed: No such file or directory` si no
hay WSL/Git Bash disponible. **El host actual es Linux (Rocky)**: `./init.sh`
funciona directamente y deberías usar esa vía. Si por algún motivo trabajas
en Windows sin Bash, ejecuta este equivalente PowerShell desde
`/opt/projects/4Reels-Backend` (o el path equivalente en Windows) y exige el
mismo resultado verde antes de tocar codigo o cerrar una feature:

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

1. Ejecuta `./init.sh` (o el equivalente PowerShell anterior si estás en
   Windows 11 sin Bash) y verifica que termina sin errores. Si falla por otra
   causa, **para** y resuelve el entorno antes de tocar código.
2. Lee `progress/current.md` para entender en qué estado quedó la última
   sesión.
3. Lee `feature_list.json`. **Estado actual: Phases 1-4 cerradas; sin fase
   activa.** Las 5 features registradas están en `done` y no se reabren. Hay
   dos vías de trabajo válidas:
   - **(a) Feature nueva**: el usuario la añade con `status: pending` y
     sigues el flujo `leader → implementer → reviewer` normal (una a la vez).
   - **(b) Hotfix**: el usuario incluye la palabra `hotfix` en su mensaje y
     puedes saltarte el protocolo (ver `CLAUDE.md` §Hotfix). Documenta el
     hotfix con prefijo `HOTFIX:` en `progress/current.md`.
   - Si no hay feature `pending` ni la palabra `hotfix`, asume que la sesión
     es de lectura/exploración y responde directamente.
4. Las reglas operativas de Phase 3 (`docs/phase_3_operating_rules.md`) y
   Phase 4 (`docs/phase_4_operating_rules.md`) son **post-mortem**, no
   override. Léelas como contexto histórico, no como reglas activas.
5. Si arrancas una feature cross-repo, abre la entrada equivalente en
   `/opt/projects/4Reels-Frontend/feature_list.json` con el mismo `id` antes
   de tocar código allí. Los `progress/explore_*` previos son histórico (de
   Phase 2/3/4 ya cerradas).

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

## 7. Runtime y servicios systemd (host actual: Linux Rocky)

> Este SaaS corre con **dos despliegues distintos** en este host. Antes de
> reiniciar nada, asegúrate de qué deploy estás tocando: producción y test
> son **dos repos diferentes**, no dos despliegues del mismo código.

### Mapa de servicios

| Servicio systemd            | Puerto | Repo / código fuente                  | Usuario   | Estado típico    |
|-----------------------------|--------|---------------------------------------|-----------|------------------|
| `reels.service`             | 8000   | `/opt/reels/` (repo `4property/4robert`, branch `ghl`) | `4robert` | producción, `active` |
| `reels-test.service`        | 8001   | `/opt/projects/4Reels-Backend` (este) | `support` | test, hoy `inactive` (se arranca a mano) |
| `reels-test-worker.service` | —      | `/opt/projects/4Reels-Backend` (este) | `support` | test worker, dispatcher de jobs |

**Implicaciones críticas:**

- :8000 es **producción** y **NO comparte código** con este repo. Cualquier
  cambio en `/opt/projects/4Reels-Backend` que quieras llevar a producción
  requiere portarlo manualmente al repo `/opt/reels` — no hay deploy
  automático. Reiniciar `reels.service` **no** refleja cambios hechos aquí.
- :8001 es el entorno de test/staging que apunta el frontend dev y el proxy
  público `https://4reelsback-test.4property.com`. Es el deploy "vivo" de
  este repo.
- Hoy (2026-05-14) el proceso real en :8001 está lanzado a mano con `nohup`
  (PID escrito a `logs/test-api-8001.pid`), no por systemd. El servicio
  `reels-test.service` existe pero está `inactive`.

### Comandos de reinicio

> Todos los `systemctl` requieren `sudo`. Claude **no debe ejecutarlos por
> su cuenta** salvo en sesión de `hotfix` y, aun así, **nunca toca
> `reels.service` (producción) sin confirmación explícita del usuario en el
> mismo turno**. Para producción, normalmente solo informa el comando y
> deja que el usuario lo ejecute.

#### API de test (:8001)

Hay dos modos. Usa el que coincida con cómo está arrancado ahora mismo
(comprueba con `ss -ltnp | grep 8001` y `systemctl is-active reels-test.service`):

**Modo systemd** (preferido si el servicio está activo):

```bash
sudo systemctl restart reels-test.service
sudo systemctl status  reels-test.service --no-pager
journalctl -u reels-test.service -n 50 --no-pager
```

**Modo manual** (lo que hay corriendo hoy en este host):

```bash
cd /opt/projects/4Reels-Backend
# Parar el proceso actual (PID en logs/test-api-8001.pid)
kill "$(cat logs/test-api-8001.pid)" 2>/dev/null || true
# Esperar a que libere el puerto
until ! ss -ltn | grep -q ':8001 '; do sleep 1; done
# Relanzar
nohup .venv/bin/python -m apps.api > logs/test-api-8001.log 2>&1 &
echo $! > logs/test-api-8001.pid
# Health check
sleep 2 && curl -fsS http://127.0.0.1:8001/health
```

#### Worker de test

Mismo dilema: o bien por systemd o bien manual.

**Modo systemd**:

```bash
sudo systemctl restart reels-test-worker.service
sudo systemctl status  reels-test-worker.service --no-pager
tail -n 50 /opt/projects/4Reels-Backend/logs/test-worker.log
```

⚠️ Aviso: en este host `reels-test-worker.service` está actualmente en bucle
de fallo (`status=209/STDOUT`, "Permission denied" al escribir
`logs/test-worker.log` por colisión con `ProtectSystem=strict`). Si vas a
depender del modo systemd, primero hay que arreglar permisos del log y/o
relajar `ReadWritePaths` para incluir `logs/`.

**Modo manual** (lo que hay corriendo hoy):

```bash
cd /opt/projects/4Reels-Backend
# Encontrar y parar el worker manual
pkill -f '.venv/bin/python -m apps.worker' || true
# Esperar a que muera
until ! pgrep -f 'apps.worker' >/dev/null; do sleep 1; done
# Relanzar
nohup .venv/bin/python -m apps.worker > logs/test-worker.log 2>&1 &
echo $! > logs/test-worker.pid
```

#### Producción (:8000) — solo con confirmación explícita

```bash
sudo systemctl restart reels.service
sudo systemctl status  reels.service --no-pager
journalctl -u reels.service -n 50 --no-pager
```

Recordatorio: el código vive en `/opt/reels/`, NO en `/opt/projects/4Reels-Backend`.

### Verificación post-reinicio

```bash
# Test
curl -fsS http://127.0.0.1:8001/health
# Producción
curl -fsS http://127.0.0.1:8000/health
```

Respuesta esperada: `{"status":"ready","dispatcher_accepting_jobs":true}`.
