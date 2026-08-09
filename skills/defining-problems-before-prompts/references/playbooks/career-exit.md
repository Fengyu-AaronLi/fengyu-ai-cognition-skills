# Career exit playbook

Load this file only when the gate returns `mode=defer_to_user` and `domain=career`.
It extends `references/core.md` and `references/high-risk.md`; it does not replace either file.

## Required coverage

A career-exit Problem Spec must keep these six dimensions explicit as concrete
`decisive_unknowns[].category` values. At most three questions must cover all six
by listing the corresponding decisive-unknown IDs in `questions[].addresses`:

- `financial_capacity`: cash runway, income interruption and obligations.
- `alternatives`: confirmed jobs, clients, income paths or internal options.
- `health_status`: observable health or daily-function effects and urgent safety concerns.
- `desired_outcome`: the real-world change the user wants, not “quit” as a solution label.
- `risk_tolerance`: losses and uncertainties the user personally cannot accept.
- `decision_target`: what must actually be decided now, rather than treating every concern as a quit-or-stay vote.

Unknown means unknown. Do not convert tiredness into a diagnosis, a current feeling
into the inevitable consequence of staying, or a deadline into permission to choose
for the user.

## Boundary

- Keep `decision_owner=user` and `execution_allowed=false`.
- Separate established facts, possible consequences and user-owned value ordering.
- Do not recommend quitting, staying, delaying, preserving optionality or sending a tactical reply.
- Past tenure, training fees and reputation investments are facts or pressures, not reasons that must govern the next choice.
- The next test may inventory existing facts and identify excluded paths. It must stop before selecting a side.

If an answer exposes immediate health or safety danger, name the uncertainty and route
to appropriate qualified or emergency support without making the career verdict.
