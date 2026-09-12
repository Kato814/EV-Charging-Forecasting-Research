# R1 diagnostic identity evidence and v1.1 repair — 2026-09-12

This is an engineering follow-up to `JPL_R1_DIAGNOSTIC_IDENTITY_FAILURE_20260912.md`, not a new R1 experiment. The earlier failed status and identity collector remain unchanged.

## 1. Observed evidence

Source: user-supplied `evcf_r1_identity_preflight_status_20260912T133808491942Z.json`.
Source SHA256: `ae2d6e5d7e5e689028f2d99177b7bdd79bc6d9f265645cdb4924c551e092c2f2`.
The private status is not committed; only the following path-free evidence is recorded.

The identity preflight completed in 0.41079270001500845 s. HEAD equals `dd05258bf44d0a71773b6522ef6fb039831c77f1`; checked tracked state was unchanged. No prediction cache, raw/interim/processed, holdout, network or model fit was accessed.

| Check | Diagnostic module | Aggregate reference |
| --- | ---: | ---: |
| Working-tree length (bytes) | 18029 | 7821 |
| Working-tree SHA256 matches pin | true | true |
| Git cat-file blob return code | 0 | 0 |
| Git blob SHA256 matches pin | true | true |
| Normalized tracked diff return code | 0 | 0 |
| Binary git show return code | 128 | 0 |
| Legacy text git show return code | 128 | 0 |
| Both git show output lengths | 0 | 7821 |
| CRLF count / UTF-8 BOM | 0 / false | 0 / false |

The collector's broad label `LEGACY_GIT_SHOW_TEXT_MISMATCH` is not a precise causal diagnosis: **both binary and text git show failed for the module**. This is an observed git-show command failure, not established text-decoding corruption. HEAD drift, current local-byte drift and current pinned-blob mismatch are not supported by this evidence. The underlying reason for return code 128 is still unknown because stderr was not published. No claim is made about antivirus, path length, Git filters or Windows configuration.

## 2. Bounded repair

Add a separate versioned `scripts/evcf_r1_mixed_diagnostic_launcher_v1_1_template.py`. Do not change the original launcher/template, diagnostic core, aggregate reference, model, protocol or accepted result.

The new verifier requires the same exact source HEAD and local LF-normalized SHA256, then reads `git cat-file blob <fixed-commit>:<fixed-path>` with binary subprocess capture and requires the same pinned SHA256. A nonzero return code or a different local/blob digest is rejected with a distinct static reason. Before/after identity evidence is included in the new status. No git-show success or text decoding is used for object identity.

Official Git documentation describes `git cat-file <type> <object>` as returning raw uncompressed object contents: https://git-scm.com/docs/git-cat-file . This motivates direct object-byte verification; it does not identify the user's underlying git-show fault.

All fixed identities remain:

- diagnostic source commit: `dd05258bf44d0a71773b6522ef6fb039831c77f1` (PR #65);
- module SHA256: `f552ce48f5a831064cff77e88ddccc26f76466697a0697860d5692bc1a1bbfc9`;
- aggregate reference SHA256: `0c8075eb05c2405769862db72012076fc2f5a019c85a260d5b0315809520c703`;
- R1 cache manifest SHA256: `56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f`;
- scientific decision: `MIXED_JOINT_STATE_SIGNAL`.

The new launcher's reviewed head and PR number are separate release metadata. They are not substitutes for the original diagnostic source commit. Only those two assignment tokens are replaced after this repair PR passes review/CI and is merged.

## 3. Runtime boundary

Reuse only the existing registered `-jpl-r1-mixed-diagnostic-code-v1` worktree already checked by the user. Missing, wrong-HEAD or tracked-dirty code worktrees are rejected. No fetch, checkout, worktree creation, reset, stash, cleanup or private-cache mutation is performed. Existing original-workspace tracked changes are preserved.

After identity succeeds, run the **unchanged PR #65 prediction-cache-only diagnostic**: all twenty development month-horizon files, accepted metric reconstruction, complete daily/hourly paired losses and final input hashes. Do not read raw/interim/processed, P1 or other baseline cache directories. No model fitting, feature selection, clipping, calibration, significance testing, new-model decision or final-holdout access.

Progress remains flushed on stderr, with real cell/file counts, stage timings and a running heartbeat. Final aggregate status remains separate. DEVICE=CPU / GPU_USED=false / FIT_COUNT=0; no backend or environment is changed to use the RTX 5080.

## 4. Validation and release gate

Fifteen focused tests passed in the controller's local synthetic Git fixtures. Coverage includes LF/CRLF byte preservation, a simulated git-show 128 failure while valid cat-file data passes, failed/empty/altered Git objects rejected, local core/reference alteration rejected, wrong HEAD rejected before file reads, existing-worktree reuse, missing/dirty worktree rejection, authorization/release gates and live progress separation. The simulated git-show failure is **not** a reproduction or proof of its Windows-level cause.

Full repository pytest/compileall/Ruff and PR review are required before release. Final launcher SHA and reviewed/merge identities must be recorded in Issue #29. The user still needs one local v1.1 diagnostic run; do not claim real daily/hourly analysis has completed before its status is received.

## 5. Current action

After the repair release gates pass, execute `evcf_r1_mixed_diagnostic_launcher_v1_1.py --authorize-r1-diagnostic` in the existing `evcf-gate1-pilot` environment, with the existing repository path. No manual git pull or worktree changes are needed. Upload only the newest `evcf_r1_mixed_diagnostic_status_*.json`; preserve all prior launcher versions, failed statuses, identity evidence and private caches. On INCOMPLETE, audit its specific reason before any retry.
