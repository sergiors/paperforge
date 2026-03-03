from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import AnyUrl, BaseModel, UrlConstraints

if TYPE_CHECKING:
    from types_boto3_s3.client import S3Client
else:
    S3Client = object

router = APIRouter()


class PfxSignature(BaseModel):
    pfx: Annotated[AnyUrl, UrlConstraints(allowed_schemes=['s3'])]
    passphrase: str


class SignRequest(BaseModel):
    pdf: Annotated[AnyUrl, UrlConstraints(allowed_schemes=['s3'])]
    signatures: list[PfxSignature]


def get_s3(request: Request) -> S3Client:
    return request.app.state.s3


@router.post('/sign')
async def sign(
    sign_request: SignRequest,
    s3_client: S3Client = Depends(get_s3),
):
    return {}
