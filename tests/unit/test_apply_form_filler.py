"""Tests for ``apply.form_filler`` — ref-parsing + fill heuristics."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from nexscout.apply import form_filler

# ---------------------------------------------------------------------------
# parse_ref
# ---------------------------------------------------------------------------


def test_parse_ref_empty_defaults_to_wildcard() -> None:
    assert form_filler.parse_ref("") == ("css selector", "*")


def test_parse_ref_xpath() -> None:
    assert form_filler.parse_ref("//div[@id='x']")[0] == "xpath"


def test_parse_ref_xpath_alt_start() -> None:
    assert form_filler.parse_ref("(./div)")[0] == "xpath"


def test_parse_ref_hash_id() -> None:
    by, sel = form_filler.parse_ref("#first")
    assert by == "css selector" and sel == "#first"


def test_parse_ref_dot_class() -> None:
    by, _sel = form_filler.parse_ref(".btn")
    assert by == "css selector"


def test_parse_ref_bracket_attr() -> None:
    by, _sel = form_filler.parse_ref('[data-testid="x"]')
    assert by == "css selector"


def test_parse_ref_id_eq_shorthand() -> None:
    _by, sel = form_filler.parse_ref("id=foo")
    assert sel == "#foo"


def test_parse_ref_name_eq_shorthand() -> None:
    _by, sel = form_filler.parse_ref("name=bar")
    assert sel == '[name="bar"]'


def test_parse_ref_default_css() -> None:
    by, sel = form_filler.parse_ref("button.primary")
    assert by == "css selector"
    assert sel == "button.primary"


# ---------------------------------------------------------------------------
# find_one
# ---------------------------------------------------------------------------


def test_find_one_returns_element() -> None:
    drv = MagicMock()
    drv.find_element.return_value = "el"
    assert form_filler.find_one(drv, "#x") == "el"


def test_find_one_returns_none_on_exception() -> None:
    drv = MagicMock()
    drv.find_element.side_effect = RuntimeError("nope")
    assert form_filler.find_one(drv, "#x") is None


# ---------------------------------------------------------------------------
# fill_input
# ---------------------------------------------------------------------------


def _el(tag: str = "input", type_: str = "text") -> Any:
    el = MagicMock()
    el.tag_name = tag
    el.get_attribute.return_value = type_
    return el


def test_fill_input_missing_element(monkeypatch: Any) -> None:
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: None)
    assert form_filler.fill_input(MagicMock(), "#x", "v") is False


def test_fill_input_text(monkeypatch: Any) -> None:
    el = _el()
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    assert form_filler.fill_input(MagicMock(), "#x", "Jane")
    el.send_keys.assert_called_once_with("Jane")


def test_fill_input_select(monkeypatch: Any) -> None:
    el = _el(tag="select")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    monkeypatch.setattr(form_filler, "select_option", lambda d, r, v: True)
    assert form_filler.fill_input(MagicMock(), "#x", "USA")


def test_fill_input_checkbox(monkeypatch: Any) -> None:
    el = _el(type_="checkbox")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    monkeypatch.setattr(form_filler, "set_checkbox", lambda d, r, v: True)
    assert form_filler.fill_input(MagicMock(), "#x", "true")


def test_fill_input_radio(monkeypatch: Any) -> None:
    el = _el(type_="radio")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    monkeypatch.setattr(form_filler, "click", lambda d, r: True)
    assert form_filler.fill_input(MagicMock(), "#x", "y")


def test_fill_input_send_keys_fallback_to_js(monkeypatch: Any) -> None:
    el = _el()
    el.send_keys.side_effect = RuntimeError("boom")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    drv = MagicMock()
    drv.execute_script.return_value = True
    assert form_filler.fill_input(drv, "#x", "Jane")


def test_fill_input_coerces_bool_true_false(monkeypatch: Any) -> None:
    el = _el()
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    assert form_filler.fill_input(MagicMock(), "#x", True)
    el.send_keys.assert_called_with("true")

    el2 = _el()
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el2)
    assert form_filler.fill_input(MagicMock(), "#x", False)


def test_fill_input_coerces_none(monkeypatch: Any) -> None:
    el = _el()
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    form_filler.fill_input(MagicMock(), "#x", None)
    el.send_keys.assert_called_with("")


# ---------------------------------------------------------------------------
# _set_via_js
# ---------------------------------------------------------------------------


def test_set_via_js_xpath_rejected() -> None:
    drv = MagicMock()
    assert form_filler._set_via_js(drv, "//div", "v") is False


def test_set_via_js_handles_exception() -> None:
    drv = MagicMock()
    drv.execute_script.side_effect = RuntimeError("boom")
    assert form_filler._set_via_js(drv, "#x", "v") is False


def test_set_via_js_success() -> None:
    drv = MagicMock()
    drv.execute_script.return_value = True
    assert form_filler._set_via_js(drv, "#x", "v")


# ---------------------------------------------------------------------------
# select_option
# ---------------------------------------------------------------------------


def test_select_option_missing_element(monkeypatch: Any) -> None:
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: None)
    assert form_filler.select_option(MagicMock(), "#x", "v") is False


def test_select_option_custom_dropdown_js(monkeypatch: Any) -> None:
    el = _el(tag="div")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    drv = MagicMock()
    drv.execute_script.return_value = True
    assert form_filler.select_option(drv, "#x", "USA")


def test_select_option_custom_dropdown_js_returns_false(monkeypatch: Any) -> None:
    el = _el(tag="div")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    drv = MagicMock()
    drv.execute_script.return_value = False
    assert form_filler.select_option(drv, "#x", "USA") is False


def test_select_option_js_raises(monkeypatch: Any) -> None:
    el = _el(tag="div")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    drv = MagicMock()
    drv.execute_script.side_effect = RuntimeError("boom")
    assert form_filler.select_option(drv, "#x", "USA") is False


# ---------------------------------------------------------------------------
# set_checkbox
# ---------------------------------------------------------------------------


def test_set_checkbox_missing(monkeypatch: Any) -> None:
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: None)
    assert form_filler.set_checkbox(MagicMock(), "#x", True) is False


def test_set_checkbox_already_in_state(monkeypatch: Any) -> None:
    el = MagicMock()
    el.is_selected.return_value = True
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    assert form_filler.set_checkbox(MagicMock(), "#x", True)
    el.click.assert_not_called()


def test_set_checkbox_toggles(monkeypatch: Any) -> None:
    el = MagicMock()
    el.is_selected.return_value = False
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    assert form_filler.set_checkbox(MagicMock(), "#x", True)
    el.click.assert_called_once()


def test_set_checkbox_is_selected_raises(monkeypatch: Any) -> None:
    el = MagicMock()
    el.is_selected.side_effect = RuntimeError("nope")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    # Defaults `current` to False so True triggers a click.
    assert form_filler.set_checkbox(MagicMock(), "#x", True)


# ---------------------------------------------------------------------------
# click
# ---------------------------------------------------------------------------


def test_click_missing(monkeypatch: Any) -> None:
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: None)
    assert form_filler.click(MagicMock(), "#x") is False


def test_click_normal(monkeypatch: Any) -> None:
    el = MagicMock()
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    assert form_filler.click(MagicMock(), "#x")
    el.click.assert_called_once()


def test_click_fallback_to_js(monkeypatch: Any) -> None:
    el = MagicMock()
    el.click.side_effect = RuntimeError("nope")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    drv = MagicMock()
    drv.execute_script.return_value = None
    assert form_filler.click(drv, "#x")


def test_click_fallback_xpath_returns_false(monkeypatch: Any) -> None:
    el = MagicMock()
    el.click.side_effect = RuntimeError("nope")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    drv = MagicMock()
    assert form_filler.click(drv, "//div") is False


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------


def test_upload_missing(monkeypatch: Any) -> None:
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: None)
    assert form_filler.upload(MagicMock(), "#x", "/path") is False


def test_upload_send_keys(monkeypatch: Any) -> None:
    el = MagicMock()
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    assert form_filler.upload(MagicMock(), "#x", "/some/path")
    el.send_keys.assert_called_once_with("/some/path")


def test_upload_send_keys_failure(monkeypatch: Any) -> None:
    el = MagicMock()
    el.send_keys.side_effect = RuntimeError("nope")
    monkeypatch.setattr(form_filler, "find_one", lambda d, r: el)
    assert form_filler.upload(MagicMock(), "#x", "/path") is False


# ---------------------------------------------------------------------------
# fill_form
# ---------------------------------------------------------------------------


def test_fill_form_map(monkeypatch: Any) -> None:
    monkeypatch.setattr(form_filler, "fill_input", lambda d, r, v: r != "#bad")
    out = form_filler.fill_form(MagicMock(), {"#name": "Jane", "#bad": "x"})
    assert out == {"#name": True, "#bad": False}
