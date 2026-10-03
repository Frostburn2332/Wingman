"""Wingman: a matchmaker's shortlist. Run with `streamlit run app.py`."""

import json
import os
from collections import Counter
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from checker import (
    BLOCKED,
    FIELD_LABELS,
    FITS,
    WARNING,
    candidates_for,
    describe_rule,
    format_value,
    intake_gaps,
    notes_for,
    shortlist,
)
from feedback import (
    ALREADY_KNOWN,
    DEFAULT_MODELS,
    NEW_RULE,
    NO_CLEAR_RULE,
    NO_VALUE,
    NOTE,
    NOTHING_NEW,
    SUGGESTED_CHANGE,
    VAGUE,
    apply_rule,
    build_prompt,
    decide_outcome,
    live_reading,
    read_feedback,
    reading_to_rule,
)

DATA = Path(__file__).parent / "data"

STATUS_LABELS = {
    FITS: ":green[**Fits**]",
    WARNING: ":orange[**Warning**]",
    BLOCKED: ":red[**Blocked**]",
}

WRITE_OWN = "Write your own reply"

NO_RULE_REASONS = {
    VAGUE: "Nothing is suggested, because a vague feeling is not a rule.",
    NO_VALUE: (
        "The reply names a preference but not what would be acceptable, so there is "
        "nothing exact to check. Ask the client, or try rewording the reply."
    ),
    NOTHING_NEW: "The client's rules already say this, so there is nothing to change.",
}

# Shown on the second line of a profile card. Age, height and city are on the first.
DETAIL_FIELDS = ["religion", "diet", "smokes", "drinks", "wants_children", "marital_status", "education"]


@st.cache_data
def load(filename):
    return json.loads((DATA / filename).read_text())


def setting(name):
    """An environment variable if set, otherwise a Streamlit secret, otherwise None.

    Locally the key lives in .streamlit/secrets.toml; in a container it is
    passed as an environment variable.
    """
    if os.environ.get(name):
        return os.environ[name]
    try:
        return st.secrets.get(name)
    except StreamlitSecretNotFoundError:
        return None


def short(error, limit=200):
    return error if len(error) <= limit else error[:limit] + "..."


def pick_key(client, profile):
    return f"pick_{client['id']}_{profile['id']}"


def override_key(client):
    return f"override_{client['id']}"


def rules_table(client):
    """Every intake question: the client's rules first, then the fields they
    answered "no preference" to, each with any note learned from feedback."""
    def notes_on(field):
        return "; ".join(note["text"] for note in client["notes"] if note["field"] == field)

    rows = [
        {
            "Preference": FIELD_LABELS[rule["field"]],
            "Accepts": describe_rule(rule),
            "Strength": rule["strength"],
            "Source": rule["source"],
            "Note": notes_on(rule["field"]),
        }
        for rule in client["rules"]
    ]
    with_rule = {rule["field"] for rule in client["rules"]}
    rows += [
        {
            "Preference": FIELD_LABELS[field],
            "Accepts": "anything",
            "Strength": "no preference",
            "Source": "intake form",
            "Note": notes_on(field),
        }
        for field in FIELD_LABELS
        if field in client.get("no_preference", []) and field not in with_rule
    ]
    return rows


def profile_card(client, item):
    profile = item["profile"]
    with st.container(border=True):
        about, verdict = st.columns(2)
        about.checkbox(f"**{profile['name']}**", key=pick_key(client, profile))
        about.caption(
            f"{profile['age']} · {format_value('height_cm', profile['height_cm'])} · "
            f"{profile['city']} · {profile['profession']}"
        )
        about.caption(" · ".join(
            f"{FIELD_LABELS[field]}: {format_value(field, profile[field])}" for field in DETAIL_FIELDS
        ))
        verdict.markdown(STATUS_LABELS[item["status"]])
        if item["reasons"]:
            verdict.markdown("\n".join(f"- {reason['text']}" for reason in item["reasons"]))
        else:
            verdict.caption("Breaks none of the client's rules.")
        for note in notes_for(profile, client["notes"]):
            verdict.markdown(f":blue[**Check with the candidate:**] {note['text']}")


