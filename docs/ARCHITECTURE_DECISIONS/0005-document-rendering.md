# ADR-0005: Markdown-canonical documents rendered to PDF (Chromium) and DOCX (python-docx)

- **Status:** Accepted
- **Date:** 2026-10-16

## Context
Generated CVs, statements and letters must be editable, versioned and rendered deterministically to
PDF and DOCX (§5.5). The primary dev host is Windows. WeasyPrint needs GTK/Pango, which is fragile
there. Pandoc is an external binary that isn't installed.

## Decision
- The canonical source is Markdown with a restricted feature set (headings, paragraphs, lists,
  emphasis, links, simple tables) plus a YAML-like front-matter block for template and format settings.
- **PDF:** Markdown → HTML (markdown-it-py, HTML escaping on, raw HTML disabled) → a template with
  embedded CSS (page size, margins, fonts) → Playwright Chromium `page.pdf()`. Chromium is already
  required for browser automation.
- **DOCX:** our own renderer walks the markdown-it token stream and emits python-docx
  paragraphs, runs, lists and tables with named styles.
- **Validation:** pypdf (opens, page count within limits, text contains the required section headings),
  python-docx (opens, headings present), and a placeholder scan (`[[PLACEHOLDER:` remaining →
  status `needs_user_input`).

## Alternatives
Pandoc (best fidelity, extra binary to ship), WeasyPrint (GTK on Windows), LibreOffice headless
(heavy). Pandoc can be added later as an optional renderer.

## Consequences
- Rendering runs in the worker, not the API request.
- Font availability differs per OS. The templates use a bundled open font (to be added) or a safe
  fallback stack.

## As built (M5, 2026-10-17)
- `infrastructure/render.py`. There is no front-matter and no table support yet; tables render
  as plain paragraphs in DOCX.
- Chromium runs with JavaScript disabled, `offline=True` and every request aborted. Playwright's
  *sync* API runs in a worker thread because the worker's Selector event loop (required by
  psycopg on Windows) can't spawn subprocesses.
- Fonts: a serif fallback stack (Georgia / Times New Roman). No bundled font yet.
- Validation results are stored per version (`artifacts.pdf.checks`, `artifacts.docx.checks`) and
  shown in the UI. Placeholders are highlighted (yellow) in PDF and DOCX.
- The backend image installs `chromium-headless-shell` (`--with-deps`), which brings it to about
  2.1 GB.
