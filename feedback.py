"""Feedback reader: turns a client's rejection reply into a suggested rule.

Two halves, kept apart on purpose:

1. Reading the reply (language understanding) produces a "reading": fixed
   fields describing what the client said. This is the AI's job.
2. Deciding what to do with the reading (compare it to the client's rules and
   the rejected profile) is plain Python, so it is exact and testable.
"""

from checker import DEAL_BREAKER, FIELD_LABELS, FLEXIBLE, rule_passes

NO_CLEAR_RULE = "no_clear_rule"
ALREADY_KNOWN = "already_known"
SUGGESTED_CHANGE = "suggested_change"
NEW_RULE = "new_rule"

UNCLEAR = "unclear"
LEARNED = "learned from feedback"

CATEGORIES = [
    "lifestyle",
    "family plans",
    "marital history",
    "location",
    "religion or community",
    "age or height",
    "education or career",
    "chemistry",
    "other",
]

# What each profile field can hold. Given to the model so it answers in the
# same terms the rule check uses.
FIELD_OPTIONS = {
    "age": "a number of years",
    "height_cm": "a number of centimetres",
    "religion": "a religion or community, for example Hindu, Jain, Muslim, Sikh, Christian, Parsi",
    "city": "a city name",
    "diet": ["vegetarian", "eggetarian", "non-vegetarian"],
    "smokes": ["yes", "no"],
    "drinks": ["never", "socially", "regularly"],
    "wants_children": ["yes", "no", "open"],
    "marital_status": ["never married", "divorced"],
    "education": ["bachelor's", "master's", "doctorate"],
}

# The fixed fields a reading has.
READING_FIELDS = {
    "category": f"one of: {', '.join(CATEGORIES)}",
    "field": f"the profile field the reason is about ({', '.join(FIELD_OPTIONS)}), or \"none\"",
    "accepted_values": "for a text field: the values the client WOULD accept. Empty otherwise",
    "minimum": "for age or height: the lowest number the client would accept, or null",
    "maximum": "for age: the highest number the client would accept, or null",
    "strength": f"\"{DEAL_BREAKER}\", \"{FLEXIBLE}\" or \"{UNCLEAR}\"",
    "evidence": "the exact phrase from the reply that supports this, copied word for word",
}

PROMPT = """\
You read a matchmaking client's reply explaining why they rejected a profile, \
and turn it into fixed fields. A matchmaker will review your answer before \
anything is changed.

Use only what the reply says. Do not guess at reasons the client did not give.

Profile fields and what they can hold:
{field_options}

Return these fields:
{reading_fields}

How to choose the strength:
- "deal-breaker" when the wording is firm: "I can't", "never", "a firm no", "I've said before".
- "flexible" when it is hedged: "I'd rather", "ideally", "I'd prefer", "though I'm open".
- "unclear" when there is no concrete, checkable reason.

If the reason is vague ("no spark", "something felt off") or is not about any \
listed field, set field to "none" and strength to "unclear". A vague feeling \
is not a rule.

If the reply gives several reasons, use the one the client states most firmly.

The client's reply:
{reply}
"""


def build_prompt(reply):
    """The full prompt for one reply. The client's existing rules are left
    out deliberately, so the model reads the reply and nothing else."""
    def options(value):
        return " / ".join(value) if isinstance(value, list) else value

    return PROMPT.format(
        field_options="\n".join(f"- {name}: {options(value)}" for name, value in FIELD_OPTIONS.items()),
        reading_fields="\n".join(f"- {name}: {meaning}" for name, meaning in READING_FIELDS.items()),
        reply=reply.strip(),
    )


def saved_reading(reply, examples):
    """The saved reading for an example reply, or None for any other text."""
    for example in examples:
        if example["reply"].strip() == reply.strip():
            return example["saved_reading"]
    return None


def read_feedback(reply, examples):
    """Read a reply. Returns (reading, source), or (None, None) if it cannot be read.

    Only the example replies can be read so far, from their saved readings.
    """
    reading = saved_reading(reply, examples)
    if reading is None:
        return None, None
    return reading, "saved"


def reading_to_rule(reading, existing=None):
    """The rule a reading implies, or None if it does not give a checkable one.

    For an age limit that names only one end ("under 31"), the other end is
    kept from the client's existing rule when there is one.
    """
    field, strength = reading.get("field"), reading.get("strength")
    if field not in FIELD_LABELS or strength not in (DEAL_BREAKER, FLEXIBLE):
        return None

    low, high = reading.get("minimum"), reading.get("maximum")
    if field == "age":
        if low is None and high is None:
            return None
        old_low, old_high = existing["value"] if existing else (18, 99)
        kind = "between"
        value = [int(low) if low is not None else old_low, int(high) if high is not None else old_high]
    elif field == "height_cm":
        if low is None:
            return None
        kind, value = "at_least", int(low)
    else:
        if not reading.get("accepted_values"):
            return None
        kind, value = "one_of", list(reading["accepted_values"])

    return {"field": field, "kind": kind, "value": value, "strength": strength, "source": LEARNED}


def decide_outcome(reading, rules, rejected_profile):
    """Compare a reading to the client's rules and the profile they rejected.

    Returns the outcome, the rule to suggest (if any), the existing rule on
    that field (if any), and a caution flag that is set when the rejected
    profile would still pass the suggested rule, which means the reading
    deserves a second look.
    """
    def result(outcome, rule=None, existing=None):
        caution = rule is not None and rule_passes(rule, rejected_profile.get(rule["field"])) is not False
        return {"outcome": outcome, "rule": rule, "existing_rule": existing, "caution": caution}

    field, strength = reading.get("field"), reading.get("strength")
    if field not in FIELD_LABELS or strength not in (DEAL_BREAKER, FLEXIBLE):
        return result(NO_CLEAR_RULE)

    existing = next((rule for rule in rules if rule["field"] == field), None)
    suggested = reading_to_rule(reading, existing)

    if existing is None:
        return result(NEW_RULE, suggested) if suggested else result(NO_CLEAR_RULE)

    broke_existing = rule_passes(existing, rejected_profile.get(field)) is False
    on_record_as_strongly = existing["strength"] == DEAL_BREAKER or strength == FLEXIBLE
    if broke_existing and on_record_as_strongly:
        return result(ALREADY_KNOWN, existing=existing)

    if suggested is None:
        if not broke_existing:
            return result(NO_CLEAR_RULE, existing=existing)
        # Firmer than the record but no new value given: keep the value, raise the strength.
        suggested = {**existing, "strength": strength, "source": LEARNED}

    # A rejection can tighten a rule but never loosens a deal-breaker.
    if existing["strength"] == DEAL_BREAKER:
        suggested["strength"] = DEAL_BREAKER
    unchanged = all(suggested[key] == existing[key] for key in ("kind", "value", "strength"))
    if unchanged:
        return result(NO_CLEAR_RULE, existing=existing)
    return result(SUGGESTED_CHANGE, suggested, existing)


def apply_rule(rules, new_rule):
    """A new list of rules with new_rule in it. A client has at most one rule
    per field, so a rule on the same field is replaced in place."""
    if any(rule["field"] == new_rule["field"] for rule in rules):
        return [new_rule if rule["field"] == new_rule["field"] else rule for rule in rules]
    return [*rules, new_rule]
