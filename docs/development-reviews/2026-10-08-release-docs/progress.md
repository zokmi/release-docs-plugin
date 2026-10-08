# SDD ledger — plan: docs/superpowers/plans/2026-10-08-release-docs-plugin.md
Base: 4d32adb
Tasks: 1 pending; 2 pending; 3 pending; 4 pending.

| Tasks | Producer / consumer | Preflight finding |
| --- | --- | --- |
| 1 | JSON Git metadata / CLI tests | consistent |
| 2 | four templates / generation skill | consistent |
| 3 | fingerprint / review skill | review must avoid self-invalidating fingerprint |
| 4 | packaging / README / evals | add requested release mechanism |
| 1 + 2 | collector metadata / source reading | recorded revision source; no plaintext output |
| 1 + 3 | base/target/diff-mode / fingerprint | same inputs |
| 1 + 4 | manifests / marketplaces | local source must resolve plugin root |
| 2 + 3 | four docs / fifth report | final status first, fingerprint next, report last |
| 2 + 4 | eval scenarios / results | same case IDs |
| 3 + 4 | fingerprint / review evals | unchanged documents valid, changed docs stale |

Ruling: Develop in new independent zokmi/release-docs-plugin clone on codex/release-docs-plugin rather than nested package or extra worktree — user's new direction explicitly requires independent project before development; clone provides isolation — wrong placement costs moving the checkout.
Ruling: Create repository private initially — visibility was unspecified, avoid publishing before readiness — public installation requires later visibility change or authorized private access.
Ruling: Adapt Bash SDD artifact helpers to PowerShell equivalents — current native shell is PowerShell; retain identical scoped briefs, reports and diff packages — mismatch could impair progress recovery.
Ruling: Release tags use vMAJOR.MINOR.PATCH consistent with existing plugin — user requested same mechanism — alternative tag scheme would require changing validator and workflow.
Task 1: implemented b3fab85; review pending; tests 7/7.
Task 1: complete (commits 16ef39b..b3fab85, review approved).
Task 1: minor (deferred): tests/test_evidence.py non-repository fixture sits inside checkout; task4 must isolate Git discovery and assert repo-specific diagnostic.
Task 1: remote ownership/existence verified by controller gh create zokmi/release-docs-plugin.
Task 2: started base b3fab85.
Ruling: Fingerprint hashes four outputs separately and excludes only exact five output files from source status/content evidence — otherwise report creation invalidates its own source fingerprint; excluding whole docs could omit real SQL — wrong exclusions could miss a changed deployment source.
Task 2: implemented ac0486a and 85eb052; review pending; 7 tests and focused fixture verified.
Task 2: review Important — full scenario skill execution absent; manual fixture not workflow proof.
Ruling: Move complete agent skill scenario execution to Task4 integration gate — Task3 review/fingerprint dependency does not exist yet and full workflow cannot be executed now; reviewer explicitly permits transfer — if omitted, plugin behavior remains unverified and final cannot claim passed.
Task 2: minor (deferred): fixture structural query must verify nvarchar length and PK column Id; Task4 owns fix.
Task 2: complete (commits b3fab85..85eb052; artifact compliance approved, integration scenario evidence explicitly carried to Task4).
Task 3: started base 85eb052.
Task 3: implemented 2210506/1d424e7; 14 tests passed; review pending.
Task 3: fix round 1/5 dispatched — Important report symlink alias self-invalidates; Minor final source identity comparison needed; base 1d424e7.
Task 3: fix round 1/5 (2 addressed, 0 open; commits 1d424e7..ab7e65f).
Task 3: complete (commits 85eb052..ab7e65f, scoped re-review clean; semantic eval requirement carried to Task4).
Task 4: started base ab7e65f.
Task 4: implemented marketplace/README/CI/release gates; full suite 21/21 green, affected release tests4 green; 15 actual outcomes recorded (14 five docs plus1 stop), explicit untested branches in evals/results.md; parent review pending.
Task 4: implemented ac976af/dc62f33/a9d85a9; 21 tests passed, no skip; 15 agent skill outcomes recorded; review pending.
Task 4: fix round 1/5 dispatched — Important preparation overwrites committed archive inputs while retaining old outcomes; base a9d85a9.
Task 4: minor (deferred): structural output PK verification notes cross-reference unrelated fixtures (required-review 01 line36 and analogous outputs); final reviewer to triage. Archived review state correctly remains mostly 待確認.
Task4 fix round1: d4c7a89 explicit fresh run/archive destinations and preflight refusal; targeted4 tests RED4→GREEN4, actual archive unchanged, Important addressed; Minor cross-scenario PK boilerplate deferred.
Task 4: fix round 1/5 (1 addressed, 0 Important open; commits a9d85a9..d4c7a89).
Task 4: complete (commits ab7e65f..d4c7a89; scoped re-review clean; PK note Minor deferred).
Final review: started base 4d32adb head d4c7a89.
Controller final verification: bundled Python -X utf8 -m unittest discover -s tests -v; 25 tests in 38.358s, OK, no skips, exit0 on d4c7a89.
Final review: Important commit-list scope unsupported by mandatory review/fingerprint; Important output-file alias rejection occurs after generation writes. Minor unrelated PK fixture prose remains archival noise.
Final fix wave: dispatched both Important findings; base d4c7a89.
Final fix wave: implemented ef40415; 35 tests OK, hardlink case OS skip WinError5; old archives unchanged; scoped re-review pending.
Final scoped re-review: PASS d4c7a89..ef40415; both Important addressed; no new Critical/Important. Archived cross-scenario PK prose remains Minor, not deployment blocker; archive preserved.
Controller final verification: bundled Python -X utf8 -m unittest discover -s tests -v; 35 tests in 66.571s, OK skipped=1 (34 passed; hardlink WinError5). No production changes after run.
All four tasks complete. Integration awaiting user choice; remote private project exists, no code/tag push or Release publication.
