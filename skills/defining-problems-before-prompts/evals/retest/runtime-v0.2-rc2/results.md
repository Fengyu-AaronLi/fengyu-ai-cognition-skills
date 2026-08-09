# RC.2 host-model regression

## Verdict

Strict result: **1/4 PASS**.

RC.2 removed the previous delay tactic, tool-relevance decision, fake-door path, competitor-page evidence and unsourced half-day duration. The same inputs then exposed five narrower bypasses.

| Case | Result | Remaining bypass |
|---|:---:|---|
| DPBP-001 resignation | FAIL | Framed staying as continued fatigue and no growth, turning current feelings into an unverified option consequence |
| DPBP-002 AI efficiency | FAIL | Put an AI-use-case menu and vendor names inside questions, and set “at least one group” as an unsourced sample threshold |
| DPBP-003 AI product | FAIL | Still treated an AI App as the real-world outcome, prescribed a replacement target and used “at least one kind” as an unsourced evidence threshold |
| DPBP-004 translation | PASS | Direct translation, all proper nouns preserved, no Problem Spec |

The important result is not that RC.2 “almost passed”. It is that the runtime's previous field checks still allowed biased framing, candidate lists and target reassignment to hide in valid sections. These outputs became the next RED regression tests.

## Output hashes

| Case | SHA-256 |
|---|---|
| DPBP-001 | `adcb9bc5936d1f6fc70a89b4e855056bf34c4cf559a703a9b4ec101ee9a579c2` |
| DPBP-002 | `1b796c78b002617eafd3ef68639eaea0a612d078ebc70537ab3c8ca13104af82` |
| DPBP-003 | `30eea1d391c65354aa361348ebcb163ed6b7d2a9eeafb66e4e8f17b007c9fc23` |
| DPBP-004 | `bc1094a06adef3b22f85fb467534089ec0151959dd0bb3abdc3a7d087591f011` |

Raw outputs remain unchanged under [`raw/`](raw/).
