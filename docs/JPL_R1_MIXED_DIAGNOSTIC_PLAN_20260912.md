# R1 MIXED prediction-only diagnostic — 2026-09-12

## Status and authority

This is the failure-source analysis allowed by the frozen R1 MIXED rule and requested by the user after the R1 outcome audit. It is not another representation/model experiment. S1 remains MIXED; P1 remains STOP and closed; R1 remains `MIXED_JOINT_STATE_SIGNAL`. No diagnostic finding automatically changes that decision or authorizes a learned set model.

The implementation PR must pass full repository CI and be merged before release of a pinned local launcher. No real private-cache diagnostic has been run in the assistant container. Local tests use synthetic arrays only.

## Exact input scope

Only the accepted R1 private cache is opened for numerical analysis:

- source R1 reviewed head: `e01607078431141a1fccdd6a9db5f75ae561bfda`;
- manifest SHA256: `56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f`;
- twenty `2019-01/04/07/10` × `15/30/60/120/240` NPZ files;
- existing truth, issue/day indexes and M2/M3/Equal/S1/Control/Joint predictions already stored by R1.

The launcher discovers this cache only under the existing external R1-run parent, one level deep, by exact manifest identity. It does not search raw/interim/processed, inspect feature support, access the P1/baseline/S1 cache directories, or load final holdout 2019-03/06/09/12. The only permitted network operation is fetching the reviewed code commit through Git; there is no data download. Historic worktrees, failed statuses and caches are preserved.

`code/configs/acn_jpl_r1_diagnostic_reference.json` is an aggregate-only extraction from the accepted uploaded R1 status, not the private status itself. Its source-status digest is `7e37ca253452ac246445aea7fcd2d30179c3648168c911c28062ac54df417ec2`. The reference contains all twenty cell counts/MAE and overall MAE/RMSE/WAPE/negative counts for all six models. It contains no row predictions, session identifiers or local absolute paths.

## Questions, not predetermined findings

1. Does July's Joint-Control degradation persist over many days, or concentrate in a small number of days/hours?
2. Where does October's remaining Joint-Equal deficit arise despite a pooled benefit versus Control?
3. Are the small 60-min gains and the longer-horizon deficits distributed consistently across days and months?
4. What do the complete hourly tables say about the previously discussed 07:00 and 09:00 periods, without selecting those cells as new decision criteria?

All four development months and all five horizons are retained. No result-selected subset, new model, composite predictor or gate is constructed.

## Fixed calculations

For comparator B in {R1-Control, Equal} define, for each existing forecast record:

`delta = abs(Joint - truth) - abs(B - truth)`.

Positive means Joint is worse. For each month-horizon cell, return the full observed-local-day table and all 24 local-hour cells. Empty hourly cells have n=0 and null errors, never zero error. The local timezone is America/Los_Angeles; cached day starts must equal the local midnight associated with their issue time.

Report counts, MAE, summed/mean paired loss delta, row win/tie/loss counts, gross worsening and gross improvement. Their difference must equal net delta. Both daily and hourly sums/counts must reconcile to the full month-horizon cell.

Daily summaries report win/tie/loss days, equally weighted daily mean/median/p10/p90 deltas, and the fraction of positive NET daily excess contributed by its largest one/three days. These concentration shares do not delete days, recompute trimmed MAE, or modify accepted results. Daily summaries and record-weighted pooled metrics use different, explicitly named weighting schemes.

For every horizon and each of the 24 hours, report four-month sign consistency and pooled paired delta. Report the number of represented months so absent cells cannot appear as wins.

## Integrity and interpretation limits

Before analysis, verify the manifest, file-name allowlist, all NPZ hashes, schema, finite numeric values, exact row counts, increasing 15-minute issue indexes, legal local month/day, and equality of issue indexes across horizons. Check Equal against the cached M2/M3 average. Load the exact in-memory bytes just hashed, with pickle disabled.

Reconstruct all twenty cell counts/MAE and all overall metrics against the accepted aggregate reference. Tolerances are fixed numerical checks (rtol=1e-10, atol=1e-8 for metric reconstruction), not prediction corrections. Rehash the complete cache after analysis.

There are 25,375 origin-horizon forecast records, not 25,375 independent samples. No p-values, confidence intervals, causal mechanism conclusions or automatic PASS/STOP upgrades are produced. A cache-only diagnostic cannot identify influential input features or establish feature-support drift. Such claims require separately authorized evidence.

## Execution and release

The core imports NumPy and standard-library modules only, not training/model modules. Model fits in this diagnostic are exactly zero. CPU is the deliberately selected device for these array statistics, not an undisclosed GPU fallback. Future approved GPU-capable models must explicitly report device choice; this diagnostic does not change any model to use the RTX 5080.

The committed launcher template has three unreleased tokens: reviewed head, PR number and core SHA256. It refuses execution before substitution. The released launcher differs only in those three literal values, verified at release. It checks code bytes and reference identity in a separate detached code worktree. It does not switch an existing worktree or run cleanup.

Progress goes directly to stderr with flush; final aggregate JSON is written separately outside worktrees/private caches. Stages include environment/worktree validation, reviewed-code resolution, cache location, file verification, accepted-result reconstruction, month-horizon analysis and final integrity checks. Completed counts are genuine completed files/cells. A 30-second heartbeat reports only that a step is still running, not completed work. Stage durations and total elapsed time are measured; no unmeasured runtime estimate is promised.

The local command uses the existing `evcf-gate1-pilot` environment (Python 3.11.16, NumPy 2.4.6). No environment upgrade is performed. Run once; upload only `evcf_r1_mixed_diagnostic_status_*.json`, not NPZ. An INCOMPLETE status requires audit before another invocation.

## Audit ledger for this step

PR #64 passed full CI and was merged as `a1c97ce425d4d2fb84c4582fb6a0d9eb2588878b`, formally recording R1 MIXED. This diagnostic is an additive implementation under that result; frozen R1 protocol/model/output files remain unchanged. Code-review and release identities are recorded on the diagnostic PR and Issue #29. Actual daily/hourly conclusions remain pending the user's local diagnostic status.
