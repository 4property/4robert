# CHECKPOINTS — Evaluación del estado final (`4reels back/`)

> En sistemas multi-agente no se evalúa el camino, se evalúa el destino.
> Estos son los checkpoints objetivos que un juez (humano o IA) puede usar
> para decidir si el backend está sano tras una sesión.

## C1 — El arnés está completo

- [ ] Existen los archivos base: `AGENTS.md`, `CLAUDE.md`, `init.sh`,
      `feature_list.json`, `progress/current.md`.
- [ ] Existen los 3 docs: `docs/architecture.md`, `docs/conventions.md`,
      `docs/verification.md`.
- [ ] `./init.sh` termina con exit code 0.

## C2 — El estado es coherente

- [ ] Como mucho una feature en `in_progress` en `feature_list.json`.
- [ ] Toda feature `done` tiene tests asociados que pasan.
- [ ] `progress/current.md` está vacío o describe la sesión activa
      (no contiene basura de sesiones anteriores).
- [ ] `progress/history.md` tiene una entrada por la última sesión cerrada.

## C3 — El código respeta la arquitectura

- [ ] Ningún archivo bajo `modules/<X>/` importa de
      `modules/<Y>/application` o `modules/<Y>/infrastructure` para
      `X != Y`. La composición vive en `apps/api/app_factory.py` o
      `apps/worker/runtime.py`.
- [ ] Ningún archivo bajo `modules/<X>/domain/` importa SQLAlchemy.
- [ ] Repositorios extienden `shared/db/repository_base.py::ModuleRepository`
      y reciben `Session` por DI; **no llaman `commit()`** por su cuenta.
- [ ] Secrets que se persisten van por `shared/db/security.py` (Fernet),
      no en plano.
- [ ] No hay código nuevo en `services/`, `application/`, `repositories/`,
      `core/`, `domain/` (legacy en transición). Solo modificaciones para
      mantener compat shims.

## C4 — La verificación es real

- [ ] `tests/` tiene cobertura para los use cases nuevos (al menos un test
      unit + uno integration cuando aplica).
- [ ] Tests de integración usan los helpers de `tests/support/postgres.py`
      (no mockean Postgres).
- [ ] `pytest -q` muestra > 0 tests y todos verdes (baseline post Phase 1:
      116 tests). Si algún test es intermitente, se reproduce y se corrige
      antes de cerrar — no se acepta como flake conocido.
- [ ] `python -m apps.api --check` y `python -m apps.worker --check`
      terminan en exit code 0.

## C5 — Schema y migraciones coherentes

- [ ] Si se modificó `shared/db/orm.py`, hay una nueva migración Alembic
      en `alembic/versions/`.
- [ ] `alembic upgrade head` aplica limpio sobre una DB vacía.
- [ ] `alembic downgrade -1` es reversible (o tiene comentario explicando
      por qué no, p. ej. una columna añadida con backfill destructivo).
- [ ] Las renames documentadas en `ARCHITECTURE.md` siguen vigentes
      (no se han reintroducido nombres legacy).

## C6 — La sesión se cerró bien

- [ ] No hay archivos sin trackear sospechosos (`*.tmp`, `.tmp_debug*/`,
      `.tmp_test_cases/`, `__pycache__/` fuera del `.gitignore`).
- [ ] La última feature trabajada está reflejada en su estado correcto en
      `feature_list.json`.
- [ ] No hay `print()` de debug ni TODOs sin contexto.
- [ ] No se han colado credenciales en `.env.example` (el `.env` real
      nunca se commitea).

---

**Cómo usar este archivo:** un agente revisor (`.claude/agents/reviewer.md`)
recorre cada checkbox, marca `[x]` o `[ ]`, y rechaza el cierre de sesión
si quedan boxes vacíos en C1-C6.
