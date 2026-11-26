"""Hard rails, in code. Nothing here depends on what the model says or what the page says.

The browser layer asks the guard before every typing, click, upload and navigation. The guard
is pure (no Playwright), so every rule is unit-tested without a browser.

Rails (DESIGN.md 8.3, 18.1; CONTRACTS.md section 8):

1. Never type into a password field (by input type, autocomplete, or a password-like name/label).
2. Never navigate off the task's allowed domains (the posting's domain, from the task).
3. Never click the submit control unless a granted permit for this task is held in memory,
   unexpired and unused. A permit is consumed by the click (single use).
4. Uploads only from the packet's file URLs, with matching sha256, never to a ``never`` file.
5. Enter is refused: it submits a form without clicking the control.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit


class RailViolation(Exception):
    """A rail refused an action. ``kind`` is stable and goes into logs, tests and blockers."""

    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class ElementInfo:
    tag: str = ""
    type: str = ""
    name: str = ""
    id: str = ""
    autocomplete: str = ""
    label: str = ""
    text: str = ""
    value: str = ""
    role: str = ""
    in_form: bool = False
    contenteditable: bool = False


@dataclass
class HeldPermit:
    permit_id: str
    expires_at: datetime
    used: bool = False


_PASSWORD_NAME = re.compile(r"pass(word|wd|code)|(^|[^a-z])pwd([^a-z]|$)", re.I)
# Words that make a control "the" submit control whatever its markup says. A bare "Apply" link
# is navigation (Lever, Greenhouse), so it is only a submit when the markup makes it one.
_SUBMIT_TEXT = re.compile(r"\b(submit|send application|send my application|finish application|"
                          r"complete application|confirm and send)\b", re.I)
_ENTER_KEYS = {"enter", "numpadenter", "return"}


def normalise_domain(value: str) -> str:
    """'https://Jobs.Example.com:8080/x' or 'jobs.example.com' -> 'jobs.example.com'."""
    value = value.strip().lower()
    if "://" in value:
        value = urlsplit(value).hostname or ""
    return value.split("/")[0].split(":")[0].lstrip(".")


class Guard:
    def __init__(self, allowed_domains: list[str], *, now: Callable[[], datetime] | None = None,
                 permit_safety: timedelta = timedelta(seconds=15)):
        self.allowed = sorted({d for d in (normalise_domain(x) for x in allowed_domains) if d})
        if not self.allowed:
            raise ValueError("a task with no allowed domain cannot be worked")
        self._now = now or (lambda: datetime.now(UTC))
        self._safety = permit_safety
        self.permit: HeldPermit | None = None
        self.submit_window_open = False  # true only during the permitted click
        self.violations: list[RailViolation] = []

    # ----- navigation ---------------------------------------------------------------
    def domain_allowed(self, host: str | None) -> bool:
        host = (host or "").lower().rstrip(".")
        return any(host == d or host.endswith("." + d) for d in self.allowed)

    def check_url(self, url: str) -> None:
        if url == "about:blank":
            return
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            raise RailViolation("off_domain", f"scheme {parts.scheme or '(none)'!r} is not allowed")
        if not self.domain_allowed(parts.hostname):
            raise RailViolation("off_domain", f"{parts.hostname!r} is outside {self.allowed}")

    # ----- typing -------------------------------------------------------------------
    @staticmethod
    def is_password_field(el: ElementInfo) -> bool:
        if el.type.lower() == "password" or "password" in el.autocomplete.lower():
            return True
        return bool(_PASSWORD_NAME.search(" ".join((el.name, el.id, el.label))))

    def check_type(self, el: ElementInfo) -> None:
        if self.is_password_field(el):
            raise RailViolation("password_field", "typing into a password field is never allowed; raise a sign_in blocker")
        if el.tag not in {"input", "textarea"} and not el.contenteditable:
            raise RailViolation("not_typeable", f"<{el.tag}> cannot be typed into")
        if el.type.lower() in {"file", "submit", "button", "image", "reset", "hidden"}:
            raise RailViolation("not_typeable", f"input type {el.type!r} cannot be typed into")

    # ----- submit -------------------------------------------------------------------
    @staticmethod
    def is_submit_control(el: ElementInfo) -> bool:
        etype = el.type.lower()
        if el.tag == "input" and etype in {"submit", "image"}:
            return True
        if el.tag == "button" and (etype == "submit" or (etype == "" and el.in_form)):
            return True
        text = " ".join((el.text, el.value, el.label, el.name, el.id))
        return bool(_SUBMIT_TEXT.search(text)) and (el.tag in {"button", "input"} or el.role == "button")

    def hold_permit(self, permit_id: str, expires_at: datetime) -> None:
        self.permit = HeldPermit(permit_id, expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC))

    def permit_usable(self) -> bool:
        p = self.permit
        return bool(p and not p.used and self._now() < p.expires_at - self._safety)

    def authorise_submit(self) -> HeldPermit:
        """Called at the moment of the click. Consumes the permit (single use)."""
        if not self.permit_usable():
            why = "no permit held" if not self.permit else "permit used" if self.permit.used else "permit expired"
            raise RailViolation("submit_without_permit", f"{why}: call request_submit_permit and wait for 'granted'")
        assert self.permit is not None
        self.permit.used = True
        return self.permit

    def check_key(self, key: str) -> None:
        if key.strip().lower() in _ENTER_KEYS:
            raise RailViolation("enter_submits", "Enter can submit a form; click the control instead")

    # ----- uploads ------------------------------------------------------------------
    @staticmethod
    def check_upload(file_name: str, packet_files: dict[str, dict]) -> dict:
        f = packet_files.get(file_name)
        if f is None:
            raise RailViolation("upload_not_in_packet", f"{file_name!r} is not a packet file")
        if f.get("attach_rule") == "never":
            raise RailViolation("upload_forbidden", f"{file_name!r} must never be attached")
        return f
