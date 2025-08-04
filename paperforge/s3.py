import logging
import sys
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, stream=sys.stdout)


def download_from_s3(s3_uri: str, *, s3_client) -> str:
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')

    logger.info(f'Downloading from S3 {s3_uri}')

    with NamedTemporaryFile(delete=False, suffix='.html') as tmp_file:
        logger.debug(f'Temporary file created {tmp_file.name}')
        s3_client.download_fileobj(bucket, key, tmp_file)
        logger.info('Download successful')

        return tmp_file.name
