from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://services.leadconnectorhq.com"
DEFAULT_API_VERSION = "2021-07-28"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_POST_TYPE = "post"
DEFAULT_PLATFORM = "youtube"
NON_TERMINAL_POST_STATUSES = {
    "accepted",
    "created",
    "draft",
    "in_progress",
    "pending",
    "processing",
    "queued",
    "scheduled",
    "verification_pending",
}
DEFAULT_CREDENTIALS_PATH = Path(__file__).resolve().parent / "assets" / "ghl-api.txt"
DEFAULT_VIDEO_PATH = Path(__file__).resolve().parent / "assets" / "7-sherwood-pollerton-carlow-reel.mp4"


@dataclass(frozen=True)
class Credentials:
    location_id: str
    access_token: str


class ProbeError(RuntimeError):
    pass


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prueba directa de subida de video a YouTube a traves de la API de GoHighLevel. "
            "Imprime por terminal cada request/response relevante."
        )
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=DEFAULT_CREDENTIALS_PATH,
        help="Ruta al archivo con locationId y token.",
    )
    parser.add_argument(
        "--video",
        type=Path,
        default=DEFAULT_VIDEO_PATH,
        help="Ruta al video que se subira.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL de la API de GoHighLevel.",
    )
    parser.add_argument(
        "--api-version",
        default=DEFAULT_API_VERSION,
        help="Header Version para la API de GoHighLevel.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout HTTP en segundos.",
    )
    parser.add_argument(
        "--platform",
        default=DEFAULT_PLATFORM,
        help="Plataforma objetivo. Por defecto youtube.",
    )
    parser.add_argument(
        "--description",
        default="Prueba tecnica desde youtube-test",
        help="Texto del post.",
    )
    parser.add_argument(
        "--title",
        default="Prueba tecnica YouTube",
        help="Titulo logico de la prueba. Por defecto se usa tambien como nombre de subida.",
    )
    parser.add_argument(
        "--upload-name",
        default=None,
        help="Nombre de archivo a enviar a GoHighLevel. Si se omite usa el titulo.",
    )
    parser.add_argument(
        "--post-type",
        default=DEFAULT_POST_TYPE,
        help="Tipo de post para GoHighLevel, por ejemplo post o reel.",
    )
    parser.add_argument(
        "--account-id",
        default=None,
        help="Fuerza un accountId concreto en lugar de seleccionar el primero activo.",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Fuerza un userId concreto en lugar de seleccionar el primero disponible.",
    )
    parser.add_argument(
        "--include-title-field",
        action="store_true",
        help="Incluye un campo title en el payload del post para experimentar con variantes.",
    )
    parser.add_argument(
        "--youtube-post-details-type",
        default=None,
        help="Si se indica y la plataforma es youtube, envia youtubePostDetails.type con este valor.",
    )
    parser.add_argument(
        "--verify-post",
        action="store_true",
        help="Consulta el post creado para ver el estado real devuelto por GoHighLevel.",
    )
    parser.add_argument(
        "--post-list-poll-attempts",
        type=int,
        default=4,
        help="Intentos para buscar el post recien creado en /posts/list.",
    )
    parser.add_argument(
        "--post-list-poll-interval",
        type=float,
        default=4.0,
        help="Segundos entre intentos de polling en /posts/list.",
    )
    parser.add_argument(
        "--post-list-limit",
        type=int,
        default=10,
        help="Numero de posts recientes a pedir en /posts/list.",
    )
    parser.add_argument(
        "--pause-before-verify",
        type=float,
        default=3.0,
        help="Segundos de espera antes de consultar el post cuando --verify-post esta activo.",
    )
    parser.add_argument(
        "--dump-full-headers",
        action="store_true",
        help="Muestra todas las cabeceras HTTP de respuesta.",
    )
    return parser


