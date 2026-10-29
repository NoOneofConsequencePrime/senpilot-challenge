"""OCI Object Storage through its S3-compatible API: upload a ZIP, hand out a time-limited download link.

Bucket lifecycle rules delete `zips/` after 7 days and `recordings/` after 2 days, matching the links.
"""

from pathlib import Path

import boto3
from botocore.config import Config

from .config import Settings


class Storage:
    def __init__(self, settings: Settings):
        self.bucket = settings.oci_bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.oci_namespace}.compat.objectstorage.{settings.oci_region}.oraclecloud.com",
            region_name=settings.oci_region,
            aws_access_key_id=settings.oci_access_key,
            aws_secret_access_key=settings.oci_secret_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                # Newer boto3 sends AWS-only checksum headers by default; OCI rejects some of them.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def upload(self, path: Path, key: str, days: int) -> str:
        """Upload (multipart for big files) and return a presigned GET URL valid for `days` (max 7)."""
        self.s3.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": "application/zip"})
        return self.s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{path.name}"',
            },
            ExpiresIn=days * 86400,
        )
