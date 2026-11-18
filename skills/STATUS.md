# SCOP skill development status

The [catalog](CATALOG.md) records a skill's current development stage. Use the evidence below to propose a status change in a repository review.

| Status | Meaning | Evidence required to advance |
| --- | --- | --- |
| PLANNED | The catalog records the proposed skill and its scope. | Provide a runnable prototype or usable skill instructions. Document inputs, outputs, permissions, dependencies, limitations, and a repeatable local example or fixture check. |
| PROTOTYPE — NOT LIVE VALIDATED | A preliminary implementation exists or has been reported. Live end-to-end validation is outstanding. | Exercise representative inputs through the normal workflow in the intended runtime with real sources or integrations where applicable. Record the revision, runtime, commands, fixtures or source references, actual pass/fail/blocked outcomes, and limitations. Include a failure case and review the permissions used. Resolve blockers in required scenarios before advancement. |
| VALIDATED — PENDING MERGE | Reported evidence supports the documented workflow in the tested environment. Repository approval and merge are pending. | Obtain maintainer approval on the reviewed revision, resolve outstanding review items, and record the merge reference. Use MERGED only after verifying the change is on the target branch. |
| MERGED | The approved skill is present on the target branch and its validation evidence is linked. | This is the final catalog stage. Record release or deployment separately if applicable. Revalidate affected scenarios after material changes. |

Record the skill ID, tested revision, environment, and evidence location in the review. Preserve blocked results with their cause. Scope any compatibility statement to the agents and versions actually tested. Record separate results for each additional agent before claiming cross-agent compatibility.

The prototype labels for Regression Test Generator and Test Failure Diagnosis reflect the supplied catalog status. The catalog assigns no live validation to either skill. The current Pull Request Summary status is based on the [reported Codex results](../tests/pr-source-summary/REPORT.md).
