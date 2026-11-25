# Mission 6.1 evidence

The base is 40c389d35fa896dc22d8da31ef7806a645f7576d. Core product behavior is frozen. This change adds two recovery regression tests, a disposable filesystem boundary probe, and the alpha documentation and voluntary local feedback template.

Clean installation used two fresh Git archive extractions, a temporary home, system Python, a launcher symlink, and a minimal environment. Installation, switching the launcher to the second identical pinned extraction, two complete demos, and removal passed in 1.933 seconds. This validates the installation mechanics on the current Linux host. A new product version, a second physical machine, and WSL remain unvalidated. Git fsck and diff whitespace checks passed.

The security probe passed read and write denial for synthetic credentials, criteria, and journal files and write denial for a trusted launcher under a distinct container UID. The disposable container has no network. Setup requires SETUID and SETGID capabilities to change from the operator identity to the agent identity. This test does not execute product approval/revocation commands with a second host user. The host lacks sudo. The Cloud agent has Docker access, so the intended operator/agent host boundary remains unproven. SECURITY BOUNDARY and PRIVATE ALPHA remain BLOCKED.

Recovery tests passed a stopped-journal copy into a fresh private directory, recovery of the prior report, approved runtime manifest use, rejection and regeneration of a missing manifest, rejection and preservation of adulterated bytes, revocation across another restore, and retry of the same event after interruption before persistence. Existing event replay tests cover persisted results. Cross-UID restore requires separate review.

Codex CLI 0.172.0-alpha.2 is installed. No separately entitled inference was started. The existing conversation supplies engineering work but the full real-client exercise with protected operator decisions remains BLOCKED. The founder protocol is in README.md.

The kit provides installation, first verification, security model, recovery, limitations, troubleshooting, manual feedback, and a short real-command demo script. The demo has synthetic agents and tasks. Voluntary feedback is a local editable JSON template with consent false by default. No collection or upload process is installed.

| Suite | Result |
| --- | --- |
| Standard pytest | 265 passed, 17 skipped |
| Disposable PostgreSQL | 29 passed |
| Chromium UI | 10 passed |
| Opt-in task and task Firewall benchmarks | 21 passed |
| Effectiveness V1 | 2 passed |
| Effectiveness V2 | 2 passed |
| Functional declarative benchmark | Completed successfully |
| Live GitHub pytest | 265 passed, 12 skipped, 5 failed |

The five live failures affect measurement, PR summary, web HTTP, workflow, and workspace paths. GitHub availability remains an external verification gap. The local product verdict does not depend on declaring those tests successful.

INSTALLATION is PARTIAL. SECURITY BOUNDARY is BLOCKED. RECOVERY is PASS. REAL AGENT VALIDATION is BLOCKED. ALPHA KIT is READY. PRIVATE ALPHA is BLOCKED.