def send_selected(client, checked):
    """Log the ticked profiles. A blocked profile needs an override reason."""
    picked = [c for c in checked if st.session_state.get(pick_key(client, c["profile"]))]
    blocked = [c for c in picked if c["status"] == BLOCKED]
    reason = st.session_state.get(override_key(client), "").strip()

    if blocked and not reason:
        st.session_state.flash = ("error", "Give an override reason before sending a blocked profile.")
        return

    st.session_state.send_log.append({
        "Client": client["name"],
        "Profiles sent": ", ".join(c["profile"]["name"] for c in picked),
        "Blocked profiles included": ", ".join(c["profile"]["name"] for c in blocked) or "none",
        "Override reason": reason if blocked else "",
    })
    for c in picked:
        st.session_state[pick_key(client, c["profile"])] = False
    st.session_state[override_key(client)] = ""
    st.session_state.flash = (
        "success",
        f"Logged {len(picked)} profile(s) for {client['name']}. Nothing was emailed.",
    )


def shortlist_screen(client, profiles):
    st.subheader(f"{client['name']}'s preferences")
    gaps = intake_gaps(client)
    if gaps:
        st.warning(
            "The intake form is incomplete. Not yet asked: "
            + ", ".join(FIELD_LABELS[field] for field in gaps) + "."
        )
    st.dataframe(rules_table(client), hide_index=True, width="stretch")

    checked = shortlist(client, profiles)
    counts = Counter(item["status"] for item in checked)
    passing = [item for item in checked if item["status"] != BLOCKED]
    blocked = [item for item in checked if item["status"] == BLOCKED]

    st.subheader("Shortlist")
    st.markdown(
        f"**{len(checked)} candidates:** {counts[FITS]} fit, "
        f"{counts[WARNING]} warnings, {counts[BLOCKED]} blocked"
    )
    st.caption("Profiles that pass every deal-breaker. Tick the ones to send.")
    for item in passing:
        profile_card(client, item)

    if st.toggle(f"Show blocked profiles ({len(blocked)})", key=f"show_blocked_{client['id']}"):
        st.caption("These break at least one deal-breaker. Sending one needs an override reason.")
        for item in blocked:
            profile_card(client, item)

    st.subheader("Send")
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        (st.success if kind == "success" else st.error)(message)

    picked = [c for c in checked if st.session_state.get(pick_key(client, c["profile"]))]
    picked_blocked = [c for c in picked if c["status"] == BLOCKED]
    if picked_blocked:
        st.markdown(f"Selected: {len(picked)} profile(s), including {len(picked_blocked)} blocked.")
        st.text_input(
            "Override reason (required to send a blocked profile)",
            key=override_key(client),
        )
    else:
        st.markdown(f"Selected: {len(picked)} profile(s).")
    st.button(
        "Send to client",
        type="primary",
        disabled=not picked,
        on_click=send_selected,
        args=(client, checked),
        key=f"send_{client['id']}",
    )
    st.caption("This prototype sends no email. Sending writes a line to the log below.")

    if st.session_state.send_log:
        st.subheader("Send log")
        st.dataframe(st.session_state.send_log, hide_index=True, width="stretch")


def rule_text(rule):
    return f"{FIELD_LABELS[rule['field']]}: {describe_rule(rule)} ({rule['strength']})"


def example_key(client):
    return f"example_{client['id']}"


def rejected_key(client):
    return f"rejected_{client['id']}"


def reply_key(client):
    return f"reply_{client['id']}"


def result_key(client):
    return f"result_{client['id']}"


def fill_example(client, examples_by_label, profiles):
    """Picking an example fills in its reply and the profile it was about."""
    example = examples_by_label.get(st.session_state[example_key(client)])
    if example:
        profile = next(p for p in profiles if p["id"] == example["profile_id"])
        st.session_state[reply_key(client)] = example["reply"]
        st.session_state[rejected_key(client)] = profile["name"]
    st.session_state.pop(result_key(client), None)


def read_reply(client, examples, live):
    reply = st.session_state.get(reply_key(client), "").strip()
    if not reply:
        st.session_state[result_key(client)] = {"empty": True}
        return
    st.session_state[result_key(client)] = {
        "reply": reply,
        "profile_name": st.session_state[rejected_key(client)],
        **read_feedback(reply, examples, live),
        "added": None,
        "added_note": None,
    }


def add_rule(client, profiles, rule):
    """Store an approved rule and note which profiles changed status."""
    before = {item["profile"]["name"]: item["status"] for item in shortlist(client, profiles)}
    new_rules = apply_rule(client["rules"], rule)
    st.session_state.rules[client["id"]] = new_rules
    after = shortlist({**client, "rules": new_rules}, profiles)
    st.session_state[result_key(client)]["added"] = {
        "rule": rule,
        "changes": [
            (item["profile"]["name"], before[item["profile"]["name"]], item["status"])
            for item in after
            if item["status"] != before[item["profile"]["name"]]
        ],
    }


