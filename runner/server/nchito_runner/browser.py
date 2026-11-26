"""Playwright tool layer. Every action goes through the Guard first.

The model never gets a selector or script surface: it names elements by the ``ref`` numbers a
snapshot assigned, and page text only ever leaves this module wrapped by ``wrap_untrusted``.
Network-level backstops (the guard also checks before each action):

* every document navigation, in any frame or popup, is checked against the allowed domains;
* a document-level POST (a classic form submit) is aborted unless the permitted submit click
  is in flight;
* a capture-phase ``submit`` listener cancels in-page submit events outside that window.

A multi-step form's submit-type "Next" (``Guard.is_next_step``) lets the page's own submit handler run (it
moves to the next step), while the network backstop stays closed: if that click would post the form to the
server after all, the post is aborted and the click is refused as a submit without a permit.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page, Playwright, Route, async_playwright

from .guard import ElementInfo, Guard, RailViolation
from .untrusted import wrap_untrusted

_INIT_SCRIPT = """
window.__nchitoSubmitOk = false;
document.addEventListener('submit', function (e) {
  if (!window.__nchitoSubmitOk) { e.preventDefault(); e.stopImmediatePropagation(); window.__nchitoBlockedSubmit = true; }
}, true);
"""

_COLLECT_JS = """
() => {
  const sel = 'input, textarea, select, button, a[href], [role=button], [role=checkbox], [role=radio], [contenteditable=true]';
  document.querySelectorAll('[data-nchito-ref]').forEach(e => e.removeAttribute('data-nchito-ref'));
  const out = []; let n = 0;
  const labelOf = (el) => {
    const bits = [];
    if (el.labels) for (const l of el.labels) bits.push(l.innerText);
    const wrap = el.closest('label'); if (wrap) bits.push(wrap.innerText);
    for (const a of ['aria-label', 'placeholder', 'title']) { const v = el.getAttribute(a); if (v) bits.push(v); }
    const by = el.getAttribute('aria-labelledby');
    if (by) for (const id of by.split(/\\s+/)) { const t = document.getElementById(id); if (t) bits.push(t.innerText); }
    return bits.join(' | ').replace(/\\s+/g, ' ').trim().slice(0, 300);
  };
  for (const el of document.querySelectorAll(sel)) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const visible = !!(el.offsetParent || el.getClientRects().length) || type === 'file';
    if (!visible || type === 'hidden') continue;
    n += 1; el.setAttribute('data-nchito-ref', String(n));
    const tag = el.tagName.toLowerCase();
    const isPw = type === 'password';
    const item = { ref: n, tag, type, name: el.getAttribute('name') || '', label: labelOf(el),
      text: tag === 'select' ? '' : (el.innerText || '').trim().slice(0, 120),
      required: !!el.required, disabled: !!el.disabled };
    if (isPw) { item.typing_forbidden = true; item.value = ''; }
    else if (tag === 'select') {
      item.options = Array.from(el.options).map(o => ({ label: o.label, value: o.value })).slice(0, 80);
      item.value = el.value;
    } else if (type === 'checkbox' || type === 'radio') { item.checked = !!el.checked; item.value = el.value; }
    else if (type !== 'file' && tag !== 'button' && tag !== 'a') item.value = (el.value || '').slice(0, 200);
    if (tag === 'a') item.href = el.href;
    out.push(item);
  }
  return { title: document.title, url: location.href, elements: out,
           text: (document.body ? document.body.innerText : '').replace(/\\n{3,}/g, '\\n\\n').slice(0, 8000),
           blockedSubmit: !!window.__nchitoBlockedSubmit };
}
"""

_INFO_JS = """
(el) => {
  const target = el.closest('button, input, a, [role=button]') || el;
  const labels = target.labels ? Array.from(target.labels).map(l => l.innerText).join(' ') : '';
  const form = target.form || target.closest('form');
  let stepCurrent = 0, stepTotal = 0, hiddenRequired = 0;
  const stepOf = (text) => (text || '').match(/step\\s+(\\d+)\\s*(?:of|\\/)\\s*(\\d+)/i);
  const m = stepOf(form ? form.innerText : '') || stepOf(document.body ? document.body.innerText : '');
  if (m) { stepCurrent = parseInt(m[1], 10); stepTotal = parseInt(m[2], 10); }
  if (form) {
    for (const f of form.querySelectorAll('input, select, textarea')) {
      const t = (f.getAttribute('type') || '').toLowerCase();
      if (['hidden', 'submit', 'button', 'image', 'reset'].includes(t)) continue;
      const required = f.required || f.getAttribute('aria-required') === 'true';
      const shown = !!(f.offsetParent || f.getClientRects().length);
      if (required && !shown) hiddenRequired += 1;
    }
  }
  return { tag: target.tagName.toLowerCase(), type: (target.getAttribute('type') || '').toLowerCase(),
    name: target.getAttribute('name') || '', id: target.id || '',
    autocomplete: target.getAttribute('autocomplete') || '',
    label: (labels + ' ' + (target.getAttribute('aria-label') || '') + ' ' + (target.getAttribute('placeholder') || '')).trim(),
    text: (target.innerText || '').trim().slice(0, 200), value: (target.value || '').toString().slice(0, 200),
    role: target.getAttribute('role') || '', in_form: !!form,
    contenteditable: target.isContentEditable === true,
    step_current: stepCurrent, step_total: stepTotal, hidden_required: hiddenRequired };
}
"""


class BrowserSession:
    def __init__(self, guard: Guard, profile_dir: Path, *, headless: bool = True):
        self.guard = guard
        self.profile_dir = profile_dir
        self.headless = headless
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(self.profile_dir), headless=self.headless, accept_downloads=False,
            args=["--no-sandbox"] if self._in_container() else [],
        )
        await self._ctx.add_init_script(_INIT_SCRIPT)
        await self._ctx.route("**/*", self._route)
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()

    @staticmethod
    def _in_container() -> bool:
        return Path("/.dockerenv").exists()

    async def close(self) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()
        self._ctx = self._pw = self._page = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("browser not started")
        return self._page

    # ----- network backstops ----------------------------------------------------------
    async def _route(self, route: Route) -> None:
        req = route.request
        if req.is_navigation_request():
            try:
                self.guard.check_url(req.url)
            except RailViolation as v:
                self.guard.violations.append(v)
                await route.abort("blockedbyclient")
                return
            if req.method.upper() not in {"GET", "HEAD"} and not self.guard.submit_window_open:
                self.guard.violations.append(RailViolation("submit_without_permit", f"blocked {req.method} to {req.url}"))
                await route.abort("blockedbyclient")
                return
        await route.continue_()

    def take_violations(self) -> list[RailViolation]:
        v, self.guard.violations = self.guard.violations, []
        return v

    # ----- reading ---------------------------------------------------------------------
    async def snapshot(self) -> tuple[str, dict[str, Any]]:
        """Returns (untrusted-wrapped text for the model, raw data for the tool layer)."""
        data = await self.page.evaluate(_COLLECT_JS)
        body = json.dumps({"title": data["title"], "elements": data["elements"], "visible_text": data["text"]},
                          ensure_ascii=False, indent=1)
        return wrap_untrusted(data["url"], body), data

    async def url(self) -> str:
        return self.page.url

    async def _info(self, ref: int) -> tuple[Any, ElementInfo]:
        loc = self.page.locator(f'[data-nchito-ref="{int(ref)}"]')
        if await loc.count() != 1:
            raise RailViolation("no_such_element", f"ref {ref} is not on the page; take a new snapshot")
        raw = await loc.evaluate(_INFO_JS)
        return loc, ElementInfo(**raw)

    # ----- acting (each goes through the guard first) -----------------------------------
    async def open(self, url: str) -> None:
        self.guard.check_url(url)
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:  # an aborted navigation surfaces as a Playwright error
            if self.guard.violations:
                raise self.guard.violations[-1] from exc
            raise
        self._raise_pending_violation()

    def _raise_pending_violation(self) -> None:
        if self.guard.violations:
            raise self.guard.violations[-1]

    async def fill(self, ref: int, value: str) -> ElementInfo:
        loc, info = await self._info(ref)
        self.guard.check_type(info)
        await loc.fill(value, timeout=10_000)
        return info

    async def select(self, ref: int, value: str) -> ElementInfo:
        loc, info = await self._info(ref)
        if info.tag != "select":
            raise RailViolation("not_a_select", f"<{info.tag}> is not a select")
        if self.guard.is_password_field(info):
            raise RailViolation("password_field", "not allowed")
        try:
            await loc.select_option(label=value, timeout=5_000)
        except Exception:
            await loc.select_option(value=value, timeout=5_000)
        return info

    async def set_checked(self, ref: int, checked: bool) -> ElementInfo:
        loc, info = await self._info(ref)
        if info.type not in {"checkbox", "radio"}:
            raise RailViolation("not_a_checkbox", f"<{info.tag} type={info.type}> is not a checkbox or radio")
        await loc.set_checked(checked, timeout=5_000)
        return info

    async def upload(self, ref: int, path: Path) -> ElementInfo:
        loc, info = await self._info(ref)
        if info.tag != "input" or info.type != "file":
            raise RailViolation("not_a_file_input", "ref is not a file input")
        await loc.set_input_files(str(path), timeout=10_000)
        return info

    async def press(self, key: str) -> None:
        self.guard.check_key(key)
        await self.page.keyboard.press(key)

    async def click(self, ref: int, before_submit: Callable[[], Awaitable[None]] | None = None) -> tuple[ElementInfo, bool]:
        """Returns (element info, was_submit). A submit control needs a held, live permit."""
        loc, info = await self._info(ref)
        if not self.guard.is_submit_control(info):
            next_step = self.guard.submits_by_markup(info)  # a submit-type "Next" with more steps to come
            seen = len(self.guard.violations)
            if next_step:
                await self.page.evaluate("window.__nchitoSubmitOk = true")  # the page's step handler may run
            try:
                await loc.click(timeout=10_000)
                await self._settle()
            finally:
                if next_step:
                    with contextlib.suppress(Exception):
                        await self.page.evaluate("window.__nchitoSubmitOk = false")
            self._raise_new_violation(seen)
            return info, False
        self.guard.authorise_submit()  # raises RailViolation when no usable permit; consumes it
        if before_submit:
            await before_submit()  # durable "submit attempted" checkpoint BEFORE the click
        self.guard.submit_window_open = True
        await self.page.evaluate("window.__nchitoSubmitOk = true")
        try:
            await loc.click(timeout=10_000)
            await self._settle()
        finally:
            self.guard.submit_window_open = False
            with contextlib.suppress(Exception):  # the page navigated away; the flag dies with it
                await self.page.evaluate("window.__nchitoSubmitOk = false")
        return info, True

    def _raise_new_violation(self, seen: int) -> None:
        """A click that led off the domain, or posted the form without a permit (it was aborted)."""
        new = self.guard.violations[seen:]
        for kind in ("off_domain", "submit_without_permit"):
            hit = next((v for v in new if v.kind == kind), None)
            if hit is not None:
                if kind == "submit_without_permit":
                    self.guard.violations = self.guard.violations[:seen]
                    raise RailViolation(kind, "that control posted the form, so it counts as the submit; it was "
                                              "stopped before anything was sent")
                raise hit

    async def _settle(self) -> None:
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=5_000)
            await self.page.wait_for_timeout(300)
        except Exception:
            pass

    async def screenshot(self, max_bytes: int) -> tuple[bytes, str]:
        """Evidence of the page as (bytes, content type): a full-page PNG, or a smaller JPEG of the viewport when
        the PNG is over ``max_bytes`` (the gateway's ``evidence_max_bytes``). Nothing is kept on disk."""
        try:
            png = await self.page.screenshot(full_page=True, type="png")
        except Exception:  # a full-page capture can fail while the page re-lays out: take the viewport
            png = await self.page.screenshot(full_page=False, type="png")
        if len(png) <= max_bytes:
            return png, "image/png"
        for quality in (70, 45, 25):
            jpg = await self.page.screenshot(full_page=False, type="jpeg", quality=quality)
            if len(jpg) <= max_bytes:
                return jpg, "image/jpeg"
        raise ValueError(f"the screenshot is larger than the gateway's {max_bytes} byte limit")
