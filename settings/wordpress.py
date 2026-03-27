from __future__ import annotations


WORDPRESS_LINK = "https://example-estate.ie/wp-json/wp/v2/property"
REQUEST_TIMEOUT_SECONDS = 30
WORDPRESS_PER_PAGE = 100
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; CPIHED/1.0)",
}


__all__ = [
    "HTTP_HEADERS",
    "REQUEST_TIMEOUT_SECONDS",
    "WORDPRESS_LINK",
    "WORDPRESS_PER_PAGE",
]
