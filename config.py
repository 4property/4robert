from __future__ import annotations


DATABASE_FILENAME = "wordpress_properties.sqlite3"

WORDPRESS_LINK = "https://ckp.ie/wp-json/wp/v2/property"
REQUEST_TIMEOUT_SECONDS = 30
WORDPRESS_PER_PAGE = 100
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; CPIHED/1.0; +https://ckp.ie)",
}
IMAGE_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (compatible; CPIHED/1.0; +https://ckp.ie)",
}
IMAGES_ROOT_DIRNAME = "wordpress_properties"
RAW_IMAGES_ROOT_DIRNAME = "wordpress_properties_raw"
RAW_PHOTOS_DIRNAME = "raw_photos"

DEFAULT_PHOTOS_TO_SELECT = 5
DEFAULT_PROPERTY_FOLDERS = ("property-1", "property-2", "property-3")
SELECTED_PHOTOS_DIRNAME = "selected_photos"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
HIST_BINS = (8, 8, 8)
THUMBNAIL_SIZE = (32, 32)
HASH_SIZE = 8
ORB_FEATURES = 800
MIN_ORB_KEYPOINTS = 12
ORB_GOOD_MATCH_DISTANCE = 45
CLUSTER_MERGE_AVERAGE_THRESHOLD = 0.62
CLUSTER_MERGE_BEST_THRESHOLD = 0.66

PROPERTY_COLUMN_DEFINITIONS: list[tuple[str, str]] = [
    ("id", "INTEGER PRIMARY KEY"),
    ("slug", "TEXT NOT NULL"),
    ("title", "TEXT"),
    ("link", "TEXT"),
    ("guid", "TEXT"),
    ("status", "TEXT"),
    ("resource_type", "TEXT"),
    ("author_id", "INTEGER"),
    ("importer_id", "TEXT"),
    ("list_reference", "TEXT"),
    ("date", "TEXT"),
    ("date_gmt", "TEXT"),
    ("modified", "TEXT"),
    ("modified_gmt", "TEXT"),
    ("excerpt_html", "TEXT"),
    ("content_html", "TEXT"),
    ("price", "TEXT"),
    ("price_sold", "TEXT"),
    ("price_term", "TEXT"),
    ("property_status", "TEXT"),
    ("property_market", "TEXT"),
    ("property_type_label", "TEXT"),
    ("property_county_label", "TEXT"),
    ("property_area_label", "TEXT"),
    ("property_size", "TEXT"),
    ("property_land_size", "TEXT"),
    ("property_accommodation", "TEXT"),
    ("property_disclaimer", "TEXT"),
    ("bedrooms", "INTEGER"),
    ("bathrooms", "INTEGER"),
    ("ber_rating", "TEXT"),
    ("ber_number", "TEXT"),
    ("energy_details", "TEXT"),
    ("bidding_method", "TEXT"),
    ("living_type", "TEXT"),
    ("country", "TEXT"),
    ("eircode", "TEXT"),
    ("directions", "TEXT"),
    ("latitude", "REAL"),
    ("longitude", "REAL"),
    ("agent_name", "TEXT"),
    ("agent_email", "TEXT"),
    ("agent_mobile", "TEXT"),
    ("agent_number", "TEXT"),
    ("agent_qualification", "TEXT"),
    ("featured_media_id", "INTEGER"),
    ("featured_image_url", "TEXT"),
    ("amenities", "TEXT"),
    ("property_order", "INTEGER"),
    ("wppd_parent_id", "TEXT"),
    ("property_type_ids", "TEXT"),
    ("property_county_ids", "TEXT"),
    ("property_area_ids", "TEXT"),
    ("property_features", "TEXT"),
    ("media_attachments_json", "TEXT"),
    ("brochure_urls", "TEXT"),
    ("floorplan_urls", "TEXT"),
    ("tour_urls", "TEXT"),
    ("viewing_times", "TEXT"),
    ("image_folder", "TEXT NOT NULL DEFAULT ''"),
    ("image_count", "INTEGER NOT NULL DEFAULT 0"),
    ("raw_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("fetched_at", "TEXT NOT NULL DEFAULT ''"),
]


__all__ = [
    "CLUSTER_MERGE_AVERAGE_THRESHOLD",
    "CLUSTER_MERGE_BEST_THRESHOLD",
    "DATABASE_FILENAME",
    "DEFAULT_PHOTOS_TO_SELECT",
    "DEFAULT_PROPERTY_FOLDERS",
    "HASH_SIZE",
    "HIST_BINS",
    "HTTP_HEADERS",
    "IMAGE_EXTENSIONS",
    "IMAGE_HEADERS",
    "IMAGES_ROOT_DIRNAME",
    "MIN_ORB_KEYPOINTS",
    "ORB_FEATURES",
    "ORB_GOOD_MATCH_DISTANCE",
    "PROPERTY_COLUMN_DEFINITIONS",
    "RAW_IMAGES_ROOT_DIRNAME",
    "RAW_PHOTOS_DIRNAME",
    "REQUEST_TIMEOUT_SECONDS",
    "SELECTED_PHOTOS_DIRNAME",
    "THUMBNAIL_SIZE",
    "WORDPRESS_LINK",
    "WORDPRESS_PER_PAGE",
]
