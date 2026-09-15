# JPL/ACN R11-S0 deterministic CUDA repair note

Date: 2026-09-15  
Status: **implementation/runtime repair only; scientific protocol unchanged**.

## 1. Trigger

The v1.3 formal attempt returned:

```text
status       INCOMPLETE
reason_code  UNEXPECTED_ERROR
outer status fit_count 0
holdout      false
```

The outer launcher value `fit_count=0` is a failure-default and does **not** prove that zero internal fits were attempted before the exception. No aggregate model metrics, architecture ranking, selected backbone, or prediction outputs were returned by the failed attempt. Final holdout remained sealed.

The formal RTX 5080 / PyTorch 2.14.0+cu132 / CUDA 13.2 preflight passed again.

## 2. Root cause

The frozen N-HiTS implementation uses `torch.nn.functional.interpolate(..., mode="linear", align_corners=False)` inside the differentiable backcast/forecast interpolation path.

The formal training policy also enables:

```text
torch.use_deterministic_algorithms(True)
```

PyTorch 2.14 documents that differentiating CUDA `torch.nn.functional.interpolate()` with `mode="linear"` raises `RuntimeError` when deterministic algorithms are enforced. Therefore the v1.3 implementation contains a deterministic-runtime incompatibility that the previous environment smoke test did not exercise.

This is a runtime implementation defect, not a data, model-selection, or result-dependent scientific finding.

## 3. Narrow repair

The repair preserves the same N-HiTS:

```text
stacks                 = 3
pool/downsample factors= [1,4,16]
blocks per stack       = 1
MLP hidden width       = 128
MLP hidden layers      = 2
forecast length         = 5
parameter count         = 116133
```

Only the CUDA-incompatible `functional.interpolate(mode="linear")` operation is replaced by an explicit 1-D align_corners=False linear interpolation using deterministic tensor indexing plus weighted sums.

CPU regression testing requires the replacement to numerically match PyTorch linear interpolation geometry for representative tensor shapes.

## 4. Stronger pre-fit gate

The formal environment preflight is extended to run one synthetic forward/backward step for **all four** frozen deep architectures under the exact deterministic CUDA setting before any real development labels are used.

The preflight must fail closed with:

```text
DETERMINISTIC_BACKWARD_UNAVAILABLE
```

if any frozen architecture cannot complete synthetic deterministic CUDA backpropagation.

This prevents another real-data run from discovering a backend incompatibility only after earlier architectures may already have trained.

## 5. Replacement-run accounting

The v1.3 attempt is preserved as an aborted infrastructure execution. Because it returned no scientific metrics or model-selection outcome, no result-dependent tuning is possible from that attempt.

The repaired implementation may authorize one complete replacement R11-S0 run only after full CI passes and a new pinned launcher identity is frozen. The replacement run must execute the original frozen 68-fit screen from the beginning; no intermediate state or predictions from the aborted attempt may be reused.

For transparency, prior aborted executions remain part of the compute/audit history even though the accepted scientific R11-S0 result, if obtained, will come from the single complete repaired run.

## 6. Scientific protocol unchanged

No change is made to:

- station-only predictor inputs;
- 96-bin history;
- 15/30/60/120/240 min horizons;
- GRU/TCN/N-HiTS/PatchTST families or capacity settings;
- Station-HGB anchor;
- chronological folds;
- optimizer/loss/early stopping;
- frozen seeds;
- model-selection thresholds;
- session-information boundary;
- final holdout rule.

Final JPL holdout `2019-03/06/09/12` remains sealed.
