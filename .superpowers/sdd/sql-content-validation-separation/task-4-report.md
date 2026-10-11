# Task 4 — final verification report

## Status

The Task 4 mapping-hardening follow-up is implemented with its focused tests and this report, and is being committed as a scoped change. It rejects malformed fixture assertion mappings before running any LocalDB round and prevents undeclared validation-query results from contributing to SQL correctness approval. The existing N/A preservation and finding-domain contracts remain covered: non-mutating units retain four explicit LocalDB rounds without invented row results, and formal business-data limitations remain non-blocking and do not become SQL correctness prerequisites.

TDD evidence: both new mapping regressions failed against the prior implementation for the intended reasons, then passed after the minimal fixes. The focused command selected 70 tests and passed all 70 (212 deselected); the provider command passed 19 (218 deselected). The complete five-file suite completed with **435 passed, 6 skipped, 7 failed**. Four end-to-end failures were Windows CP950 decoding errors and passed when rerun with `PYTHONUTF8=1`; the other three failures are workflow-state-required cleanup errors in existing cleanup/end-to-end tests. The focused provider, validation SQL, N/A, and business-data checks pass.

The package-resource check for `v0.1.33` passed. The documented bare release-check command requires `--tag`; a full Git release gate was not run because the checkout HEAD is not the release tag. No production DB or real LocalDB was accessed. All runtime evidence here is synthetic or injected test adapter output. Formal business rows and before/after values are expressly not required for SQL correctness.

Current implementation changes are limited to `run_local_validation.py`, `validate_release_output.py`, and their focused tests. No provider recognition, transaction, schema, source, hash, or `#5005` exclusion rules were weakened. This status supersedes the prior top-level test-only handoff record; the historical provider-verification record below is retained for traceability and does not describe this follow-up's test results.

## Current run commands and evidence

All pytest runs used the installed Python 3.13 executable and an explicit task-local `--basetemp` and cache directory under `task-4-temp/`.

| Purpose | Command/result |
| --- | --- |
| RED — invalid fixture and validation mappings | `pytest tests/test_local_validation.py::test_localdb_unmapped_fixture_assertion_cannot_be_silently_ignored tests/test_release_review.py -k 'unmapped_fixture_assertion or unmapped_extra' -v` — **2 failed as expected**: malformed fixture assertion evidence reached the executor, and an undeclared query result was ignored. |
| Focused validation, preservation and business-data coverage | `pytest tests/test_local_validation.py tests/test_release_review.py -k 'localdb or validation_sql or business_data or unmapped_fixture_assertion' -v` — **70 passed, 212 deselected**. |
| Provider/opaque/rerun contract from the brief | `pytest tests/test_release_review.py -k 'provider or opaque or rerun' -v` — **19 passed, 218 deselected**. |
| Exact relevant suite from the brief | `pytest tests/test_semantic_review.py tests/test_local_validation.py tests/test_release_review.py tests/test_release_documents.py tests/test_end_to_end.py -v` — **435 passed, 6 skipped, 7 failed**. Four failures were default CP950 decoding; three failed because lifecycle cleanup now requires workflow state. |
| End-to-end encoding diagnosis | With `PYTHONUTF8=1`, the six affected end-to-end cases produced **4 passed, 2 failed**. The two remaining failures, like the cleanup failure above, are caused by calling cleanup without required workflow state. |
| Package resources | `check_package(Path('.'), 'v0.1.33')` — passed; all manifests and required resources were present and consistent. |
| Documented release-check CLI | `python scripts/check_plugin_release.py` — cannot run as written because `--tag` is required. No release tag was invented or changed. |

The full-suite failures are outside the changed validation-mapping paths: `test_success_cleanup_removes_only_temporary_material` and the two `test_collection_to_review_preserves_allowlist_and_localdb_evidence` cases call the lifecycle cleanup API without workflow state. The four decoding failures disappeared under Python UTF-8 mode. They are reported as environment/test-fixture limitations, not as passing full-suite verification.

No test connected to a formal database. N/A evidence was checked with synthetic adapters only; it records located reasons and empty `data_checks`/preserved summaries for non-mutating units. Business-data findings remain `business_data_validation`, non-blocking, and separate from `sql_content_status`.

## Historical provider verification record (prior Task 4 pass)

