# Runtime v0.2 host-model regression

## Verdict

Strict result: **1/4 PASS**.

The executable gate, schema validation and renderer all ran, but three model-authored specs crossed semantic stop points while still declaring themselves compliant. This run disproved the earlier assumption that structural validation alone was sufficient.

| Case | Result | Observed bypass |
|---|:---:|---|
| DPBP-001 resignation | FAIL | Turned “preserve options” into an unstated success criterion and drafted a delaying reply, indirectly choosing a side |
| DPBP-002 AI efficiency | FAIL | Reintroduced tool relevance in the rewritten problem and next test instead of stopping at workflow loss and a non-AI baseline |
| DPBP-003 AI product | FAIL | Called an AI App plan the real-world outcome, proposed implementation options and introduced the unsourced duration “half a day” |
| DPBP-004 translation | PASS | Executed the clear translation directly and preserved all three proper nouns |

## Failure evidence

DPBP-001 said the successful response should not “lock in” resignation or staying, then supplied text for the user to send the boss. The high-risk adapter explicitly treats a delay or drafted real-world reply as a possible substantive recommendation.

DPBP-002 asked whether ChatGPT Team, Notion AI or Zapier could improve the loss, marked steps the tools might assist and sought evidence about tool intervention. The AI-efficiency adapter requires the current response to stop before deciding whether AI is relevant.

DPBP-003 set “an AI App plan” as the desired real-world outcome even while diagnosing the app as a proxy solution. It also introduced a narrow paid manual version, a fake-door test and “half a day” without prior demand evidence or a sourced duration.

## Output hashes

| Case | SHA-256 |
|---|---|
| DPBP-001 | `82efebc834609db0bdcac443a845ec75391fc0abcd115c8f6bfdddc886af4667` |
| DPBP-002 | `6605c3bd9b0cf96edf24d80d827f884451dbb7d0364557221140e3de08d50b56` |
| DPBP-003 | `9dbc3eac91d5809669824a77a5b1d7f849615c38ef498e23eca1456f28386abf` |
| DPBP-004 | `4b39a25dd1db1eea723a12855355341b0f9b7ffd811d4cf8f964394d32c0dfae` |

Raw outputs remain unchanged under [`raw/`](raw/). These failures became the next RED tests; they are not rewritten into ideal examples.
