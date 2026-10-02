"""Wingman: a matchmaker's shortlist. Run with `streamlit run app.py`."""

import json
from collections import Counter
from pathlib import Path

import streamlit as st

from checker import (
    BLOCKED,
    FIELD_LABELS,
    FITS,
    WARNING,
    describe_rule,
    format_value,
    shortlist,
)

DATA = Path(__file__).parent / "data"

STATUS_LABELS = {
    FITS: ":green[**Fits**]",
    WARNING: ":orange[**Warning**]",
    BLOCKED: ":red[**Blocked**]",
}

# Shown on the second line of a profile card. Age, height and city are on the first.
DETAIL_FIELDS = ["religion", "diet", "smokes", "drinks", "wants_children", "marital_status", "education"]


@st.cache_data
def load(filename):
    return json.loads((DATA / filename).read_text())


def pick_key(client, profile):
    return f"pick_{client['id']}_{profile['id']}"


def override_key(client):
    return f"override_{client['id']}"


def rules_table(rules):
    return [
        {
            "Preference": FIELD_LABELS[rule["field"]],
            "Accepts": describe_rule(rule),
            "Strength": rule["strength"],
            "Source": rule["source"],
        }
        for rule in rules
    ]


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
    st.subheader(f"{client['name']}'s rules")
    st.dataframe(rules_table(client["rules"]), hide_index=True, width="stretch")

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
    )
    st.caption("This prototype sends no email. Sending writes a line to the log below.")

    if st.session_state.send_log:
        st.subheader("Send log")
        st.dataframe(st.session_state.send_log, hide_index=True, width="stretch")


def main():
    st.set_page_config(page_title="Wingman", layout="wide")
    st.session_state.setdefault("send_log", [])

    clients = load("clients.json")
    profiles = load("profiles.json")

    st.title("Wingman")
    st.caption(
        "A shortlist that keeps out profiles a client has already said no to. "
        "All data is made up."
    )

    with st.sidebar:
        name = st.selectbox("Client", [c["name"] for c in clients])
        client = next(c for c in clients if c["name"] == name)
        st.markdown(f"{client['age']}, {client['city']}")
        st.markdown(f"Looking for a {client['looking_for']}")
        st.markdown(f"Matchmaker: {client['matchmaker']}")

    shortlist_screen(client, profiles)


if __name__ == "__main__":
    main()
