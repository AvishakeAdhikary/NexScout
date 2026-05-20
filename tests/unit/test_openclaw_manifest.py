"""§18 manifest.toml MUST be byte-equal to the plan template."""

from __future__ import annotations

from pathlib import Path

EXPECTED = """[skill]
name = "nexscout"
version = "0.1.0"
description = "Always-on autonomous job-application agent."
homepage = "https://github.com/<owner>/NexScout"

[heartbeat]
command = "nexscout tick"
interval_minutes = 30
working_dir = "{{HOME}}/.nexscout"

[memory]
namespace = "nexscout"
files = ["learned-answers.md", "learned-employers.md", "do-not-ask-again.md", "feedback.md"]

[[commands]]
name = "status"
description = "Pipeline stats and last 5 events."
run = "nexscout status --format=openclaw"

[[commands]]
name = "apply"
description = "One-shot apply to a job URL."
args = ["url"]
run = "nexscout apply --url {{url}} --workers 1"

[[commands]]
name = "pause"
run = "nexscout controls pause"

[[commands]]
name = "resume"
run = "nexscout controls resume"

[[commands]]
name = "question"
description = "List pending clarifying questions."
run = "nexscout question list --format=openclaw"

[[commands]]
name = "answer"
description = "Answer a pending question."
args = ["question", "reply"]
run = "nexscout question answer --question \\\"{{question}}\\\" --reply \\\"{{reply}}\\\""
"""


def test_manifest_matches_plan_byte_for_byte() -> None:
    manifest = Path(__file__).parent.parent.parent / "src" / "nexscout" / "openclaw" / "manifest.toml"
    text = manifest.read_text(encoding="utf-8")
    assert text == EXPECTED
