# Rocky Linux deployment

Runs under `systemd` with a Python virtual environment and a writable workspace.

## Packages

```bash
sudo dnf install -y git python3.11 python3.11-pip python3.11-devel
sudo dnf install -y epel-release
sudo dnf install -y https://download1.rpmfusion.org/free/el/rpmfusion-free-release-9.noarch.rpm
sudo dnf install -y ffmpeg
```

If RPM Fusion is not allowed, install a trusted static `ffmpeg` build and put it on the service user's `PATH`.

## Layout

- App: `/opt/cpihed`
- Env file: `/etc/cpihed/cpihed.env`
- Service user: `cpihed`

```bash
sudo useradd --system --create-home --home-dir /opt/cpihed --shell /sbin/nologin cpihed
sudo mkdir -p /opt/cpihed /etc/cpihed
sudo chown -R cpihed:cpihed /opt/cpihed /etc/cpihed
```

## Install

Copy the repository into `/opt/cpihed`, then:

```bash
cd /opt/cpihed
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt
install -m 640 .env.example /etc/cpihed/cpihed.env
```

In `/etc/cpihed/cpihed.env`, at minimum set:

- `DATABASE_URL` — PostgreSQL DSN with the Alembic schema applied
- `WEBHOOK_SITE_SECRETS` — real per-site secrets (no `change-me`)
- `WEBHOOK_DISABLE_SECURITY=false`
- `WEBHOOK_ALLOWED_HOSTS` if the public hostname differs from the dotted `site_id`
- `GO_HIGH_LEVEL_BASE_URL` if non-default
- `GEMINI_API_KEY` if AI photo selection is enabled

## Preflight

```bash
sudo -u cpihed bash -lc 'cd /opt/cpihed && set -a && source /etc/cpihed/cpihed.env && set +a && .venv/bin/python main.py --check'
```

The check validates PostgreSQL connectivity and schema, runtime directories, `ffmpeg`, subtitle font, background music, and webhook secret configuration. For production, both `Runtime ready` and `Production ready` must report `Yes`. The check fails if `WEBHOOK_DISABLE_SECURITY=true` or any site secret still uses a placeholder.

## systemd

```bash
sudo install -m 644 deploy/rocky-linux/cpihed.service /etc/systemd/system/cpihed.service
sudo systemctl daemon-reload
sudo systemctl enable --now cpihed
sudo systemctl status cpihed
sudo journalctl -u cpihed -f
```

`/health/live` and `/health/ready` return minimal status only — use `python main.py --check` and `journalctl` for diagnostics.

## Reverse proxy

Bind to localhost and proxy through Nginx with TLS:

```
WEBHOOK_HOST=127.0.0.1
WEBHOOK_PORT=8000
WEBHOOK_TRUST_PROXY_HEADERS=true
WEBHOOK_FORWARDED_ALLOW_IPS=127.0.0.1
```

If the public hostname differs from the dotted `site_id` keys in `WEBHOOK_SITE_SECRETS`, set `WEBHOOK_ALLOWED_HOSTS=example-api.yourdomain.tld`.

## Notes

- Keep `generated_media`, `property_media`, and `property_media_raw` writable by the service user.
- If `ffmpeg` reports `Cannot allocate memory`, lower `REEL_FFMPEG_FILTER_THREADS` and `REEL_FFMPEG_ENCODER_THREADS`.
- For webhook auth failures, compare incoming headers against the configured `WEBHOOK_*_HEADER` values and verify the secret for the source `site_id`.
