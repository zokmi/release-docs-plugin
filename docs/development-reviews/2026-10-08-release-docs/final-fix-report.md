# Final fix report — cross-stage scope and safe writes

Date: 2026-10-08 / Asia/Taipei. Base: d4c7a89. One scoped fix wave; no subagents, installs, publishing or pushes.

## Changes

- Added review_fingerprint.py --commit-scope PATH for a nonempty ordered JSON list of exact commit/parent pairs. Resolves all revisions to SHA, requires an actual direct parent, requires null for roots, and requires an explicit chosen parent for merges. Mutually exclusive with every range selector; existing range result schema and CLI remain compatible. List results contain commit_scope and per-pair source-tree/status/content identities, with no fabricated base/target/diff_mode. A+C is not widened into an A-through-C range.
- Added read-only validate_output_paths.py --repo PATH --documents PATH. Checks Git/docs containment and each exact 01–05 destination, rejects symlinks (including internal aliases), nonregular destinations and st_nlink > 1 hardlinks. Allows safe not-yet-created directories without creating them. Fingerprint reuses the same guard.
- Updated both skills, all four scope headers, the fifth report interface/identity comparison and README. First creation and every immediate update/fallback, including 04 status and 05, require preflight after choosing the final signed-record-preserving version directory. Refusal stops writes and is reported in conversation only. Final save compares commit_scope order/pairs as well as committed/working_tree source identities against the actually reviewed snapshot.
- Added only tests/test_final_fix.py and new evals/final-fix evidence. Prior evals/actual, task2 and archived fingerprints were not adjusted. Collector remains range-only; explicit pairs require per-pair evidence gathering.

## RED evidence

Bundled Python: C:/Users/kenny/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe. All commands used -X utf8 in the independent repository.

Initial command:

```text
python -X utf8 -m unittest discover -s tests -p test_final_fix.py -v
```

Observed scope failures before scope implementation: test_ordered_noncontiguous_pairs_exclude_intermediate_diff, test_merge_explicit_parent_identity and test_root_and_direct_parent_validation returned CLI exit 2, requiring --base/--target/--diff-mode. Initial inherited fixture tests redundantly expanded this run to 31; final focused test structure removes that duplication.

Process limitation: that first long RED run was still completing when implementation was written; its later output-path cases saw the new guard, so they are not claimed as preimplementation RED. A separate baseline replay against the unchanged HEAD (d4c7a89) script then selected the above three scope tests plus test_regular_and_not_yet_created_docs_are_permitted_read_only. The replay copied `git show HEAD:skills/release-docs/scripts/review_fingerprint.py` into a fresh temporary directory, assigned tests.SCRIPT/GUARD to that baseline directory, and ran a unittest.TestSuite. It observed four expected failures in 3.978s: three unsupported scope CLI failures and missing preflight CLI (safe ordinary path expected exit 0, actual exit 2). This confirms the baseline interface gap, but is not an independent agent pressure evaluation or a claim of strict temporal RED for every guard case.

## GREEN / verification

Final focused command:

```text
python -X utf8 -m unittest discover -s tests -p test_final_fix.py -v
```

10 tests in 26.350s: OK (skipped=1). Real Git covers noncontiguous selected paths and exact selected diff content hashes, order changes, chosen merge-parent identity, invalid parent, root/null, revision aliases, mutually exclusive CLI; read-only guard covers internal/external 01–05 symlinks, fifth report aliases, ordinary/missing directories, outside directory symlink and nonregular files. Target bytes remain intact on refusal.

One final complete suite: `python -X utf8 -m unittest discover -s tests -v`, exit 0, 35 tests in 61.679s, OK (skipped=1). Raw complete output captured in final-full-suite.txt. No further production changes after this full-suite run started.

`git diff --check`: exit 0; Git emitted only the repository's CRLF checkout notice for the changed Python file.

skill-creator quick_validate.py was invoked separately for both skills; both failed before validation with ModuleNotFoundError: No module named yaml. No dependencies installed. Project PackagingTests checks required frontmatter, names and every local skill reference; its actual status is part of the complete-suite log. Missing PyYAML is disclosed rather than presented as validator success.

## Actual scoped skill/preflight outputs

New real Git fixture at .superpowers/final-fix-run/source-repo; raw source exports and exact SHA topology in evals/final-fix/sources and source-identities.json. The implementer read the updated skills, full selected revision sources and all four products, generated literal four documents, then performed the required separate reread/review. This is an implementation-side actual exercise, not an independent reviewer. See evals/final-fix/README.md for commands and boundaries.

- A parent baseline; C parent B. Only 01_a.sql and 03_c.sql are selected changed_paths; independent 02_b.sql is excluded from execution. All four headers and fifth snapshot preserve the same exact ordered commit_scope.
- Initial internal/external 01 symlinks, fifth fallback alias, and existing-four-documents report-update alias: guard exit 2; source hashes and existing documents unchanged; no draft/status/fallback write to the blocked destinations. Evidence in preflight-actual.json.
- review-start.json equals reviewed.json. Only already-reviewed 04 status changed after successful guard. Final commit_scope/committed/working_tree equal the reviewed identities; guard precedes 05 write, and recomputation after 05 equals final-snapshot.json.
- Final fixture fingerprint: 06cb8cedce9adfc9030abe0bbb743286d138196fa4e5bb7fca08de20a19f479e. Five outputs archived under evals/final-fix/outputs. Review correctly stays 待確認 because formal environment, tested backup/recovery and UAT evidence are missing. No SQL executed.

## Concerns / scope boundaries

- Windows sandbox os.link fails with WinError 5 (access denied) in the real fixture, so test_hardlinks_refused is explicitly skipped. Production st_nlink branch exists, but this environment did not prove hardlink filesystem behavior. No escalation or environment changes attempted.
- Guard is a preflight; skills require immediate recheck before every write. It is not an atomic filesystem lock against a separate actor changing paths between validation and writing.
- Prior Minor PK prose remains archived honest evidence. Future expected values must remain scenario-specific; the new fixture records PostgreSQL primary-key non-NULL and seed id=7 from its own SQL, not universal checks.
- No installing, publishing, pushing, SQL execution or historical evidence rewriting. Parent's scoped re-review remains separate from this fix implementation.
