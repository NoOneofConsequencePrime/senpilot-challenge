"""Loads the repo-root .env for the feasibility checks. Never prints secret values."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class GateEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    agentmail_api_key: str = ""
    agentmail_inbox: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"
    oci_namespace: str = ""
    oci_region: str = ""
    oci_bucket: str = "uarb-agent-zips"
    oci_access_key: str = ""
    oci_secret_key: str = ""
    test_recipient: str = ""

    def require(self, *names: str) -> None:
        missing = [n.upper() for n in names if not getattr(self, n)]
        if missing:
            raise SystemExit(f"Missing in {ROOT / '.env'}: {', '.join(missing)}")


def s3_client(env: GateEnv):
    """boto3 client for OCI's S3-compatible endpoint."""
    import boto3
    from botocore.config import Config

    env.require("oci_namespace", "oci_region", "oci_access_key", "oci_secret_key")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{env.oci_namespace}.compat.objectstorage.{env.oci_region}.oraclecloud.com",
        region_name=env.oci_region,
        aws_access_key_id=env.oci_access_key,
        aws_secret_access_key=env.oci_secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            # Newer boto3 sends AWS-only checksum headers by default; OCI rejects some of them.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
