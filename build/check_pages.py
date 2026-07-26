#!/usr/bin/env python3
"""
check_pages.py — syntax-check the browser code before it ships.

The pages are single files with a big inline <script>. A syntax error anywhere
in that block silently kills the WHOLE script: the page loads, renders its
"Loading…" placeholder, and simply never boots — no console error visible in a
casual look, no failed request. That happened, and it reached production twice.
This makes it a build failure instead.

Extracts every inline <script> from each .html and runs `node --check` on it,
plus each standalone .js file. Exits non-zero if anything fails to parse.

    python build/check_pages.py
"""

import glob
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# inline scripts only — anything with a src= attribute is a separate file
INLINE_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)

failures = []


def node_check(source, label, suffix):
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(source)
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        if r.returncode != 0:
            msg = [ln for ln in (r.stderr or "").splitlines() if ln.strip()]
            detail = next((ln for ln in msg if "SyntaxError" in ln), msg[-1] if msg else "?")
            print(f"  [FAIL] {label}: {detail.strip()}")
            failures.append(label)
            return False
        print(f"  [ok]   {label}")
        return True
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def main():
    try:
        if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
            raise OSError
    except OSError:
        # no node here (this Windows box) — CI has it, so the gate still holds
        print("node not available — skipping page syntax check")
        return

    print("Checking inline page scripts")
    for path in sorted(glob.glob(os.path.join(ROOT, "*.html"))):
        html = open(path, encoding="utf-8").read()
        blocks = INLINE_RE.findall(html)
        name = os.path.basename(path)
        if not blocks:
            print(f"  [--]   {name} (no inline script)")
            continue
        for i, src in enumerate(blocks):
            label = name if len(blocks) == 1 else f"{name} #{i + 1}"
            node_check(src, label, ".js")          # classic script semantics

    print("\nChecking standalone scripts")
    for path in sorted(glob.glob(os.path.join(ROOT, "*.js"))):
        # .mjs so top-level await (the Scriptable widget uses it) is legal
        node_check(open(path, encoding="utf-8").read(), os.path.basename(path), ".mjs")

    print()
    if failures:
        print(f"FAILED: {len(failures)} script(s) do not parse: {', '.join(failures)}")
        sys.exit(1)
    print("All page scripts parse.")


if __name__ == "__main__":
    main()
