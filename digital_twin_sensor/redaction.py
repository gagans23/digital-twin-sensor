from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\w)"
)
URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
SECRET_RE = re.compile(
    r"(?i)\b(?:"
    r"sk-[a-z0-9_-]{16,}|"
    r"gh[pousr]_[a-z0-9_]{16,}|"
    r"xox[baprs]-[a-z0-9-]{16,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r")\b"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    findings: dict[str, int]


def _luhn_valid(digits: str) -> bool:
    total = 0
    double = False
    for char in reversed(digits):
        value = ord(char) - ord("0")
        if double:
            value *= 2
            if value > 9:
                value -= 9
        total += value
        double = not double
    return total % 10 == 0


def _replace_counted(
    text: str,
    regex: re.Pattern[str],
    label: str,
    findings: dict[str, int],
    repl: str | Callable[[re.Match[str]], str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        findings[label] = findings.get(label, 0) + 1
        return repl(match) if callable(repl) else repl

    return regex.sub(replace, text)


def _redact_url(match: re.Match[str]) -> str:
    value = match.group(0)
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[url]"

    host = parsed.hostname or "url"
    if parsed.scheme and host:
        return f"{parsed.scheme}://{host}/[redacted-path]"
    return "[url]"


def _redact_cards(text: str, findings: dict[str, int]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        digits = re.sub(r"\D", "", value)
        if len(digits) < 13 or len(digits) > 19 or not _luhn_valid(digits):
            return value
        findings["credit_card"] = findings.get("credit_card", 0) + 1
        return "[credit-card]"

    return CARD_CANDIDATE_RE.sub(replace, text)


def _redact_configured_names(text: str, config: dict[str, Any], findings: dict[str, int]) -> str:
    terms = config.get("name_terms_to_mask", [])
    for term in sorted({str(item).strip() for item in terms}, key=len, reverse=True):
        if len(term) < 3:
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(term)}(?![A-Za-z0-9_-])", re.IGNORECASE)
        text = _replace_counted(text, pattern, "name", findings, "[name]")
    return text


def redact_text(text: str, config: dict[str, Any]) -> RedactionResult:
    if not text or not config.get("mask_pii", True):
        return RedactionResult(text=text, findings={})

    findings: dict[str, int] = {}
    output = text

    output = _replace_counted(output, SECRET_RE, "secret", findings, "[secret]")
    output = _redact_cards(output, findings)
    output = _replace_counted(output, EMAIL_RE, "email", findings, "[email]")
    output = _replace_counted(output, SSN_RE, "ssn", findings, "[ssn]")
    output = _replace_counted(output, PHONE_RE, "phone", findings, "[phone]")

    if config.get("mask_ip_addresses", True):
        output = _replace_counted(output, IPV4_RE, "ip_address", findings, "[ip-address]")

    if config.get("redact_url_paths", True):
        output = _replace_counted(output, URL_RE, "url", findings, _redact_url)

    if config.get("mask_configured_names", True):
        output = _redact_configured_names(output, config, findings)

    return RedactionResult(text=output, findings=findings)
