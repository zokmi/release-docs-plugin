# Task 3 report: resumable production coordination

## Status

`resume_release(repo, run_root, *, current_inputs, adapters=None)` now supports a built-in production path through the existing `produce_release` API. Put its keyword arguments in `current_inputs['source_collected']['production_request']`; the requested repository and owned run root must match the resume call. The existing production pipeline continues to perform its source, baseline, LocalDB, and output safety checks. Its durable source metadata, exclusion/fixture manifest, and LocalDB receipt checkpoint the first three workflow stages. Semantic review, report finalization, and delivery finalization remain adapter stages.

`current_inputs` must be a mapping with exactly every name in `STAGES`, and each value must be a mapping. An adapter cannot mark a stage completed without at least one durable `output_files` entry. To return a `ProductionResult`, the built-in pipeline or at least one adapter must provide a complete result with inventory, artifact, and fingerprint. Resume stores those fields in immutable `production_result.json`, includes it in the output hash inventory, and reconstructs the public result types on later calls. Resumed results remain `delivery_eligible=False` until a separate authorized finalization flow establishes eligibility.

## Changed files

- `skills/release-docs/scripts/resume_release.py`
- `tests/test_resumable_workflow.py`
- `.superpowers/sdd/2026-10-11-resumable-evidence-workflow/task-3-report.md`

`produce_release.py` and `tests/test_release_review.py` were not changed. The built-in path delegates to the existing production function.

## Verification

- RED: `pytest.exe tests/test_resumable_workflow.py -q --basetemp .pytest-task3-review-red` — 5 failed, 6 passed. The new assertions exposed missing/unknown stage-key acceptance, empty-output completion, the absent built-in pipeline path, and missing durable result reconstruction.
- Focused GREEN: `pytest.exe tests/test_resumable_workflow.py -q -k "exactly or durable or existing_production or reconstructs" --basetemp .pytest-task3-review-focus` — 5 passed, 6 deselected in 26.84s.
- Required Task 3 suite: `pytest.exe tests/test_resumable_workflow.py tests/test_release_review.py -q --basetemp .pytest-task3-review-final` — 245 passed, 2 skipped in 692.68s.
- Existing production-pipeline integration: `pytest.exe tests/test_resumable_workflow.py::test_resume_runs_existing_production_pipeline_and_reconstructs_its_result -q --basetemp .pytest-task3-pipeline-integration` — 1 passed in 7.84s. This also verified a second resume reconstructs inventory, artifact, and fingerprint, with review still pending.
- `git diff --check` — passed (exit 0; Git printed only its existing LF/CRLF conversion warnings).

## Bounded concern

The existing monolithic pipeline is now reachable and safely checkpoints source through LocalDB. The remaining semantic-review and report/delivery finalization stages still require stage adapters; Task 3 does not decompose those existing flows or claim that a partial resumed result has passed review or is eligible for delivery.

## Commit

Commit: `fix: complete resumable production coordination`.
