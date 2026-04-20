# Rocky Linux Deployment

This project is ready to run on Rocky Linux with `systemd`, a Python virtual environment, and a writable workspace directory.

## Packages

Install the base OS dependencies first:

```bash
sudo dnf install -y git python3.11 python3.11-pip python3.11-devel
```

`ffmpeg` is required for reel rendering. On Rocky Linux it usually comes from RPM Fusion or another approved repository:

```bash
sudo dnf install -y epel-release
sudo dnf install -y https://download1.rpmfusion.org/free/el/rpmfusion-free-release-9.noarch.rpm
sudo dnf install -y ffmpeg
```

If your estate policy does not allow RPM Fusion, install a trusted static `ffmpeg` build and make sure it is on `PATH` for the service user.

## Recommended layout

- App code: `/opt/cpihed`
- Environment file: `/etc/cpihed/cpihed.env`
- Service user: `cpihed`

Create the service user and workspace:

```bash
sudo useradd --system --create-home --home-dir /opt/cpihed --shell /sbin/nologin cpihed
sudo mkdir -p /opt/cpihed /etc/cpihed
sudo chown -R cpihed:cpihed /opt/cpihed /etc/cpihed
```

## Install the app

Clone or copy the repository into `/opt/cpihed`, then:

```bash
cd /opt/cpihed
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt
install -m 640 .env.example /etc/cpihed/cpihed.env
```

Edit `/etc/cpihed/cpihed.env` and set at least:

- `WEBHOOK_SITE_SECRETS`
- `WEBHOOK_DISABLE_SECURITY=false`
- `WEBHOOK_ALLOWED_HOSTS` if your public webhook hostname does not match the dotted `site_id` values in `WEBHOOK_SITE_SECRETS`
- `GO_HIGH_LEVEL_BASE_URL` if you use a non-default endpoint
- `GEMINI_API_KEY` only if you want AI photo selection enabled

## Preflight checks

Run the built-in readiness check before enabling the service:

```bash
cd /opt/cpihed
sudo -u cpihed bash -lc 'cd /opt/cpihed && set -a && source /etc/cpihed/cpihed.env && set +a && .venv/bin/python main.py --check'
```

This validates:

- PostgreSQL connectivity, required tables, and write access
- runtime directories and temp writes
- `ffmpeg`
- subtitle font presence
- background music asset presence
- webhook secret configuration

For a production deployment, the command must report both `Runtime ready: Yes` and `Production ready: Yes`.

If the check fails, the error output now includes a troubleshooting hint and the failing check name. A deployment check will also fail if:

- `WEBHOOK_DISABLE_SECURITY=true`
- `WEBHOOK_SITE_SECRETS` still uses placeholder values such as `change-me`

## systemd

Install the provided unit:

```bash
sudo install -m 644 deploy/rocky-linux/cpihed.service /etc/systemd/system/cpihed.service
sudo systemctl daemon-reload
sudo systemctl enable --now cpihed
```

Useful commands:

```bash
sudo systemctl status cpihed
sudo journalctl -u cpihed -f
curl -fsS http://127.0.0.1:8000/health/ready
```

The `/health` endpoints are intentionally minimal in production:

- `/health/live` returns only `{"status":"ok"}`
- `/health/ready` returns only `{"status":"ready"}` or `{"status":"not_ready"}`

Use `python main.py --check` or `journalctl -u cpihed -f` for detailed troubleshooting instead of relying on HTTP health output.

## Reverse proxy

The service can bind directly to `0.0.0.0`, but in production it is usually better to keep:

- `WEBHOOK_HOST=127.0.0.1`
- `WEBHOOK_PORT=8000`
- `WEBHOOK_TRUST_PROXY_HEADERS=true`
- `WEBHOOK_FORWARDED_ALLOW_IPS=127.0.0.1`

and expose it through Nginx or another reverse proxy with TLS.

If the public webhook hostname differs from the dotted `site_id` values you use in `WEBHOOK_SITE_SECRETS`, set:

- `WEBHOOK_ALLOWED_HOSTS=example-api.yourdomain.tld`

## Operational notes

- Keep `/opt/cpihed/generated_media`, `/opt/cpihed/property_media`, and `/opt/cpihed/property_media_raw` writable by the service user.
- Ensure `DATABASE_URL` points to a reachable PostgreSQL instance with the Alembic schema applied.
- If `ffmpeg` fails with `Cannot allocate memory`, reduce `REEL_FFMPEG_FILTER_THREADS` and `REEL_FFMPEG_ENCODER_THREADS`.
- If webhook authentication fails, compare the incoming headers against the configured `WEBHOOK_*_HEADER` values and confirm the secret for the source `site_id`.
