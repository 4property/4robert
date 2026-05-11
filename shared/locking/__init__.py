"""Cross-platform exclusive file locks.

Implementation lives in `shared.locking.file_lock`.
"""

from shared.locking.file_lock import exclusive_file_lock, property_job_lock_path

__all__ = ["exclusive_file_lock", "property_job_lock_path"]
