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
