# Wingman

A matchmaker's wingman: a shortlist that filters out profiles a client has already said no to, plus an AI reader for rejection feedback.

This is a small prototype of an internal tool, built for The Date Crew's Product & Tech Generalist assessment. All data in this repository is made up.

## The problem

In the scenario's last 30 days, 690 of 1,000 shared profiles were rejected. About 35% of those rejections (roughly 241) were for reasons the client had already stated in their preferences. Each one costs matchmaker search time and a client's attention.

## How it works

Every client answers the same intake questions on ten basic preferences: age, height, religion or community, city, diet, smoking, drinking, children, marital status and education. Each answer is either a rule (deal-breaker or flexible) or an explicit "no preference", so basics never have to be learned from rejections.

On top of that, one loop in two layers:

1. **Shortlist (no AI).** Each candidate is compared to the client's rules and marked:
   - **Fits:** breaks no rule.
   - **Warning:** breaks only a flexible preference, or is missing a value.
   - **Blocked:** breaks a deal-breaker.

   The matchmaker starts from the profiles that pass. A blocked profile can still be sent, but only with an override reason.
2. **Feedback reader (AI).** When a client rejects a profile and explains why in their own words, Gemini turns the reply into fixed fields: category, profile field, what the client would accept, strength, and the supporting phrase. Plain code then compares that to the client's rules and the rejected profile, and shows one of four outcomes:

   | Outcome | Meaning |
   |---|---|
   | Already in preferences | The rejection was avoidable: the rule was on record |
   | Suggested change | A rule exists but the reply is firmer or stricter |
   | New rule | The client said "no preference" at intake, but the reply shows otherwise |
   | No clear rule | The reply is vague, gives no exact value, or says nothing new |

3. **A person approves every rule.** Clicking "Add rule" stores it and shows which profiles changed status on the shortlist.

## Try it in a minute

1. Pick **Priya Nair** in the sidebar. The shortlist reads 4 fit, 6 warnings, 10 blocked.
2. Open **Rejection feedback** and choose Vikram Shetty's example: "I can't move out of Bangalore, my parents are here."
3. Click **Read feedback**, then **Add rule**. Four profiles move from Warning to Blocked.
4. Back on **Shortlist**, it now reads 4 fit, 2 warnings, 14 blocked, and the city rule is marked "learned from feedback".
5. **Reset learned rules** in the sidebar puts everything back.

Then try a reply of your own. For example, choose **Gautam Bose** as the rejected profile and type "He drinks a lot every weekend. I honestly can't be with a heavy drinker." This needs a Gemini key (see below).

## Run it locally

Tested with Python 3.14.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Gemini API key (optional)

Without a key, the example replies use saved outputs and typed replies cannot be read. To read any reply live:

1. Create a free key in [Google AI Studio](https://aistudio.google.com).
2. Save it in `.streamlit/secrets.toml`, which git ignores:

   ```toml
   GEMINI_API_KEY = "your-key"
   ```

   Alternatively, set it as an environment variable called `GEMINI_API_KEY`.

The app uses `gemini-3.5-flash-lite` and falls back to `gemini-flash-latest` if the first is busy. To use another model, set `GEMINI_MODEL` the same way.

### Tests

```bash
python -m pytest
```

The tests cover the rule check, every outcome of the feedback logic, the fallback when the live call fails, and the mocked data. They make no network calls.

## Design choices

- **Rules are plain code.** A deal-breaker check has to be exact, explainable and free, so no AI is involved in the shortlist.
- **AI does only the language part.** The model reads the reply; code decides what to do with it. The outcome logic is fully tested.
- **The model never sees the client's rules.** It reads the reply and nothing else, so it cannot be led by what is already on record.
- **The answer is constrained.** Gemini must answer in a fixed JSON shape, and the answer is checked again before use.
- **Errors are caught, not trusted.**
  - A rejection can tighten a rule but never loosens a deal-breaker.
  - If the rejected profile would still pass the suggested rule, the suggestion is flagged for a second look.
  - The supporting phrase is shown, so the matchmaker can check it against the reply.
- **Model choice.** On the eight example replies, `gemini-3.5-flash-lite` produced the expected outcome for all eight, at about a second per call. A larger Flash model was often unavailable under load during testing, so it is the fallback rather than the default.

## Project layout

| File | What it does |
|---|---|
| `app.py` | The two Streamlit screens |
| `checker.py` | The rule check |
| `feedback.py` | The prompt, the Gemini call, and the outcome logic |
| `data/clients.json` | Three clients and their rules |
| `data/profiles.json` | 36 candidate profiles |
| `data/feedback_examples.json` | Eight example replies, each with a saved output and expected outcome |
| `test_checker.py`, `test_feedback.py` | Tests |

## What is mocked or left out

- **Mocked:** clients, profiles and replies are made up. The saved outputs were written by hand as the expected answer for each example; the live model has matched them in testing.
- **No email:** "Send to client" writes to an on-screen log.
- **No database:** added rules and the send log live in the browser session and reset on refresh.
- **Left out on purpose:** login, ranking by predicted fit, automatic sending, and any model trained on past rejections.

## Screenshots

**Shortlist**

![Shortlist screen](screenshots/shortlist.png)

**Rejection feedback, after adding a rule**

![Rejection feedback screen](screenshots/feedback.png)
