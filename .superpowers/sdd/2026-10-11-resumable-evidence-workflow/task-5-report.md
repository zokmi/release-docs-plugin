# Task 5 review remediation — shared secret redaction

## Findings addressed

- Unknown `credential material: opaque-value` now fails closed with the non-sensitive `secret_redaction_required` error. The raw input is never included in the error.
- Text `user_id=...` assignments are masked. Ordinary SQL identifiers, including `user_id` column references and `dbo.ReleaseUser`, remain unchanged.
- `produce_release(..., secrets=())` and `resume_release(..., secrets=())` now accept known secret values with backward-compatible defaults. Values flow to lifecycle evidence, production results, workflow checkpoints, and failure checkpoints; the built-in resume production request combines its own secrets with the resume-level values.

Exception persistence remains limited to the existing non-sensitive stage summary. Business-data validation classification and production semantics are unchanged.

## Verification

- TDD regressions for unrecognized credential material, text `user_id` masking, and known unlabelled secrets through both public APIs were observed failing before implementation and passing afterward.
- `pytest.exe tests/test_evidence_redaction.py tests/test_local_validation.py tests/test_artifact_lifecycle.py tests/test_resumable_workflow.py -q --basetemp .pytest-task5-review-focused` → **112 passed, 2 skipped**.
- `pytest.exe tests/test_evidence_redaction.py tests/test_resumable_workflow.py tests/test_produce_release.py tests/test_release_review.py -q --basetemp .pytest-task5-review-rerun` → **281 passed, 2 skipped**.
- An initial combined run surfaced two backward-compatibility failures because empty `secrets` was added to existing production request kwargs. The forwarding now omits that argument when absent and empty; both affected workflow cases passed in the rerun above.
- The Python test process emitted the existing `pyreadline3` `Console.__del__` Windows `WinError 0xc0000008` during teardown after successful runs; pytest exit status and test results were unaffected.

Base: `d6b6c23`.
