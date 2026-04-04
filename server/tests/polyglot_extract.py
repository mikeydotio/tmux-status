"""Extract Python functions from the tmux-claude-status polyglot script."""

import os
import re
import textwrap


SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "tmux-claude-status"
)


def extract_function(func_name):
    """Extract a Python function definition from the polyglot script.

    Reads the script, finds 'def <func_name>(' and extracts all lines
    until the next line at the same or lower indentation level (i.e.,
    the next module-level definition or unindented code).

    Returns the function source as a string, dedented to top level.
    """
    with open(SCRIPT_PATH) as f:
        lines = f.readlines()

    start = None
    base_indent = None
    for i, line in enumerate(lines):
        if re.match(rf'^(\s*)def {func_name}\(', line):
            start = i
            base_indent = len(line) - len(line.lstrip())
            break

    if start is None:
        raise ValueError(f"Function '{func_name}' not found in {SCRIPT_PATH}")

    func_lines = [lines[start]]
    for line in lines[start + 1:]:
        stripped = line.rstrip()
        if not stripped:
            func_lines.append(line)
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= base_indent and stripped:
            break
        func_lines.append(line)

    while func_lines and not func_lines[-1].strip():
        func_lines.pop()

    source = textwrap.dedent(''.join(func_lines))
    return source


def load_function(func_name):
    """Extract and compile a function, returning it as a callable.

    The function is compiled and exec'd into a namespace that includes
    common stdlib modules the polyglot script uses.
    """
    source = extract_function(func_name)

    if func_name == '_maybe_fetch_quota':
        assert 'urllib.request.Request' in source, \
            f"Extracted {func_name} missing urllib.request.Request - extraction failed"
        assert 'os.replace' in source, \
            f"Extracted {func_name} missing os.replace - extraction failed"

    namespace = {}
    exec("import os, json, time, urllib.request", namespace)

    code = compile(source, f"tmux-claude-status:{func_name}", "exec")
    exec(code, namespace)

    if func_name not in namespace:
        raise ValueError(f"Function '{func_name}' not found after exec")

    return namespace[func_name]
