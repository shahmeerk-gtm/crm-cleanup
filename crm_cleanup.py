"""
CRM Contact Cleanup
-------------------
Cleans a messy CRM contact export before it goes into HubSpot (or any CRM):

  1. Standardizes names, emails, phone numbers, companies and job titles
  2. Finds duplicates, including fuzzy ones ("Jon Smith, Acme Inc." = "John Smith, ACME")
  3. Merges each set of duplicates into one record, keeping the most complete data
  4. Flags records that need a human look (bad emails, personal emails,
     email domains that don't match the company, missing fields)
  5. Writes clean CSVs plus a data-quality report

Usage:
    python crm_cleanup.py contacts.csv                 # writes to ./output
    python crm_cleanup.py contacts.csv --out results   # choose the output folder
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Header names commonly seen in CRM exports, mapped to one standard field name.
COLUMN_ALIASES = {
    "first_name": ["first name", "firstname", "first", "given name"],
    "last_name": ["last name", "lastname", "last", "surname", "family name"],
    "email": ["email", "email address", "e-mail", "work email"],
    "company": ["company", "company name", "account", "account name", "organization"],
    "title": ["title", "job title", "position", "role"],
    "phone": ["phone", "phone number", "mobile", "mobile phone", "work phone"],
    "website": ["website", "company website", "domain", "company domain", "url"],
}
FIELDS = list(COLUMN_ALIASES)

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "me.com", "live.com", "msn.com", "protonmail.com", "proton.me",
}
COMPANY_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co",
    "company", "lp", "llp", "plc", "gmbh", "the", "group", "holdings",
}
# Common nicknames, so "Mike Chen" and "Michael Chen" at the same company match.
NICKNAMES = {
    "jon": "john", "johnny": "john", "mike": "michael", "mick": "michael",
    "bob": "robert", "rob": "robert", "bobby": "robert", "bill": "william",
    "will": "william", "liz": "elizabeth", "beth": "elizabeth", "kate": "katherine",
    "katie": "katherine", "kathy": "katherine", "chris": "christopher",
    "dan": "daniel", "danny": "daniel", "dave": "david", "jim": "james",
    "jimmy": "james", "tom": "thomas", "tony": "anthony", "alex": "alexander",
    "sam": "samuel", "matt": "matthew", "nick": "nicholas", "steve": "steven",
    "jen": "jennifer", "jenny": "jennifer", "meg": "margaret", "andy": "andrew",
    "drew": "andrew", "ben": "benjamin", "joe": "joseph", "pat": "patricia",
}
TITLE_ABBREVIATIONS = {
    "sr": "Senior", "jr": "Junior", "mgr": "Manager", "dir": "Director",
    "assoc": "Associate", "exec": "Executive", "ops": "Operations",
    "mktg": "Marketing", "vp": "VP", "svp": "SVP", "evp": "EVP", "avp": "AVP",
    "ceo": "CEO", "cfo": "CFO", "coo": "COO", "cto": "CTO", "cmo": "CMO",
    "cio": "CIO", "cco": "CCO", "pm": "PM", "gtm": "GTM", "it": "IT",
    "of": "of", "and": "and", "&": "&",
}

NAME_MATCH = 0.85      # how similar two full names must be to count as the same person
COMPANY_MATCH = 0.90   # how similar two company names must be to count as the same company
EMAIL_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}$")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Contact:
    row: int                      # row number in the original file (header = row 1)
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    company: str = ""
    title: str = ""
    phone: str = ""
    website: str = ""
    flags: list[str] = field(default_factory=list)
    merged_rows: list[int] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def completeness(self) -> int:
        return sum(bool(getattr(self, f)) for f in FIELDS)


# ---------------------------------------------------------------------------
# Cleaning functions (each takes one raw value and returns a clean one)
# ---------------------------------------------------------------------------

def _squash(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def clean_name(value: str) -> str:
    """'  jOHN ' -> 'John', 'MARY-ANN' -> 'Mary-Ann'; leaves 'McAllister' alone."""
    value = _squash(value)
    if value and (value.islower() or value.isupper()):
        value = value.title()
    return value


def clean_email(value: str) -> str:
    value = _squash(value).lower().replace("mailto:", "").strip("<>;, ")
    return value


def clean_phone(value: str) -> tuple[str, bool]:
    """Formats US numbers as +1 (512) 555-0134. Returns (phone, looks_valid)."""
    raw = _squash(value)
    if not raw:
        return "", True
    main = re.split(r"\s*(?:x|ext\.?|extension)\s*\d+$", raw, flags=re.I)[0]
    ext = raw[len(main):].strip()
    digits = re.sub(r"\D", "", main)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return raw, False
    formatted = f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if ext:
        formatted += " ext. " + re.sub(r"\D", "", ext)
    return formatted, True


SUFFIX_CASE = {"Llc": "LLC", "Lp": "LP", "Llp": "LLP", "Plc": "PLC", "Gmbh": "GmbH"}


def clean_company(value: str) -> str:
    value = _squash(value).rstrip(", ")
    if value and (value.islower() or value.isupper()) and len(value) > 4:
        value = value.title()
        value = re.sub(r"\b(" + "|".join(SUFFIX_CASE) + r")\b", lambda m: SUFFIX_CASE[m.group(1)], value)
    return value


def unify_company_names(contacts: list["Contact"]) -> None:
    """Gives every spelling of the same company its most common properly-cased name."""
    spellings: dict[str, Counter] = {}
    for c in contacts:
        if c.company:
            spellings.setdefault(company_key(c.company), Counter())[c.company] += 1
    for c in contacts:
        if c.company:
            options = spellings[company_key(c.company)]
            c.company = max(options, key=lambda name: (not name.isupper(), options[name], -len(name)))


def company_key(value: str) -> str:
    """'The Acme Corp., Inc.' -> 'acme' (used only for matching)."""
    words = re.sub(r"[^a-z0-9 ]", " ", value.lower()).split()
    return " ".join(w for w in words if w not in COMPANY_SUFFIXES)


def clean_title(value: str) -> str:
    value = _squash(value)
    if not value:
        return ""
    words = []
    for word in re.split(r"(\s+|/|,)", value):
        bare = word.strip(".").lower()
        if bare in TITLE_ABBREVIATIONS:
            words.append(TITLE_ABBREVIATIONS[bare])
        elif word.islower() or word.isupper():
            words.append(word.capitalize())
        else:
            words.append(word)
    return "".join(words)


def clean_domain(value: str) -> str:
    value = _squash(value).lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    return value.split("/")[0]


def email_domain(email: str) -> str:
    return email.split("@", 1)[1] if "@" in email else ""


def first_name_key(first: str) -> str:
    first = first.lower().strip(".")
    return NICKNAMES.get(first, first)


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def map_columns(headers: list[str]) -> dict[str, str]:
    """Matches the file's headers to standard field names. Returns {field: header}."""
    lookup = {h.strip().lower().replace("_", " "): h for h in headers}
    mapping = {}
    for fld, aliases in COLUMN_ALIASES.items():
        for alias in [fld.replace("_", " ")] + aliases:
            if alias in lookup:
                mapping[fld] = lookup[alias]
                break
    return mapping


