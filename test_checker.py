import json
from collections import Counter
from pathlib import Path

import pytest

from checker import (
    BLOCKED,
    FITS,
    WARNING,
    FIELD_LABELS,
    candidates_for,
    check_profile,
    describe_rule,
    intake_gaps,
    notes_for,
    rule_passes,
    shortlist,
)

DATA = Path(__file__).parent / "data"
CLIENTS = {c["name"]: c for c in json.loads((DATA / "clients.json").read_text())}
PROFILES = json.loads((DATA / "profiles.json").read_text())
BY_NAME = {p["name"]: p for p in PROFILES}


def rule(field, kind, value, strength="deal-breaker"):
    return {"field": field, "kind": kind, "value": value, "strength": strength, "source": "test"}


# --- one rule at a time -----------------------------------------------------

@pytest.mark.parametrize("age, expected", [(27, False), (28, True), (34, True), (35, False)])
def test_between_includes_both_ends(age, expected):
    assert rule_passes(rule("age", "between", [28, 34]), age) is expected


@pytest.mark.parametrize("height, expected", [(171, False), (172, True), (180, True)])
def test_at_least(height, expected):
    assert rule_passes(rule("height_cm", "at_least", 172), height) is expected


def test_one_of():
    cities = rule("city", "one_of", ["Mumbai", "Pune"])
    assert rule_passes(cities, "Pune") is True
    assert rule_passes(cities, "Delhi") is False


def test_missing_value_is_neither_pass_nor_fail():
    assert rule_passes(rule("smokes", "one_of", ["no"]), None) is None


def test_unknown_rule_kind_is_an_error():
    unknown = rule("age", "under", 30)
    with pytest.raises(ValueError):
        rule_passes(unknown, 25)


def test_rules_are_described_in_plain_words():
    assert describe_rule(rule("age", "between", [28, 34])) == "28 to 34"
    assert describe_rule(rule("height_cm", "at_least", 172)) == "at least 172 cm"
    assert describe_rule(rule("city", "one_of", ["Mumbai", "Pune"])) == "Mumbai or Pune"


# --- a whole profile --------------------------------------------------------

def test_breaking_a_deal_breaker_blocks():
    result = check_profile(BY_NAME["Rahul Mehta"], CLIENTS["Priya Nair"]["rules"])
    assert result["status"] == BLOCKED
    assert "Smokes: yes (deal-breaker: no)" in [r["text"] for r in result["reasons"]]


def test_breaking_only_a_flexible_preference_warns():
    result = check_profile(BY_NAME["Vikram Shetty"], CLIENTS["Priya Nair"]["rules"])
    assert result["status"] == WARNING
    assert [r["text"] for r in result["reasons"]] == [
        "City: Hyderabad (flexible preference: Bangalore)"
    ]


def test_breaking_nothing_fits():
    result = check_profile(BY_NAME["Karthik Iyer"], CLIENTS["Priya Nair"]["rules"])
    assert result == {"status": FITS, "reasons": []}


def test_missing_value_on_a_deal_breaker_warns_but_never_blocks():
    # Sameer has no "wants children" value, which is a deal-breaker for Priya.
    result = check_profile(BY_NAME["Sameer Khan"], CLIENTS["Priya Nair"]["rules"])
    assert result["status"] == WARNING
    assert "Wants children: not stated (deal-breaker: yes or open)" in [
        r["text"] for r in result["reasons"]
    ]


def test_blocked_profile_lists_every_broken_rule():
    # Anand breaks all three of Priya's deal-breakers and two flexible preferences.
    result = check_profile(BY_NAME["Anand Verma"], CLIENTS["Priya Nair"]["rules"])
    assert result["status"] == BLOCKED
    assert {r["field"] for r in result["reasons"]} == {"smokes", "wants_children", "age", "city", "education"}


# --- the intake form --------------------------------------------------------

@pytest.mark.parametrize("client", CLIENTS.values(), ids=lambda c: c["name"])
def test_every_client_answered_every_intake_question(client):
    assert intake_gaps(client) == []


@pytest.mark.parametrize("client", CLIENTS.values(), ids=lambda c: c["name"])
def test_no_field_is_both_a_rule_and_no_preference(client):
    assert not {r["field"] for r in client["rules"]} & set(client["no_preference"])


def test_unanswered_questions_are_reported_in_form_order():
    partial = {"rules": [rule("age", "between", [25, 35])], "no_preference": ["city"]}
    assert intake_gaps(partial) == [f for f in FIELD_LABELS if f not in ("age", "city")]


def test_notes_apply_to_profiles_with_the_value_they_were_written_about():
    note = {"field": "diet", "text": "Not cooked at home", "values": ["non-vegetarian"], "source": "test"}
    assert notes_for(BY_NAME["Joel Fernandes"], [note]) == [note]
    assert notes_for(BY_NAME["Sameer Khan"], [note]) == [note]
    assert notes_for(BY_NAME["Karthik Iyer"], [note]) == []


def test_no_preference_never_marks_a_profile_down():
    # Priya has no preference on drinking, so Dev's regular drinking is not a reason.
    result = check_profile(BY_NAME["Dev Malhotra"], CLIENTS["Priya Nair"]["rules"])
    assert "drinks" not in {r["field"] for r in result["reasons"]}


# --- the shortlist for a client ---------------------------------------------

def test_client_only_sees_the_gender_they_are_looking_for():
    assert {p["gender"] for p in candidates_for(CLIENTS["Priya Nair"], PROFILES)} == {"man"}
    assert {p["gender"] for p in candidates_for(CLIENTS["Arjun Patel"], PROFILES)} == {"woman"}


def test_shortlist_is_ordered_fits_then_warnings_then_blocked():
    statuses = [c["status"] for c in shortlist(CLIENTS["Arjun Patel"], PROFILES)]
    assert statuses == [FITS] * 5 + [WARNING] * 5 + [BLOCKED] * 6


@pytest.mark.parametrize("client, fits, warnings, blocked", [
    ("Priya Nair", 4, 6, 10),
    ("Arjun Patel", 5, 5, 6),
    ("Meera Khanna", 5, 4, 11),
])
def test_mocked_data_gives_each_client_a_mix(client, fits, warnings, blocked):
    counts = Counter(c["status"] for c in shortlist(CLIENTS[client], PROFILES))
    assert (counts[FITS], counts[WARNING], counts[BLOCKED]) == (fits, warnings, blocked)
