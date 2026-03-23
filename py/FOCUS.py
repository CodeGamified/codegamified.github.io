"""
╔══════════════════════════════════════════════════════════════╗
║  FOCUS.py — Control .gitignore & .copilotignore at root     ║
║  Focus Copilot context on active projects only               ║
╚══════════════════════════════════════════════════════════════╝
Usage:
  python FOCUS.py galaga asteroids      # focus on galaga + asteroids
  python FOCUS.py --all                 # clear focus (include everything)
  python FOCUS.py --list                # show current focus state
  python FOCUS.py --dry-run galaga      # preview without writing
"""
import sys, os, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from TUI import *

# ─────────────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(SCRIPT_DIR)

GITIGNORE_PATH      = os.path.join(REPO_ROOT, '.gitignore')
COPILOTIGNORE_PATH  = os.path.join(REPO_ROOT, '.copilotignore')

MARKER = '# [FOCUS.py]'

# Always ignored in .copilotignore regardless of focus
COPILOT_ALWAYS = ['.data/', '.engine/', 'png/', 'mp3/', 'builds/', 'LICENSE.txt', 'CNAME']

# Heavy Unity dirs to ignore even within focused projects (per-project .copilotignore)
UNITY_NOISE = [
    'Library/PackageCache',
    'Assets/Resources/',
    'Assets/TextMesh Pro',
    'Temp',
    'Logs',
    'Library',
]

# Non-project dirs to skip during discovery
SKIP_DIRS = {
    '.git', '.github', '.data', '.engine', '.vscode',
    'builds', 'css', 'js', 'json', 'mp3', 'png', 'py',
    'azure', 'node_modules', '__pycache__',
}

# ─────────────────────────────────────────────────────────────
#  Discovery
# ─────────────────────────────────────────────────────────────

def discover_projects():
    """Return sorted list of project directory names (lowercase)."""
    projects = []
    for entry in os.listdir(REPO_ROOT):
        if entry.startswith('.') or entry in SKIP_DIRS:
            continue
        full = os.path.join(REPO_ROOT, entry)
        if not os.path.isdir(full):
            continue
        # Must contain a Unity project subdir or a README.md
        if any(os.path.isdir(os.path.join(full, sub)) for sub in os.listdir(full)
               if os.path.isdir(os.path.join(full, sub))):
            projects.append(entry)
    return sorted(projects)


def find_unity_subdir(project_dir):
    """Return the PascalCase Unity project subdir name, or None."""
    full = os.path.join(REPO_ROOT, project_dir)
    for entry in os.listdir(full):
        sub = os.path.join(full, entry)
        if os.path.isdir(sub) and os.path.isdir(os.path.join(sub, 'Assets')):
            return entry
    return None

# ─────────────────────────────────────────────────────────────
#  File reading — parse current focus
# ─────────────────────────────────────────────────────────────

