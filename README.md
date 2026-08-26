# Paperforge

Paperforge is a lightweight, self-hosted HTTP API for generating and digitally signing PDF documents. It renders HTML templates with Jinja2, converts them to PDF with WeasyPrint, and applies digital signatures using PKCS#12 (PFX) certificates.

## Features

- HTML to PDF conversion
- Jinja2 template rendering
- Multiple uploaded assets (CSS, images, fonts, etc.)
- PDF digital signing
- Multiple sequential signatures
- Simple HTTP API
- Docker-friendly
- Optional API key authentication

## Installation

### Docker

```sh
docker build -t paperforge .
docker run -p 8000:8000 paperforge
```

### Docker Compose

```sh
docker compose up -d
```

### Environment variables

| Variable  | Description                                                                         |
| --------- | ----------------------------------------------------------------------------------- |
| `API_KEY` | Optional API key. When set, requests must include it in the `Authorization` header. |

Authentication is disabled when `API_KEY` is not configured.

## Authentication

When `API_KEY` is configured, every request must include it as a Bearer token:

```http
Authorization: Bearer <API_KEY>
```

## API

### Convert HTML to PDF

```
POST /convert/html
```

Converts an uploaded HTML document to PDF.

The request is `multipart/form-data` with the following fields:

- `files` (required) — one or more files. Exactly one must be named `index.html`; it is the document entry point. Additional files (CSS, images, fonts, etc.) are available by relative path.
- `context` (optional) — a JSON object serialized as a string. When provided, `index.html` is rendered as a Jinja2 template using the object as its context.

```sh
curl \
  --request POST http://localhost:8000/convert/html \
  --header "Authorization: Bearer my-secret-api-key" \
  --form files=@index.html \
  --form files=@style.css \
  --form 'context={"name":"Sergio","company":"Paperforge"}' \
  --output document.pdf
```

### Sign PDF

```
POST /pdf/sign
```

Digitally signs an uploaded PDF with one or more PKCS#12 certificates.

The request is `multipart/form-data` with the following fields:

- `files` (required) — exactly one PDF document and one or more PKCS#12 (`.p12`/`.pfx`) certificates.
- `signers` (required) — a JSON array serialized as a string. Each object references an uploaded certificate by filename and provides its passphrase. Signatures are applied sequentially in order.

```sh
curl \
  --request POST http://localhost:8000/pdf/sign \
  --header "Authorization: Bearer my-secret-api-key" \
  --form files=@document.pdf \
  --form files=@company.p12 \
  --form 'signers=[{"file":"company.p12","passphrase":"secret"}]' \
  --output signed.pdf
```

## Error Responses

The API returns standard HTTP status codes. Failures are returned as JSON error responses with a descriptive message.

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE.md) for details.