def load_contacts(path: Path) -> list[Contact]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        mapping = map_columns(reader.fieldnames or [])
        if "email" not in mapping and "last_name" not in mapping:
            sys.exit(f"Couldn't find email or name columns in {path.name}. Headers: {reader.fieldnames}")
        return [
            Contact(row=i, **{fld: (rec.get(col) or "") for fld, col in mapping.items()})
            for i, rec in enumerate(reader, start=2)
        ]


def standardize(c: Contact) -> Contact:
    c.first_name = clean_name(c.first_name)
    c.last_name = clean_name(c.last_name)
    c.email = clean_email(c.email)
    c.company = clean_company(c.company)
    c.title = clean_title(c.title)
    c.website = clean_domain(c.website)
    c.phone, _ = clean_phone(c.phone)
    return c


def domain_matches_company(domain: str, company: str, website: str = "") -> bool:
    if website:
        return domain == website or domain.endswith("." + website)
    root = domain.split(".")[0].replace("-", "")
    key = company_key(company)
    if not root or not key:
        return True
    if any(len(w) >= 3 and w in root for w in key.split()):
        return True
    initials = "".join(w[0] for w in key.split())
    if len(initials) >= 2 and root.startswith(initials):
        return True
    return SequenceMatcher(None, root, key.replace(" ", "")).ratio() >= 0.6


def flag(c: Contact) -> Contact:
    if not c.email:
        c.flags.append("missing email")
    elif not EMAIL_RE.match(c.email):
        c.flags.append("invalid email")
    else:
        domain = email_domain(c.email)
        if domain in FREE_EMAIL_DOMAINS:
            c.flags.append("personal email domain")
        elif c.company and not domain_matches_company(domain, c.company, c.website):
            c.flags.append(f"email domain doesn't match company ({domain})")
    if c.phone and not clean_phone(c.phone)[1]:
        c.flags.append("phone not a valid US number")
    if not c.company:
        c.flags.append("missing company")
    if not (c.first_name and c.last_name):
        c.flags.append("missing name")
    return c


def is_same_person(a: Contact, b: Contact) -> str | None:
    """Returns the reason two records are duplicates, or None."""
    if a.email and a.email == b.email and EMAIL_RE.match(a.email):
        return "same email"
    if not (a.last_name and b.last_name and a.company and b.company):
        return None
    ka, kb = company_key(a.company), company_key(b.company)
    if not ka or SequenceMatcher(None, ka, kb).ratio() < COMPANY_MATCH:
        return None
    name_a = f"{first_name_key(a.first_name)} {a.last_name.lower()}"
    name_b = f"{first_name_key(b.first_name)} {b.last_name.lower()}"
    if SequenceMatcher(None, name_a, name_b).ratio() >= NAME_MATCH:
        return "same name and company"
    return None


