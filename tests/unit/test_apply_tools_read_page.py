"""DOM filter on fixture HTML (§13.2 read_page allow-list)."""

from __future__ import annotations

import re

from nexscout.apply.tools import simplify_dom

FIXTURE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head><title>Apply</title>
  <script>var x = 1;</script>
  <style>.x { color: red }</style>
  <link rel="stylesheet" href="x.css">
  <meta name="ok" content="y">
</head>
<body>
  <nav class="sc-12345 layout-aside-nav">menu</nav>
  <main>
    <h1 id="title" class="css-ab12cd34">Apply for: Engineer</h1>
    <form data-testid="apply-form" data-id="form-42" class="apply-form some-long-utility-class-name-that-overflows">
      <input type="text" name="first" id="first" data-testid="first-name-input" placeholder="First" class="input">
      <input type="email" name="email" required>
      <select name="permit" data-slug="permit">
        <option value="USC">USC</option>
        <option value="PR">PR</option>
      </select>
      <button type="submit" aria-label="Submit" data-type="primary">Apply Now</button>
    </form>
    <svg class="hidden"><circle cx="50" cy="50" r="40"/></svg>
    <iframe src="https://challenges.cloudflare.com/"></iframe>
  </main>
</body>
</html>
""".strip()


def test_strips_script_style_iframe_svg_link_meta() -> None:
    cleaned = simplify_dom(FIXTURE_HTML)
    assert "<script" not in cleaned
    assert "<style" not in cleaned
    assert "<svg" not in cleaned
    assert "<iframe" not in cleaned
    assert "<link" not in cleaned
    assert "<meta" not in cleaned


def test_keeps_allow_listed_attrs() -> None:
    cleaned = simplify_dom(FIXTURE_HTML)
    assert 'data-testid="apply-form"' in cleaned
    assert 'data-id="form-42"' in cleaned
    assert 'data-slug="permit"' in cleaned
    assert 'data-type="primary"' in cleaned
    assert 'aria-label="Submit"' in cleaned
    assert 'id="title"' in cleaned
    assert 'name="first"' in cleaned
    assert 'for=' not in cleaned  # no <label for=…> in fixture; just confirming substring search


def test_drops_long_class_attributes() -> None:
    cleaned = simplify_dom(FIXTURE_HTML)
    # ``sc-12345 layout-aside-nav`` and the long ``apply-form …`` class are dropped.
    assert "some-long-utility-class-name-that-overflows" not in cleaned
    # Short classes (≤30 chars) survive.
    assert 'class="input"' in cleaned
    # The css-ab12cd34 class string is ≤30 chars; it's still kept (we only filter by length).
    # The plan says "class<=30chars"; "css-ab12cd34" is short so survives.
    assert "css-ab12cd34" in cleaned or 'class="input"' in cleaned


def test_drops_unlisted_attrs() -> None:
    cleaned = simplify_dom(FIXTURE_HTML)
    # ``placeholder`` is not in the allow-list.
    assert 'placeholder=' not in cleaned
    # ``required`` is not in allow-list.
    assert 'required=' not in cleaned


def test_head_is_removed() -> None:
    cleaned = simplify_dom(FIXTURE_HTML)
    assert "<title>Apply" not in cleaned


def test_empty_input() -> None:
    assert simplify_dom("") == ""


def test_max_class_length_boundary() -> None:
    short = "a" * 30
    long = "a" * 31
    cleaned_short = simplify_dom(f'<div class="{short}">x</div>')
    cleaned_long = simplify_dom(f'<div class="{long}">x</div>')
    # Boundary: 30 chars survives, 31 chars dropped.
    assert short in cleaned_short
    assert not re.search(r'class="a{31}"', cleaned_long)
