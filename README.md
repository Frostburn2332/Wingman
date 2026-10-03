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

   The matchmaker starts from the profiles that pass. A blocked profile can still be sent, but only with an override reason. Every send is logged.
2. **Feedback reader (AI).** Feedback is about the latest list sent to the client, so only those profiles can be picked as rejected. Recording a rejection blocks that profile on the shortlist from then on, and sending the next list clears the screen for the next round. When a client explains a rejection in their own words, Gemini turns the reply into fixed fields: category, profile field, what the client would accept, strength, any condition on it, and the supporting phrase. Plain code then compares that to the client's rules and the rejected profile, and shows one of five outcomes:

   | Outcome | Meaning |
   |---|---|
   | Already in preferences | The rejection was avoidable: the rule was on record |
   | Suggested change | A rule exists but the reply is firmer or stricter |
   | New rule | The client said "no preference" at intake, but the reply shows otherwise |
   | Note | The objection has a condition a rule can't check, such as "fine with non-veg eaten out, not cooked at home" |
   | No clear rule | The reply is vague, gives no exact value, or says nothing new |

3. **A person approves every rule and note.** "Add rule" stores a rule and shows which profiles changed status on the shortlist. "Add note" leaves the rules alone and shows the note as "Check with the candidate" on every candidate it applies to.

## Try it in a minute

1. Pick **Priya Nair** in the sidebar. The shortlist reads 4 fit, 6 warnings, 10 blocked.
2. Tick **Karthik Iyer**, **Vikram Shetty** and **Joel Fernandes**, and click **Send to client**.
3. Open **Rejection feedback**. Only those three can be picked as rejected. Choose Vikram's example: "I can't move out of Bangalore, my parents are here."
4. Click **Read feedback**. The rejection is recorded, so Vikram is now blocked as "Already rejected by this client". Click **Add rule**: three more profiles move from Warning to Blocked.
5. Back on **Shortlist**, it reads 4 fit, 2 warnings, 14 blocked, and the city rule is marked "learned from feedback".
6. On **Rejection feedback**, choose Joel's example, where Priya is fine with non-veg eaten out but not cooked at home. Instead of making diet a deal-breaker, which would block every non-vegetarian candidate, it suggests a note. Add it, and the note appears on the non-vegetarian candidates' cards.
7. Send the next list: tick **Sameer Khan** and send. The feedback screen clears, and Sameer is the only profile that can be picked. Type a reply about him, for example "Sameer is sweet, but a master's degree really matters to me. I can't compromise on that." This needs a Gemini key (see below).
8. To see an avoidable rejection, send **Rahul Mehta**, who is blocked because he smokes. Sending him needs an override reason. Then read his example reply.
9. **Start over** in the sidebar puts everything back.

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
- **Conditions become notes, not rules.** A nuanced objection should not turn into a blanket block, so anything a fixed value can't express goes to the matchmaker as something to check with the candidate.
- **Errors are caught, not trusted.**
  - A rejection can tighten a rule but never loosens a deal-breaker.
  - If the rejected profile would still pass the suggested rule, the suggestion is flagged for a second look.
  - The supporting phrase is shown, so the matchmaker can check it against the reply.
- **Model choice.** On the nine example replies, `gemini-3.5-flash-lite` produced the expected outcome for all nine, at about a second per call. A larger Flash model was often unavailable under load during testing, so it is the fallback rather than the default.

## Project layout

| File | What it does |
|---|---|
| `app.py` | The two Streamlit screens |
| `checker.py` | The rule check |
| `feedback.py` | The prompt, the Gemini call, and the outcome logic |
| `data/clients.json` | Three clients and their rules |
| `data/profiles.json` | 36 candidate profiles |
| `data/feedback_examples.json` | Nine example replies, each with a saved output and expected outcome |
| `test_checker.py`, `test_feedback.py` | Tests |

## What is mocked or left out

- **Mocked:** clients, profiles and replies are made up. The saved outputs were written by hand as the expected answer for each example; the live model has matched them in testing.
- **No email:** "Send to client" writes to an on-screen log.
- **Example replies:** each is about one profile, so it appears once that profile is in the latest list sent to the client.
- **No database:** sends, rejections, added rules and notes live in the browser session and reset on refresh.
- **Left out on purpose:** login, ranking by predicted fit, automatic sending, and any model trained on past rejections.

## Screenshots

**Shortlist**

![Shortlist screen](screenshots/shortlist.png)

**Rejection feedback, after adding a rule**

![Rejection feedback screen](screenshots/feedback.png)
