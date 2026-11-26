"""Static checks that have bitten this codebase. Run: python3 tests/test_lint.py

1. A function that calls gettext `_()` must never also bind `_` locally (`x, *_ = …`, `for _ in …`,
   `_ = …`): Python then treats `_` as local in the whole function and the call crashes.
2. Every module imports.
"""
import ast
import glob
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
problems = []


def binds_underscore(fn):
    for node in ast.walk(fn):
        if node is not fn and isinstance(node, (ast.FunctionDef, ast.Lambda, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.Name) and node.id == "_" and isinstance(node.ctx, ast.Store):
            return node.lineno
        if isinstance(node, ast.arg) and node.arg == "_":
            return node.lineno
    return None


def calls_underscore(fn):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_" for n in ast.walk(fn))


def direct_body_nodes(fn):
    """Nodes of fn excluding nested functions/lambdas/comprehensions (their own scopes)."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ListComp, ast.SetComp,
                          ast.DictComp, ast.GeneratorExp, ast.ClassDef)):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


for path in glob.glob(os.path.join(REPO, "kluis", "**", "*.py"), recursive=True):
    tree = ast.parse(open(path).read(), path)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(direct_body_nodes(fn))
        binds = [n.lineno for n in body if isinstance(n, ast.Name) and n.id == "_" and isinstance(n.ctx, ast.Store)]
        binds += [fn.lineno for a in fn.args.args + fn.args.kwonlyargs if a.arg == "_"]
        uses = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_" for n in body)
        if binds and uses:
            problems.append(f"{os.path.relpath(path, REPO)}:{binds[0]} binds `_` in {fn.name}() which calls _()")

mods = [os.path.relpath(p, REPO)[:-3].replace(os.sep, ".") for p in
        glob.glob(os.path.join(REPO, "kluis", "**", "*.py"), recursive=True)]
for m in sorted(mods):
    if m.endswith("__main__"):
        continue
    try:
        importlib.import_module(m)
    except Exception as e:  # noqa: BLE001
        problems.append(f"import {m}: {type(e).__name__}: {e}")

# every Kluis icon the UI names ships with Kluis (desktop themes like Mint-Y lack many symbolic icons)
import re  # noqa: E402
icon_dir = os.path.join(REPO, "kluis", "data", "icons")
for path in glob.glob(os.path.join(REPO, "kluis", "ui", "*.py")):
    for name in set(re.findall(r'"(kluis-[a-z-]+-symbolic)"', open(path).read())):
        if not os.path.exists(os.path.join(icon_dir, name + ".svg")):
            problems.append(f"{os.path.relpath(path, REPO)} uses icon {name}, but {name}.svg is not in kluis/data/icons")

# Cairo drawing (map, gallery, graph) needs the gi ↔ pycairo bridge: python-cairo / python3-gi-cairo
try:
    import gi
    gi.require_foreign("cairo")
except Exception as e:  # noqa: BLE001
    problems.append(f"gi cairo bridge missing (install python-cairo / python3-gi-cairo): {e}")

for p in problems:
    print("FAIL:", p)
print(f"\n{len(mods)} modules checked, {len(problems)} problem(s)")
sys.exit(1 if problems else 0)
