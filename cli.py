#!/usr/bin/env python3
"""
Interactive CLI for adding a new company or individual/group blog entry
to README.md, keeping entries in the correct alphabetical subsection.

Usage:
    python cli.py
    python cli.py --file /path/to/README.md
"""

import argparse
import re
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich import box
except ImportError:
    sys.stderr.write(
        "This tool needs the 'rich' package.\n"
        "Install it with:  pip install rich\n"
    )
    sys.exit(1)

console = Console()

# The literal heading marker used in the README for non-alphabetic entries,
# e.g. "#### \# companies"
HASH_MARKER = r"\#"

CATEGORY_CONFIG = {
    "Company": {
        "section_header": "### Companies",
        "suffix": "companies",
    },
    "Individual": {
        "section_header": "### Individuals/Group Contributors",
        "suffix": "individuals",
    },
}

ENTRY_RE = re.compile(r"^\* (.+?)\s+(\S+)$")


# --------------------------------------------------------------------------
# File I/O
# --------------------------------------------------------------------------

def resolve_readme_path(cli_arg: str | None) -> Path:
    if cli_arg:
        path = Path(cli_arg)
    else:
        candidate = Path(__file__).resolve().parent / "README.md"
        path = candidate if candidate.exists() else Path("README.md")

    if not path.exists():
        console.print(f"[bold red]Could not find README.md at:[/bold red] {path}")
        sys.exit(1)
    return path


def load_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def save_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------

def letter_for(name: str) -> str:
    first = name.strip()[0].upper()
    return first if first.isalpha() else HASH_MARKER


def sort_key(name: str) -> str:
    return name.strip().lower()


def normalize_url(url: str) -> str:
    return url.strip().lower().rstrip("/")


def letter_sort_key(letter: str) -> tuple:
    if letter == HASH_MARKER:
        return (0, "")
    return (1, letter.upper())


def find_category_block(lines: list[str], section_header: str) -> tuple[int, int]:
    """Return (start, end) line-index range (end exclusive) owned by a
    top-level '### ...' section, i.e. everything until the next '### ' line."""
    try:
        start = lines.index(section_header) + 1
    except ValueError:
        console.print(f"[bold red]Could not find section:[/bold red] {section_header}")
        sys.exit(1)

    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("### "):
            end = i
            break
    return start, end


def parse_subsections(lines: list[str], start: int, end: int, suffix: str):
    """Find every '#### {letter} {suffix}' subsection within [start, end).

    Returns:
        sections: dict letter -> {"header_idx", "entries": [(idx, name, link)], "block_end"}
        order: list of letters in the order they appear in the file
    """
    header_re = re.compile(r"^#### (\S+) " + re.escape(suffix) + r"$")
    sections: dict = {}
    order: list = []
    i = start
    while i < end:
        m = header_re.match(lines[i])
        if not m:
            i += 1
            continue

        letter = m.group(1)
        header_idx = i
        j = i + 1
        entries = []
        while j < end and not lines[j].startswith("#### ") and not lines[j].startswith("### "):
            stripped = lines[j].strip()
            entry_match = ENTRY_RE.match(stripped)
            if entry_match:
                entries.append((j, entry_match.group(1), entry_match.group(2)))
            j += 1

        sections[letter] = {"header_idx": header_idx, "entries": entries, "block_end": j}
        order.append(letter)
        i = j
    return sections, order


# --------------------------------------------------------------------------
# Core insertion logic
# --------------------------------------------------------------------------

def find_duplicate(sections: dict, link: str) -> str | None:
    """Search every subsection in the category for an entry with the same
    URL (normalized), regardless of which letter it's filed under. Returns
    the existing entry's display name if found, else None."""
    target = normalize_url(link)
    for sec in sections.values():
        for _, existing_name, existing_link in sec["entries"]:
            if normalize_url(existing_link) == target:
                return existing_name
    return None


