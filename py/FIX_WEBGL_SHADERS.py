#!/usr/bin/env python3
"""
FIX_WEBGL_SHADERS.py — Ensures URP shaders survive WebGL builds.

PROBLEM:
  All CodeGamified games create materials at runtime via ProceduralAssembler,
  which calls Shader.Find("Universal Render Pipeline/Unlit"). In WebGL builds,
  Unity strips shaders not statically referenced by any material in any scene.
  Shader.Find() returns null → materials don't load → magenta/invisible objects.

FIX:
  Add the URP Lit shader (GUID 650dd9526735d5b46b79224bc6e94025) to the
  Always Included Shaders list in each project's GraphicsSettings.asset.
  Pong has this; the others (from urp-blank template) don't.

USAGE:
  python py/FIX_WEBGL_SHADERS.py              # dry-run (default)
  python py/FIX_WEBGL_SHADERS.py --apply      # actually write files
  python py/FIX_WEBGL_SHADERS.py --check      # exit 0 if all OK, 1 if not
"""
import argparse
import os
import re
import sys

# The shader entry Pong has that fixes WebGL material loading.
# fileID 4800000 = Shader asset, type 3 = project/package asset
# GUID = URP Lit shader from com.unity.render-pipelines.universal
REQUIRED_SHADER = "  - {fileID: 4800000, guid: 650dd9526735d5b46b79224bc6e94025, type: 3}"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories to skip (not Unity projects)
SKIP_DIRS = {"builds", "css", "js", "json", "mp3", "png", "py", "azure", ".git", "memories"}


def find_graphics_settings():
    """Find all GraphicsSettings.asset files in Unity projects."""
    results = []
    for entry in sorted(os.listdir(REPO_ROOT)):
        if entry in SKIP_DIRS or entry.startswith("."):
            continue
        entry_path = os.path.join(REPO_ROOT, entry)
        if not os.path.isdir(entry_path):
            continue
        # Look for {game}/{Game}/ProjectSettings/GraphicsSettings.asset
        for sub in os.listdir(entry_path):
            gs_path = os.path.join(entry_path, sub, "ProjectSettings", "GraphicsSettings.asset")
            if os.path.isfile(gs_path):
                results.append((entry, gs_path))
    return results


def check_file(path):
    """Return True if the file already has the required shader entry."""
    with open(path, "r", encoding="utf-8") as f:
        return "650dd9526735d5b46b79224bc6e94025" in f.read()


def fix_file(path, dry_run=True):
    """Add the required shader entry after the last built-in shader line."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if "650dd9526735d5b46b79224bc6e94025" in content:
        return False  # Already fixed

    # Find the last built-in shader entry (type: 0) before m_PreloadedShaders
    # Insert our shader entry right after it
    pattern = (
        r"(  - \{fileID: 10783, guid: 0000000000000000f000000000000000, type: 0\})\n"
        r"(  m_PreloadedShaders:)"
    )
    replacement = rf"\1\n{REQUIRED_SHADER}\n\2"

    new_content, count = re.subn(pattern, replacement, content)

    if count == 0:
        # Fallback: insert before m_PreloadedShaders regardless
        pattern2 = r"(  m_PreloadedShaders:)"
        replacement2 = rf"{REQUIRED_SHADER}\n\1"
        new_content, count = re.subn(pattern2, replacement2, content)

    if count == 0:
        return None  # Could not find insertion point

    if not dry_run:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_content)

    return True


def main():
    parser = argparse.ArgumentParser(description="Fix WebGL shader stripping for CodeGamified games")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="Write fixes to disk")
    group.add_argument("--check", action="store_true", help="Check only, exit 1 if any need fixing")
    args = parser.parse_args()

    dry_run = not args.apply
    projects = find_graphics_settings()

    if not projects:
        print("No Unity projects found.")
        sys.exit(1)

    ok_count = 0
    fix_count = 0
    fail_count = 0

    for game_name, gs_path in projects:
        if check_file(gs_path):
            print(f"  OK   {game_name}")
            ok_count += 1
        else:
            result = fix_file(gs_path, dry_run=dry_run)
            if result is True:
                action = "FIXED" if not dry_run else "NEEDS FIX"
                print(f"  {action}  {game_name}")
                fix_count += 1
            elif result is False:
                print(f"  OK   {game_name}")
                ok_count += 1
            else:
                print(f"  FAIL {game_name} — could not find insertion point")
                fail_count += 1

    print()
    print(f"Summary: {ok_count} OK, {fix_count} {'fixed' if not dry_run else 'need fix'}, {fail_count} failed")

    if args.check:
        sys.exit(1 if fix_count > 0 or fail_count > 0 else 0)
    elif dry_run and fix_count > 0:
        print("\nRun with --apply to write changes.")


if __name__ == "__main__":
    main()
