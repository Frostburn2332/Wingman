import json
from pathlib import Path

import pytest

from checker import BLOCKED, DEAL_BREAKER, FLEXIBLE, WARNING, check_profile
from feedback import (
    ALREADY_KNOWN,
    LEARNED,
    NEW_RULE,
    NO_CLEAR_RULE,
    NO_VALUE,
    NOTHING_NEW,
    READING_SCHEMA,
    SUGGESTED_CHANGE,
    VAGUE,
    apply_rule,
    build_prompt,
    check_reading,
    decide_outcome,
    read_feedback,
    reading_to_rule,
)

DATA = Path(__file__).parent / "data"
CLIENTS = {c["id"]: c for c in json.loads((DATA / "clients.json").read_text())}
PROFILES = {p["id"]: p for p in json.loads((DATA / "profiles.json").read_text())}
EXAMPLES = json.loads((DATA / "feedback_examples.json").read_text())
BY_ID = {e["id"]: e for e in EXAMPLES}

PRIYA, ARJUN, MEERA = CLIENTS["c1"], CLIENTS["c2"], CLIENTS["c3"]


def reading(field, strength, accepted_values=(), minimum=None, maximum=None):
    return {
        "category": "other",
        "field": field,
        "accepted_values": list(accepted_values),
        "minimum": minimum,
        "maximum": maximum,
        "strength": strength,
        "evidence": "",
    }


def outcome_for(example_id):
    example = BY_ID[example_id]
    rules = CLIENTS[example["client_id"]]["rules"]
    return decide_outcome(example["saved_reading"], rules, PROFILES[example["profile_id"]])


# --- the saved examples -----------------------------------------------------

@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["id"])
def test_each_example_gives_its_expected_outcome(example):
    assert outcome_for(example["id"])["outcome"] == example["expected_outcome"]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["id"])
def test_evidence_is_quoted_word_for_word_from_the_reply(example):
    assert example["saved_reading"]["evidence"] in example["reply"]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["id"])
def test_no_example_raises_a_caution(example):
    assert outcome_for(example["id"])["caution"] is False


def test_without_a_key_example_replies_are_read_from_their_saved_readings():
    example = BY_ID["f2"]
    assert read_feedback(example["reply"], EXAMPLES) == {
        "reading": example["saved_reading"], "source": "saved", "model": None, "error": None,
    }


def test_without_a_key_other_text_cannot_be_read():
    assert read_feedback("He is too far away.", EXAMPLES)["reading"] is None


# --- reading live -----------------------------------------------------------

def test_live_reading_is_used_when_it_works():
    live_answer = reading("city", DEAL_BREAKER, ["Bangalore"])
    result = read_feedback("He is too far away.", EXAMPLES, live=lambda reply: (live_answer, "test-model"))
    assert result == {"reading": live_answer, "source": "live", "model": "test-model", "error": None}


def busy(reply):
    raise RuntimeError("503 model is busy")


def test_failed_live_reading_falls_back_to_the_saved_example():
    example = BY_ID["f7"]
    result = read_feedback(example["reply"], EXAMPLES, live=busy)
    assert (result["reading"], result["source"]) == (example["saved_reading"], "saved")
    assert result["error"] == "503 model is busy"


def test_failed_live_reading_of_other_text_reports_the_error():
    result = read_feedback("He is too far away.", EXAMPLES, live=busy)
    assert (result["reading"], result["source"], result["error"]) == (None, None, "503 model is busy")


def test_check_reading_accepts_every_saved_example():
    for example in EXAMPLES:
        assert check_reading(example["saved_reading"]) == example["saved_reading"]


@pytest.mark.parametrize("change", [
    {"strength": "maybe"},
    {"field": "income"},
    {"category": "weather"},
])
def test_check_reading_rejects_values_outside_the_lists(change):
    bad = {**BY_ID["f2"]["saved_reading"], **change}
    with pytest.raises(ValueError):
        check_reading(bad)


def test_check_reading_rejects_a_missing_field():
    bad = dict(BY_ID["f2"]["saved_reading"])
    del bad["evidence"]
    with pytest.raises(ValueError):
        check_reading(bad)


def test_schema_requires_every_reading_field():
    assert set(READING_SCHEMA["required"]) == set(BY_ID["f2"]["saved_reading"])


# --- the loop closes: an approved rule changes the shortlist ----------------

def test_city_becoming_a_deal_breaker_blocks_the_profile_that_was_a_warning():
    vikram = PROFILES["m04"]
    assert check_profile(vikram, PRIYA["rules"])["status"] == WARNING

    suggested = outcome_for("f2")["rule"]
    assert (suggested["field"], suggested["strength"], suggested["source"]) == ("city", DEAL_BREAKER, LEARNED)

    assert check_profile(vikram, apply_rule(PRIYA["rules"], suggested))["status"] == BLOCKED


def test_drinking_becoming_a_deal_breaker_blocks_the_profile_that_was_a_warning():
    tanvi = PROFILES["w03"]
    assert check_profile(tanvi, ARJUN["rules"])["status"] == WARNING
    updated = apply_rule(ARJUN["rules"], outcome_for("f5")["rule"])
    assert check_profile(tanvi, updated)["status"] == BLOCKED


def test_a_new_flexible_rule_warns_but_does_not_block():
    nikhil = PROFILES["m06"]
    updated = apply_rule(MEERA["rules"], outcome_for("f7")["rule"])
    result = check_profile(nikhil, updated)
    assert result["status"] == WARNING
    assert "marital_status" in {r["field"] for r in result["reasons"]}


# --- deciding the outcome ---------------------------------------------------

