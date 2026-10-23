import os
from pathlib import Path
from time import time

import cloudinary
from cloudinary.utils import private_download_url
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def configure_cloudinary() -> dict[str, str]:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not all((cloud_name, api_key, api_secret)):
        raise RuntimeError("Cloudinary environment variables are required.")

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )

    return {
        "cloud_name": cloud_name,
        "api_key": api_key,
        "api_secret": api_secret,
    }


def create_signed_raw_download_url(public_id: str, file_format: str) -> str:
    cloudinary_config = configure_cloudinary()
    return private_download_url(
        public_id,
        file_format,
        resource_type="raw",
        type="upload",
        expires_at=int(time()) + 300,
        **cloudinary_config,
    )