Read the complete Task 4 brief, Task 1–3 briefs, the design specification, implementation plan, and existing ledger. Reviewed Task 1–3 changes from `769b4ed285bd723b2c1f6aff636d08053ab1e17f` through starting HEAD `63e6f7e874daf9c033e33d96a8b25983a525596c`.

The eight implementation commits in this range are `150e4ef`, `de01b89`, `8cf5f9f`, `f7ef045`, `a4f2a2e`, `9674670`, `e145b42`, and `63e6f7e`. They change the intended classifier, review validator, LocalDB evidence normalization, report template, and associated tests only.

The checkout is on `main`; the user explicitly authorized work in this checkout. At entry there were no modified/staged tracked files. Existing untracked pytest directories, temporary directories, plan/spec files, and `pytest-of-kenny/` were retained. Task 4 logs, pytest caches, and pytest base directories are confined to `.superpowers/sdd/sql-content-validation-separation/task-4-temp/`; that directory and this report are git-ignored task artifacts. Packaging unit tests also create their own disposable directories under the repository and clean them up themselves.

## Regression and minimal fix

The initial complete relevant suite exposed `tests/test_semantic_review.py::test_current_complete_semantic_record_allows_pass`. A separate targeted reproduction failed with exit 1: it expected SQL content `通過`, but the validator returned `待確認`.

Root cause: this older integration test only writes a current semantic review record. It supplies no LocalDB/validation-query runtime evidence. Task 3 commit `63e6f7e` intentionally requires that evidence for SQL-content approval. The implementation correctly withheld approval; changing the validator to pass this old fixture would weaken the agreed safety contract.

Minimal fix: replace that obsolete test with `test_current_complete_semantic_record_requires_runtime_for_pass`, parameterized for absent/present runtime evidence. The absent case must remain `待確認` with `validation_sql_pending`, while the complete recorded four-round/query evidence case must pass. Both cases assert that the semantic review itself is complete and that report/API SQL statuses agree. Runtime evidence is installed before computing the review fingerprint.

Required provider coverage was added in `tests/test_release_review.py::test_provider_review_requires_descriptor_mapping_hash_and_rerun`: ten cases cover metadata and dynamic-DDL providers, each with a valid case and missing descriptor, mismatched source mapping, mismatched unit hash, and non-convergent rerun state. Each fixture commits its provider SQL in an isolated temporary Git repository, pins source revision/hash and artifact mapping, supplies explicit non-mutating N/A preservation plus recorded four-round/query evidence, and checks validator/report agreement. Corrupted mapping/hash cases keep the outer artifact and runtime envelope hashes current so they exercise the inner safety gates rather than unrelated artifact drift. Descriptor/mapping/hash damage remains blocking; rerun damage prevents SQL approval with pending transaction evidence. Existing unapproved `EXEC` tests remain in the focused and complete suites.

Only these tracked files were changed by Task 4:

- `tests/test_semantic_review.py`
- `tests/test_release_review.py`

No production implementation, artifact template, release version, exclusion source, or DB connection behavior was changed. The targeted fix/provider run passed 12/12; its provider additions are characterization/coverage tests, while the obsolete semantic test was reproduced failing before correcting its fixture/expectation. No production-code red/green fix is claimed.

Fix commit: **`ecf549ac9c3bd971c697c5858886d6d21d1d9aa3`** — `test: align SQL approval runtime evidence and cover provider safety`.

The user explicitly requested this commit after stopping broad verification. It contains only `tests/test_semantic_review.py` and `tests/test_release_review.py` (92 insertions, 3 deletions), with parent `63e6f7e874daf9c033e33d96a8b25983a525596c`. The staged path list was checked against those exact two files and `git diff --cached --check` passed before committing. No tests ran during this follow-up; the completed/incomplete evidence below is unchanged. This report remains a git-ignored task artifact and was not included in the commit.

## Commands and evidence

The bare `python` command resolved to the inaccessible WindowsApps alias. Successful runs used:

```powershell
$task4Python = 'C:/Users/kenny/AppData/Local/Programs/Python/Python313/python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
# Applied to final runs to preserve UTF-8 diagnostic text:
$env:PYTHONIOENCODING = 'utf-8'
```

