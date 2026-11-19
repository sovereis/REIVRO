"""Read-only skill discovery, matching and policy evaluation.

This module does not execute agent instructions or contact external services.
"""
from dataclasses import dataclass
from pathlib import Path
import re

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({"a", "an", "and", "are", "at", "by", "for", "from", "in", "is", "of", "on", "or", "the", "to", "with"})


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    file: Path


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    # Closing delimiter is a complete line, including when it ends at EOF.
    match = re.search(r"(?m)^---(?:\n|$)", text[4:])
    if match is None:
        raise ValueError("unterminated frontmatter")
    header = text[4:4 + match.start()]
    fields: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError("malformed frontmatter")
        key, value = line.split(":", 1)
        if key.strip() not in {"name", "description"}:
            continue
        if key.strip() in fields:
            raise ValueError("duplicate field")
        fields[key.strip()] = value.strip().strip('"').strip("'")
    if not fields.get("name") or not fields.get("description"):
        raise ValueError("name and description are required")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fields["name"]):
        raise ValueError("invalid skill name")
    return fields


def discover(skills_dir: Path) -> list[Skill]:
    """Find one SKILL.md per immediate skill subfolder; don't follow symlinks."""
    if skills_dir.is_symlink():
        raise ValueError(f"symlinked skills root is not allowed: {skills_dir}")
    if not skills_dir.is_dir():
        raise FileNotFoundError(f"skills directory not found: {skills_dir}")
    found: list[Skill] = []
    names: set[str] = set()
    for folder in sorted(skills_dir.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            continue
        path = folder / "SKILL.md"
        if not path.is_file() or path.is_symlink():
            continue
        if path.stat().st_size > 256_000:
            raise ValueError(f"oversized skill definition: {path}")
        fields = _frontmatter(path.read_text(encoding="utf-8"))
        if fields["name"] in names:
            raise ValueError(f"duplicate skill name: {fields['name']}")
        names.add(fields["name"])
        found.append(Skill(fields["name"], fields["description"], path))
    return found


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower())) - _STOPWORDS


def match(task: str, skills: list[Skill]) -> list[tuple[Skill, int]]:
    """Deterministic lexical ranking, not AI reasoning or skill execution."""
    if not task.strip():
        raise ValueError("task must not be empty")
    task_words = _tokens(task)
    scores = []
    for skill in skills:
        name_words = _tokens(skill.name.replace("-", " "))
        description_words = _tokens(skill.description)
        score = 4 * len(task_words & name_words) + len(task_words & description_words)
        if score > 0:
            scores.append((skill, score))
    return sorted(scores, key=lambda item: (-item[1], item[0].name))


def permissions_for(skill: Skill) -> tuple[str, ...]:
    """v0.1 policy: listing and matching only; no skill execution permissions."""
    return ("local:read-skill-definition",)