def add_note(client, profiles, note):
    """Store an approved note and record which candidates it will show on."""
    st.session_state.notes[client["id"]] = [*client["notes"], note]
    st.session_state[result_key(client)]["added_note"] = {
        "note": note,
        "shown_on": [p["name"] for p in candidates_for(client, profiles) if notes_for(p, [note])],
    }


def note_text(note):
    return note["text"].rstrip(". ")


def show_reading(result, existing):
    reading = result["reading"]
    rule = reading_to_rule(reading, existing)
    field = reading["field"]
    lines = [
        f"- **Reason category:** {reading['category']}",
        f"- **Profile field:** {FIELD_LABELS.get(field, 'none')}",
        f"- **Would accept:** {describe_rule(rule) if rule else 'not given'}",
        f"- **Strength:** {reading['strength']}",
    ]
    if (reading.get("condition") or "").strip():
        lines.append(f"- **Condition:** {reading['condition']}")
    lines.append(f"- **Supporting phrase:** \"{reading['evidence']}\"")
    st.markdown("\n".join(lines))
    if result["source"] == "live":
        st.caption(f"Source: live reading by {result['model']}.")
    elif result["error"]:
        st.caption(f"Source: saved example output, because the live reading failed: {short(result['error'])}")
    else:
        st.caption("Source: saved example output. No API key is set, so the live reading is off.")


def show_note_suggestion(client, profiles, note):
    label = FIELD_LABELS[note["field"]].lower()
    if note["values"]:
        applies = f"It will show on every candidate whose {label} is {' or '.join(map(str, note['values']))}."
    else:
        applies = "The rejected profile has no value for this field, so it would show on no one."
    st.info(
        f"**Suggested note.** {note_text(note)}.\n\n"
        "The reply puts a condition on this that a rule can't check, so the rule stays as it is. "
        f"The matchmaker checks it with the candidate instead. {applies}"
    )
    st.button(
        "Add note",
        type="primary",
        disabled=not note["values"],
        on_click=add_note,
        args=(client, profiles, note),
        key=f"add_note_{client['id']}",
    )
    st.caption("Nothing changes until you add the note.")


def show_decision(client, profiles, decision):
    outcome, rule, existing = decision["outcome"], decision["rule"], decision["existing_rule"]
    if outcome == NO_CLEAR_RULE:
        st.info(f"**No clear rule.** {NO_RULE_REASONS[decision['why']]}")
        return
    if outcome == NOTE:
        show_note_suggestion(client, profiles, decision["note"])
        return
    if outcome == ALREADY_KNOWN:
        st.warning(
            "**Already in preferences: this rejection was avoidable.** "
            f"On record: {rule_text(existing)}. Source: {existing['source']}."
        )
        return
    if outcome == SUGGESTED_CHANGE:
        st.info(f"**Suggested change.** On record: {rule_text(existing)}. Suggested: {rule_text(rule)}.")
    elif outcome == NEW_RULE:
        message = f"**New: suggested rule.** {rule_text(rule)}."
        if rule["field"] in client.get("no_preference", []):
            message += (
                f" At intake, {client['name']} said they had no preference on this, "
                "so what they said and how they choose differ."
            )
        st.info(message)
    if decision["caution"]:
        st.warning(
            "The rejected profile would still pass this rule, so it may not be "
            "the real reason. Read the reply again before adding it."
        )
    st.button(
        "Add rule",
        type="primary",
        on_click=add_rule,
        args=(client, profiles, rule),
        key=f"add_rule_{client['id']}",
    )
    st.caption("Nothing changes until you add the rule. The AI never edits a client's preferences on its own.")


