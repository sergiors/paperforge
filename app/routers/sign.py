from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import AnyUrl, BaseModel, UrlConstraints

from ..boto3clients import S3Client, get_s3_client

router = APIRouter()


class PfxSignature(BaseModel):
    pfx: Annotated[AnyUrl, UrlConstraints(allowed_schemes=['s3'])]
    passphrase: str


class SignRequest(BaseModel):
    pdf: Annotated[AnyUrl, UrlConstraints(allowed_schemes=['s3'])]
    signatures: list[PfxSignature]


@router.post('/sign')
async def sign(
    sign_request: SignRequest,
    s3_client: S3Client = Depends(get_s3_client),
):
    return {}
