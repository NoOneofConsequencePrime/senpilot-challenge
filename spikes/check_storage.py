"""Gate G8: upload a ~10 MB test ZIP to OCI via the S3 API, presign a GET URL, download it, compare bytes.

Leaves gate/test-10mb.zip in the bucket for the AgentMail URL-attachment check (G7).
Usage: python spikes/check_storage.py
"""

import hashlib
import io
import os
import time
import zipfile

import httpx

from gate_env import GateEnv, s3_client

KEY = "gate/test-10mb.zip"


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("random.bin", os.urandom(10 * 1024 * 1024))
    return buf.getvalue()


def main() -> None:
    env = GateEnv()
    s3 = s3_client(env)
    data = build_zip()
    t0 = time.time()
    s3.put_object(Bucket=env.oci_bucket, Key=KEY, Body=data, ContentType="application/zip")
    print(f"uploaded {len(data) / 1e6:.1f} MB in {time.time() - t0:.1f}s")

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": env.oci_bucket, "Key": KEY, "ResponseContentDisposition": 'attachment; filename="test-10mb.zip"'},
        ExpiresIn=3600,
    )
    print("presigned URL host:", httpx.URL(url).host)
    t0 = time.time()
    resp = httpx.get(url, timeout=120, follow_redirects=True)
    same = hashlib.sha256(resp.content).hexdigest() == hashlib.sha256(data).hexdigest()
    print(f"GET {resp.status_code} {len(resp.content) / 1e6:.1f} MB in {time.time() - t0:.1f}s; bytes match: {same}")
    print("PASS" if resp.status_code == 200 and same else "FAIL")


if __name__ == "__main__":
    main()
