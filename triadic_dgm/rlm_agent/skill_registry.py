"""Catalog and load local data-agent skills from their SKILL.md frontmatter."""

from __future__ import annotations

from pathlib import Path
from typing import Any


SKILLS_ROOT = Path(__file__).with_name("skills")


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata


def _skill_entry(skill_file: Path) -> dict[str, Any]:
    metadata = _frontmatter(skill_file.read_text(encoding="utf-8"))
    name = metadata.get("name") or skill_file.parent.name
    return {
        "name": name,
        "description": metadata.get("description", ""),
        "argument_hint": metadata.get("argument-hint", ""),
        "user_invocable": metadata.get("user-invocable", "true").lower() != "false",
    }


def list_skills(
    *,
    user_invocable_only: bool = False,
    skills_root: str | Path = SKILLS_ROOT,
) -> list[dict[str, Any]]:
    """Return the installed skill catalog without loading full instruction bodies."""
    root = Path(skills_root)
    if not root.exists():
        return []
    entries = [_skill_entry(path) for path in sorted(root.glob("*/SKILL.md"))]
    if user_invocable_only:
        entries = [entry for entry in entries if entry["user_invocable"]]
    return entries


def read_skill(name: str, *, skills_root: str | Path = SKILLS_ROOT) -> str:
    """Read an installed skill by exact catalog name, rejecting filesystem paths."""
    normalized = str(name or "").strip()
    root = Path(skills_root)
    catalog = {
        entry["name"]: entry for entry in list_skills(skills_root=root)
    }
    if normalized not in catalog:
        raise ValueError(
            f"Skill {normalized!r} not found; available skills: {sorted(catalog)}"
        )
    skill_file = root / normalized / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"Skill {normalized!r} has no SKILL.md entrypoint")
    return skill_file.read_text(encoding="utf-8")


def load_selected_skill(name: str | None) -> dict[str, Any] | None:
    """Validate a user-selected skill and return metadata plus full instructions."""
    if not name:
        return None
    normalized = str(name).strip()
    catalog = {
        entry["name"]: entry
        for entry in list_skills(user_invocable_only=True)
    }
    if normalized not in catalog:
        raise ValueError(
            f"Skill {normalized!r} is not user-invocable; available skills: "
            f"{sorted(catalog)}"
        )
    return {**catalog[normalized], "instructions": read_skill(normalized)}
