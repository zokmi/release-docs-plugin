# Task 5 review remediation — shared secret redaction

## Findings addressed

- Unknown `credential material: opaque-value` now fails closed with the non-sensitive `secret_redaction_required` error. The raw input is never included in the error.
- Text `user_id=...` assignments are masked. A bare identifier assignment inside an `UPDATE ... SET` statement is preserved as SQL evidence, including `UPDATE t SET user_id = source_user_id`; prose such as `login failed user_id=alice` remains masked. Ordinary SQL identifiers, including `user_id` column references and `dbo.ReleaseUser`, remain unchanged.
- `produce_release(..., secrets=())` and `resume_release(..., secrets=())` now accept known secret values with backward-compatible defaults. Values flow to lifecycle evidence, production results, workflow checkpoints, and failure checkpoints; the built-in resume production request combines its own secrets with the resume-level values.
- The built-in resume path passes the combined request-level and resume-level secret values to `_save_result`, so request-only secrets in findings or unit mapping are masked in `production_result.json`.

Exception persistence remains limited to the existing non-sensitive stage summary. Business-data validation classification and production semantics are unchanged.

## Verification

- New regressions first failed as expected: the generic assignment rule changed `source_user_id` to `[REDACTED]`, and a request-only secret remained visible in `production_result.json`. Both passed after the fixes.
- `pytest.exe tests/test_evidence_redaction.py tests/test_resumable_workflow.py tests/test_produce_release.py -q --basetemp .pytest-task5-final-review-focused` → **49 passed** in 219.58s.
- The focused run emitted the existing `pyreadline3` `Console.__del__` Windows `WinError 0xc0000008` during shutdown; pytest exited successfully.
- `pytest.exe tests/test_evidence_redaction.py tests/test_local_validation.py tests/test_artifact_lifecycle.py tests/test_resumable_workflow.py -q --basetemp .pytest-task5-review-focused` → **112 passed, 2 skipped**.
- `pytest.exe tests/test_evidence_redaction.py tests/test_resumable_workflow.py tests/test_produce_release.py tests/test_release_review.py -q --basetemp .pytest-task5-review-rerun` → **281 passed, 2 skipped**.
- An initial combined run surfaced two backward-compatibility failures because empty `secrets` was added to existing production request kwargs. The forwarding now omits that argument when absent and empty; both affected workflow cases passed in the rerun above.
- The Python test process emitted the existing `pyreadline3` `Console.__del__` Windows `WinError 0xc0000008` during teardown after successful runs; pytest exit status and test results were unaffected.

Base: `d6b6c23`.

## P2 follow-up on `323676a`

- Bounded the SQL `user_id` identifier exemption at comment boundaries. Added a regression for `UPDATE t SET user_id = source_user_id -- login failed user_id=alice`; the source identifier remains byte-for-byte intact and `alice` is redacted.
- The direct `produce_release(..., secrets=...)` persistence assertion already covers secret forwarding and passed unchanged.
- Focused verification: `pytest.exe tests/test_evidence_redaction.py tests/test_resumable_workflow.py tests/test_produce_release.py -q --basetemp .pytest-task5-comment-boundary-run1` → **50 passed** in 190.91s. A first attempt using Windows Temp failed to create pytest fixture directories under the sandbox; the workspace-basetemp rerun completed successfully. Pytest also emitted the existing non-failing `pyreadline3` Windows shutdown warning (`WinError 0xc0000008`).
- Fix commit: `fix: bound SQL redaction exemption`.

## Final review findings on `f26a175`

- The SQL `user_id` exemption now preserves only an unquoted identifier RHS. Quoted values such as `UPDATE users SET user_id='alice'` are redacted. SQL-context matching spans line breaks and stops at comments and statement boundaries; comments and prose assignments remain redacted.
- `produce_release`, `resume_release`, and `write_lifecycle_run` now materialize and validate secret iterables once as a reusable tuple before their durable writes. Generator inputs are covered at all three boundaries, including workflow checkpoints, lifecycle documents, and the durable production result.
- Existing safe error summaries remain unchanged; raw exception details are not persisted. Public defaults remain `secrets=()`.
- Regression tests were first run against the pre-fix implementation and failed on the quoted RHS, multiline SQL context, and generator-secret persistence cases. All added regressions passed after the fix.
- Focused verification: `pytest.exe tests/test_evidence_redaction.py tests/test_resumable_workflow.py tests/test_produce_release.py tests/test_analysis_metadata.py tests/test_local_validation.py tests/test_artifact_lifecycle.py -q --basetemp .pytest-task5-final-review-focused` → **142 passed, 2 skipped** in 344.50s. The pytest process exited successfully; the existing `pyreadline3` Windows `Console.__del__` shutdown warning (`WinError 0xc0000008`) appeared afterward.
- Diff whitespace verification: `git diff --check`.

## Lexical SQL redaction hardening on `a49f3a8`

- Replaced the regex look-behind SQL exemption with a small lexical scan. SQL single-quoted literals are consumed through doubled-quote escapes, bracketed identifiers are consumed as tokens, and comments/literals cannot create an `UPDATE ... SET` context. The exemption is limited to an unquoted bare or bracketed identifier at an actual `SET` assignment target; SQL-looking text inside a quoted note and nested `user_id=...` prose remain redacted.
- Sensitive assignment matching now consumes complete single-quoted values with doubled-quote escapes, so `user_id='ali''ce'` is masked as a whole. Safe literal and identifier bytes are preserved when no secret is present. Existing `normalize_secrets` behavior remains in place.
- Added regressions for quoted SQL-looking notes, doubled-quote literals, SQL Server bracketed identifiers, multiline literals and comments, nested pseudo-assignments, and unchanged safe SQL evidence.
- Red tests first reproduced all four reported gaps against the prior implementation. `pytest.exe tests/test_evidence_redaction.py -q` → **26 passed**.
- Focused lifecycle verification: `pytest.exe tests/test_evidence_redaction.py tests/test_resumable_workflow.py tests/test_produce_release.py tests/test_artifact_lifecycle.py -q --basetemp .pytest-task5-hardening-run` → **89 passed, 1 skipped** in 320.15s. Default Windows temp fixture creation failed on the first attempt; the dedicated workspace basetemp rerun completed successfully. The existing non-failing `pyreadline3` Windows shutdown warning appeared after pytest exited successfully.
