"""Resolve render-daemon Python functions for tests.

Historically these functions lived inside the tmux-claude-status bash polyglot
(Python embedded in a heredoc) and had to be source-sliced out of the script.
They now live in the importable ``tmux_status_server.render`` module, so we
resolve them directly — tests exercise the real functions (with their real
module globals) instead of a re-exec'd copy. The public API is unchanged so
existing callers keep working.
"""

import inspect
import os

from tmux_status_server import render as _render

# The module file the resolved functions now live in (retained for callers
# that reference SCRIPT_PATH in assertion messages).
SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "tmux_status_server", "render.py"
)


def extract_function(func_name):
    """Return the source text of a render-daemon function.

    Raises ValueError if no such callable exists (preserves the old
    "function not found" contract).
    """
    fn = getattr(_render, func_name, None)
    if fn is None or not callable(fn):
        raise ValueError(f"Function '{func_name}' not found in {SCRIPT_PATH}")
    return inspect.getsource(fn)


def load_function(func_name):
    """Return the real render-daemon function as a callable."""
    source = extract_function(func_name)

    if func_name == '_maybe_fetch_quota':
        assert 'urllib.request.Request' in source, \
            f"{func_name} missing urllib.request.Request"
        assert 'os.replace' in source, \
            f"{func_name} missing os.replace"

    return getattr(_render, func_name)