def test_vague_reply_gives_no_rule():
    result = decide_outcome(reading("none", "unclear"), PRIYA["rules"], PROFILES["m02"])
    assert (result["outcome"], result["why"]) == (NO_CLEAR_RULE, VAGUE)


def test_firm_reason_on_a_new_field_without_values_says_so():
    # "I can't be with a heavy drinker", read as drinks + deal-breaker but no accepted values.
    no_values = reading("drinks", DEAL_BREAKER)
    result = decide_outcome(no_values, PRIYA["rules"], PROFILES["m20"])
    assert (result["outcome"], result["why"]) == (NO_CLEAR_RULE, NO_VALUE)


def test_field_without_a_firm_or_hedged_reason_gives_no_rule():
    unclear = reading("city", "unclear", ["Bangalore"])
    assert decide_outcome(unclear, PRIYA["rules"], PROFILES["m04"])["outcome"] == NO_CLEAR_RULE


def test_field_without_a_checkable_value_gives_no_rule():
    no_value = reading("marital_status", DEAL_BREAKER)
    assert decide_outcome(no_value, MEERA["rules"], PROFILES["m06"])["outcome"] == NO_CLEAR_RULE


def test_flexible_reason_already_on_record_as_flexible_is_known():
    # Kavya is 33; Arjun's flexible age range is 26 to 31.
    older = reading("age", FLEXIBLE, maximum=31)
    assert decide_outcome(older, ARJUN["rules"], PROFILES["w06"])["outcome"] == ALREADY_KNOWN


def test_firmer_reply_without_a_value_keeps_the_value_and_raises_the_strength():
    firm = reading("city", DEAL_BREAKER)
    result = decide_outcome(firm, PRIYA["rules"], PROFILES["m04"])
    assert result["outcome"] == SUGGESTED_CHANGE
    assert (result["rule"]["value"], result["rule"]["strength"]) == (["Bangalore"], DEAL_BREAKER)


def test_stricter_limit_than_the_record_suggests_a_change():
    # Vikram is 33, inside Priya's 28 to 34. She now says no one over 31.
    result = decide_outcome(reading("age", DEAL_BREAKER, maximum=31), PRIYA["rules"], PROFILES["m04"])
    assert result["outcome"] == SUGGESTED_CHANGE
    assert result["rule"]["value"] == [28, 31]
    assert result["caution"] is False


def test_a_rejection_never_loosens_a_deal_breaker():
    hedged = reading("age", FLEXIBLE, maximum=31)
    result = decide_outcome(hedged, PRIYA["rules"], PROFILES["m04"])
    assert result["rule"]["strength"] == DEAL_BREAKER


def test_reading_that_matches_the_record_changes_nothing():
    # Karthik is a non-smoker, so a "non-smokers only" reading adds nothing new.
    same = reading("smokes", DEAL_BREAKER, ["no"])
    result = decide_outcome(same, PRIYA["rules"], PROFILES["m02"])
    assert (result["outcome"], result["why"]) == (NO_CLEAR_RULE, NOTHING_NEW)


def test_caution_when_the_rejected_profile_would_pass_the_suggested_rule():
    # Nikhil is divorced, so "never married or divorced" would not explain the rejection.
    odd = reading("marital_status", DEAL_BREAKER, ["never married", "divorced"])
    result = decide_outcome(odd, MEERA["rules"], PROFILES["m06"])
    assert result["outcome"] == NEW_RULE
    assert result["caution"] is True


# --- turning a reading into a rule ------------------------------------------

def test_age_with_one_end_uses_wide_defaults_when_there_is_no_existing_rule():
    assert reading_to_rule(reading("age", FLEXIBLE, maximum=35))["value"] == [18, 35]
    assert reading_to_rule(reading("age", FLEXIBLE, minimum=30))["value"] == [30, 99]


def test_height_becomes_an_at_least_rule():
    rule = reading_to_rule(reading("height_cm", FLEXIBLE, minimum=170.0))
    assert (rule["kind"], rule["value"]) == ("at_least", 170)


def test_unknown_field_gives_no_rule():
    assert reading_to_rule(reading("income", DEAL_BREAKER, ["high"])) is None


# --- storing a rule ---------------------------------------------------------

def test_apply_rule_replaces_the_rule_on_the_same_field_in_place():
    new = {"field": "city", "kind": "one_of", "value": ["Bangalore"], "strength": DEAL_BREAKER, "source": LEARNED}
    updated = apply_rule(PRIYA["rules"], new)
    assert len(updated) == len(PRIYA["rules"])
    assert [r["field"] for r in updated] == [r["field"] for r in PRIYA["rules"]]
    assert next(r for r in updated if r["field"] == "city") == new


def test_apply_rule_appends_a_rule_on_a_new_field_and_leaves_the_original_alone():
    new = {"field": "drinks", "kind": "one_of", "value": ["never"], "strength": FLEXIBLE, "source": LEARNED}
    before = json.dumps(PRIYA["rules"])
    updated = apply_rule(PRIYA["rules"], new)
    assert updated[-1] == new
    assert len(updated) == len(PRIYA["rules"]) + 1
    assert json.dumps(PRIYA["rules"]) == before


# --- the prompt -------------------------------------------------------------

def test_prompt_contains_the_reply_and_the_field_list_but_no_client_rules():
    prompt = build_prompt("  He lives too far away.  ")
    assert prompt.rstrip().endswith("He lives too far away.")
    assert "- drinks: never / socially / regularly" in prompt
    assert "Priya" not in prompt


def test_prompt_asks_for_what_the_client_would_accept_not_what_they_reject():
    one_line = " ".join(build_prompt("x").split())
    assert "list what they would accept instead" in one_line