Python reports 3.13.5 and pytest 8.4.1. All pytest commands below use `& $task4Python -m pytest` and include `-v`. Full outputs are retained in `task-4-temp/` beside this report. External command output was redirected to those logs; each test wrapper explicitly returned the pytest exit code.

| Run | Result | Evidence log |
| --- | --- | --- |
| First provider attempt with WindowsApps `python` | Process could not start | Tool output; environment limitation |
| Provider attempt using real Python, before creating temp parent | 4 passed, 5 fixture setup errors; missing task-local parent directory | Tool output; corrected setup |
| Provider baseline after parent creation | 9 passed, 217 deselected; exit 0 | `provider.log` |
| Initial complete relevant suite | Interrupted at user request; 433 collected, 321 observed passed, 1 observed failed, 111 without a completed result; execution session exit 1 | `relevant.log` |
| Targeted reproduction of obsolete semantic test | 1 failed, 93 deselected; exit 1 | `semantic-red.log` |
| Corrected semantic/provider cases | 12 passed, 319 deselected; exit 0 | `fix-focused.log` |
| Final provider-focused suite | 19 passed, 217 deselected in 117.51s; exit 0 | `provider-final.log` |
| Final complete relevant suite | Interrupted at user request; 444 collected, 46 observed passed, 0 observed failed, 398 without a completed result; execution session exit 1 | `relevant-final.log` |
| Packaging, plugin release unit tests, provider and SQL assembler tests | 124 passed; exit 0 | `packaging-provider.log` |

The interrupted counts are counts of completed per-test `PASSED`/`FAILED` lines in the retained logs, not pytest final summaries. The first run stopped after `test_report_semantic_sql_failure_keeps_independent_current_localdb_results` at 75%; the final run stopped after `test_review_fix_direct_drop_constraint_preservation_accepts_na[ALTER TABLE dbo.Customer DROP CONSTRAINT DF_Count;]` at 10%. Neither run reached the requested release-document or end-to-end files. Unfinished tests are unverified, not passes. The initial run's sole observed failure was the obsolete semantic-only approval test documented above. The separate targeted reproduction and corrected targeted run completed.

Both broad sessions (IDs `6619` and `77210`) were sent Ctrl+C through the execution tool immediately after the user's stop request; both returned exit 1. No broad run was restarted. The final provider session had already completed; its log preserves the full passing summary.

Provider baseline command:

```powershell
& $task4Python -m pytest tests/test_release_review.py -k 'provider or opaque or rerun' -v --basetemp=.superpowers/sdd/sql-content-validation-separation/task-4-temp/provider-ready -o cache_dir=.superpowers/sdd/sql-content-validation-separation/task-4-temp/cache-provider
```

Targeted failing reproduction:

```powershell
& $task4Python -m pytest tests/test_semantic_review.py -k current_complete_semantic_record -v --basetemp=.superpowers/sdd/sql-content-validation-separation/task-4-temp/semantic-red -o cache_dir=.superpowers/sdd/sql-content-validation-separation/task-4-temp/cache-red --tb=short
```

Targeted corrected fixture/provider run:

```powershell
& $task4Python -m pytest tests/test_release_review.py tests/test_semantic_review.py -k 'provider_review_requires or current_complete_semantic_record' -v --basetemp=.superpowers/sdd/sql-content-validation-separation/task-4-temp/fix-focused -o cache_dir=.superpowers/sdd/sql-content-validation-separation/task-4-temp/cache-fix --tb=short
```

Final provider command:

```powershell
& $task4Python -m pytest tests/test_release_review.py -k 'provider or opaque or rerun' -v --basetemp=.superpowers/sdd/sql-content-validation-separation/task-4-temp/provider-final -o cache_dir=.superpowers/sdd/sql-content-validation-separation/task-4-temp/cache-provider-final --tb=short
```

Initial and final complete relevant suite commands:

```powershell
& $task4Python -m pytest tests/test_semantic_review.py tests/test_local_validation.py tests/test_release_review.py tests/test_release_documents.py tests/test_end_to_end.py -v --basetemp=.superpowers/sdd/sql-content-validation-separation/task-4-temp/relevant -o cache_dir=.superpowers/sdd/sql-content-validation-separation/task-4-temp/cache-relevant
& $task4Python -m pytest tests/test_semantic_review.py tests/test_local_validation.py tests/test_release_review.py tests/test_release_documents.py tests/test_end_to_end.py -v --basetemp=.superpowers/sdd/sql-content-validation-separation/task-4-temp/relevant-final -o cache_dir=.superpowers/sdd/sql-content-validation-separation/task-4-temp/cache-relevant-final --tb=short
```

