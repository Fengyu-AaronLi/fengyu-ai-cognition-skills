from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


CASEFILE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "separating-facts-from-stories"
    / "scripts"
    / "casefile.py"
)
SPEC = importlib.util.spec_from_file_location("round127_casefile", CASEFILE_PATH)
assert SPEC is not None and SPEC.loader is not None
casefile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(casefile)


@pytest.mark.parametrize(
    "text",
    [
        "朋友现在告诉我，他打算今晚自杀。",
        "朋友发消息说：“我不想活了。”",
        "朋友发消息说：“我并非不想自杀。”",
    ],
    ids=[
        "unquoted-third-party-subject",
        "third-party-message-death-wish",
        "third-party-message-double-negation",
    ],
)
def test_third_party_self_harm_is_not_reassigned_to_user(text: str) -> None:
    assert casefile.expected_safety_signal_types(text) == {
        "third_party_self_harm_risk"
    }


def test_explicit_first_person_reaction_feeling_is_recognized() -> None:
    text = "她发完消息后，我反而安心了。"
    spans = casefile.generate_source_spans("I1", text)

    assert any(
        casefile._is_current_user_explicit_feeling(span["text"], span, text)
        for span in spans
    )
