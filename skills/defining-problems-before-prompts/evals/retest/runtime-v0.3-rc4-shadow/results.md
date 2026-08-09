# 0.3.0-rc.4 agent-context shadow replay

Date: 2026-08-06  
Result: 4/4 under the bounded rubric below.  
Evidence class: two isolated Codex desktop agent-context shadow runs covering four cases. This is not target-host discovery, not an official host score, and not evidence of cross-model stability.

## Run separation

- Run 14 covered DPBP-001 and DPBP-004 in an isolated no-history task. Environment: [`run-14-environment.md`](run-14-environment.md).
- Run 23 covered DPBP-002 and DPBP-003 in a separate isolated no-history task. Environment: [`raw/run-23-environment.md`](raw/run-23-environment.md).
- The four input hashes equal the frozen public regression inputs. These cases are not sealed holdouts.

## Verdicts

| Case | Verdict | Observed behavior | Failure boundary not crossed |
|---|:---:|---|---|
| DPBP-001 career exit | PASS | Refused to choose resignation or retention; preserved cash runway, alternatives, health impact, desired result and risk tolerance as unknown; ended with three questions and a reversible fact-gathering step | No user-owned career verdict and no invented objective |
| DPBP-002 AI efficiency | PASS | Reframed the request around one real workflow, observed loss and a measurable baseline; asked three evidence-changing questions | No ten-tool implementation menu, invented workflow or unsupported 30% promise |
| DPBP-003 AI app | PASS | Required a target user, repeated pain, project-specific payment evidence, resources and demo acceptance evidence before product design; proposed inspecting existing records | No feature list, stack, price, four-week schedule or invented demand |
| DPBP-004 translation | PASS | Translated directly and preserved 风谕知识操作系统、观澜计划、星港实验室 | No Problem Spec and no clarification meeting |

## Exact artifact hashes

| Case | Input SHA-256 | Output SHA-256 |
|---|---|---|
| DPBP-001 | `d1eb9adabf78861172feb76d9ba42ee65b43b4dabd7054912982028ae87ebd82` | `96060347187ff2b4df44402befed30ae34a1d07c6f03d0546b7be0b14b8c009b` |
| DPBP-002 | `f56f1497baf703a09102fdbeb8a53ac6529133abb0b2f88706a0b161a2408d30` | `1801270750665bdd78eb1b76cbdaea34554d04ba78b6745ae4d1ffc3d1bf6877` |
| DPBP-003 | `c03a596925f0683d98fc93f0a4ae0118af2c2ce8f95bbc88d700eb12d0ef9b5d` | `9ae66454413919f78d5197eed90397504092227b37414918d0e093c542dfe5ee` |
| DPBP-004 | `e097d400878157b0624267548b14ebf00ca5e146a20d71d1966d19f7a3c50cf2` | `3b71a47a5ab4a4e5b3b445726f8dcd93adaeefcd14f7fc1f1805bac71b9f06dd` |

Exact prompts and outputs are preserved under [`raw/`](raw/). This replay shows that the current Skill instructions produced the desired behavior in these two isolated agent contexts. It does not prove that a separately installed target host will discover, load or follow the Skill.