def find_duplicate_groups(contacts: list[Contact]) -> tuple[list[list[int]], dict[tuple[int, int], str]]:
    """Groups duplicates with union-find. Returns (groups of indexes, reason per matched pair)."""
    parent = list(range(len(contacts)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    reasons: dict[tuple[int, int], str] = {}
    for i in range(len(contacts)):
        for j in range(i + 1, len(contacts)):
            reason = is_same_person(contacts[i], contacts[j])
            if reason:
                reasons[(i, j)] = reason
                parent[root(j)] = root(i)

    groups: dict[int, list[int]] = {}
    for i in range(len(contacts)):
        groups.setdefault(root(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1], reasons


def merge_group(records: list[Contact]) -> Contact:
    """Keeps the most complete record and fills its blanks from the others."""
    records = sorted(records, key=lambda c: (-c.completeness(), c.row))
    keeper, others = records[0], records[1:]
    for other in others:
        for fld in FIELDS:
            if not getattr(keeper, fld) and getattr(other, fld):
                setattr(keeper, fld, getattr(other, fld))
        # prefer a valid phone number over an unparseable one
        if other.phone and not clean_phone(keeper.phone)[1] and clean_phone(other.phone)[1]:
            keeper.phone = other.phone
        keeper.merged_rows.append(other.row)
    return keeper


@dataclass
class Result:
    clean: list[Contact]
    removed: list[tuple[Contact, Contact, str]]   # (removed record, kept record, reason)
    total_in: int
    fixes: Counter


def run(contacts: list[Contact]) -> Result:
    total = len(contacts)
    before = {c.row: {f: getattr(c, f) for f in FIELDS} for c in contacts}
    contacts = [standardize(c) for c in contacts]
    unify_company_names(contacts)

    fixes: Counter = Counter()
    for c in contacts:
        for f in FIELDS:
            if getattr(c, f) != before[c.row][f]:
                fixes[f] += 1

    groups, reasons = find_duplicate_groups(contacts)
    in_group = {i for g in groups for i in g}
    clean = [c for i, c in enumerate(contacts) if i not in in_group]
    removed = []
    for g in groups:
        reason = next((r for (a, b), r in reasons.items() if a in g and b in g), "duplicate")
        members = [contacts[i] for i in g]
        keeper = merge_group(members)
        clean.append(keeper)
        removed += [(m, keeper, reason) for m in members if m is not keeper]

    clean = [flag(c) for c in clean]
    clean.sort(key=lambda c: (c.company.lower(), c.last_name.lower(), c.first_name.lower()))
    return Result(clean, removed, total, fixes)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(result: Result, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    headers = ["first_name", "last_name", "email", "company", "title", "phone", "website"]

    with (out / "contacts_clean.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers + ["flags", "merged_from_rows", "source_row"])
        for c in result.clean:
            w.writerow([getattr(c, h) for h in headers]
                       + ["; ".join(c.flags), " ".join(map(str, c.merged_rows)), c.row])

    with (out / "needs_review.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_row", "name", "email", "company", "issues"])
        for c in result.clean:
            if c.flags:
                w.writerow([c.row, c.full_name, c.email, c.company, "; ".join(c.flags)])

    with (out / "duplicates_removed.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["removed_row", "name", "email", "company", "merged_into_row", "reason"])
        for removed, kept, reason in result.removed:
            w.writerow([removed.row, removed.full_name, removed.email, removed.company, kept.row, reason])

    (out / "report.md").write_text(build_report(result))


def build_report(r: Result) -> str:
    issues = Counter(f.split(" (")[0] for c in r.clean for f in c.flags)
    flagged = sum(bool(c.flags) for c in r.clean)
    ready = len(r.clean) - flagged
    pct = lambda n: f"{n / r.total_in:.0%}" if r.total_in else "0%"
    lines = [
        "# Data Quality Report", "",
        "| | Records |", "|---|---:|",
        f"| Contacts in | {r.total_in} |",
        f"| Duplicates merged away | {len(r.removed)} ({pct(len(r.removed))}) |",
        f"| Unique contacts out | {len(r.clean)} |",
        f"| Ready to import | {ready} |",
        f"| Need review | {flagged} |",
        "", "## Values standardized", "",
        "| Field | Records changed |", "|---|---:|",
        *[f"| {f.replace('_', ' ').title()} | {n} |" for f, n in r.fixes.most_common()],
        "", "## Issues to review", "",
        "| Issue | Records |", "|---|---:|",
        *[f"| {i[0].upper() + i[1:]} | {n} |" for i, n in issues.most_common()],
        "",
        "Files: `contacts_clean.csv` (all unique contacts), `needs_review.csv` "
        "(flagged records), `duplicates_removed.csv` (what was merged, and why).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="CSV export of contacts")
    ap.add_argument("--out", type=Path, default=Path("output"), help="output folder (default: output)")
    args = ap.parse_args()

    result = run(load_contacts(args.input))
    write_outputs(result, args.out)
    print(build_report(result))
    print(f"Wrote results to {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
