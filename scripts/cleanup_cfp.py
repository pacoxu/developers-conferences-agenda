#!/usr/bin/env python3
"""
cleanup_cfp.py - Remove expired CFP links and dates from README.md

Automatically removes CFP date & links once the CFP deadline is more than
1 week (7 days) in the past.

Patterns handled in README.md:
  1. ([CFP](url) 截止 date)          – CFP link + date inside parens
  2. ([CFP](url)) 截止 date           – CFP link in parens, date outside
  3. [CFP](url) 截止 date             – standalone CFP link + date
  4. * [... CFP ...](url) 截止 date   – whole bullet is a CFP-only entry
     (the entire line is removed when expired)

Date formats recognised:
  - YYYY年M月D日   e.g. 2025年2月1日
  - M月D日         e.g. 2月24日  (current year assumed)
"""

import re
import sys
import os
import datetime

# ---------------------------------------------------------------------------
# Shared date regex fragment: captures (year?, month, day)
# ---------------------------------------------------------------------------
_DATE = r"(?:(\d{4})年)?(\d+)月(\d+)日"

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Pattern 1: ([CFP text](url) 截止 date)
_P1 = re.compile(r"\s*\(\[[^\]]*CFP[^\]]*\]\([^)]*\)\s+截止\s+" + _DATE + r"\)")

# Pattern 2: ([CFP text](url)) 截止 date
_P2 = re.compile(r"\s*\(\[[^\]]*CFP[^\]]*\]\([^)]*\)\)\s+截止\s+" + _DATE)

# Pattern 3: [CFP text](url) 截止 date  (standalone, preceded by whitespace)
_P3 = re.compile(r"\s+\[[^\]]*CFP[^\]]*\]\([^)]*\)\s+截止\s+" + _DATE)

# Pattern for a bullet whose *entire* content is a CFP link + deadline
# e.g. "  * [Maintainer Track + Project Lightning CFP](url) 截止 4月12日"
_CFP_ONLY_LINE = re.compile(
    r"^(\s*\*\s*)\[[^\]]*CFP[^\]]*\]\([^)]*\)\s+截止\s+" + _DATE + r"\s*$"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(year_str, month_str, day_str, ref_year):
    """Return a date object, using *ref_year* when year is not explicit."""
    try:
        year = int(year_str) if year_str else ref_year
        return datetime.date(year, int(month_str), int(day_str))
    except (ValueError, TypeError) as exc:
        print(
            f"Warning: could not parse CFP date "
            f"(year={year_str!r}, month={month_str!r}, day={day_str!r}): {exc}",
            file=sys.stderr,
        )
        return None


def _is_expired(date, today, grace_days=7):
    """True when *date* is more than *grace_days* days before *today*."""
    if date is None:
        return False
    return (today - date).days > grace_days


# ---------------------------------------------------------------------------
# Per-line processing
# ---------------------------------------------------------------------------

def _process_line(line, today, ref_year):
    """Remove expired CFP fragments from *line* and return the result."""
    modified = line
    for pattern in (_P1, _P2, _P3):
        matches = list(pattern.finditer(modified))
        # Iterate in reverse so removal doesn't shift earlier positions
        for m in reversed(matches):
            date = _parse_date(m.group(1), m.group(2), m.group(3), ref_year)
            if _is_expired(date, today):
                modified = modified[: m.start()] + modified[m.end() :]
    return modified


# ---------------------------------------------------------------------------
# Main processing function (public for tests)
# ---------------------------------------------------------------------------

def process_readme(content, today=None):
    """
    Process README *content*, stripping all expired CFP info.

    Returns the (possibly unchanged) content string.
    """
    if today is None:
        today = datetime.date.today()
    ref_year = today.year

    result = []
    for line in content.split("\n"):
        m = _CFP_ONLY_LINE.match(line.rstrip())
        if m:
            # Groups: 1=indent+bullet, 2=year?, 3=month, 4=day
            date = _parse_date(m.group(2), m.group(3), m.group(4), ref_year)
            if _is_expired(date, today):
                continue  # Drop the whole line
        result.append(_process_line(line, today, ref_year))

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    readme_path = os.path.normpath(os.path.join(script_dir, "..", "README.md"))

    with open(readme_path, encoding="utf-8") as fh:
        original = fh.read()

    updated = process_readme(original)

    if updated != original:
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write(updated)
        print("README.md updated: expired CFP links and dates removed.")
    else:
        print("README.md unchanged: no expired CFP links found.")


if __name__ == "__main__":
    main()
