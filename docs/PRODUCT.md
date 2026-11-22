# REIVRO product direction

REIVRO is being built to verify AI-generated development work, learn from failures, and prevent recurring mistakes from creating rework.

**VERIFY → LEARN → PREVENT**

Audience: software developers and engineering teams using AI coding tools, initially in the United States.

Your AI does the work. REIVRO verifies what actually happened. This describes the intended direction, not a guarantee of general agent verification today.

| Status | Capability and boundary |
| --- | --- |
| AVAILABLE | Local public GitHub PR summary workflow with traceable excerpts, source matching, execution records, human evaluation and optional measurements. Excerpt verification does not prove all claims or code correctness. |
| PROTOTYPE | Regression Test Generator skill and documented upstream cases; no executable workflow adapter. |
| IN DEVELOPMENT | Broader verification foundation; arbitrary task/acceptance-criteria verification is not available. |
| PLANNED | Failure knowledge, proposed invariants, developer-approved persistent rules and recurring-regression prevention as an integrated Rework Firewall. |

Proposed verification inputs include the original task, acceptance criteria, agent claims, code, Git diff, changed files, test results and logs. Detected failures should become reproducible cases and proposed safeguards. Persistent rules must be reviewed and approved by the developer. These are requirements for future work, not claims that the current runtime implements them.

Agents, skills, commands, MCP and workflows may remain implementation components. Their counts are not the value proposition. Existing catalog development statuses describe individual artifacts and do not imply execution adapters or product-wide availability.

No cross-agent compatibility, time savings or percentage reduction in rework is claimed without measurements. The landing's domain-migration example is illustrative, not a recorded execution.
