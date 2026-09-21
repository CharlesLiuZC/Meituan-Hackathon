"""Read and surgically rewrite the CONFIG literal in submission/solver.py.

Promotion must not reformat the 69KB solver (ast.unparse would drop every
comment), so we locate the top-level `CONFIG = {...}` assign and splice only
those source lines. A compile() check guards against syntax breakage.
"""
from __future__ import annotations

import ast
from pathlib import Path


def config_span(source: str) -> tuple[int, int] | None:
    """Return (start_line, end_line) 1-based inclusive of the CONFIG assign."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CONFIG" for t in node.targets):
            return node.lineno, node.end_lineno
    return None


def read_config(solver_path: str | Path) -> dict:
    source = Path(solver_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CONFIG" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("CONFIG assign not found in " + str(solver_path))


def write_config(solver_path: str | Path, new_config: dict) -> dict:
    path = Path(solver_path)
    source = path.read_text(encoding="utf-8")
    span = config_span(source)
    if span is None:
        raise ValueError("CONFIG assign not found in " + str(path))
    start, end = span
    literal = repr(new_config)
    compile(f"CONFIG = {literal}\n", "<config>", "exec")  # sanity
    lines = source.splitlines(keepends=True)
    replacement = f"CONFIG = {literal}\n"
    new_source = "".join(lines[:start - 1]) + replacement + "".join(lines[end:])
    compile(new_source, str(path), "exec")  # full-file syntax gate before writing
    path.write_text(new_source, encoding="utf-8", newline="")
    return {"config_keys": len(new_config), "replaced_lines": [start, end],
            "size_bytes": path.stat().st_size}
