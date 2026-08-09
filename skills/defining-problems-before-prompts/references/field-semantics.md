# Problem Spec field semantics

Read this only when a field meaning is ambiguous or validation fails.

1. `original_question`: the user's current question, preserved rather than professionally rewritten.
2. `desired_outcome`: only an explicitly stated real-world change. Otherwise use `unknown`.
3. `proxy_problem`: a possible means, format or emotional demand being treated as the goal. Mark inference as `hypothesis`.
4. `hidden_assumptions`: premises that must be true for the current question to be worth answering.
5. `known_facts`: only user-provided claims, each with an exact source span. Values must be unique after trimming leading and trailing whitespace; comparison remains case-sensitive and does not otherwise normalize Chinese or other text. Different source spans do not make a duplicate fact value distinct.
6. `decisive_unknowns`: unknowns whose answers change route, outcome, success, risk or the next test. Each has a stable `id`; its `category` describes the dimension but is not an address.
7. `hard_constraints`: future feasibility, safety, legal, scope or non-negotiable limits. Past spending is not a hard constraint.
8. `value_tradeoffs`: conflicts that more facts cannot automatically settle. The owner is always the user.
9. `success_evidence`, `failure_conditions`, `change_evidence`: observable feedback, not invented targets. Provisional success items may be strings; every confirmed item is `{value, sources}` and must quote active user evidence.
10. `rewritten_problem`: a more worthwhile question connecting outcome, conflict and evidence. It is not a prompt formula.
11. `next_test`: one evidence-producing action that is reversible, low cost and stops before a solution commitment. Its structural boundary is `action_type: evidence_collection`, `evidence_only: true`, `solution_commitment: none`.
12. `questions`: at most three; every entry states which judgment it changes and uses `addresses` to reference existing decisive-unknown IDs.

For `stated` or `hypothesis` claims, provide exact source spans. For an unknown outcome, write exactly `当前未知` with an empty source list. Before state starts, the evidence span uses a zero-based, end-exclusive slice of `original_request`; omitted `source_id` means `request`. In a state-aware `advance`, an active answer or amendment may be cited with `source_id: answer:<id>` or `source_id: amendment:<id>`. Unknown or superseded sources are rejected.

`status: confirmed` is valid only through the resumable state `advance` command after the desired outcome and each structured success criterion cite active `answer:` or `amendment:` evidence, decisive unknowns are empty and questions are empty. Each criterion must add a determinate dimension beyond the outcome; adding “记录、是否、验收” around the same vague phrase is insufficient. Model-proposed string criteria remain provisional until the user explicitly confirms them. Standalone validation cannot certify convergence. A provisional spec with zero questions is not automatically confirmed; the state reports `needs_reassessment` until the spec is revised or a valid next action exists.

High-risk value choices use a separate post-definition source. After phase `awaiting_user_decision`, `decide` must receive a fresh `user_input` such as “我选择继续求职，不在今天辞职”，store it as `decision_input:<id>`, and cite an exact selected span from that source. That span must express a committed choice: “我决定不了”、疑问、待定表达，以及“我决定明天吃饭。现金覆盖六个月。”中被选出的背景事实都会被拒绝。`answer:<id>` and `amendment:<id>` remain valid evidence for diagnosis but can never serve as the final decision source. This local provenance rule does not authenticate who typed the input or prove full semantic relevance to a tradeoff; the host must enforce those boundaries.