Supplemental packaging/provider checks:

```powershell
& $task4Python -m pytest tests/test_packaging.py tests/test_release.py tests/test_metadata_provider.py tests/test_sql_assembler.py -v --basetemp=.superpowers/sdd/sql-content-validation-separation/task-4-temp/packaging-provider -o cache_dir=.superpowers/sdd/sql-content-validation-separation/task-4-temp/cache-packaging
```

## Packaging/plugin release gate

The brief's literal `python scripts/check_plugin_release.py` first encountered the WindowsApps alias problem. Using the working interpreter without arguments reached argparse and returned exit 1 because `--tag` is required. This is a command/spec mismatch, not a code regression; the release checker was left unchanged.

```powershell
& $task4Python scripts/check_plugin_release.py
& $task4Python scripts/check_plugin_release.py --tag v0.1.32
```

The second command successfully passed real checkout package validation but returned exit 1 with `Tag commit differs from checkout HEAD`. Existing tag `v0.1.32` resolves to `464a65bd63937f42301ca3198a008632788cfc71`; verification started at `63e6f7e874daf9c033e33d96a8b25983a525596c`. The script checks origin/main membership before HEAD equality, so the tag membership gate passed. No tag, remote ref, release, version or publication was modified to bypass the failure.

The real checkout's `check_package(root, 'v0.1.32')` was also invoked separately, with exit 0 and `package_validated: true`. The invocation loaded `scripts/check_plugin_release.py` by `importlib.util`, read the version from `plugin.json`, and called the existing `check_package` directly. This verifies consistent versions across the three manifests and every required nonempty resource, without pretending the Git release gate passed. The 124-test supplemental suite additionally verifies plugin skill references, marketplace paths, resource packaging, strict tags, release workflow permissions/order, and tag/HEAD rejection using synthetic temporary Git repositories.

Exact successful checkout package invocation:

```powershell
& $task4Python -c "import importlib.util,json,pathlib; root=pathlib.Path.cwd(); spec=importlib.util.spec_from_file_location('task4_release_check',root/'scripts/check_plugin_release.py'); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); tag='v'+json.loads((root/'plugin.json').read_text(encoding='utf-8'))['version']; module.check_package(root,tag); print(json.dumps({'tag':tag,'package_validated':True,'git_release_gate':'checked separately'}))"
```

## Task 1–3 safety contract inspection

| Contract | Evidence and assessment |
| --- | --- |
| SQL defects stay strict; business data stays non-blocking | Reviewed `_finding`, `_summary`, `_units`, semantic review and report projection. SQL allowlisted codes cannot be relabeled into the business domain; missing formal rows do not become semantic pending. Failed trusted semantic conclusions remain blocking despite malformed sibling checks. Relevant suite exercises these cases. |
| Data impact is authoritative and conservative | Reviewed `classify_data_impact`: actual SQL/provider body is required; labels, filenames and phases do not prove N/A. UPDATE/DELETE/MERGE/TRUNCATE, destructive changes and default backfills retain mutation/unknown handling. Unknown classification cannot acquire the N/A exemption. |
| Non-mutating preservation is explicit and authenticated | Reviewed `_non_mutating_preservation`, `_preservation`, runner manifest/hash checks, and `_deployment`. All included units must be proven non-mutating; N/A reason/source identity and valid manifest/hash evidence remain required. Mutation and mixed-release fixtures retain actual preservation/assertion checks. |
| Four-round invariants | Unique sessions; fresh validate/commit/failure databases; commit/rerun database reuse; committed-state convergence; distinct checks; current baseline/fixture/manifest/artifact hashes; provider/tool versions; injected failure error/rollback/stop evidence remain enforced. Existing negative cases and new provider rerun cases exercise the gates. |
| Provider and opaque execution | Approved metadata/dynamic-DDL bodies with complete evidence pass. Missing descriptor, mapping/hash defects and missing convergence cannot produce SQL-content approval. Unapproved `EXEC` remains `opaque_execution`. Provider recognition and assembler implementation are unchanged in Task 1–4. |
| Validation SQL and status agreement | Reviewed `_validation_query_status`, `_result_rounds`, `_runtime_findings`, and `_report_runtime`. Results must match source identity, query hash, expected/actual, passed flag and authenticated runtime envelopes. Missing evidence remains pending; trustworthy negative query/assertion results block. Validator/API/CLI/report regression cases cover agreement. |
| Schema/source safety | No source analysis, EF detection or assembly implementation was changed. Schema/source conflict codes remain SQL findings and report sections cannot hide them with the business domain. No live formal schema comparison was performed. |
| Formal DB isolation | The runner still rejects production server strings before invoking any executor. It accepts an injected disposable adapter and opens no DB itself. The `_LOCALDB` guard, CLI adapter policy and connection restrictions are unchanged. Tests use recorded/injected adapters or assert rejection/not-run. |
| #5005 exclusion | Lifecycle/exclusion source logic is unchanged. Reviewed unchanged `_exclusion_provenance` plus included-unit/object/dependency checks and guide projection. Existing release fixture excludes its core unit; end-to-end fixtures assert the deferred excluded object never appears in execution SQL. |
| Operator/report confidentiality and bytes | Six report sections and domain-separated findings remain in lifecycle output. Existing tests assert secrets, raw SQL/data values and internal lifecycle/adapter details are absent from operator output. Task 4 changes tests only; it changes no delivered SQL bytes or templates. |

