import os

import uvicorn


def main() -> None:
    uvicorn.run(
        'app.main:app',
        host=os.getenv('HOST', '0.0.0.0'),
        port=int(os.getenv('PORT', '8000')),
        workers=int(os.getenv('WORKERS', '1')),
        log_level=os.getenv('LOG_LEVEL', 'info').lower(),
        forwarded_allow_ips=os.getenv('FORWARDED_ALLOW_IPS', None),
        loop=os.getenv('UVICORN_LOOP', 'auto'),
    )


if __name__ == '__main__':
    main()
