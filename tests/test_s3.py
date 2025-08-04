import os

import boto3
from paperforge.s3 import download_from_s3

s3 = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION'),
)


def test_download_from_s3():
    s = download_from_s3('s3://saladeaula.digital/billing/template.html', s3_client=s3)
    print(s)
