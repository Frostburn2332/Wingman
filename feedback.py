"""Feedback reader: turns a client's rejection reply into a suggested rule.

Two halves, kept apart on purpose:

1. Reading the reply (language understanding) produces a "reading": fixed
   fields describing what the client said. This is the AI's job.
2. Deciding what to do with the reading (compare it to the client's rules and
   the rejected profile) is plain Python, so it is exact and testable.
"""

import json

from google import genai
from google.genai import types

from checker import DEAL_BREAKER, FIELD_LABELS, FLEXIBLE, rule_passes

# Tried in order. The first is fast and got all eight example replies right
# in testing; the second is a fallback for when the first is busy.
DEFAULT_MODELS = ["gemini-3.5-flash-lite", "gemini-flash-latest"]

NO_CLEAR_RULE = "no_clear_rule"
ALREADY_KNOWN = "already_known"
SUGGESTED_CHANGE = "suggested_change"
NEW_RULE = "new_rule"
NOTE = "note"

UNCLEAR = "unclear"
LEARNED = "learned from feedback"

# Why a reading gave no clear rule.
VAGUE = "vague"
NO_VALUE = "no_value"
NOTHING_NEW = "nothing_new"

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
    "accepted_values": (
        "for a text field: every value the client WOULD accept, taken from the values listed "
        "above. Empty only when field is none, age or height"
    ),
    "minimum": "for age or height: the lowest number the client would accept, or null",
    "maximum": "for age: the highest number the client would accept, or null",
    "strength": f"\"{DEAL_BREAKER}\", \"{FLEXIBLE}\" or \"{UNCLEAR}\"",
    "condition": (
        "any condition or exception the client puts on the reason that the listed values "
        "cannot express, such as where or when something is acceptable. Empty if there is none"
    ),
    "evidence": "the exact phrase from the reply that supports this, copied word for word",
}

STRENGTHS = [DEAL_BREAKER, FLEXIBLE, UNCLEAR]

# The same fields as a JSON schema, so the model can only answer in this shape.
READING_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "field": {"type": "string", "enum": [*FIELD_OPTIONS, "none"]},
        "accepted_values": {"type": "array", "items": {"type": "string"}},
        "minimum": {"type": ["number", "null"]},
        "maximum": {"type": ["number", "null"]},
        "strength": {"type": "string", "enum": STRENGTHS},
        "condition": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": list(READING_FIELDS),
    "additionalProperties": False,
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

When the reply names what the client does not want, list what they would \
accept instead. For example, "I can't be with a heavy drinker" means drinks: \
never, socially.

Only fill in condition when the client accepts the thing under some \
circumstances and objects only in others. For example, "I don't mind him \
eating meat outside, just not cooked at home" has the condition "fine with \
non-veg eaten outside or ordered in, not cooked at home". An explanation of \
why the client objects ("my parents are here") is not a condition. Leave \
condition empty when there is none.

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


def check_reading(reading):
    """Raise ValueError unless the reading has every field with an allowed value."""
    missing = [name for name in READING_FIELDS if name not in reading]
    if missing:
        raise ValueError(f"Reading is missing: {', '.join(missing)}")
    if reading["category"] not in CATEGORIES:
        raise ValueError(f"Unknown category: {reading['category']}")
    if reading["field"] not in [*FIELD_OPTIONS, "none"]:
        raise ValueError(f"Unknown field: {reading['field']}")
    if reading["strength"] not in STRENGTHS:
        raise ValueError(f"Unknown strength: {reading['strength']}")
    return reading


def live_reading(reply, api_key, models=DEFAULT_MODELS):
    """Ask Gemini to read a reply. Returns (reading, model name).

    Tries each model in turn and raises the last error if none answers.
    """
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=READING_SCHEMA,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    error = None
    for model in models:
        try:
            response = client.models.generate_content(model=model, contents=build_prompt(reply), config=config)
            return check_reading(json.loads(response.text)), model
        except Exception as exc:  # busy model, quota, network or a malformed answer: try the next one
            error = exc
    raise error


