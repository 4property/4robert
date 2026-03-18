from __future__ import annotations

import sys
import time
from pathlib import Path

from services.wordpress_fetch_service import refetch_wordpress_properties


def main() -> None:
    base_dir = Path(__file__).resolve().parent

    start = time.perf_counter()
    try:
        new_property_ids = refetch_wordpress_properties(base_dir)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(f"New property ids: {new_property_ids}")
    print("Total time:", time.perf_counter() - start)


if __name__ == "__main__":
    main()
