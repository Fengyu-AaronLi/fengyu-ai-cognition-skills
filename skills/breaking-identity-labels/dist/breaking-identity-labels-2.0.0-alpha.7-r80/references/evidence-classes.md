# Evidence Classes

Use these exact runtime values.

| Runtime value | Meaning | Maximum justified claim |
|---|---|---|
| `reported_clinical_diagnosis` | User reports a diagnosis made by a qualified professional | Preserve the report and any function effects the user actually states |
| `formal_scale_result` | User reports a formal administration or result; metadata completeness is assessed separately | Preserve the exact report, identify missing metadata, and interpret only a checkable record within the scale's stated scope |
| `user_self_description` | First-person label or description | Preserve how the user describes experience; do not generalize across contexts |
| `ai_inference` | A model generated the label from conversation, memory or profiling | Treat as an unverified hypothesis |
| `social_media_label` | Label came from a post, video, informal quiz or online comment | Use only as a question or search clue |
| `other_person_attribution` | A named or unnamed person attributes a label to the current user or another person | Preserve who said what about whom; do not promote the attribution into a fact about the target |
| `unknown_source` | Source cannot be established | Preserve uncertainty |

Behavioral facts and counterexamples require a source span. Candidate variables use `status: hypothesis` and must not carry a fact-like source span.

Source status follows provenance, not the label word. If an AI says “you have ADHD,” the source remains `ai_inference`; the clinical term does not upgrade it. A colleague saying “you are controlling” remains `other_person_attribution`, including when the target is the current user. Suspicion, screening risk or an explicit statement that no diagnosis exists must never become `reported_clinical_diagnosis`.

`formal_scale_result` records the user's provenance claim, not independent verification. A report such as “I formally completed ASRS-v1.1” may retain this class while version, date, score, scoring method or source record remains unknown. Only a record with checkable metadata supports interpretation of that measured result, and only within the scale's stated scope.
