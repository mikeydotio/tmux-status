"""Claude model-ID shortener for the tmux status bar.

Used by scripts/tmux-claude-status to turn raw model IDs from the JSONL
transcript into short labels suitable for the status line.
"""
import re

_MODEL_RE = re.compile(r"(opus|sonnet|haiku)-(\d+)(?:-(\d+))?")


def format_model(model_id: str) -> str:
    """Render a Claude model ID as a short status-bar label.

    Examples:
        claude-opus-4-7             -> "Opus 4.7"
        claude-opus-4-7[1m]         -> "Opus 4.7 1M"
        claude-opus-4-1-20250805    -> "Opus 4.1"      (8-digit date tail ignored)
        claude-sonnet-4-20250514    -> "Sonnet 4"      (no minor -- date follows major)
        claude-haiku-4-10           -> "Haiku 4.10"
        <unmatched>                 -> raw input
        ""                          -> ""

    The "1M" suffix is driven solely by the "[1m]" marker in the raw ID.
    """
    if not model_id:
        return ""

    lower = model_id.lower()
    is_1m = "[1m]" in lower
    bare = re.sub(r"\[[^\]]*\]", "", lower)

    m = _MODEL_RE.search(bare)
    if not m:
        return model_id

    family, major, minor = m.group(1), m.group(2), m.group(3)
    if minor and len(minor) == 8 and minor.isdigit():
        minor = None

    label = f"{family.capitalize()} {major}"
    if minor:
        label += f".{minor}"
    if is_1m:
        label += " 1M"
    return label