def read_feedback(reply, examples, live=None):
    """Read a reply, live if possible and from the saved examples otherwise.

    `live` is a function that takes the reply and returns (reading, model
    name), or None when there is no API key. Returns a dict with the
    reading (None if the reply could not be read), its source ("live",
    "saved" or None), the model used, and any live error.
    """
    error = None
    if live is not None:
        try:
            reading, model = live(reply)
            return {"reading": reading, "source": "live", "model": model, "error": None}
        except Exception as exc:
            # Gemini errors carry a readable message; anything else falls back to its text.
            error = getattr(exc, "message", None) or str(exc) or type(exc).__name__

    reading = saved_reading(reply, examples)
    return {
        "reading": reading,
        "source": "saved" if reading is not None else None,
        "model": None,
        "error": error,
    }


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


def note_from(reading, rejected_profile):
    """A note for the matchmaker when the reply has a condition on a profile
    field, or None. The note applies to candidates with the same value as the
    rejected profile, since that value is what the condition is about."""
    field, condition = reading.get("field"), (reading.get("condition") or "").strip()
    if field not in FIELD_LABELS or not condition:
        return None
    value = rejected_profile.get(field)
    return {"field": field, "text": condition, "values": [] if value is None else [value], "source": LEARNED}


def decide_outcome(reading, rules, rejected_profile):
    """Compare a reading to the client's rules and the profile they rejected.

    Returns the outcome, the rule to suggest (if any), the existing rule on
    that field (if any), and a caution flag that is set when the rejected
    profile would still pass the suggested rule, which means the reading
    deserves a second look. When there is no clear rule, `why` says whether
    the reply was vague, named a field without a checkable value, or said
    nothing new.

    A reply with a condition the fixed values cannot express gives a note
    instead of a rule, so a nuanced objection never becomes a blanket block.
    """
    def result(outcome, rule=None, existing=None, why=None, note=None):
        caution = rule is not None and rule_passes(rule, rejected_profile.get(rule["field"])) is not False
        return {
            "outcome": outcome, "rule": rule, "existing_rule": existing,
            "caution": caution, "why": why, "note": note,
        }

    field, strength = reading.get("field"), reading.get("strength")
    existing = next((rule for rule in rules if rule["field"] == field), None)

    note = note_from(reading, rejected_profile)
    if note:
        return result(NOTE, existing=existing, note=note)

    if field not in FIELD_LABELS or strength not in (DEAL_BREAKER, FLEXIBLE):
        return result(NO_CLEAR_RULE, why=VAGUE)

    suggested = reading_to_rule(reading, existing)

    if existing is None:
        return result(NEW_RULE, suggested) if suggested else result(NO_CLEAR_RULE, why=NO_VALUE)

    broke_existing = rule_passes(existing, rejected_profile.get(field)) is False
    on_record_as_strongly = existing["strength"] == DEAL_BREAKER or strength == FLEXIBLE
    if broke_existing and on_record_as_strongly:
        return result(ALREADY_KNOWN, existing=existing)

    if suggested is None:
        if not broke_existing:
            return result(NO_CLEAR_RULE, existing=existing, why=NO_VALUE)
        # Firmer than the record but no new value given: keep the value, raise the strength.
        suggested = {**existing, "strength": strength, "source": LEARNED}

    # A rejection can tighten a rule but never loosens a deal-breaker.
    if existing["strength"] == DEAL_BREAKER:
        suggested["strength"] = DEAL_BREAKER
    unchanged = all(suggested[key] == existing[key] for key in ("kind", "value", "strength"))
    if unchanged:
        return result(NO_CLEAR_RULE, existing=existing, why=NOTHING_NEW)
    return result(SUGGESTED_CHANGE, suggested, existing)


def apply_rule(rules, new_rule):
    """A new list of rules with new_rule in it. A client has at most one rule
    per field, so a rule on the same field is replaced in place."""
    if any(rule["field"] == new_rule["field"] for rule in rules):
        return [new_rule if rule["field"] == new_rule["field"] else rule for rule in rules]
    return [*rules, new_rule]
