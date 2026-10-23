import os
from pathlib import Path

import cloudinary
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
