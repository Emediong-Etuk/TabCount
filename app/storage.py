"""Optional S3 persistence. Runs as a FastAPI BackgroundTask after the response
is sent; failures are logged and never affect the user's response.

Keys: requests/{yyyy}/{mm}/{dd}/{request_id}/{input.<ext>, annotated.jpg, result.json}
The bucket has a lifecycle rule deleting requests/ after 60 days.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import uuid
from collections import OrderedDict

log = logging.getLogger("tabcount.storage")

_EXT_CT = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class S3Store:
    def __init__(self, bucket: str, region: str | None = None):
        self.bucket = bucket
        self.region = region
        self._client = None
        self._lock = threading.Lock()
        self._recent: OrderedDict[str, str] = OrderedDict()  # request_id -> key prefix

    @property
    def client(self):
        if self._client is None:
            with self._lock:
                if self._client is None:
                    import boto3  # imported lazily so tests never touch AWS
                    self._client = boto3.client("s3", region_name=self.region)
        return self._client

    @staticmethod
    def prefix_for(request_id: str, when: dt.datetime) -> str:
        return f"requests/{when:%Y/%m/%d}/{request_id}/"

    def save_request(self, request_id: str, input_bytes: bytes, input_ext: str,
                     annotated_jpeg: bytes, result: dict) -> None:
        prefix = self.prefix_for(request_id, dt.datetime.now(dt.timezone.utc))
        try:
            ext = input_ext if input_ext in _EXT_CT else "jpg"
            self.client.put_object(Bucket=self.bucket, Key=prefix + f"input.{ext}",
                                   Body=input_bytes, ContentType=_EXT_CT[ext])
            self.client.put_object(Bucket=self.bucket, Key=prefix + "annotated.jpg",
                                   Body=annotated_jpeg, ContentType="image/jpeg")
            self.client.put_object(Bucket=self.bucket, Key=prefix + "result.json",
                                   Body=json.dumps(result).encode(), ContentType="application/json")
            self._remember(request_id, prefix)
            log.info(json.dumps({"event": "s3_saved", "request_id": request_id}))
        except Exception as exc:  # never propagate
            log.warning(json.dumps({"event": "s3_error", "request_id": request_id,
                                    "error": type(exc).__name__}))

    def _remember(self, request_id: str, prefix: str) -> None:
        self._recent[request_id] = prefix
        while len(self._recent) > 1000:
            self._recent.popitem(last=False)

    def get_result(self, request_id: str, max_days: int = 61) -> dict | None:
        """Fetch result.json. Without s3:ListBucket we probe dated prefixes."""
        try:
            uuid.UUID(request_id)
        except ValueError:
            return None
        candidates = []
        if request_id in self._recent:
            candidates.append(self._recent[request_id])
        today = dt.datetime.now(dt.timezone.utc)
        candidates += [self.prefix_for(request_id, today - dt.timedelta(days=d)) for d in range(max_days)]
        for prefix in candidates:
            try:
                obj = self.client.get_object(Bucket=self.bucket, Key=prefix + "result.json")
                return json.loads(obj["Body"].read())
            except Exception:
                continue
        return None
