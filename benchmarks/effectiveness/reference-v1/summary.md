# REIVRO effectiveness benchmark v1

Code: `6df2794cb2980b2ae654ca936be7b9be14bfd3f7`.
Integrity: PASS.

| Mode | TP | FP | TN | FN | Undecided positive | Undecided negative | Median ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0 | 0 | 3 | 5 | 0 | 0 | 0.002 | 0.004 |
| B | 4 | 0 | 2 | 0 | 1 | 1 | 205.553 | 324.731 |
| C | 3 | 0 | 2 | 0 | 2 | 1 | 1917.0140000000001 | 3337.317 |

| Scenario | A | B | C |
| --- | --- | --- | --- |
| valid | ACCEPTED | PASS | OBSERVED |
| novel | ACCEPTED | REGRESSION_DETECTED | OBSERVED |
| recurrence | ACCEPTED | REGRESSION_DETECTED | VIOLATION |
| approved_valid | ACCEPTED | PASS | PASS |
| tampered_artifact | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| revoked | ACCEPTED | REGRESSION_DETECTED | OBSERVED |
| incomplete | ACCEPTED | INCONCLUSIVE | INCONCLUSIVE |
| divergent | ACCEPTED | INCONCLUSIVE | INCONCLUSIVE |
| execution_failure | ACCEPTED | ERROR | RETRYABLE |
| duplicate | ACCEPTED | REGRESSION_DETECTED | COMPLETED |

Synthetic public-PR responses, isolated local compiler and disposable PostgreSQL.
A is simulated acceptance without verification. No merge blocking was exercised.
See JSON for precision, recall, errors, CPU time, versions and row-level evidence.
