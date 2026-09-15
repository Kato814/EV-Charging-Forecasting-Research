# JPL/ACN R11-S0 pre-fit label-reader repair note

Date: 2026-09-15  
Status: **pre-fit compatibility repair only; scientific protocol unchanged**.

## 1. Trigger

The second formal R11-S0 launcher attempt returned:

```text
status       INCOMPLETE
reason_code  LABEL_INVALID
fit_count    0
holdout      false
```

The formal environment preflight again passed on the intended `NVIDIA GeForce RTX 5080`, PyTorch `2.14.0+cu132`, CUDA `13.2`, and the frozen four-model parameter counts. No R11-S0 fit completed and no final-holdout data were accessed.

## 2. Root cause

The frozen development snapshots serialize label dictionaries with `sort_keys=True`. JSON object key order is not semantic, so the stored horizon-key order is lexicographic rather than the numerical frozen horizon order.

The historical base development-expert reader incorrectly required insertion order to equal:

```text
15 / 30 / 60 / 120 / 240
```

A previously accepted compatibility reader already repairs this by validating the exact horizon-key set and then reading values in the frozen horizon order. R11-S0 imported the historical base reader directly instead of installing that accepted compatibility reader, so the same frozen snapshots were rejected as `LABEL_INVALID` before any fit.

## 3. Narrow repair

The formal R11-S0 runner now installs the already-existing, accepted order-insensitive development-snapshot label loader process-locally before invoking the frozen R11-S0 controller.

The repair:

- does not rewrite any label file;
- does not change any label value;
- does not change the target or horizon order;
- validates the exact five-key set;
- reads values only in frozen order `15, 30, 60, 120, 240`;
- keeps all R11-S0 architecture, feature, chronology, optimizer, seed, fit-count and decision rules unchanged.

## 4. Scientific state

```text
R11-S0 formal completed fits   0
R11-S0 result                  NONE
final holdout accessed         false
session predictors used        false
```

The failed v1.2 status is retained as evidence. A replacement formal run is permitted only after this repair passes full CI and a new pinned launcher is frozen.

Final JPL holdout `2019-03/06/09/12` remains sealed.
