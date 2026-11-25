# REIVRO effectiveness benchmark v2

Code: `65fc4b92fe7bd93787f1bcd468cd4e2f3194cf25`.
Integrity: PASS.

| Mode | TP | FP | TN | FN | Undecided positive | Undecided negative | Median ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0 | 0 | 9 | 18 | 0 | 0 | 0.002 | 0.005 |
| B | 15 | 0 | 9 | 0 | 3 | 0 | 138.408 | 297.19 |
| C | 15 | 0 | 9 | 0 | 3 | 0 | 1390.372 | 2543.133 |

| Scenario | A | B | C |
| --- | --- | --- | --- |
| seed/r1 | ACCEPTED | REGRESSION_DETECTED | OBSERVED |
| active_regression/r1 | ACCEPTED | REGRESSION_DETECTED | VIOLATION |
| active_clean/r1 | ACCEPTED | PASS | PASS |
| tampered_regression/r1 | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| missing_regression/r1 | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| provider_failure_regression/r1 | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| tampered_clean/r1 | ACCEPTED | PASS | INCONCLUSIVE |
| missing_evidence/r1 | ACCEPTED | INCONCLUSIVE | INCONCLUSIVE |
| revoked_clean/r1 | ACCEPTED | PASS | OBSERVED |
| seed/r2 | ACCEPTED | REGRESSION_DETECTED | OBSERVED |
| active_regression/r2 | ACCEPTED | REGRESSION_DETECTED | VIOLATION |
| active_clean/r2 | ACCEPTED | PASS | PASS |
| tampered_regression/r2 | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| missing_regression/r2 | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| provider_failure_regression/r2 | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| tampered_clean/r2 | ACCEPTED | PASS | INCONCLUSIVE |
| missing_evidence/r2 | ACCEPTED | INCONCLUSIVE | INCONCLUSIVE |
| revoked_clean/r2 | ACCEPTED | PASS | OBSERVED |
| seed/r3 | ACCEPTED | REGRESSION_DETECTED | OBSERVED |
| active_regression/r3 | ACCEPTED | REGRESSION_DETECTED | VIOLATION |
| active_clean/r3 | ACCEPTED | PASS | PASS |
| tampered_regression/r3 | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| missing_regression/r3 | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| provider_failure_regression/r3 | ACCEPTED | REGRESSION_DETECTED | INCONCLUSIVE |
| tampered_clean/r3 | ACCEPTED | PASS | INCONCLUSIVE |
| missing_evidence/r3 | ACCEPTED | INCONCLUSIVE | INCONCLUSIVE |
| revoked_clean/r3 | ACCEPTED | PASS | OBSERVED |

Synthetic public-PR responses, isolated local compiler and disposable PostgreSQL.
A is simulated acceptance without verification. No merge blocking was exercised.
See JSON for precision, recall, errors, CPU time, versions and row-level evidence.
