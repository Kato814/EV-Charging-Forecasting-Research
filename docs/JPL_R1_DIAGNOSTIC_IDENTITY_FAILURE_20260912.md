# R1 diagnostic v1 identity failure — 2026-09-12

## Observed local outcome

The user-supplied status `evcf_r1_mixed_diagnostic_status_20260912T130658779671Z.json` reports:

- INCOMPLETE / IMPLEMENTATION_DRIFT, elapsed 3.452330800006166 s.
- Last substantive stage: RESOLVE_REVIEWED_CODE.
- A diagnostic code worktree was created; the existing worktree must be preserved.
- fit_count=0; model_fit_attempted=false; raw_interim_processed_accessed=false; holdout_accessed=false.
- No LOCATE_R1_CACHE/READ_VERIFY/ANALYZE stage or diagnostic result is present.
- Cache/worktree post-check fields are null, meaning not checked, not evidence of mutation.
- Launcher SHA256 matches the released v1: `784752eb1db8bfd22c77c954224f4c489faa717e0db0c61e880028dcb60273bc`.

This is not a new R1 experiment or a scientific rejection. R1 remains MIXED_JOINT_STATE_SIGNAL. The 550-fit accepted training result is unchanged. Daily/hourly findings remain unavailable.

## Verification performed by the controller

Read the frozen PR #65 code at `dd05258bf44d0a71773b6522ef6fb039831c77f1` through the GitHub connector. Reconstructed local copies were checked against the returned Git blob SHA-1 and the released SHA256:

| Artifact | Git blob SHA-1 | SHA256 |
| --- | --- | --- |
| Diagnostic module | ce4030e37cc1fb261847e0e18636ce7582c9129c | f552ce48f5a831064cff77e88ddccc26f76466697a0697860d5692bc1a1bbfc9 |
| Aggregate reference | 34bea59010a808719e84d72dc21950c51eec751d | 0c8075eb05c2405769862db72012076fc2f5a019c85a260d5b0315809520c703 |

Both pins agree with the accepted repository artifacts. The aggregate reference was also reconstructed from the already supplied R1 aggregate status. No private NPZ was available or read. The pins must not be changed merely to pass verification.

The v1 verifier already normalizes local CRLF to LF. Its generic failure code does not identify whether HEAD, local code/reference bytes or text-mode `git show` output failed. Therefore CRLF, Git transport, checkout damage and other causes are not established by this status. A specific cause must not be declared without observed fingerprints.

## Narrow next step

Release the separate `evcf_r1_identity_preflight_v1.py` after its own review/CI. It checks the existing v1 diagnostic code worktree at the original pinned source commit. It reads only the two versioned code/reference files and read-only Git outputs. It does not import the diagnostic module, fetch from the network, create/change a worktree, read a prediction cache, fit a model or relax any verifier.

It reports path-free HEAD/SHA/length/EOL/BOM/return-code evidence for local bytes, LF-normalized bytes, raw `git cat-file blob`, binary `git show`, legacy text-mode `git show`, and normalized tracked diff. Separate classifications distinguish observed local-content, Git-blob and text-output mismatches. If everything matches now, it explicitly leaves the earlier cause unresolved rather than inventing a repair.

A COMPLETE preflight means evidence collection completed. It does not mean the load-forecasting analysis completed or that a mismatch has been accepted. Upload only the generated identity-preflight status. Do not rerun the original diagnostic until this evidence is audited.

## Release and tests

The preflight template refuses execution until its single review-head assignment is pinned. The delivered file differs only at that assignment. Tests cover accepted artifact pins, real local Git LF/CRLF cases, local modification, mocked Git blob/text differences, wrong HEAD, state changes and authorization/template gates. Synthetic tests do not reproduce the user's Windows failure.

No frozen model, protocol, metric, threshold, data boundary, diagnostic mathematics, core/reference digest or historical failure record is changed. This file is the engineering-failure ledger entry; scientific evidence remains in the existing R1 outcome and experiment ledger.
