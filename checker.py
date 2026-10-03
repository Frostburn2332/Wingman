"""Rule check: compares a profile to a client's rules.

Plain Python on purpose. A deal-breaker check has to be exact, explainable
and free, so no AI is involved here.
"""

FITS = "fits"
WARNING = "warning"
BLOCKED = "blocked"

DEAL_BREAKER = "deal-breaker"
FLEXIBLE = "flexible"

STATUS_ORDER = {FITS: 0, WARNING: 1, BLOCKED: 2}

FIELD_LABELS = {
    "age": "Age",
    "height_cm": "Height",
    "religion": "Religion or community",
    "city": "City",
    "diet": "Diet",
    "smokes": "Smokes",
    "drinks": "Drinks",
    "wants_children": "Wants children",
    "marital_status": "Marital status",
    "education": "Education",
}


def rule_passes(rule, value):
    """True if the value satisfies the rule, False if it breaks it,
    None if the profile has no value for that field."""
    if value is None:
        return None
    kind, accepted = rule["kind"], rule["value"]
    if kind == "between":
        low, high = accepted
        return low <= value <= high
    if kind == "at_least":
        return value >= accepted
    if kind == "one_of":
        return value in accepted
    raise ValueError(f"Unknown rule kind: {kind}")


def format_value(field, value):
    """A profile value in plain words."""
    if value is None:
        return "not stated"
    if field == "height_cm":
        return f"{value} cm"
    return str(value)


def describe_rule(rule):
    """What the rule accepts, in plain words."""
    field, kind, accepted = rule["field"], rule["kind"], rule["value"]
    if kind == "between":
        return f"{accepted[0]} to {accepted[1]}"
    if kind == "at_least":
        return f"at least {format_value(field, accepted)}"
    return " or ".join(str(v) for v in accepted)


def check_profile(profile, rules):
    """Check one profile against a client's rules.

    Returns the status (fits, warning or blocked) and one reason for every
    rule the profile breaks or has no value for.
    """
    reasons = []
    for rule in rules:
        field = rule["field"]
        value = profile.get(field)
        if rule_passes(rule, value):
            continue
        strength_label = "deal-breaker" if rule["strength"] == DEAL_BREAKER else "flexible preference"
        reasons.append({
            "field": field,
            "strength": rule["strength"],
            "not_stated": value is None,
            "text": f"{FIELD_LABELS[field]}: {format_value(field, value)} "
                    f"({strength_label}: {describe_rule(rule)})",
        })

    # A missing value is something to confirm with the candidate, so it can
    # warn but never block.
    broke_deal_breaker = any(
        r["strength"] == DEAL_BREAKER and not r["not_stated"] for r in reasons
    )
    if broke_deal_breaker:
        status = BLOCKED
    elif reasons:
        status = WARNING
    else:
        status = FITS
    return {"status": status, "reasons": reasons}


def notes_for(profile, notes):
    """The matchmaker's notes that apply to this profile: those about a field
    where the profile has the value the note was written about."""
    return [note for note in notes if profile.get(note["field"]) in note["values"]]


def intake_gaps(client):
    """Basic preference questions the client has not answered.

    The intake form asks every client about every field. Each answer is
    either a rule or an explicit "no preference", so a field with neither
    was never asked.
    """
    answered = {rule["field"] for rule in client["rules"]} | set(client.get("no_preference", []))
    return [field for field in FIELD_LABELS if field not in answered]


def candidates_for(client, profiles):
    """The profiles a client could be shown at all."""
    return [p for p in profiles if p["gender"] == client["looking_for"]]


def shortlist(client, profiles):
    """Every candidate for a client with its check result, fits first,
    then warnings, then blocked."""
    checked = [
        {"profile": p, **check_profile(p, client["rules"])}
        for p in candidates_for(client, profiles)
    ]
    return sorted(checked, key=lambda c: STATUS_ORDER[c["status"]])
