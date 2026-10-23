from time import time

from cloudinary.utils import api_sign_request

from schemas.documents import UploadSignatureResponse
from utils.cloudinary import configure_cloudinary


def create_upload_signature(user_id: int) -> UploadSignatureResponse:
    config = configure_cloudinary()
    timestamp = int(time())
    folder = f"documents/{user_id}"
    params = {"timestamp": timestamp, "folder": folder}

    return UploadSignatureResponse(
        upload_url=f"https://api.cloudinary.com/v1_1/{config['cloud_name']}/raw/upload",
        cloud_name=config["cloud_name"],
        api_key=config["api_key"],
        timestamp=timestamp,
        folder=folder,
        signature=api_sign_request(params, config["api_secret"]),
    )
