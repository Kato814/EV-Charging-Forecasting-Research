# JPL/ACN R11-S0 station-level backbone screening outcome

Date: 2026-09-15  
Status: **COMPLETE / STOP_DEEP_CORE_ROUTE**.

## 1. Accepted formal run

```text
launcher schema      evcf-r11-s0-launcher/v1.4.1
launcher SHA256      c6caaaf1a00aa41f8778aeb24ab0c55f1fee02a847e93c205439735aac987f42
reviewed executable  a7dceaabab7a27cf6a6323a4630ea38494ffed71
implementation merge bebe0ebcb94f1ce8a9bafd35156be0a94dcfbd87
status file          evcf_r11_s0_status_20260915T120120Z.json
status SHA256        2706d5ed65e2d2c0e6ed5d2aace4fd9f95ccc23f61833a9d41f5184361e77f70
formal fits          68 / 68
final holdout         NOT ACCESSED
session predictors   NOT USED
development writes   false
```

The strengthened deterministic CUDA preflight passed for GRU, TCN, N-HiTS and PatchTST on the user RTX 5080 / PyTorch 2.14.0+cu132 / CUDA 13.2 environment.

## 2. Frozen Station-HGB anchor

Pooled over 5,075 frozen origins and five horizons (25,375 origin-horizon records):

```text
MAE   25.8731522189 A
RMSE  53.1466051439 A
WAPE  0.1737126243
```

Horizon MAE:

```text
15 min   11.2074011740 A
30 min   17.4805070019 A
60 min   25.2404332683 A
120 min  33.2954316198 A
240 min  42.1419880303 A
```

## 3. Deep candidates

Frozen median-seed screening results:

| Candidate | Pooled MAE (A) | vs Station-HGB | Seed spread | Worst horizon degradation | Worst month degradation | Eligible |
|---|---:|---:|---:|---:|---:|---|
| GRU | 27.2072425618 | +5.16% | 5.03% | +64.02% | +15.85% | No |
| TCN | 26.9086600381 | +4.00% | 3.03% | +49.36% | +12.24% | No |
| N-HiTS | 34.8304657865 | +34.62% | 5.31% | +95.12% | +44.50% | No |
| PatchTST | 32.3044344149 | +24.86% | 8.20% | +126.42% | +47.12% | No |

No candidate satisfies the frozen eligibility rule. Therefore the only protocol-valid outcome is:

```text
STOP_DEEP_CORE_ROUTE
selected_backbone = null
```

R11-M1, as originally defined, must not be launched because it requires a selected stable deep backbone.

## 4. Diagnostic observation, not a selection override

TCN is the closest deep candidate. Its horizon MAE is:

```text
15 min   16.7398461761 A   (+49.36% vs HGB)
30 min   19.5558990917 A   (+11.87%)
60 min   24.6809469543 A   (-2.22%)
120 min  32.9585013346 A   (-1.01%)
240 min  40.7305229433 A   (-3.35%)
```

GRU shows the same broad pattern: poor short-horizon performance and roughly competitive or slightly better 120-240 min behavior. This does **not** rescue R11-S0 and does not authorize a horizon ensemble under the frozen protocol. It is retained only as development evidence for a separately frozen follow-up hypothesis.

## 5. Scientific interpretation

The negative S0 result rejects the assumption that one compact end-to-end deep station-level backbone can replace the same-information Station-HGB anchor across all five horizons under the frozen data budget and training protocol.

The result does **not** test the privileged-supervision hypothesis itself. It only shows that the originally planned carrier architecture route is not credible enough to justify R11-M1.

A follow-up method, if pursued, must be defined as a new protocol. It may use the observed horizon asymmetry as motivation, but must not retroactively alter S0 thresholds, add a fifth architecture, tune seeds, clip/calibrate predictions, or access the final holdout.

## 6. Holdout and scope

Final JPL holdout remains sealed:

```text
2019-03 / 2019-06 / 2019-09 / 2019-12
```

No final-holdout readiness claim is made. No zero-shot or cross-dataset generalization claim is made.