def read_current_focus():
    """Parse .copilotignore for FOCUS.py-managed block. Return set of excluded project names."""
    if not os.path.exists(COPILOTIGNORE_PATH):
        return set()
    with open(COPILOTIGNORE_PATH, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
    excluded = set()
    in_block = False
    for line in lines:
        if line.strip() == f'{MARKER} BEGIN':
            in_block = True
            continue
        if line.strip() == f'{MARKER} END':
            in_block = False
            continue
        if in_block and line.strip() and not line.startswith('#'):
            # Lines look like "galaga/" — strip trailing slash
            name = line.strip().rstrip('/')
            if name:
                excluded.add(name)
    return excluded

# ─────────────────────────────────────────────────────────────
#  Generation
# ─────────────────────────────────────────────────────────────

def build_copilotignore(excluded, focused):
    """Build .copilotignore content."""
    lines = list(COPILOT_ALWAYS)
    lines.append('')

    # Per-focused-project Unity noise
    for proj in sorted(focused):
        unity = find_unity_subdir(proj)
        if unity:
            for noise in UNITY_NOISE:
                lines.append(f'{proj}/{unity}/{noise}')
            lines.append('')

    # Excluded projects block
    if excluded:
        lines.append(f'{MARKER} BEGIN')
        for proj in sorted(excluded):
            lines.append(f'{proj}/')
        lines.append(f'{MARKER} END')

    return '\n'.join(lines) + '\n'


def build_gitignore(excluded):
    """Build .gitignore content. Only the FOCUS.py-managed block."""
    # Preserve any pre-existing non-FOCUS content
    existing_lines = []
    if os.path.exists(GITIGNORE_PATH):
        with open(GITIGNORE_PATH, 'r', encoding='utf-8') as f:
            raw = f.read().splitlines()
        in_block = False
        for line in raw:
            if line.strip() == f'{MARKER} BEGIN':
                in_block = True
                continue
            if line.strip() == f'{MARKER} END':
                in_block = False
                continue
            if not in_block:
                existing_lines.append(line)
    # Strip trailing blanks
    while existing_lines and not existing_lines[-1].strip():
        existing_lines.pop()

    lines = list(existing_lines)
    if excluded:
        if lines:
            lines.append('')
        lines.append(f'{MARKER} BEGIN')
        for proj in sorted(excluded):
            lines.append(f'{proj}/')
        lines.append(f'{MARKER} END')

    return '\n'.join(lines) + '\n' if lines else ''

# ─────────────────────────────────────────────────────────────
#  Display
# ─────────────────────────────────────────────────────────────

def print_state(projects, focused, excluded):
    """Print focus table."""
    w = term_width()
    print()
    print(header_line('FOCUS', w))
    print()
    for i, proj in enumerate(projects):
        t = i / max(len(projects) - 1, 1)
        r, g, b = gradient_rgb(t)
        color = fg(r, g, b)
        if proj in focused:
            icon = f'{C.BGRN}{CHECK}{C.RST}'
            label = f'{C.BWHT}{proj}{C.RST}'
        elif proj in excluded:
            icon = f'{C.DIM}{CROSS}{C.RST}'
            label = f'{C.DIM}{proj}{C.RST}'
        else:
            icon = f'{C.DIM}{CIRCLE_EMPTY}{C.RST}'
            label = f'{C.DIM}{proj}{C.RST}'
        print(f'  {color}{BOX_V}{C.RST} {icon}  {label}')
    print()


def print_diff(path, content, label):
    """Show what would be written."""
    print(f'  {C.BCYN}{DIAMOND_FILLED}{C.RST} {C.BWHT}{label}{C.RST}  {C.DIM}{ARROW_R}{C.RST}  {path}')
    for line in content.splitlines():
        print(f'    {C.DIM}{line}{C.RST}')
    print()

# ─────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Focus Copilot + Git context on active projects.',
        epilog='Examples:\n'
               '  python FOCUS.py galaga asteroids\n'
               '  python FOCUS.py --all\n'
               '  python FOCUS.py --list\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('projects', nargs='*', help='Project dirs to focus on (lowercase)')
    parser.add_argument('--all', action='store_true', help='Clear focus — include everything')
    parser.add_argument('--list', action='store_true', help='Show current focus state')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without writing')
    parser.add_argument('--git', action='store_true', help='Also update .gitignore (default: .copilotignore only)')
    args = parser.parse_args()

    all_projects = discover_projects()

    if not all_projects:
        print(f'  {C.RED}{CROSS}{C.RST} No project directories found in {REPO_ROOT}')
        sys.exit(1)

    # --list: show current state and exit
    if args.list:
        excluded = read_current_focus()
        focused = set(all_projects) - excluded
        print_state(all_projects, focused, excluded)
        sys.exit(0)

    # --all: clear all exclusions
    if args.all:
        focused = set(all_projects)
        excluded = set()
    elif args.projects:
        # Validate project names
        bad = [p for p in args.projects if p not in all_projects]
        if bad:
            print(f'  {C.RED}{CROSS}{C.RST} Unknown project(s): {", ".join(bad)}')
            print(f'  {C.DIM}Available: {", ".join(all_projects)}{C.RST}')
            sys.exit(1)
        focused = set(args.projects)
        excluded = set(all_projects) - focused
    else:
        parser.print_help()
        sys.exit(0)

    # Build file contents
    copilot_content = build_copilotignore(excluded, focused)
    git_content = build_gitignore(excluded) if args.git else None

    # Show state
    print_state(all_projects, focused, excluded)

    # Dry-run
    if args.dry_run:
        print(f'  {C.BYLW}{WARN}{C.RST} {C.BWHT}--dry-run{C.RST}  no files written\n')
        print_diff(COPILOTIGNORE_PATH, copilot_content, '.copilotignore')
        if git_content is not None:
            print_diff(GITIGNORE_PATH, git_content, '.gitignore')
        sys.exit(0)

    # Write
    with open(COPILOTIGNORE_PATH, 'w', encoding='utf-8') as f:
        f.write(copilot_content)
    print(f'  {C.BGRN}{CHECK}{C.RST} wrote {C.BWHT}.copilotignore{C.RST}  ({len(excluded)} excluded, {len(focused)} focused)')

    if git_content is not None:
        with open(GITIGNORE_PATH, 'w', encoding='utf-8') as f:
            f.write(git_content)
        print(f'  {C.BGRN}{CHECK}{C.RST} wrote {C.BWHT}.gitignore{C.RST}')

    if not args.git and excluded:
        print(f'  {C.DIM}{INFO}  pass --git to also update .gitignore{C.RST}')

    print()


if __name__ == '__main__':
    main()
