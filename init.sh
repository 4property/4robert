#!/usr/bin/env bash
# init.sh — Verificación e inicialización del entorno (4reels back)
#
# Este script lo ejecuta el agente al COMENZAR una sesión y antes de
# declarar cualquier tarea como `done`. Si falla, la sesión no debe avanzar.
#
# Salida esperada: códigos de salida claros y bloques marcados con [OK]/[FAIL].

set -u
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

ok()    { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
fail()  { printf "${RED}[FAIL]${NC}  %s\n" "$1"; }

EXIT_CODE=0

echo "── 1. Verificando entorno ─────────────────────────────"

# Python disponible (preferimos el del .venv, fallback al del sistema)
PYTHON=""
if [ -x ".venv/Scripts/python.exe" ]; then
  PYTHON=".venv/Scripts/python.exe"
  ok "Usando Python del venv: $PYTHON"
elif [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
  ok "Usando Python del venv: $PYTHON"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
  warn ".venv no detectado — usando python del sistema"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
  warn ".venv no detectado — usando python3 del sistema"
else
  fail "No hay python disponible"
  exit 1
fi

PY_VERSION=$("$PYTHON" --version 2>&1)
ok "$PY_VERSION"

# Versión mínima 3.11 (FastAPI 0.135 + pydantic v2 + sqlalchemy 2.0)
PY_VERSION_OK=$("$PYTHON" -c 'import sys; print(int(sys.version_info >= (3, 11)))')
if [ "$PY_VERSION_OK" != "1" ]; then
  fail "Se requiere Python >= 3.11"
  EXIT_CODE=1
fi

# Dependencias clave
"$PYTHON" -c "import fastapi, pydantic, sqlalchemy, alembic" 2>/dev/null && \
  ok "Dependencias clave importables (fastapi, pydantic, sqlalchemy, alembic)" || \
  { fail "Faltan dependencias — ejecuta 'pip install -r requirements.txt'"; EXIT_CODE=1; }

echo ""
echo "── 2. Verificando archivos base del arnés ──────────────"

for f in AGENTS.md CLAUDE.md feature_list.json progress/current.md docs/architecture.md docs/conventions.md docs/verification.md CHECKPOINTS.md; do
  if [ ! -f "$f" ]; then
    fail "Falta archivo base: $f"
    EXIT_CODE=1
  else
    ok "Existe $f"
  fi
done

echo ""
echo "── 3. Validando feature_list.json ──────────────────────"

"$PYTHON" - <<'PY'
import json, sys
try:
    data = json.load(open("feature_list.json"))
    valid = {"pending", "in_progress", "done", "blocked"}
    in_progress = [f for f in data["features"] if f["status"] == "in_progress"]
    if len(in_progress) > 1:
        print(f"[FAIL]  Hay {len(in_progress)} features en in_progress (máximo 1)")
        sys.exit(1)
    for f in data["features"]:
        if f["status"] not in valid:
            print(f"[FAIL]  Estado inválido en feature {f['id']}: {f['status']}")
            sys.exit(1)
    print(f"[OK]    feature_list.json válido ({len(data['features'])} features)")
except Exception as e:
    print(f"[FAIL]  feature_list.json inválido: {e}")
    sys.exit(1)
PY
if [ $? -ne 0 ]; then EXIT_CODE=1; fi

echo ""
echo "── 4. Verificando que no han renacido directorios legacy ─"

# Phase 2 (cierre 2026-05-06) eliminó services/, application/, repositories/,
# core/ y domain/. Si alguno reaparece, es una regresión a investigar.
LEGACY_DIRS_PRESENT=""
for legacy_dir in services application repositories core domain; do
  if [ -d "$legacy_dir" ]; then
    LEGACY_DIRS_PRESENT="$LEGACY_DIRS_PRESENT $legacy_dir"
  fi
done
if [ -n "$LEGACY_DIRS_PRESENT" ]; then
  fail "Directorios legacy reaparecidos:$LEGACY_DIRS_PRESENT"
  fail "Phase 2 los retiró el 2026-05-06; investiga la regresión."
  EXIT_CODE=1
else
  ok "Sin directorios legacy (services|application|repositories|core|domain)"
fi

# Verificación adicional: ningún import legacy sigue vivo en el árbol activo.
LEGACY_IMPORTS=$("$PYTHON" - <<'PY'
import re, sys
from pathlib import Path
root = Path(".")
pattern = re.compile(
    r"^\s*(?:from|import)\s+(?:services|application|repositories|core|domain)\."
)
hits = 0
for top in ("apps", "modules", "shared", "tests"):
    base = root / top
    if not base.exists():
        continue
    for path in base.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if pattern.match(line):
                hits += 1
                break
print(hits)
PY
)
if [ "$LEGACY_IMPORTS" -gt 0 ]; then
  fail "$LEGACY_IMPORTS archivo(s) en apps|modules|shared|tests importan de legacy."
  EXIT_CODE=1
else
  ok "0 imports legacy en apps|modules|shared|tests"
fi

echo ""
echo "── 5. Ejecutando readiness checks ──────────────────────"

if "$PYTHON" -m apps.api --check >/dev/null 2>&1; then
  ok "apps.api --check verde"
else
  warn "apps.api --check falló (puede ser por config/.env, revisa manualmente)"
fi

if "$PYTHON" -m apps.worker --check >/dev/null 2>&1; then
  ok "apps.worker --check verde"
else
  warn "apps.worker --check falló (puede ser por config/.env, revisa manualmente)"
fi

echo ""
echo "── 6. Ejecutando tests ─────────────────────────────────"

if [ -d "tests" ]; then
  if "$PYTHON" -m pytest -q --no-header 2>&1 | tee /tmp/harness_pytest.log | tail -10; then
    ok "pytest verde"
  else
    # pytest devuelve != 0 también si hay deselects; comprobamos el último resumen
    if grep -E "^(=+ )?[0-9]+ passed" /tmp/harness_pytest.log >/dev/null 2>&1 && \
       ! grep -E "[0-9]+ failed" /tmp/harness_pytest.log >/dev/null 2>&1; then
      ok "pytest verde (con deselects/skips)"
    else
      fail "Hay tests rotos — revisa /tmp/harness_pytest.log"
      EXIT_CODE=1
    fi
  fi
else
  fail "Carpeta tests/ no existe"
  EXIT_CODE=1
fi

echo ""
echo "── 7. Resumen ──────────────────────────────────────────"

if [ $EXIT_CODE -eq 0 ]; then
  ok "Entorno listo. Puedes empezar a trabajar."
else
  fail "Entorno NO está listo. Resuelve los errores antes de avanzar."
fi

exit $EXIT_CODE
