# Record preview components

Record preview helpers, templates and viewer integration are adapted from
Safebox Web, Copyright (c) 2026 Tim Bouma, MIT licensed (see LICENSE).

The bundled PDF.js files retain their Mozilla Foundation Apache-2.0 notices.
Standard fonts and their license files are retained in app/static/standard_fonts.
The preview viewer uses locally served assets, with no external CDN requests.

## PDF.js browser compatibility

The wallet and POS both serve the official **pdfjs-dist 5.4.624 legacy build**
(`legacy/build/pdf.mjs` and `legacy/build/pdf.worker.mjs`). This is the same
PDF.js release as before, with upstream compatibility shims for older browsers,
including Chrome 138's missing Uint8Array base64/hex methods. Both the main
library and worker must be updated together. Do not replace just one file or
silently switch back to the modern build. Only trailing whitespace in upstream
bundler comments has been normalized; runtime code is unchanged. Cache-versioned imports ensure a
rebuilt app does not reuse the previously served modern assets.

Source: https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-5.4.624.tgz

Verified npm package integrity:

```text
sha512-sm6TxKTtWv1Oh6n3C6J6a8odejb5uO4A4zo/2dgkHuC0iu8ZMAXOezEODkVaoVp8nX1Xzr+0WxFJJmUr45hQzg==
```

The upstream Apache-2.0 license is retained in
`app/static/PDFJS-LICENSE.txt`, alongside the inline copyright notices.
No remote viewer, CDN, or third-party document upload is used. The compatibility
build serves wallet previews, attachment-upload previews, and POS presentations.
Rebuild both app and POS to deploy. Device-specific PDF rendering still needs a
live check on the target phone; compatibility tests do not guarantee every PDF
or older Android device will render successfully.