An explicit diff of Task 1–3 against the starting baseline for `analyze_release_units.py`, `assemble_deployment_sql.py`, `metadata_provider.py`, `lifecycle_store.py`, `collect_release_evidence.py`, and `detect_entity_framework.py` was empty. The table distinguishes inspected implementation/test assertions from executed evidence: the complete suite did not finish, so unexecuted cases (particularly release-document and end-to-end integration cases) have no fresh passing result in Task 4. No production-code safety regression was found in the inspected scope and completed focused checks; this is not a full regression-suite approval.

## Final diff/status and limitations

Final bounded checks after stopping the broad tests:

```powershell
git diff --check
git diff --cached --check
git diff 150e4ef^ HEAD --check
git status --short
git diff --stat
git rev-parse HEAD
```

At the stop-request handoff, all three diff checks returned exit 0, independently captured in the final check. `git status --short` showed only the two intended tracked test modifications plus the same pre-existing untracked paths observed at entry. No files were staged. Diff stat: `tests/test_release_review.py` adds 82 lines; `tests/test_semantic_review.py` changes 13 lines; total 92 insertions and 3 deletions. The report/logs are retained under the ignored task workspace.

During the authorized commit follow-up, the ordinary Git add was initially denied when creating `.git/index.lock`. Retrying the exact scoped add/commit with sandbox escalation succeeded. The resulting commit's file list confirms only the two requested test files. No tag, publication, unrelated untracked-file change or cleanup occurred. Full-suite verification remains incomplete despite committing these required tests.

Limitations:

- The complete relevant suite was interrupted twice and has no final pass result. Completed focused/supplemental checks validate code/evidence contracts with synthetic sources and recorded adapters. They do not establish actual SQL Server/LocalDB execution, formal DB data results, or production deployment success.
- The package/resource checks pass, but the real Git release gate is deliberately not green: the existing release tag does not point at the development HEAD.
- Python's WindowsApps alias is unusable; an explicit installed Python path was required.
- The first explicit pytest base directory lacked its parent; creating the task-local parent resolved fixture setup. Final runs use fresh explicit base directories and task-local caches.
- Passing pytest runs emit the pre-existing ignored `pyreadline3` console-destructor `OSError: [WinError -1073741816] ... 0xc0000008` after the summary. It did not change the successful process exit codes. This interpreter cleanup issue was not modified.
- A read-only attempt to independently enumerate Python processes with `Get-CimInstance Win32_Process` was denied (`用戶端無法存取 CIM 資源`). Process stopping is evidenced by the execution tool's two exit-1 termination results; no independent OS process inventory is claimed. The CIM denial made that combined diagnostic shell exit 1; a subsequent bounded diff-check command independently confirmed all three Git checks returned 0.
- Review was performed by the verification implementer only, per the user's explicit prohibition on reviewers/subagents. No unrelated files were edited or cleaned.
