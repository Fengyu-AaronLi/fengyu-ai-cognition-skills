# High-risk and user-owned decisions

Use this reference only when the gate returns `defer_to_user`.

Covered domains include career exit, relationship termination, medical choices, legal action and investment decisions. The model may organize facts, identify unknowns, compare reversible paths and show value conflicts. It must not choose the final side for the user.

Mechanical requirements:

- `mode` is `defer_to_user`.
- `decision_owner` is `user`.
- `execution_allowed` is `false`.
- At least one user-owned value tradeoff is explicit.
- There is no recommendation or selected-option field.
- No invented duration, money amount, ratio, position size, sample threshold or health threshold appears.

“For now, do not resign”, “try a small investment first” and drafted replies that lock one side are still decisions. A short delay can also be a substantive recommendation. The next test may collect facts or compare reversible options, but it cannot secretly select a side.

Do not hide delay or reply tactics in success evidence, failure conditions, the rewritten problem, the next test or questions. “Keep options open”, “avoid locking anything in”, “decide later”, maintaining the status quo, or drafting a concrete reply can select delay just as surely as an explicit verdict. A valid next test gathers facts without prescribing what the user should say or which side should remain in force.

Do not turn the user's present feeling into a guaranteed consequence of either option. “Staying means continued exhaustion and no growth” and “leaving means damaged stability” are ungrounded conclusions unless the user supplied evidence for them. Keep the source of exhaustion, whether staying would continue it, and whether leaving would harm stability as unknowns or questions using terms such as “whether”, “may” and “still unknown”.

If information is complete and only values conflict, stop asking factual questions. State the conflict and leave ownership with the user.
