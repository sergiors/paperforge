## Paperforge

Paperforge is a lightweight and efficient API for generating dynamic PDF documents from HTML templates using Jinja2 and WeasyPrint. It supports Amazon S3-based template storage and digital PDF signing using PKCS#12 (PFX) certificates.

## Database Schema

On startup the API calls `app.schema.setup()` to create the `pdfs` table from SQLModel metadata and install the Postgres pub/sub and trigger SQL.

## Python 3.14

If `uv sync` needs to build `pydantic-core` from source under Python 3.14, enable PyO3 forward compatibility:

```bash
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
uv sync
```

The Docker image already sets this flag during the build.

Or use the project shortcut:

```bash
make sync
```
