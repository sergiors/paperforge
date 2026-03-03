import os
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from types_boto3_s3.client import S3Client
else:
    S3Client = object


@lru_cache
def get_s3_client() -> S3Client:
    return boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
