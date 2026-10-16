"""Store emails, committee part, v2. Only the date changes from v1: the committee copies what is
written (month, day and year if present) and the code builds the date.

Code (resolve_date), no LLM:
- drops a day, month or year that is not literally written in the email;
- with no year written, infers it: the first time that month and day falls on or after the order
  date recorded on chain (payment time in the escrow);
- if the email names a weekday, the date has to fall on one of the named days; otherwise it is empty;
- the date has to fall between the order date and 120 days later; otherwise it is empty.
The type question is the same as in mail_llm.py (same prompt text).
The prompt structure follows lacre/llmfields.py (github.com/eudomar500/lacre, MIT,
Copyright (c) 2026 Insidr Labs). Standard library only.
"""
import datetime
import hashlib
import json
import re

import mail_llm

TYPES, DATE_TYPES, HEADER = mail_llm.TYPES, mail_llm.DATE_TYPES, mail_llm.HEADER

DATE_RULES = HEADER + """
Question: the email may give a delivery date: the expected delivery date, the new estimated date,
or the date the order was delivered. Copy only what is written for that date.
Answer with one JSON object and nothing else: {"month": m, "day": d, "year": y}, where m is the month
as a number from 1 to 12, d the day of the month from 1 to 31, and y the year with four digits. Use
null for any of them that is not written for that date, and null for all three if the email gives
no delivery date. Do not compute, complete or guess anything.
"""

PROMPTS = {"type": mail_llm.PROMPTS["type"],
           "date": DATE_RULES + "\nBEGIN-<<TAG>>-EMAIL\n<<EMAIL>>\nEND-<<TAG>>-EMAIL\n\n" + DATE_RULES}
PROMPT_SHA256 = hashlib.sha256("\x00".join(PROMPTS[k] for k in sorted(PROMPTS)).encode()).hexdigest()

MONTHS = {
    1: ("january", "jan", "enero", "ene"), 2: ("february", "feb", "febrero"), 3: ("march", "mar", "marzo"),
    4: ("april", "apr", "abril", "abr"), 5: ("may", "mayo"), 6: ("june", "jun", "junio"),
    7: ("july", "jul", "julio"), 8: ("august", "aug", "agosto", "ago"),
    9: ("september", "sept", "sep", "septiembre", "setiembre", "set"), 10: ("october", "oct", "octubre"),
    11: ("november", "nov", "noviembre"), 12: ("december", "dec", "diciembre", "dic"),
}
WEEKDAYS = (("monday", "lunes"), ("tuesday", "martes"), ("wednesday", "miercoles"), ("thursday", "jueves"),
            ("friday", "viernes"), ("saturday", "sabado"), ("sunday", "domingo"))
MAX_DELIVERY_DAYS = 120  # a delivery date outside [order, order + 120 days] is dropped
_FOLD = str.maketrans("áéíóúüñ", "aeiouun")


def build_prompt(question, subject, body_text):
    text = mail_llm.email_text(subject, body_text)
    tag = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return PROMPTS[question].replace("<<TAG>>", tag).replace("<<EMAIL>>", json.dumps(text, ensure_ascii=True))


def canonical(question, raw):
    """type: as in mail_llm. date: "m|d|y" with what the model said is written ("" for each null);
    None if the answer does not have the requested form."""
    if question == "type":
        return mail_llm.canonical("type", raw)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if not isinstance(raw, dict) or set(raw) != {"month", "day", "year"}:
        return None
    out = []
    for k, lo, hi in (("month", 1, 12), ("day", 1, 31), ("year", 1000, 9999)):
        v = raw[k]
        if v is None:
            out.append("")
        elif isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            return None
        else:
            out.append(str(v))
    return "|".join(out)


def _words(text):
    return re.findall(r"[a-z]+|\d+", text.lower().translate(_FOLD))


def resolve_date(parts, text, order_date):
    """The date built in code from what the committee copied. parts: "m|d|y" (canonical);
    order_date: "YYYY-MM-DD" of the order on chain. Returns "YYYY-MM-DD" or ""."""
    if not parts:
        return ""
    month, day, year = [int(p) if p else None for p in parts.split("|")]
    words = _words(text)
    numbers = {int(w) for w in words if w.isdigit()}
    if month is None or day is None or day not in numbers:
        return ""
    if month not in numbers and not any(name in words for name in MONTHS[month]):
        return ""
    if year is not None and year not in numbers:
        year = None  # a year that is not written is dropped
    start = datetime.date.fromisoformat(order_date)
    if year is None:
        for y in (start.year, start.year + 1):
            try:
                candidate = datetime.date(y, month, day)
            except ValueError:
                continue
            if candidate >= start:
                year = y
                break
        if year is None:
            return ""
    try:
        date = datetime.date(year, month, day)
    except ValueError:
        return ""
    named = [i for i, names in enumerate(WEEKDAYS) if any(n in words for n in names)]
    if named and date.weekday() not in named:
        return ""
    if not start <= date <= start + datetime.timedelta(days=MAX_DELIVERY_DAYS):
        return ""
    return date.isoformat()


needs_date = mail_llm.needs_date
