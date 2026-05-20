# LaTeX templates

NexScout renders the tailored resume and (when needed) the cover letter
through Jinja2 templates that output LaTeX, then compiles the LaTeX with
**tectonic**, **latexmk**, or **pdflatex** in that preference order. The
engine and templates live in `src/nexscout/scoring/render/`.

## Jinja2 delimiters

Standard Jinja2 delimiters (`{{ }}` and `{% %}`) collide with LaTeX's own use
of `{` and `}`. NexScout configures the Jinja2 environment with non-default
delimiters so the templates can be written in clean LaTeX:

```python
env = Environment(
    block_start_string="<%",   block_end_string="%>",
    variable_start_string="<<", variable_end_string=">>",
    comment_start_string="<#", comment_end_string="#>",
    autoescape=False,
)
env.filters["tex"]   = latex_escape            # escapes & % $ # _ { } ~ ^ \
env.filters["money"] = lambda n, c: f"{c}{n:,}"
```

So a template line looks like:

```latex
\textbf{<< me.legal | tex >>} \\
\href{mailto:<< me.email >>}{<< me.email >>}
```

## Context shape

Both resume templates accept the same context dict, produced by
`scoring/tailor.py`:

```python
{
    "me": profile.me,                # Pydantic model: legal, pref, email, ...
    "title": data["title"],          # str: tailored target title
    "summary": data["summary"],      # str: 2-3 sentence tailored summary
    "skills": data["skills"],        # dict[str, str]: category -> comma list
    "experience": data["experience"],# list of {header, subtitle, bullets[]}
    "projects": data["projects"],    # list of {header, subtitle, bullets[]}
    "education": data["education"],  # str: "<school> | <degree>"
    "today": "2026-05-21",           # ISO date
}
```

The cover letter context is:

```python
{
    "me": profile.me,
    "company": job["site"],
    "title": job["title"],
    "body": cover_letter_text,       # full paragraphs, ASCII-sanitised
    "today": "2026-05-21",
}
```

## Bundled templates

Two starters ship under `src/nexscout/scoring/render/templates/`:

- **`resume_classic.tex.j2`** — single-column, Latin Modern Roman, A4.
  Sections: SUMMARY, TECHNICAL SKILLS, EXPERIENCE, PROJECTS, EDUCATION.
  Uses `enumitem` for tight bullet spacing; `hyperref` for clickable
  email/LinkedIn.
- **`resume_modern.tex.j2`** — two-column, TeX Gyre Heros. Left rail:
  contact + skills. Right column: summary, experience, projects, education.
- **`cover_letter.tex.j2`** — block-form letter, name + contact header,
  salutation, three paragraphs, sign-off.

## Filters

| Filter   | Effect                                                   |
|----------|----------------------------------------------------------|
| `tex`    | Escapes the LaTeX special characters `& % $ # _ { } ~ ^ \\` |
| `money`  | `\| money(c)` -> `"{c}{n:,}"` e.g. `165000 \| money("$")` -> `$165,000` |

## Adding a custom template

1. Drop your `.tex.j2` file into `src/nexscout/scoring/render/templates/`.
2. Set `profile.apply.resume_template` to the filename (without `.tex.j2`).
3. The engine will pick it up on the next render. The same context dict
   above is provided — no code change needed unless you want new context
   keys, in which case add them to the dict in `scoring/tailor.py`.

## Engine selection

`scoring/render/engine.py` checks the PATH in this order:

1. **Tectonic.** `tectonic --keep-logs -o <dir> <file>.tex`. Preferred — it
   downloads packages lazily and is fully self-contained.
2. **latexmk.** `latexmk -pdf -interaction=nonstopmode -outdir=<dir> <file>.tex`.
3. **pdflatex.** `pdflatex -interaction=nonstopmode -output-directory=<dir>
   <file>.tex`, run twice for cross-references.

`nexscout doctor` reports which engines are available. The Tier 3 (apply)
requirement is that at least one engine is on PATH.
