"""Storage helpers for generated scripts."""

import aioboto3
import structlog

from backend.config import settings
from backend.models.story import FinalScript

log = structlog.get_logger(__name__)


async def upload_script_to_s3(script: FinalScript, *, suffix: str = "") -> str:
    """Serialise a script to JSON and upload it to the configured S3 bucket."""
    safe_title = script.title[:50].replace(" ", "_")
    suffix_part = f"_{suffix}" if suffix else ""
    key = f"scripts/{script.story_id}/{safe_title}{suffix_part}.json"
    content = script.model_dump_json(indent=2).encode("utf-8")

    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    client_kwargs = {}
    if settings.s3_endpoint_url:
        client_kwargs["endpoint_url"] = settings.s3_endpoint_url
    async with session.client("s3", **client_kwargs) as s3:
        await s3.put_object(
            Bucket=settings.s3_bucket_scripts,
            Key=key,
            Body=content,
            ContentType="application/json",
        )
    log.info("script_storage.s3_uploaded", key=key)
    return key
