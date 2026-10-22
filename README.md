# CRM Contact Cleanup 🧹

![tests](https://github.com/shahmeerk-gtm/crm-cleanup/actions/workflows/tests.yml/badge.svg)

**Cleans a messy contact list before it goes into the CRM.** I built this after spending hours at work fixing a 6,000-contact HubSpot database by hand: duplicates, ALL-CAPS names, five phone formats, and personal emails mixed in with work ones. This tool does that cleanup in seconds and shows exactly what it changed.

## The problem

Contact lists come from event sign-ups, purchased lists, sales reps and old spreadsheets, and every source formats data differently. Importing them as-is causes real costs:

- **Duplicates** mean the same person gets the same email twice, and reporting double-counts them.
- **Inconsistent company names** ("Acme Inc.", "ACME", "Acme Corp") break account-based segmentation.
- **Bad or personal emails** hurt deliverability and sender reputation.
- **Messy formatting** makes personalized emails look careless ("Hi JOHN,").

## What it does

```
messy CSV ──► standardize ──► unify company names ──► find & merge duplicates ──► flag issues ──► clean CSV + report
```

| Step | Example |
|---|---|
| **Standardize names** | `  SARAH ` → `Sarah`, `o'neill` → `O'Neill` |
| **Standardize emails** | ` SGARCIA@BLUEPEAKAM.COM` → `sgarcia@bluepeakam.com` |
| **Standardize phones** | `575.346.5146`, `15753465146`, `(575) 346-5146` → `+1 (575) 346-5146` |
| **Standardize titles** | `sr. analyst` → `Senior Analyst`, `vp, operations` → `VP, Operations` |
| **Unify company names** | `KESTREL DATA, INC.` and `Kestrel Data Co.` → `Kestrel Data Co.` |
| **Merge duplicates** | Matches on email, or on name + company with fuzzy matching and nicknames (`Mike Chen` = `Michael Chen`). Keeps the most complete record and fills its gaps from the others. |
| **Flag for review** | Invalid emails, personal emails (Gmail, Yahoo), email domains that don't match the company, unparseable phones, missing fields |

Nothing is silently deleted: every merge is listed in `duplicates_removed.csv` with the reason.

## Results on the sample data

The [sample file](sample_data/contacts_messy.csv) is 82 fake contacts with problems planted on purpose. From the [report](sample_output/report.md):

| | Records |
|---|---:|
| Contacts in | 82 |
| Duplicates merged away | 12 (15%) |
| Unique contacts out | 70 |
| Ready to import | 64 |
| Need review | 6 |

It caught all 12 planted duplicates and all 6 planted problem records. See [`sample_output/`](sample_output) for the full results.

## Run it

Python 3.10+, no extra packages needed.

```bash
python crm_cleanup.py sample_data/contacts_messy.csv --out output
```

It reads common export headers automatically ("First Name", "Email Address", "Company Name", "Job Title", and so on), so a HubSpot, Salesforce or Apollo export works without renaming columns.

**Output files**

| File | What's in it |
|---|---|
| `contacts_clean.csv` | Every unique contact, cleaned, with any flags |
| `needs_review.csv` | Only the records a person should check, with the reason |
| `duplicates_removed.csv` | Each merged record, the record it was merged into, and why |
| `report.md` | Data-quality summary |

## Tests

```bash
pip install pytest
pytest
```

41 tests cover each cleaning rule, duplicate matching (including cases that should *not* match, like two John Smiths at different companies), merging, and a full run on the sample file. They run on every push with GitHub Actions.

## Tech

Python (standard library only) · fuzzy matching with `difflib` · union-find for grouping duplicates · pytest · GitHub Actions

## What's next

- Push cleaned records straight into HubSpot through its API
- Enrich missing titles and phones from a data provider
- Score each record's completeness for list prioritization

*All names, companies and contact details in this repo are fictional.*
