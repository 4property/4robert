# CPIHED

Webhook-driven property media pipeline for multi-site real estate content.

It ingests WordPress property payloads, prepares images, renders short reels with companion posters, and publishes through GoHighLevel.

## What it does

- Multi-site webhook ingestion with per-site secrets
- PostgreSQL job queue with keyed serialization per property
- Full reels for `for_sale` / `to_let`, short status reels for `sale_agreed`, `sold`, `let_agreed`, `let`
- Poster image generated alongside every reel
- Publishing to TikTok, Instagram, LinkedIn, YouTube, Facebook, and Google Business Profile via GoHighLevel
- Durable media revisions and an outbox of domain events

## Layout

- `application/` — orchestration, dispatch, pipeline stages, admin
- `services/` — transport (HTTP), media (rendering, storage), publishing (social), AI adapters
- `repositories/` — PostgreSQL persistence
- `settings/` — environment configuration
- `tests/` — regression and architecture coverage

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate    # or source .venv/bin/activate on Linux
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env      # then fill in the values
```

## Run

```bash
python main.py            # start the server
python main.py --check    # readiness check, no server
python main.py --check --readiness-json   # machine-readable output
```

## Test

```bash
python -m pytest -q
```

## Runtime folders (gitignored)

- `property_media/` — selected images per property
- `property_media_raw/` — downloaded originals
- `generated_media/` — rendered reels and posters
- `logs/` — persistent log output

## Notes

- A reel is only considered complete if its companion poster also exists.
- Optional capabilities (AI copy, AI narration, notifications, review) can stay disabled without blocking the core flow.
- Google Business Profile must already be connected to the target HighLevel sub-account in Social Planner before webhooks are sent.
- Rocky Linux deployment guide: [`deploy/rocky-linux/README.md`](deploy/rocky-linux/README.md).
- Architecture detail: [`ARCHITECTURE.md`](ARCHITECTURE.md).
