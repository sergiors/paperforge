## Paperforge

Paperforge is a lightweight and efficient API for generating PDF documents from HTML templates using Jinja2 and WeasyPrint. It also supports digitally signing PDFs using PKCS#12 (PFX) certificates.

To generate a PDF, send a `multipart/form-data` request to `POST /convert/html`.

```sh
curl \
  --request POST http://localhost:8000/convert/html \
  --form files=@index.html \
  --form 'context={"name":"Sergio"}' \
  --output invoice.pdf
```

The uploaded HTML entry point **must** be named `index.html`. Additional files uploaded using the same `files` form field (such as CSS, images, and fonts) are available to the document using their relative paths.

The endpoint returns the generated PDF with the `application/pdf` content type.
