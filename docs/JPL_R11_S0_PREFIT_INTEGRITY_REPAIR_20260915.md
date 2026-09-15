# JPL/ACN R11-S0 pre-fit integrity repair note

Date: 2026-09-15  
Status: **pre-fit implementation repair only; scientific protocol unchanged**.

## 1. Trigger

The first formal R11-S0 launcher attempt returned:

```text
status       INCOMPLETE
reason_code  IMPLEMENTATION_DRIFT
fit_count    0
holdout      false
```

The formal environment preflight passed on the intended `NVIDIA GeForce RTX 5080`, PyTorch `2.14.0+cu132`, CUDA `13.2`, and the frozen four-model parameter counts. No R11-S0 model fit completed and no final-holdout data were accessed.

## 2. Root cause class

The authoritative PR #103 controller verified implementation identity by comparing raw working-tree bytes with `git show <commit>:<path>` bytes. That is stricter than Git's own tracked-content identity and is not portable across checkout/text-normalization filters. A clean detached worktree can therefore be rejected as `IMPLEMENTATION_DRIFT` even when Git regards the tracked content as identical to the reviewed commit.

This is an execution-integrity defect, not a model/data/result defect.

## 3. Narrow repair

The repair changes only the formal runner-side implementation verifier. The repaired verifier requires:

1. current `HEAD` exactly equals the frozen repair executable commit;
2. every authoritative R11-S0 implementation path exists as a regular non-symlink file;
3. every path exists in the frozen commit;
4. `git diff --quiet --no-ext-diff <commit> -- <path>` reports no tracked-content drift under Git's normalization semantics.

This preserves fail-closed implementation identity while allowing Git-declared text normalization that does not alter tracked content.

No architecture, feature, chronology, horizon, optimizer, seed, fit ceiling, metric, decision threshold, holdout rule, or session-information boundary is changed.

## 4. Scientific state

```text
R11-S0 formal completed fits   0
R11-S0 result                  NONE
final holdout accessed         false
session predictors used        false
```

The original failed launcher attempt is retained as evidence and must not be deleted.

## 5. Re-authorization boundary

A repaired executable must pass full CI and be frozen under a new pinned launcher identity before one replacement formal R11-S0 run is allowed. This replacement run is permitted because the failed attempt ended before any model fit completed (`fit_count=0`).

Final JPL holdout `2019-03/06/09/12` remains sealed.