def load_credentials(path: Path) -> Credentials:
    resolved_path = path.expanduser().resolve()
    if not resolved_path.is_file():
        raise ProbeError(f"No existe el archivo de credenciales: {resolved_path}")

    values: dict[str, str] = {}
    for raw_line in resolved_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        key, value = parts
        values[key.strip()] = value.strip()

    location_id = values.get("locationId", "").strip()
    access_token = values.get("token", "").strip()
    if not location_id:
        raise ProbeError(f"Falta locationId en {resolved_path}")
    if not access_token:
        raise ProbeError(f"Falta token en {resolved_path}")
    return Credentials(location_id=location_id, access_token=access_token)


def redact_token(token: str) -> str:
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def format_json(data: Any) -> str:
    try:
        return json.dumps(data, indent=2, ensure_ascii=True, sort_keys=True)
    except TypeError:
        return repr(data)


def print_heading(title: str) -> None:
    print()
    print(f"{'=' * 24} {title} {'=' * 24}")


def print_kv(label: str, value: Any) -> None:
    print(f"{label}: {value}")


def summarise_response_headers(response: httpx.Response, dump_full_headers: bool) -> dict[str, str]:
    if dump_full_headers:
        return dict(response.headers)

    interesting_headers = {
        "content-type",
        "content-length",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "cf-ray",
        "traceparent",
    }
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() in interesting_headers
    }


def print_response(
    *,
    step_name: str,
    response: httpx.Response,
    dump_full_headers: bool,
) -> None:
    print_heading(step_name)
    print_kv("HTTP", f"{response.request.method} {response.request.url}")
    print_kv("Status", response.status_code)
    print_kv("Headers", format_json(summarise_response_headers(response, dump_full_headers)))

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        try:
            payload = response.json()
        except json.JSONDecodeError:
            print_kv("Body", response.text)
            return
        print("Body:")
        print(format_json(payload))
        return

    print("Body:")
    print(response.text or "<empty>")


class GoHighLevelProbeClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_version: str,
        timeout_seconds: float,
        access_token: str,
        dump_full_headers: bool,
    ) -> None:
        self.api_version = api_version
        self.access_token = access_token
        self.dump_full_headers = dump_full_headers
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        step_name: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "Version": self.api_version,
        }

        print_heading(f"{step_name} REQUEST")
        print_kv("Method", method.upper())
        print_kv("URL", f"{self.client.base_url}{path}")
        print_kv("Authorization", f"Bearer {redact_token(self.access_token)}")
        print_kv("Version", self.api_version)
        if params:
            print("Query params:")
            print(format_json(params))
        if json_body is not None:
            print("JSON body:")
            print(format_json(json_body))
        if data is not None:
            print("Form data:")
            print(format_json(data))
        if files is not None:
            file_summary = {
                key: {
                    "filename": value[0],
                    "content_type": value[2],
                }
                for key, value in files.items()
            }
            print("Files:")
            print(format_json(file_summary))

        try:
            response = self.client.request(
                method=method,
                url=path,
                params=params,
                headers=headers,
                json=json_body,
                data=data,
                files=files,
            )
        except httpx.HTTPError as error:
            raise ProbeError(f"Fallo HTTP en {step_name}: {error}") from error

        print_response(
            step_name=step_name,
            response=response,
            dump_full_headers=self.dump_full_headers,
        )

        if not response.content:
            return {}

        if response.status_code >= 400:
            raise ProbeError(
                f"{step_name} fallo con HTTP {response.status_code}. "
                f"Consulta el bloque anterior para ver la respuesta completa."
            )

        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise ProbeError(
                f"{step_name} devolvio una respuesta no JSON: {response.text[:500]}"
            ) from error

        if isinstance(payload, dict):
            return payload
        return {"results": payload}


