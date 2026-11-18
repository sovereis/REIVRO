"""Run with python -m server.scop_core from the repository root."""
import argparse
import json
from pathlib import Path
from .core import discover, match, permissions_for


def main() -> int:
    parser = argparse.ArgumentParser(description="SCOP Core v0.1 (discovery only)")
    parser.add_argument("--skills-dir", type=Path, default=Path(__file__).resolve().parents[2] / "skills")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List installed skill definitions")
    selector = sub.add_parser("match", help="Rank skills using lexical matching")
    selector.add_argument("task", help="Task description in English")
    args = parser.parse_args()
    try:
        skills = discover(args.skills_dir)
        if args.command == "list":
            payload = [{"name": s.name, "description": s.description, "permissions": permissions_for(s)} for s in skills]
        else:
            payload = [{"name": s.name, "score": score, "permissions": permissions_for(s), "executed": False} for s, score in match(args.task, skills)]
        print(json.dumps(payload, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"SCOP error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
