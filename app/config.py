"""Environment-driven settings. No credentials live here: boto3 uses its default chain."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    s3_bucket: str | None
    aws_region: str | None
    max_upload_bytes: int
    disable_imds: bool

    @property
    def s3_enabled(self) -> bool:
        return bool(self.s3_bucket)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            s3_bucket=os.environ.get("TABCOUNT_S3_BUCKET") or None,
            aws_region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None,
            max_upload_bytes=_int("TABCOUNT_MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
            disable_imds=os.environ.get("TABCOUNT_DISABLE_IMDS", "0") in ("1", "true", "yes"),
        )


# Query-parameter override limits (validated by the API).
PEAK_RATIO_RANGE = (0.1, 0.95)
MIN_AREA_RANGE = (1, 100_000)
