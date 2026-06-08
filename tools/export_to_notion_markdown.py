#!/usr/bin/env python3
"""Export exact repository files into a single Notion-ready Markdown bundle.

The output is a plain Markdown document that contains the full text of every
tracked source/document file in the repository, excluding common generated,
secret, and virtual-environment paths.

Usage:
    python tools/export_to_notion_markdown.py

Output:
    notion-export/devpulse-exact-files.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "notion-export" / "devpulse-exact-files.md"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}

EXCLUDED_FILES = {
    ".env",
    "mcp-filesystem.log",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".ico",
}


@dataclass(frozen=True)
class ExportedFile:
    path: Path
    content: str


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_DIRS:
        return True
    if path.name in EXCLUDED_FILES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    return False


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_dir() or should_skip(path):
            continue
        yield path


def read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def export_files(root: Path) -> list[ExportedFile]:
    exported: list[ExportedFile] = []
    for path in iter_text_files(root):
        exported.append(ExportedFile(path=path.relative_to(root), content=read_text(path)))
    return exported


def build_markdown(files: list[ExportedFile]) -> str:
    lines: list[str] = []
    lines.append("# DevPulse Exact Files Bundle")
    lines.append("")
    lines.append("This document contains the exact text of repository files that are safe to export.")
    lines.append("Excluded: `.git/`, `.venv/`, `__pycache__/`, `mcp-filesystem.log`, `.env`, and binary assets.")
    lines.append("")
    lines.append(f"Total exported files: {len(files)}")
    lines.append("")
    lines.append("## File Index")
    for item in files:
        lines.append(f"- `{item.path.as_posix()}`")
    lines.append("")

    for item in files:
        lines.append(f"## `{item.path.as_posix()}`")
        lines.append("")
        lines.append("```text")
        lines.append(item.content.rstrip("\n"))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    files = export_files(ROOT)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(build_markdown(files), encoding="utf-8")
    print(f"Exported {len(files)} files to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()