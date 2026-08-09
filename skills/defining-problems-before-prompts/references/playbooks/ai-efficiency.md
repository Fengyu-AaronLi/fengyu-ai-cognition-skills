# AI efficiency adapter

Use this adapter only when the gate returns `define` with domain `ai_efficiency`.

“Efficiency” is not an observable result until the user names a real workflow, its present loss and a measurement source. Purchased tools and a manager's deadline are facts or pressure, not proof that tool adoption is the goal.

The coverage gate requires concrete decisive unknowns categorized as `desired_outcome`, `current_bottleneck` and `measurement_source`. The combined `questions[].addresses` must reference the IDs of unknowns covering all three categories. A stated desired outcome must name an observable changed result; AI, tools, automation, “efficiency” and “improving efficiency” remain solution or abstraction labels.

While the desired result, bottleneck or measurement source is unknown:

- Do not list tools, AI use cases, deployment steps, schedules or improvement percentages.
- Keep tool names only in anchored facts or hypotheses if the user mentioned them.
- Rewrite the problem around one real workflow and one observable loss.
- Make the next test inspect an existing workflow sample and locate waiting, rework, errors or omissions.
- A single sample may identify a candidate loss only. It cannot establish the maximum or primary loss, or a representative baseline.
- Stop before deciding whether AI is relevant.

This stopping point applies to the rewritten problem, next-test action and evidence, questions, success evidence and change evidence. None of those fields may judge whether AI or a tool is relevant, suitable, helpful, matched, adopted or ready to intervene. The only permitted endpoint is locating workflow loss and establishing the no-AI baseline.

In those constrained fields, tool and vendor names stay out entirely; “no-AI baseline” is the sole permitted AI phrase. Slack, Notion, Zapier and similar names may appear only in anchored facts or hypotheses supplied by the user. Questions must not use “for example” or “such as” to feed the user a menu of candidate use cases. A menu is still solution steering and contaminates the feedback loop.

The adapter constrains the stopping point. It does not choose the user's workflow or invent a baseline.