def insert_entry(lines: list[str], category_key: str, name: str, link: str) -> tuple[list[str], bool]:
    config = CATEGORY_CONFIG[category_key]
    start, end = find_category_block(lines, config["section_header"])
    sections, order = parse_subsections(lines, start, end, config["suffix"])

    target_letter = letter_for(name)
    new_line = f"* {name.strip()} {link.strip()}"

    duplicate = find_duplicate(sections, link)
    if duplicate:
        if not Confirm.ask(
            f"[yellow]This URL is already listed under '{duplicate}'. Add anyway?[/yellow]",
            default=False,
        ):
            return lines, False

    if target_letter in sections:
        sec = sections[target_letter]
        entries = sec["entries"]
        # Default: append right after the last real entry line (not at
        # block_end, which may include trailing blank lines that separate
        # this subsection from the next header).
        insert_at = entries[-1][0] + 1 if entries else sec["header_idx"] + 1
        for idx, existing_name, _existing_link in entries:
            if sort_key(existing_name) > sort_key(name):
                insert_at = idx
                break
        lines.insert(insert_at, new_line)
        return lines, True

    # No subsection for this letter yet -- create one in the right spot.
    insert_at = end
    for letter in order:
        if letter_sort_key(letter) > letter_sort_key(target_letter):
            insert_at = sections[letter]["header_idx"]
            break

    header_text = f"#### {target_letter} {config['suffix']}"
    block = [header_text, new_line, ""]
    lines[insert_at:insert_at] = block
    return lines, True


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

def print_banner(path: Path) -> None:
    console.print(
        Panel.fit(
            "[bold cyan]Software Engineering Blogs[/bold cyan]\n"
            f"[dim]Adding entries to {path}[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )


def prompt_category() -> str:
    console.print()
    console.print("[bold]What would you like to add?[/bold]")
    console.print("  [cyan]1[/cyan]) Company")
    console.print("  [cyan]2[/cyan]) Individual / Group")
    choice = Prompt.ask(
        "Select an option", choices=["1", "2"], default="1", show_choices=False
    )
    return "Company" if choice == "1" else "Individual"


def prompt_name() -> str:
    while True:
        name = Prompt.ask("[bold]Name[/bold]").strip()
        if name:
            return name
        console.print("[red]Name cannot be empty.[/red]")


def prompt_link() -> str:
    while True:
        link = Prompt.ask("[bold]Blog URL[/bold]").strip()
        if not link:
            console.print("[red]Link cannot be empty.[/red]")
            continue
        if not re.match(r"^https?://", link):
            if not Confirm.ask(
                f"[yellow]'{link}' doesn't look like a URL (missing http/https). "
                "Use it anyway?[/yellow]",
                default=False,
            ):
                continue
        return link


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a company or individual to README.md")
    parser.add_argument("--file", help="Path to README.md (defaults to the file next to this script)")
    args = parser.parse_args()

    readme_path = resolve_readme_path(args.file)
    print_banner(readme_path)

    lines = load_lines(readme_path)
    added: list[tuple[str, str, str]] = []

    while True:
        category = prompt_category()
        name = prompt_name()
        link = prompt_link()

        console.print()
        preview = f"* {name} {link}"
        console.print(
            Panel(preview, title=f"New {category} entry", border_style="green", box=box.ROUNDED)
        )

        if not Confirm.ask("Add this entry?", default=True):
            console.print("[dim]Skipped.[/dim]")
        else:
            lines, ok = insert_entry(lines, category, name, link)
            if ok:
                save_lines(readme_path, lines)
                added.append((category, name, link))
                console.print(f"[bold green]\u2713 Added '{name}' to {readme_path.name}[/bold green]")
            else:
                console.print("[dim]Skipped.[/dim]")

        console.print()
        if not Confirm.ask("Add another entry?", default=True):
            break

    console.print()
    if added:
        table = Table(title="Summary", box=box.SIMPLE_HEAVY)
        table.add_column("Type", style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Link", style="dim")
        for category, name, link in added:
            table.add_row(category, name, link)
        console.print(table)
        plural = "y" if len(added) == 1 else "ies"
        console.print(f"[bold green]Done! {len(added)} entr{plural} added.[/bold green]")
    else:
        console.print("[yellow]No entries were added.[/yellow]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[red]Cancelled.[/red]")
        sys.exit(130)