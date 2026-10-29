"""Amount parsing. Receipts arrive as free text in four currencies and two
decimal conventions, often with UTF-8 read as Latin-1 ("â¬", "Â£").
Everything is stored as integer minor units."""
from __future__ import annotations
import re

SIGN_TO_CODE = {"€": "EUR", "£": "GBP", "$": "USD"}
CODES = ("EUR", "GBP", "USD", "HKD", "CHF")
_NUM = re.compile(r"[-+]?\d[\d.,\s ]*")


def fix_mojibake(s: str) -> str:
    """Undo UTF-8 bytes that were decoded as Latin-1 or CP1252."""
    if not s:
        return s
    if any(ch in s for ch in ("â", "Â", "Ã", "ð")):
        for enc in ("latin-1", "cp1252"):
            try:
                fixed = s.encode(enc).decode("utf-8")
                if fixed != s:
                    return fixed
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
    return s


def detect_currency(s: str) -> str | None:
    s2 = fix_mojibake(s)
    if "HK$" in s2.upper():
        return "HKD"
    for sign, code in SIGN_TO_CODE.items():
        if sign in s2:
            return code
    up = s2.upper()
    for code in CODES:
        if re.search(rf"\b{code}\b", up) or up.startswith(code):
            return code
    return None


def _to_minor(num: str) -> int | None:
    num = num.replace(" ", "").replace(" ", "")
    neg = num.startswith("-")
    num = num.lstrip("+-")
    if not num:
        return None
    if "," in num and "." in num:
        dec = "," if num.rfind(",") > num.rfind(".") else "."
        num = num.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in num or "." in num:
        sep = "," if "," in num else "."
        head, tail = num.rsplit(sep, 1)
        if len(tail) == 2 and sep not in head:
            num = f"{head}.{tail}"
        elif len(tail) == 3:
            num = (head + tail).replace(sep, "")
        else:
            num = num.replace(sep, ".") if len(tail) <= 2 else num.replace(sep, "")
    try:
        value = round(float(num) * 100)
    except ValueError:
        return None
    return -value if neg else value


def parse_amount(s: str | None) -> tuple[int | None, str | None]:
    """Return (minor_units, currency). Either may be None."""
    if not s:
        return None, None
    s2 = fix_mojibake(s).strip()
    cur = detect_currency(s2)
    cleaned = s2.replace("HK$", "")
    m = _NUM.search(cleaned)
    if not m:
        return None, cur
    return _to_minor(m.group(0)), cur


def fmt(minor: int | None, cur: str | None) -> str:
    if minor is None:
        return "?"
    sign = "-" if minor < 0 else ""
    v = abs(minor)
    return f"{sign}{v // 100:,}.{v % 100:02d} {cur or ''}".strip()
