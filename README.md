## Paperforge

Paperforge is a lightweight and efficient API for generating PDF documents from HTML templates using Jinja2 and WeasyPrint. It also supports digitally signing PDFs using PKCS#12 (PFX) certificates.

> **⚠️ Development Status**
> This project is under active development. APIs, configuration formats, and
> architecture decisions may change without prior notice. Use with caution in
> production environments.

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

To digitally sign a PDF, send a `multipart/form-data` request to `POST /pdf/sign`.

```sh
curl \
  --request POST http://localhost:8000/pdf/sign \
  --form files=@document.pdf \
  --form files=@company.p12 \
  --form 'signers=[{"file":"company.p12","passphrase":"secret"}]' \
  --output signed.pdf
```

Exactly one uploaded file must be a PDF document; the rest are the PKCS#12
certificates referenced by the `signers` array. Signatures are applied
sequentially in the order given.

The endpoint returns the signed PDF with the `application/pdf` content type.

## 📝 License

GNU General Public License v3.0 - see [LICENSE](LICENSE.md) for details.
