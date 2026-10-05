# Test design reference

## Validator rules and risk severity

The deterministic rules are defined in code, and their codes and messages come back from
`submit_test_cases` / `validate_test_cases`. Errors block export; warnings should be fixed
or justified. Act on the returned message. Don't rely on a copy of the rules here.

- Test-case rules: `src/qa_assistant/testdesign/rules.py`
- Analysis checks: `src/qa_assistant/analysis/checks.py`
- Risk severity (computed by the server from likelihood x impact):
  `risk_severity` in `src/qa_assistant/domain/analysis.py`

## Worked example: password length 12-64

AC: "The new password must be 12-64 characters long."

- `boundary_value`: 11 (rejected), 12 (accepted), 64 (accepted), 65 (rejected).
- `equivalence_partitioning`: empty, whitespace-only, valid 30-char password.
- `negative`: password equal to the email address (only if a rule exists; otherwise a PO
  question, not a test).

Good step:
- action: "Enter an 11-character password `Abcdefgh1!x` and submit."
- expected_result: "Validation message 'Password must be 12-64 characters' is shown; password
  is not changed."

Bad step:
- action: "Test password length." / expected_result: "Works as expected."
