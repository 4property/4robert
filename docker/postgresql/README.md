PostgreSQL local development now uses the root-level `compose.yml`.

Usage:

```powershell
docker compose up -d postgres
docker compose down
```

The database data lives in the named Docker volume `postgres_data`, not inside the repository.
