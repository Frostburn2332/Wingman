# Wingman

A matchmaker's wingman: a shortlist that filters out profiles a client has already said no to, plus an AI reader for rejection feedback.

This is a small prototype of an internal tool, built for The Date Crew's Product & Tech Generalist assessment.

## The problem

In the scenario's last 30 days, 690 of 1,000 shared profiles were rejected. About 35% of those rejections (roughly 241) were for reasons the client had already stated in their preferences. Each one costs matchmaker search time and a client's attention.

## The idea

One loop, in two layers:

1. **Rule check (no AI).** Each candidate profile is compared to the client's rules and marked as fits, warning (breaks a flexible preference) or blocked (breaks a deal-breaker). The matchmaker starts from the profiles that pass.
2. **Feedback reader (AI).** When a client rejects a profile and explains why in free text, the reply is turned into fixed fields. If it reveals something new, the tool suggests a rule, and the matchmaker approves it.

A person approves every new rule. The AI never changes a client's preferences on its own.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

All data in this repository is made up.
