# Verificación — Cómo demostrar que el trabajo funciona (`/opt/projects/4Reels-Backend`)

> Regla de oro: **el agente no dice "funciona", lo demuestra**.
> Toda feature termina con evidencia ejecutable, no con afirmaciones.

## Niveles de verificación

### Nivel 1 — Tests unitarios (obligatorio)

Toda función pública nueva en `modules/<bc>/application/` o
`modules/<bc>/domain/` tiene al menos un test en `tests/unit/<bc>/` que:

1. Cubre el camino feliz.
2. Cubre al menos un camino de error si la función puede fallar.
3. No depende de Postgres, ffmpeg ni de la red — usa fakes o stubs.

Comando:
```bash
.venv/Scripts/python -m pytest tests/unit -q
```

### Nivel 2 — Tests de integración (obligatorio si toca DB o HTTP)

Las features que tocan Postgres o exponen un endpoint se verifican
contra una base real provisionada por los helpers de
`tests/support/postgres.py`:

```python
from tests.support.postgres import seed_tenant, seed_provider_connection

def test_publish_reel_writes_outbox_event(postgres_session):
    agency = seed_tenant(postgres_session, slug="acme")
    seed_provider_connection(
        postgres_session,
        agency_id=agency.agency_id,
        provider="gohighlevel",
    )
    # ...act + assert
```

Comando:
```bash
.venv/Scripts/python -m pytest tests/integration -q
```

### Nivel 3 — Readiness checks (obligatorio antes de cerrar)

Los procesos exponen un modo `--check` que no abre socket: solo valida
que la config carga, las migraciones están al día, y los handlers de
worker están registrados.

```bash
.venv/Scripts/python -m apps.api --check
.venv/Scripts/python -m apps.worker --check
```

Ambos deben terminar con exit code 0.

### Nivel 4 — Schema y migración (obligatorio si tocaste `shared/db/orm.py`)

```bash
# Limpia DB local (entorno dev), aplica desde cero, vuelve atrás una.
alembic downgrade base
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

La migración debe ser reversible. Si no lo es, lo documentas en el
docstring de la función `upgrade()` y lo comentas en
`progress/current.md`.

### Nivel 5 — Smoke test manual (recomendado para features de transport)

Levanta los procesos en local con `compose.yml` (o directamente) y
golpea el endpoint nuevo con `httpx` o `curl`:

```bash
docker compose up -d postgres
.venv/Scripts/python -m apps.api &
.venv/Scripts/python -m apps.worker &
curl -s -X POST http://localhost:8000/v1/<...> -d @payload.json
```

## Anti-patrones (no hacer)

- ❌ "He añadido el use case, debería funcionar." → falta test
  ejecutable.
- ❌ Test que solo verifica que la función no lanza excepción. → tiene
  que comprobar el resultado concreto (estado en DB, evento en outbox,
  payload de respuesta).
- ❌ Mockear `Session`, `DatabaseUnitOfWork`, o `psycopg`. → usa la
  fixture real de `tests/support/postgres.py`.
- ❌ Mockear el filesystem para los reels. → usa
  `tempfile.TemporaryDirectory()`.
- ❌ Marcar la feature como `done` sin pasar `./init.sh`.
- ❌ Tests que dependen de la fecha actual sin fixar la zona horaria. Usa
  el inyector de fecha que ya emplean los tests de `core/logging.py` o
  pasa una fecha explícita; nunca dejes `datetime.now()` sin tz en un test.

## Verificación final antes de cerrar

```bash
./init.sh
```

Debe terminar con `[OK] Entorno listo`. Si está rojo, **no** marques nada
como `done`. Anota el bloqueo en `progress/current.md` con estado
`blocked` en `feature_list.json`.
