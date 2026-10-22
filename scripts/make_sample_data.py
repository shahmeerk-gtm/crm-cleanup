"""
Generates sample_data/contacts_messy.csv: a fake CRM export with the kinds of
problems real exports have. Every person and company here is made up.

    python scripts/make_sample_data.py
"""

import csv
import random
from pathlib import Path

random.seed(7)
OUT = Path(__file__).resolve().parents[1] / "sample_data" / "contacts_messy.csv"

COMPANIES = [
    ("Bluepeak Asset Management", "bluepeakam.com"),
    ("Harborview Capital Partners", "harborviewcap.com"),
    ("Cedar Ridge Investments", "cedarridgeinv.com"),
    ("Northgate Fund Services", "northgatefs.com"),
    ("Silverline Advisors LLC", "silverlineadvisors.com"),
    ("Ironwood Capital", "ironwoodcapital.com"),
    ("Meridian Point Asset Management", "meridianpoint.com"),
    ("Lakeshore Wealth Partners", "lakeshorewealth.com"),
    ("Granite Bay Holdings", "granitebayholdings.com"),
    ("Kestrel Data Co.", "kestreldata.com"),
]
FIRST = ["Michael", "Sarah", "John", "Priya", "David", "Emily", "Robert", "Aisha",
         "Daniel", "Laura", "James", "Mei", "Christopher", "Olivia", "Ahmed", "Rachel",
         "Thomas", "Sofia", "Andrew", "Hannah", "Kevin", "Nadia", "Samuel", "Grace",
         "Brian", "Elena", "Victor", "Chloe", "Omar", "Julia"]
LAST = ["Chen", "Patel", "Smith", "Garcia", "Okafor", "Nguyen", "Brennan", "Kowalski",
        "Rahman", "Fischer", "Morales", "Tanaka", "O'Neill", "Haddad", "Lindqvist",
        "Romero", "Sato", "Bianchi", "Mensah", "Novak", "Quinn", "Delgado", "Ferreira",
        "Ivanova", "Park", "Walsh", "Adeyemi", "Moreau", "Kim", "Russo"]
TITLES = ["Portfolio Manager", "Chief Operating Officer", "Head of Trading", "COO",
          "VP, Operations", "Director of Fund Accounting", "Senior Analyst",
          "Chief Financial Officer", "Operations Manager", "Managing Director",
          "Head of Technology", "Controller"]
NICK = {"Michael": "Mike", "John": "Jon", "Robert": "Bob", "Daniel": "Dan",
        "James": "Jim", "Christopher": "Chris", "Andrew": "Andy", "Samuel": "Sam",
        "Thomas": "Tom"}


def phone_variants():
    a, b, c = random.randint(201, 989), random.randint(200, 999), random.randint(1000, 9999)
    return random.choice([
        f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}.{b}.{c}", f"+1 {a} {b} {c}",
        f"1{a}{b}{c}", f"{a}{b}{c}", f"{a}-{b}-{c} x{random.randint(10, 999)}", "",
    ])


def messy(s: str) -> str:
    """Randomly mangles capitalization and spacing."""
    return random.choice([s, s, s.lower(), s.upper(), f"  {s} ", s])


rows = []
people = set()
while len(rows) < 64:
    first, last = random.choice(FIRST), random.choice(LAST)
    if (first, last) in people:
        continue
    people.add((first, last))
    company, domain = random.choice(COMPANIES)
    email = f"{first[0]}{last}".lower().replace("'", "") + "@" + domain
    rows.append({
        "First Name": messy(first), "Last Name": messy(last),
        "Email Address": random.choice([email, email, email.upper(), f" {email}"]),
        "Company Name": random.choice([company, company, company.upper(),
                                       company.replace(" LLC", "").replace(" Co.", "") + ", Inc."]),
        "Job Title": random.choice([t.lower() if random.random() < 0.3 else t for t in TITLES]),
        "Phone Number": phone_variants(),
        "Website": random.choice([f"https://www.{domain}", domain, f"http://{domain}/", ""]),
    })

# --- duplicates: the same person entered again with small differences ---
for base in random.sample(rows, 12):
    dup = dict(base)
    first = base["First Name"].strip().title()
    variant = random.choice(["nickname", "case", "email", "company"])
    if variant == "nickname" and first in NICK:
        dup["First Name"] = NICK[first]
        dup["Email Address"] = ""          # second record came from an event list
    elif variant == "case":
        dup["Email Address"] = base["Email Address"].strip().upper()
        dup["Phone Number"] = ""
    elif variant == "email":
        dup["Job Title"] = ""
        dup["Website"] = ""
    else:
        dup["Company Name"] = base["Company Name"].strip().upper().replace(" LLC", "") + " LLC"
        dup["Email Address"] = ""
    rows.append(dup)

# --- records with problems a person should look at ---
rows += [
    {"First Name": "Grace", "Last Name": "Mensah", "Email Address": "grace.mensah88@gmail.com",
     "Company Name": "Ironwood Capital", "Job Title": "sr. analyst", "Phone Number": "512-555-0199",
     "Website": "ironwoodcapital.com"},
    {"First Name": "Victor", "Last Name": "Russo", "Email Address": "vrusso@harborviewcap",
     "Company Name": "Harborview Capital Partners", "Job Title": "VP Ops", "Phone Number": "555-0123",
     "Website": ""},
    {"First Name": "Elena", "Last Name": "Walsh", "Email Address": "ewalsh@summitlegal.com",
     "Company Name": "Cedar Ridge Investments", "Job Title": "General Counsel",
     "Phone Number": "(646) 555-0172", "Website": ""},
    {"First Name": "", "Last Name": "Delgado", "Email Address": "info@lakeshorewealth.com",
     "Company Name": "Lakeshore Wealth Partners", "Job Title": "", "Phone Number": "",
     "Website": "lakeshorewealth.com"},
    {"First Name": "Omar", "Last Name": "Haddad", "Email Address": "omar.haddad@yahoo.com",
     "Company Name": "", "Job Title": "Investor Relations", "Phone Number": "+44 20 7946 0958",
     "Website": ""},
    {"First Name": "Julia", "Last Name": "Ferreira", "Email Address": "",
     "Company Name": "Kestrel Data Co.", "Job Title": "head of data", "Phone Number": "737.555.0148",
     "Website": "kestreldata.com"},
]

random.shuffle(rows)
OUT.parent.mkdir(exist_ok=True)
with OUT.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(f"Wrote {len(rows)} rows to {OUT}")
