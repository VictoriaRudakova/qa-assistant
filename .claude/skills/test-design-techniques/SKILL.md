---
name: test-design-techniques
description: Reference for manual test design techniques (equivalence partitioning, boundary values, decision tables, state transitions, error guessing) and the quality bar for test cases in this project. Use when designing or reviewing test cases.
user-invocable: false
---

# Test design techniques

Map each test case to the `technique` value that produced it.

| technique | Use when | Minimum expectation |
|---|---|---|
| `positive` | Main success path of an AC | One per AC |
| `negative` | Invalid input, unauthorized action, missing data | At least one per input/permission rule |
| `equivalence_partitioning` | Input domains with classes of values | One representative per valid and invalid class |
| `boundary_value` | Numeric/length/date/time limits | min-1, min, max, max+1 (merge steps if cheap) |
| `decision_table` | Several conditions combine into outcomes | One case per meaningful rule column |
| `state_transition` | Status/lifecycle changes | Valid transitions + at least one invalid transition |
| `error_handling` | Downstream failures, timeouts, retries | User-visible behavior and data consistency |
| `error_guessing` | Known failure patterns (double submit, back button, concurrency, special chars) | Only for plausible risks |

## Quality bar

- **Atomic steps:** one action per step; the expected result is observable (UI text, state,
  email, record) and specific.
- **Independent tests:** each test sets up its own preconditions.
- **Synthetic data:** `example.com` emails, fictitious names, no production identifiers.
- **Traceability:** `covers` lists only ACs the test truly verifies; `risk_ids` only risks
  it would detect.
- **No duplication:** the same behavior with the same partition belongs in one test.

See [reference.md](reference.md) for a worked example and where the validator rules live.
