# SCOP Core v0.1 — skill discovery and matching

This is the smallest working component of the SCOP orchestration engine. It reads `SKILL.md` frontmatter from immediate subfolders under `skills/` and ranks installed skills for an English task using **deterministic keyword matching**. It does not run an AI model, fetch pull requests, execute skills, write files, or modify repositories.

## Usage (from repository root)

```bash
python -m server.scop_core list
python -m server.scop_core match "summarize GitHub pull requests"
python -m unittest discover -s tests -p 'test_core.py' -v
```

No third-party dependencies are required. On Windows PowerShell, use the same `python` commands. A different skills directory can be provided via `--skills-dir PATH` before the subcommand.

## Policy and limitations

- Current allowed capability: reading local skill definitions only (`local:read-skill-definition`). Neither write operations nor network calls are implemented.
- Files and folder symlinks are not followed; duplicate skill names and malformed metadata cause errors.
- Matching uses literal token overlaps and should not be mistaken for semantic/agent selection or proof of skill execution. No match returns an empty list.
- Repository root path and Python module invocation are intentionally explicit to avoid hidden environment assumptions.
- Future milestones: explicit permission grants and approvals; adapter interface; read-only GitHub fetch; orchestrated source-grounded output; audit logs and end-to-end evaluations. Each requires independent tests.