def normalize_platform(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def list_accounts(
    client: GoHighLevelProbeClient,
    *,
    location_id: str,
) -> list[dict[str, Any]]:
    payload = client.request(
        "GET",
        f"/social-media-posting/{location_id}/accounts",
        step_name="LIST ACCOUNTS",
    )
    results = payload.get("results", {})
    raw_accounts = results.get("accounts", []) if isinstance(results, dict) else []
    if not isinstance(raw_accounts, list):
        return []
    return [item for item in raw_accounts if isinstance(item, dict)]


def list_users(
    client: GoHighLevelProbeClient,
    *,
    location_id: str,
) -> list[dict[str, Any]]:
    payload = client.request(
        "GET",
        "/users/",
        step_name="LIST USERS",
        params={"locationId": location_id},
    )
    raw_users = payload.get("users", [])
    if not isinstance(raw_users, list):
        return []
    return [item for item in raw_users if isinstance(item, dict)]


def select_account(
    accounts: list[dict[str, Any]],
    *,
    platform: str,
    requested_account_id: str | None,
) -> dict[str, Any]:
    normalized_platform = normalize_platform(platform)
    platform_accounts = [
        account
        for account in accounts
        if normalize_platform(str(account.get("platform") or "")) == normalized_platform
    ]
    active_platform_accounts = [
        account for account in platform_accounts if not bool(account.get("isExpired"))
    ]

    print_heading("ACCOUNT SUMMARY")
    print(format_json(platform_accounts))

    if requested_account_id:
        for account in platform_accounts:
            if str(account.get("id") or "").strip() == requested_account_id.strip():
                return account
        raise ProbeError(
            f"No existe el accountId solicitado para {platform}: {requested_account_id}"
        )

    if active_platform_accounts:
        return sorted(
            active_platform_accounts,
            key=lambda item: (
                str(item.get("name") or "").lower(),
                str(item.get("id") or ""),
            ),
        )[0]

    if platform_accounts:
        raise ProbeError(
            f"Hay cuentas {platform} conectadas pero todas salen expiradas. "
            "Revisa el bloque ACCOUNT SUMMARY."
        )

    raise ProbeError(f"No hay ninguna cuenta conectada para la plataforma {platform}.")


def select_user(
    users: list[dict[str, Any]],
    *,
    requested_user_id: str | None,
) -> dict[str, Any]:
    print_heading("USER SUMMARY")
    print(format_json(users))

    if not users:
        raise ProbeError("No hay usuarios disponibles para la location.")

    if requested_user_id:
        for user in users:
            if str(user.get("id") or "").strip() == requested_user_id.strip():
                return user
        raise ProbeError(f"No existe el userId solicitado: {requested_user_id}")

    return sorted(
        users,
        key=lambda item: (
            str(item.get("firstName") or "").lower(),
            str(item.get("lastName") or "").lower(),
            str(item.get("id") or ""),
        ),
    )[0]


def upload_media(
    client: GoHighLevelProbeClient,
    *,
    video_path: Path,
    upload_name: str,
) -> dict[str, Any]:
    resolved_path = video_path.expanduser().resolve()
    if not resolved_path.is_file():
        raise ProbeError(f"No existe el video: {resolved_path}")

    mime_type = mimetypes.guess_type(resolved_path.name)[0] or "application/octet-stream"
    file_size = resolved_path.stat().st_size

    print_heading("LOCAL FILE")
    print_kv("Path", resolved_path)
    print_kv("Size bytes", file_size)
    print_kv("Mime type", mime_type)
    print_kv("Upload name", upload_name)

    with resolved_path.open("rb") as file_handle:
        return client.request(
            "POST",
            "/medias/upload-file",
            step_name="UPLOAD MEDIA",
            data={
                "hosted": "false",
                "name": upload_name,
            },
            files={
                "file": (upload_name, file_handle, mime_type),
            },
        )


def create_post(
    client: GoHighLevelProbeClient,
    *,
    platform: str,
    location_id: str,
    account_id: str,
    user_id: str,
    media_url: str,
    mime_type: str,
    post_type: str,
    description: str,
    title: str,
    include_title_field: bool,
    youtube_post_details_type: str | None,
) -> dict[str, Any]:
    json_body: dict[str, Any] = {
        "accountIds": [account_id],
        "summary": description,
        "media": [{"url": media_url, "type": mime_type}],
        "status": "published",
        "type": post_type,
        "userId": user_id,
    }
    if include_title_field:
        json_body["title"] = title
    normalized_platform = normalize_platform(platform)
    normalized_youtube_type = str(youtube_post_details_type or "").strip()
    if normalized_platform == "youtube" and normalized_youtube_type:
        json_body["youtubePostDetails"] = {"type": normalized_youtube_type}

    return client.request(
        "POST",
        f"/social-media-posting/{location_id}/posts",
        step_name="CREATE POST",
        json_body=json_body,
    )


def extract_created_post_id(payload: dict[str, Any]) -> str | None:
    candidates: list[dict[str, Any]] = []
    results = payload.get("results")
    if isinstance(results, dict):
        candidates.append(results)
    candidates.append(payload)
    for candidate in candidates:
        for key in ("id", "_id", "postId"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def get_post(
    client: GoHighLevelProbeClient,
    *,
    location_id: str,
    post_id: str,
) -> dict[str, Any]:
    return client.request(
        "GET",
        f"/social-media-posting/{location_id}/posts/{post_id}",
        step_name="GET POST",
    )


def list_posts(
    client: GoHighLevelProbeClient,
    *,
    location_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    payload = client.request(
        "POST",
        f"/social-media-posting/{location_id}/posts/list",
        step_name="LIST POSTS",
        json_body={"limit": str(max(1, limit))},
    )
    results = payload.get("results", {})
    raw_posts = results.get("posts", []) if isinstance(results, dict) else []
    if not isinstance(raw_posts, list):
        return []
    return [item for item in raw_posts if isinstance(item, dict)]


def extract_media_urls(post: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    raw_media = post.get("media")
    if not isinstance(raw_media, list):
        return urls
    for item in raw_media:
        if not isinstance(item, dict):
            continue
        raw_url = item.get("url")
        if isinstance(raw_url, str) and raw_url.strip():
            urls.add(raw_url.strip())
    return urls


def match_recent_post(
    posts: list[dict[str, Any]],
    *,
    media_url: str,
    platform: str,
    created_by: str,
) -> dict[str, Any] | None:
    normalized_platform = normalize_platform(platform)
    for post in posts:
        if normalize_platform(str(post.get("platform") or "")) != normalized_platform:
            continue
        if str(post.get("createdBy") or "").strip() != created_by:
            continue
        if media_url in extract_media_urls(post):
            return post
    return None


def summarise_post(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "postId": post.get("postId") or post.get("_id"),
        "platform": post.get("platform"),
        "status": post.get("status"),
        "error": post.get("error"),
        "createdAt": post.get("createdAt"),
        "updatedAt": post.get("updatedAt"),
        "publishedAt": post.get("publishedAt"),
        "createdBy": post.get("createdBy"),
        "accountId": post.get("accountId"),
        "summary": post.get("summary"),
        "media": post.get("media"),
    }


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    credentials = load_credentials(args.credentials_file)
    upload_name = str(args.upload_name or args.title or args.video.stem).strip()
    if not upload_name:
        upload_name = args.video.name

    print_heading("CONFIG")
    print_kv("Credentials file", args.credentials_file.expanduser().resolve())
    print_kv("Video", args.video.expanduser().resolve())
    print_kv("Location ID", credentials.location_id)
    print_kv("Token", redact_token(credentials.access_token))
    print_kv("Platform", args.platform)
    print_kv("Post type", args.post_type)
    print_kv("Include title field", args.include_title_field)
    print_kv("YouTube post details type", args.youtube_post_details_type or "<none>")
    print_kv("Verify post", args.verify_post)

    client = GoHighLevelProbeClient(
        base_url=args.base_url,
        api_version=args.api_version,
        timeout_seconds=args.timeout,
        access_token=credentials.access_token,
        dump_full_headers=args.dump_full_headers,
    )
    try:
        accounts = list_accounts(client, location_id=credentials.location_id)
        selected_account = select_account(
            accounts,
            platform=args.platform,
            requested_account_id=args.account_id,
        )
        print_heading("SELECTED ACCOUNT")
        print(format_json(selected_account))

        users = list_users(client, location_id=credentials.location_id)
        selected_user = select_user(users, requested_user_id=args.user_id)
        print_heading("SELECTED USER")
        print(format_json(selected_user))

        upload_payload = upload_media(
            client,
            video_path=args.video,
            upload_name=upload_name,
        )
        file_id = str(upload_payload.get("fileId") or "").strip()
        media_url = str(upload_payload.get("url") or "").strip()
        if not file_id or not media_url:
            raise ProbeError(
                "La subida del media no devolvio fileId o url. "
                "Consulta el bloque UPLOAD MEDIA."
            )

        mime_type = mimetypes.guess_type(args.video.name)[0] or "application/octet-stream"
        post_payload = create_post(
            client,
            platform=args.platform,
            location_id=credentials.location_id,
            account_id=str(selected_account.get("id") or "").strip(),
            user_id=str(selected_user.get("id") or "").strip(),
            media_url=media_url,
            mime_type=mime_type,
            post_type=args.post_type,
            description=args.description,
            title=args.title,
            include_title_field=args.include_title_field,
            youtube_post_details_type=args.youtube_post_details_type,
        )

        created_post_id = extract_created_post_id(post_payload)
        print_heading("CREATE POST SUMMARY")
        print_kv("fileId", file_id)
        print_kv("mediaUrl", media_url)
        print_kv("createdPostId", created_post_id or "<none>")

        selected_user_id = str(selected_user.get("id") or "").strip()
        matched_post: dict[str, Any] | None = None
        for attempt in range(1, max(1, args.post_list_poll_attempts) + 1):
            if attempt > 1 and args.post_list_poll_interval > 0:
                print_heading("LIST POSTS WAIT")
                print_kv("Attempt", f"{attempt}/{max(1, args.post_list_poll_attempts)}")
                print_kv("Seconds", args.post_list_poll_interval)
                time.sleep(args.post_list_poll_interval)

            recent_posts = list_posts(
                client,
                location_id=credentials.location_id,
                limit=args.post_list_limit,
            )
            matched_post = match_recent_post(
                recent_posts,
                media_url=media_url,
                platform=args.platform,
                created_by=selected_user_id,
            )
            print_heading("LIST POSTS MATCH")
            if matched_post is None:
                print("No se encontro aun el post recien creado en la ventana consultada.")
            else:
                print(format_json(summarise_post(matched_post)))
                matched_status = str(matched_post.get("status") or "").strip().lower()
                if matched_status and matched_status not in NON_TERMINAL_POST_STATUSES:
                    break

        if args.verify_post and created_post_id:
            if args.pause_before_verify > 0:
                print_heading("VERIFY WAIT")
                print_kv("Seconds", args.pause_before_verify)
                time.sleep(args.pause_before_verify)
            get_post(
                client,
                location_id=credentials.location_id,
                post_id=created_post_id,
            )

        if matched_post is not None:
            matched_status = str(matched_post.get("status") or "").strip().lower()
            matched_error = str(matched_post.get("error") or "").strip()
            if matched_status == "failed":
                raise ProbeError(
                    "GoHighLevel creo el post pero el publish downstream fallo. "
                    f"status={matched_post.get('status')}; error={matched_error or '<none>'}; "
                    f"postId={matched_post.get('postId') or matched_post.get('_id') or '<none>'}"
                )

        print_heading("DONE")
        print("La prueba termino sin errores de transporte. Revisa los bloques anteriores.")
        return 0
    except ProbeError as error:
        print_heading("PROBE ERROR")
        print(str(error))
        return 1
    except Exception:
        print_heading("UNEXPECTED ERROR")
        traceback.print_exc()
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
