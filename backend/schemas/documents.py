from pydantic import BaseModel


class UploadSignatureResponse(BaseModel):
    upload_url: str
    cloud_name: str
    api_key: str
    timestamp: int
    folder: str
    signature: str
