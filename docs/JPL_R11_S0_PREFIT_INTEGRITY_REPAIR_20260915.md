# JPL/ACN R11-S0 pre-fit integrity repair note

Date: 2026-09-15  
Status: **repair reviewed / full CI passed / replacement pinned launcher frozen; scientific protocol unchanged**.

## 1. Trigger

The first formal R11-S0 launcher attempt (`evcf_r11_s0_launcher_v1_1.py`) returned:

```text
status       INCOMPLETE
reason_code  IMPLEMENTATION_DRIFT
fit_count    0
holdout      false
status file  evcf_r11_s0_status_20260915T061213Z.json
status SHA256 f29049799cf1536b514d0b20464b30d057224204a6151428fbed437ddd40cd1e
```

The formal environment preflight passed on the intended `NVIDIA GeForce RTX 5080`, PyTorch `2.14.0+cu132`, CUDA `13.2`, and the frozen four-model parameter counts. No R11-S0 model fit completed and no final-holdout data were accessed.

## 2. Root cause class

The authoritative PR #103 controller verified implementation identity by comparing raw working-tree bytes with `git show <commit>:<path>` bytes. That is stricter than Git's own tracked-content identity and is not portable across checkout/text-normalization filters. A clean detached worktree can therefore be rejected as `IMPLEMENTATION_DRIFT` even when Git regards the tracked content as identical to the reviewed commit.

This is an execution-integrity defect, not a model/data/result defect.

## 3. Narrow repair

The repair changes only the formal runner-side implementation verifier. The repaired verifier requires:

1. current `HEAD` exactly equals the frozen repaired executable commit;
2. every authoritative R11-S0 implementation path exists as a regular non-symlink file;
3. every path exists in the frozen commit;
4. `git diff --quiet --no-ext-diff <commit> -- <path>` reports no tracked-content drift under Git's normalization semantics.

This preserves fail-closed implementation identity while allowing Git-declared text normalization that does not alter tracked content.

Regression coverage explicitly verifies that CRLF/LF checkout normalization is accepted while semantic content changes still fail as `IMPLEMENTATION_DRIFT`.

No architecture, feature, chronology, horizon, optimizer, seed, fit ceiling, metric, decision threshold, holdout rule, or session-information boundary was changed.

## 4. Frozen repair identity

```text
repair PR                  #105
reviewed repaired executable 2107795e817bb8f2b490b98ed78f663f685306c8
repair implementation merge  384ff65f36c78bcc3cb89aed9e08ade1b5f12260
final repair CI run           34940555171
final repair CI               1264 passed, 4 skipped; compileall PASS; Ruff PASS
replacement launcher          evcf_r11_s0_launcher_v1_2.py
launcher SHA256               c990a5dced70a75ac5c5b48615363fdb0e694fc19902d8c58ef13a573f2e7724
```

The repaired PR head is the sole reviewed executable for the replacement formal run. The launcher checks out this exact commit in a detached preserved worktree and verifies its ancestry in the repair merge.

## 5. Scientific state

```text
R11-S0 formal completed fits   0
R11-S0 result                  NONE
final holdout accessed         false
session predictors used        false
```

The original failed launcher/status are retained as evidence and must not be deleted.

Because the failed attempt ended before any completed fit (`fit_count=0`), one replacement formal R11-S0 run is authorized under the unchanged frozen scientific protocol using only the exact v1.2 launcher above.

## 6. Next action

Run the replacement pinned launcher exactly once on the user machine. After it exits, upload only the newest:

```text
evcf_r11_s0_status_YYYYMMDDTHHMMSSZ.json
```

whether `COMPLETE` or `INCOMPLETE`.

If `INCOMPLETE`, do not edit code, alter the environment, or rerun before inspecting the status. If `COMPLETE`, audit the frozen SELECT/MIXED/STOP result before designing R11-M1.

Final JPL holdout `2019-03/06/09/12` remains sealed in every outcome.
