import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import crm_cleanup as cc  # noqa: E402


# --- standardizing single values -------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("  jOHN ", "jOHN"),          # mixed case is left alone (could be intentional)
    ("MARY-ANN", "Mary-Ann"),
    ("o'neill", "O'Neill"),
    ("McAllister", "McAllister"),
    ("", ""),
])
def test_clean_name(raw, expected):
    assert cc.clean_name(raw) == expected


@pytest.mark.parametrize("raw, expected, ok", [
    ("(512) 555-0134", "+1 (512) 555-0134", True),
    ("512.555.0134", "+1 (512) 555-0134", True),
    ("15125550134", "+1 (512) 555-0134", True),
    ("+1 512 555 0134", "+1 (512) 555-0134", True),
    ("512-555-0134 x204", "+1 (512) 555-0134 ext. 204", True),
    ("555-0123", "555-0123", False),
    ("+44 20 7946 0958", "+44 20 7946 0958", False),
    ("", "", True),
])
def test_clean_phone(raw, expected, ok):
    assert cc.clean_phone(raw) == (expected, ok)


@pytest.mark.parametrize("raw, expected", [
    ("SILVERLINE ADVISORS LLC", "Silverline Advisors LLC"),
    ("Kestrel Data Co.", "Kestrel Data Co."),
    ("  Acme Corp,  ", "Acme Corp"),
])
def test_clean_company(raw, expected):
    assert cc.clean_company(raw) == expected


def test_company_key_ignores_suffixes_and_punctuation():
    assert cc.company_key("The Acme Corp., Inc.") == cc.company_key("ACME") == "acme"


@pytest.mark.parametrize("raw, expected", [
    ("sr. analyst", "Senior Analyst"),
    ("vp, operations", "VP, Operations"),
    ("VP Ops", "VP Operations"),
    ("head of data", "Head of Data"),
    ("Chief Operating Officer", "Chief Operating Officer"),
])
def test_clean_title(raw, expected):
    assert cc.clean_title(raw) == expected


def test_clean_email_and_domain():
    assert cc.clean_email(" MAILTO:Jane.Doe@ACME.com; ") == "jane.doe@acme.com"
    assert cc.clean_domain("https://www.acme.com/about") == "acme.com"


# --- flags ------------------------------------------------------------------

def contact(**kw):
    return cc.flag(cc.standardize(cc.Contact(row=2, **kw)))


def test_good_record_has_no_flags():
    c = contact(first_name="Jane", last_name="Doe", email="jdoe@bluepeakam.com",
                company="Bluepeak Asset Management", phone="512-555-0134")
    assert c.flags == []


@pytest.mark.parametrize("kw, expected_flag", [
    (dict(email="jane@gmail.com"), "personal email domain"),
    (dict(email="jane@acme"), "invalid email"),
    (dict(email=""), "missing email"),
    (dict(email="jane@summitlegal.com"), "email domain doesn't match company (summitlegal.com)"),
    (dict(email="jdoe@bluepeakam.com", company=""), "missing company"),
    (dict(email="jdoe@bluepeakam.com", phone="555-0123"), "phone not a valid US number"),
])
def test_flags(kw, expected_flag):
    base = dict(first_name="Jane", last_name="Doe", company="Bluepeak Asset Management")
    assert expected_flag in contact(**(base | kw)).flags


def test_domain_check_uses_website_when_present():
    assert cc.domain_matches_company("acme.com", "Totally Different Name", "acme.com")
    assert not cc.domain_matches_company("other.com", "Acme", "acme.com")


def test_domain_check_accepts_initials():
    assert cc.domain_matches_company("hcp.com", "Harborview Capital Partners")


# --- duplicates ---------------------------------------------------------------

def people(*specs):
    return [cc.standardize(cc.Contact(row=i + 2, **s)) for i, s in enumerate(specs)]


def test_same_email_different_case_is_duplicate():
    a, b = people(dict(last_name="Doe", email="JDOE@acme.com"), dict(last_name="Doe", email="jdoe@acme.com"))
    assert cc.is_same_person(a, b) == "same email"


def test_nickname_at_same_company_is_duplicate():
    a, b = people(dict(first_name="Michael", last_name="Chen", company="Acme Inc."),
                  dict(first_name="Mike", last_name="Chen", company="ACME"))
    assert cc.is_same_person(a, b) == "same name and company"


def test_same_name_different_company_is_not_duplicate():
    a, b = people(dict(first_name="John", last_name="Smith", company="Acme"),
                  dict(first_name="John", last_name="Smith", company="Globex"))
    assert cc.is_same_person(a, b) is None


def test_different_people_same_company_are_not_duplicates():
    a, b = people(dict(first_name="Sarah", last_name="Chen", company="Acme"),
                  dict(first_name="David", last_name="Patel", company="Acme"))
    assert cc.is_same_person(a, b) is None


def test_merge_keeps_most_complete_and_fills_gaps():
    contacts = people(
        dict(first_name="Mike", last_name="Chen", company="Acme", phone="512-555-0134"),
        dict(first_name="Michael", last_name="Chen", company="Acme", email="mchen@acme.com",
             title="COO", website="acme.com"),
    )
    result = cc.run(contacts)
    assert len(result.clean) == 1
    kept = result.clean[0]
    assert kept.first_name == "Michael" and kept.email == "mchen@acme.com"
    assert kept.phone == "+1 (512) 555-0134"         # filled in from the duplicate
    assert kept.merged_rows == [2]


def test_chain_of_duplicates_becomes_one_record():
    contacts = people(
        dict(first_name="Jon", last_name="Smith", company="Acme", email="js@acme.com"),
        dict(first_name="John", last_name="Smith", company="ACME Inc."),
        dict(first_name="J", last_name="Smith", company="Other", email="JS@acme.com"),
    )
    assert len(cc.run(contacts).clean) == 1


def test_company_spellings_are_unified():
    contacts = people(dict(last_name="A", company="Kestrel Data Co."),
                      dict(last_name="B", company="KESTREL DATA, INC."),
                      dict(last_name="C", company="Kestrel Data Co."))
    assert {c.company for c in cc.run(contacts).clean} == {"Kestrel Data Co."}


# --- end to end on the sample file ---------------------------------------------

def test_sample_file_end_to_end(tmp_path):
    result = cc.run(cc.load_contacts(ROOT / "sample_data" / "contacts_messy.csv"))
    cc.write_outputs(result, tmp_path)
    assert result.total_in == 82
    assert len(result.removed) == 12          # every planted duplicate found
    assert len(result.clean) == 70
    review = list(csv.DictReader((tmp_path / "needs_review.csv").open()))
    assert len(review) == 6                   # every planted problem record flagged
    assert (tmp_path / "report.md").read_text().startswith("# Data Quality Report")


def test_column_mapping_handles_common_export_headers():
    m = cc.map_columns(["First Name", "Last Name", "Email Address", "Company Name", "Job Title"])
    assert m == {"first_name": "First Name", "last_name": "Last Name", "email": "Email Address",
                 "company": "Company Name", "title": "Job Title"}
