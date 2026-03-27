# CPIHED

WordPress webhook pipeline that ingests property payloads from multiple sites, selects images with Gemini, renders short-form property reels, and optionally publishes them to social platforms.

## What is in the repo

- `application/`: orchestration, job dispatching, and pipeline entrypoints
- `services/`: adapters for webhook transport, media handling, reel rendering, AI photo selection, and social delivery
- `repositories/`: SQLite-backed persistence layer
- `settings/`: environment-driven configuration
- `tests/`: regression and architecture tests

## Local setup

1. Create a virtual environment.
2. Install runtime dependencies with `pip install -r requirements.txt`.
3. Install test dependencies with `pip install -r requirements-dev.txt`.
4. Copy `.env.example` to `.env` and replace the placeholder values.

## Running the app

```powershell
python main.py
```

The server reads configuration from `.env` and starts the WordPress webhook endpoint.

## Running tests

```powershell
python -m pytest -q
```

## Important local-only folders

These paths are generated at runtime and are ignored by Git:

- `property_media/`
- `property_media_raw/`
- `generated_reels/`
- `.runtime_locks/`
- `.tmp_test_cases/`

## Notes

- The repository is configured for multi-site webhook ingestion; no single agency is treated as the preferred source.
- The default reel fonts are bundled in `assets/fonts/` to avoid machine-specific Windows font dependencies.
