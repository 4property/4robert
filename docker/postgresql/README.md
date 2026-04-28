# PostgreSQL (local dev)

Use the root `compose.yml`:

```bash
docker compose up -d postgres
docker compose down
```

Data lives in the `postgres_data` named volume, not in the repo.
