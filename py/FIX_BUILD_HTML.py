#!/usr/bin/env python3
"""
FIX_BUILD_HTML.py — Re-injects postMessage into Unity WebGL build index.html files.

PROBLEM:
  Unity WebGL builds overwrite builds/{game}/index.html, wiping the custom
  postMessage({ type: 'unity-ready' }) call that the parent page (MODALS.js)
  listens for to know when the iframe game has finished loading.

FIX:
  Inject `window.parent.postMessage({ type: 'unity-ready' }, '*');` into the
  .then((unityInstance) => { ... }) callback after `loadingBar.style.display = "none";`

USAGE:
  python py/FIX_BUILD_HTML.py              # dry-run (default)
  python py/FIX_BUILD_HTML.py --apply      # actually write files
  python py/FIX_BUILD_HTML.py --check      # exit 0 if all OK, 1 if not
"""
import argparse
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDS_DIR = os.path.join(REPO_ROOT, "builds")

# The postMessage snippet that must exist in every build's index.html
POSTMESSAGE_MARKER = "window.parent.postMessage"

# Pattern: the .then callback with only loadingBar hidden (no postMessage)
# Matches the Unity-generated default callback
NEEDS_FIX_PATTERN = re.compile(
    r"(\.then\(\(unityInstance\)\s*=>\s*\{\s*\n)"
    r"(\s*loadingBar\.style\.display\s*=\s*\"none\";\s*\n)"
    r"(\s*\})\)",
)

# Replacement: same callback but with postMessage injected
REPLACEMENT_TEMPLATE = (
    r'\1\2'
    r'{indent}if (window.parent !== window) {{\n'
    r'{indent}  window.parent.postMessage({{ type: \'unity-ready\' }}, \'*\');\n'
    r'{indent}}}\n'
    r'\3)'
)


def find_build_htmls():
    """Find all builds/*/index.html files."""
    results = []
    if not os.path.isdir(BUILDS_DIR):
        return results
    for entry in sorted(os.listdir(BUILDS_DIR)):
        html_path = os.path.join(BUILDS_DIR, entry, "index.html")
        if os.path.isfile(html_path):
            results.append((entry, html_path))
    return results


def has_postmessage(path):
    """Return True if the file already has the postMessage injection."""
    with open(path, "r", encoding="utf-8") as f:
        return POSTMESSAGE_MARKER in f.read()


def fix_file(path, dry_run=True):
    """Inject the postMessage call. Returns True=fixed, False=already ok, None=failed."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if POSTMESSAGE_MARKER in content:
        return False

    match = NEEDS_FIX_PATTERN.search(content)
    if not match:
        return None

    # Detect indent from the loadingBar line
    loading_line = match.group(2)
    indent = re.match(r"(\s*)", loading_line).group(1)

    replacement = REPLACEMENT_TEMPLATE.format(indent=indent)
    new_content = NEEDS_FIX_PATTERN.sub(replacement, content, count=1)

    if not dry_run:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_content)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Fix Unity WebGL build HTML files with postMessage injection"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="Write fixes to disk")
    group.add_argument("--check", action="store_true", help="Check only, exit 1 if any need fixing")
    args = parser.parse_args()

    dry_run = not args.apply
    builds = find_build_htmls()

    if not builds:
        print("No build index.html files found in builds/.")
        sys.exit(1)

    ok_count = 0
    fix_count = 0
    fail_count = 0

    for game_name, html_path in builds:
        if has_postmessage(html_path):
            print(f"  OK   {game_name}")
            ok_count += 1
        else:
            result = fix_file(html_path, dry_run=dry_run)
            if result is True:
                action = "FIXED" if not dry_run else "NEEDS FIX"
                print(f"  {action}  {game_name}")
                fix_count += 1
            elif result is False:
                print(f"  OK   {game_name}")
                ok_count += 1
            else:
                print(f"  FAIL {game_name} — could not find .then() callback pattern")
                fail_count += 1

    print()
    print(f"Summary: {ok_count} OK, {fix_count} {'fixed' if not dry_run else 'need fix'}, {fail_count} failed")

    if args.check:
        sys.exit(1 if fix_count > 0 or fail_count > 0 else 0)
    elif dry_run and fix_count > 0:
        print("\nRun with --apply to write changes.")


if __name__ == "__main__":
    main()
