# CPIHED

Webhook-driven property media pipeline for multi-site real estate content.

It ingests WordPress property payloads, prepares images, renders short-form reels with companion posters, stores durable media revisions, and publishes through GoHighLevel to the configured social platforms.

## Current capabilities

- multi-site webhook ingestion
- durable PostgreSQL job queue
- keyed worker serialization per property
- full reels for `for_sale` and `to_let`
- short status reels for `sale_agreed`, `sold`, `let_agreed`, and `let`
- poster generation persisted alongside every successful reel render
- multi-platform publishing through GoHighLevel
- Google Business Profile publishing through GoHighLevel using poster images
- durable outbox events for future notifications and review workflows
- manifest-level overlay layout auditing with safe text wrapping and clamp warnings

## Project structure

- `application/`: workflow orchestration, dispatching, planning, and content generation
- `services/`: webhook transport, rendering, media prep, AI adapters, and social delivery
- `repositories/`: PostgreSQL persistence and compatibility shims
- `settings/`: environment-driven configuration
- `tests/`: regression and architecture coverage

## Local setup

1. Create a virtual environment.
2. Install runtime dependencies with `pip install -r requirements.txt`.
3. Install dev dependencies with `pip install -r requirements-dev.txt`.
4. Copy `.env.example` to `.env` and fill in the required values.

## Run

```powershell
python main.py
```

## Preflight checks

Run the deployment checks before starting the service:

```powershell
python main.py --check
```

If you need the machine-readable readiness payload for automation:

```powershell
python main.py --check --readiness-json
```

## Test

```powershell
python -m pytest -q
```

## Runtime folders

Generated at runtime and ignored by Git:

- `property_media/`
- `property_media_raw/`
- `generated_media/`
- `.runtime_locks/`
- `.tmp_test_cases/`

## Notes

- The webhook runtime is ready when core storage, queue, and ffmpeg checks pass.
- Optional capabilities such as AI copy, AI narration, notifications, and review can stay disabled without blocking the core webhook workflow.
- Captions are generated through a dedicated content-generation boundary so deterministic copy can be replaced later by an AI-backed implementation.
- Durable reel output is `reel + poster`; a reel is not treated as a complete local artifact unless its companion poster exists too.
- Keep `google_business_profile` in `SOCIAL_PUBLISHING_DEFAULT_PLATFORMS` if GBP posting is required in deployment.
- Google Business Profile publishing requires the GBP to be connected to the target HighLevel sub-account in Social Planner / GBP Optimization before webhooks are sent.
- For future GBP automation research, HighLevel's documented connection sequence is: start Google OAuth, get Google business locations, then set the Google business location for the sub-account.
- Deployment guidance for Rocky Linux, including `systemd`, lives in `deploy/rocky-linux/README.md`.
