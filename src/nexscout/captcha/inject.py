"""Verbatim §15.4 injection JS for each CAPTCHA kind."""

# ruff: noqa: E501 — verbatim JS strings from plan.md cannot be reformatted.

from __future__ import annotations

import json
from typing import Any, Protocol

from ..core.errors import CaptchaUnsolvable
from .base import CaptchaKind

# Verbatim §15.4 snippets. ``THE_TOKEN`` is replaced by a JSON-encoded literal
# at call time so single-quote / backslash safety is guaranteed.
RECAPTCHA_INJECT_JS = """(token => {
    document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => { el.value = token; el.style.display = 'block'; });
    if (window.___grecaptcha_cfg) {
      const clients = window.___grecaptcha_cfg.clients;
      for (const k in clients) {
        const walk = (o,d)=>{ if (d>4||!o) return; for (const k in o) {
          if (typeof o[k] === 'function' && k.length < 3) try { o[k](token); } catch(e){}
          else if (typeof o[k] === 'object') walk(o[k], d+1);
        }}; walk(clients[k], 0);
      }
    }
  })('THE_TOKEN');"""

HCAPTCHA_INJECT_JS = """(token => {
    const ta = document.querySelector('[name="h-captcha-response"], textarea[name*="hcaptcha"]');
    if (ta) ta.value = token;
    document.querySelectorAll('iframe[data-hcaptcha-response]').forEach(f => f.setAttribute('data-hcaptcha-response', token));
  })('THE_TOKEN');"""

TURNSTILE_INJECT_JS = """(token => {
    const inp = document.querySelector('[name="cf-turnstile-response"], input[name*="turnstile"]');
    if (inp) inp.value = token;
  })('THE_TOKEN');"""

FUNCAPTCHA_INJECT_JS = """(token => {
    const inp = document.querySelector('#FunCaptcha-Token, input[name="fc-token"]');
    if (inp) inp.value = token;
    if (window.ArkoseEnforcement) try { window.ArkoseEnforcement.setConfig({data:{blob:token}}); } catch(e){}
  })('THE_TOKEN');"""


INJECT_JS: dict[str, str] = {
    "recaptchav2": RECAPTCHA_INJECT_JS,
    "recaptchav3": RECAPTCHA_INJECT_JS,
    "hcaptcha": HCAPTCHA_INJECT_JS,
    "turnstile": TURNSTILE_INJECT_JS,
    "funcaptcha": FUNCAPTCHA_INJECT_JS,
}


class _DriverLike(Protocol):
    def execute_script(self, script: str, *args: Any) -> Any: ...


def build_inject_script(kind: CaptchaKind, token: str) -> str:
    """Substitute the token into the per-kind verbatim JS snippet."""
    if kind not in INJECT_JS:
        raise CaptchaUnsolvable(f"no injector for CAPTCHA kind: {kind!r}")
    # json.dumps escapes quotes/backslashes/control chars — token literal is
    # always JS-safe, regardless of provider quirks.
    literal = json.dumps(token)
    snippet = INJECT_JS[kind]
    return snippet.replace("'THE_TOKEN'", literal)


def inject(driver: _DriverLike, kind: CaptchaKind, token: str) -> None:
    """Run the per-kind injector JS via ``driver.execute_script``."""
    driver.execute_script(build_inject_script(kind, token))