def feedback_screen(client, profiles, examples, live):
    st.subheader("Rejection feedback")
    st.caption(
        "Paste the client's reply. It is turned into fixed fields, compared to "
        "the client's rules, and a rule is suggested only if it says something new."
    )

    candidates = candidates_for(client, profiles)
    names = {p["id"]: p["name"] for p in candidates}
    examples_by_label = {
        f"{names[e['profile_id']]}: \"{e['reply']}\"": e
        for e in examples
        if e["client_id"] == client["id"]
    }

    st.selectbox(
        "Example replies",
        [WRITE_OWN, *examples_by_label],
        key=example_key(client),
        on_change=fill_example,
        args=(client, examples_by_label, candidates),
    )
    st.selectbox("Profile that was rejected", [p["name"] for p in candidates], key=rejected_key(client))
    st.text_area("Client's reply", key=reply_key(client))
    st.button("Read feedback", on_click=read_reply, args=(client, examples, live), key=f"read_{client['id']}")

    result = st.session_state.get(result_key(client))
    if not result:
        return
    if result.get("empty"):
        st.error("Pick an example or paste a reply first.")
        return
    if result["reading"] is None:
        if result["error"]:
            st.warning(
                f"The live reading failed: {short(result['error'])} "
                "Until it works again, only the example replies can be read."
            )
        else:
            st.info("No API key is set, so only the example replies can be read. Pick one from the list above.")
        return

    profile = next(p for p in candidates if p["name"] == result["profile_name"])
    reading = result["reading"]
    existing = next((r for r in client["rules"] if r["field"] == reading["field"]), None)

    st.markdown(f"**What {client['name']} said about {profile['name']}**")
    show_reading(result, existing)

    if result["added"]:
        added = result["added"]
        st.success(f"**Rule added.** {rule_text(added['rule'])}, learned from feedback.")
        if added["changes"]:
            st.markdown("Profiles whose status changed on the shortlist:")
            st.markdown("\n".join(
                f"- {name}: {STATUS_LABELS[before]} to {STATUS_LABELS[after]}"
                for name, before, after in added["changes"]
            ))
        else:
            st.markdown("No profile changed status.")
        st.caption("Open the Shortlist tab to see the updated list.")
    elif result["added_note"]:
        added = result["added_note"]
        st.success(f"**Note added.** {note_text(added['note'])}, learned from feedback.")
        st.markdown(
            f"It shows on {len(added['shown_on'])} candidate(s) as \"Check with the candidate\": "
            + ", ".join(added["shown_on"]) + "."
        )
        st.caption("No rule changed, so no profile changed status.")
    else:
        show_decision(client, profiles, decide_outcome(reading, client["rules"], profile))

    with st.expander("Prompt and output fields"):
        st.code(build_prompt(result["reply"]), language=None, wrap_lines=True)


def reset_rules(clients):
    st.session_state.rules = {c["id"]: c["rules"] for c in clients}
    st.session_state.notes = {c["id"]: [] for c in clients}
    for c in clients:
        st.session_state.pop(result_key(c), None)


def main():
    st.set_page_config(page_title="Wingman", layout="wide")
    st.session_state.setdefault("send_log", [])

    clients = load("clients.json")
    profiles = load("profiles.json")
    examples = load("feedback_examples.json")

    # Rules and notes live in the session so that approved ones take effect. They reset on refresh.
    if "rules" not in st.session_state:
        st.session_state.rules = {c["id"]: c["rules"] for c in clients}
    if "notes" not in st.session_state:
        st.session_state.notes = {c["id"]: [] for c in clients}

    api_key = setting("GEMINI_API_KEY")
    models = [setting("GEMINI_MODEL")] if setting("GEMINI_MODEL") else DEFAULT_MODELS
    live = (lambda reply: live_reading(reply, api_key, models)) if api_key else None

    st.title("Wingman")
    st.caption(
        "A shortlist that keeps out profiles a client has already said no to, "
        "and learns new rules from rejection feedback. All data is made up."
    )

    with st.sidebar:
        name = st.selectbox("Client", [c["name"] for c in clients], key="client")
        chosen = next(c for c in clients if c["name"] == name)
        client = {
            **chosen,
            "rules": st.session_state.rules[chosen["id"]],
            "notes": st.session_state.notes[chosen["id"]],
        }
        st.markdown(f"{client['age']}, {client['city']}")
        st.markdown(f"Looking for a {client['looking_for']}")
        st.markdown(f"Matchmaker: {client['matchmaker']}")
        st.divider()
        st.button("Reset learned rules", on_click=reset_rules, args=(clients,), key="reset_rules")
        st.caption("Puts every client's rules back to the intake form and clears learned notes.")
        st.divider()
        if live:
            st.caption(f"AI reading: live, using {models[0]}.")
        else:
            st.caption("AI reading: off, because no API key is set. Example replies use saved outputs.")

    shortlist_tab, feedback_tab = st.tabs(["Shortlist", "Rejection feedback"])
    with shortlist_tab:
        shortlist_screen(client, profiles)
    with feedback_tab:
        feedback_screen(client, profiles, examples, live)


if __name__ == "__main__":
    main()
