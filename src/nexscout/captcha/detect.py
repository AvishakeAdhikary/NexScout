"""Verbatim §15.1 detection script + Python helper."""

# ruff: noqa: E501 — verbatim JS strings from plan.md cannot be reformatted.

from __future__ import annotations

import time
from typing import Any, Protocol

# Verbatim §15.1 detection JS — module-level constant referenced by the
# helper below and surfaced for testing.
DETECT_JS = """(() => {
  const r = {}; const url = window.location.href;
  // 1. hCaptcha FIRST (hCaptcha uses data-sitekey too)
  const hc = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
  if (hc) { r.type = 'hcaptcha'; r.sitekey = hc.dataset.sitekey || hc.dataset.hcaptchaSitekey; }
  if (!r.type && document.querySelector('script[src*="hcaptcha.com"], iframe[src*="hcaptcha.com"]')) {
    const el = document.querySelector('[data-sitekey]');
    if (el) { r.type = 'hcaptcha'; r.sitekey = el.dataset.sitekey; }
  }
  // 2. Cloudflare Turnstile
  if (!r.type) {
    const cf = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
    if (cf) {
      r.type = 'turnstile'; r.sitekey = cf.dataset.sitekey || cf.dataset.turnstileSitekey;
      if (cf.dataset.action) r.action = cf.dataset.action;
      if (cf.dataset.cdata) r.cdata = cf.dataset.cdata;
    }
  }
  if (!r.type && document.querySelector('script[src*="challenges.cloudflare.com"]')) {
    r.type = 'turnstile_script_only'; r.note = 'Wait 3s and re-detect.';
  }
  // 3. reCAPTCHA v3
  if (!r.type) {
    const s = document.querySelector('script[src*="recaptcha"][src*="render="]');
    if (s) { const m = s.src.match(/render=([^&]+)/); if (m && m[1] !== 'explicit') { r.type = 'recaptchav3'; r.sitekey = m[1]; } }
  }
  // 4. reCAPTCHA v2
  if (!r.type) {
    const rc = document.querySelector('.g-recaptcha');
    if (rc) { r.type = 'recaptchav2'; r.sitekey = rc.dataset.sitekey; }
  }
  if (!r.type && document.querySelector('script[src*="recaptcha"]')) {
    const el = document.querySelector('[data-sitekey]'); if (el) { r.type = 'recaptchav2'; r.sitekey = el.dataset.sitekey; }
  }
  // 5. FunCaptcha (Arkose)
  if (!r.type) {
    const fc = document.querySelector('#FunCaptcha, [data-pkey], .funcaptcha');
    if (fc) { r.type = 'funcaptcha'; r.sitekey = fc.dataset.pkey; }
  }
  if (!r.type && document.querySelector('script[src*="arkoselabs"], script[src*="funcaptcha"]')) {
    const el = document.querySelector('[data-pkey]'); if (el) { r.type = 'funcaptcha'; r.sitekey = el.dataset.pkey; }
  }
  if (r.type) { r.url = url; return r; }
  return null;
})();"""


class _DriverLike(Protocol):
    def execute_script(self, script: str, *args: Any) -> Any: ...


def detect_in_driver(driver: _DriverLike, *, sleep: float = 3.0) -> dict[str, Any] | None:
    """Run ``DETECT_JS`` in the page. Re-runs after a sleep on ``turnstile_script_only``."""
    result = driver.execute_script(DETECT_JS)
    if not isinstance(result, dict):
        return None
    if result.get("type") == "turnstile_script_only":
        time.sleep(sleep)
        second = driver.execute_script(DETECT_JS)
        if isinstance(second, dict):
            return second
        return result
    return result
