# JPL/ACN R4-D1 state-geometry failure diagnostic protocol

Date: 2026-09-13
Status: frozen after formal R4-I0 `MIXED_STATE_ALIASING_SIGNAL` and before any R4-D1 data run.

## 1. Purpose

R4-I0 produced a specific MIXED pattern:

- M3 improves over M2 by 8.19% pooled and in every pooled horizon/month summary;
- M3 does not improve over Level-Control pooled;
- M3-vs-Level changes from strongly negative at short horizons to positive at 240 min;
- April is favorable to M3 while October is strongly unfavorable;
- analog support itself passes comfortably.

R4-D1 asks only:

> Does the frozen M3 analog metric select histories that are closer in session-state geometry but farther in instantaneous station-current level, creating a horizon/month-dependent geometry trade-off relative to Level-Control?

This is a read-only explanation diagnostic. It is not a new forecasting method, not metric learning, not a new nearest-neighbor rule, and cannot change the formal R4-I0 decision.

## 2. Frozen source evidence

R4-D1 is bound to:

```text
R4 source status SHA256       a8b7142e0361b5cd56e53c7de99d8e699a27e1aee78728810773c127f385823f
R4 reviewed executable head   d3f00320e90aeb213d97d63d3460f58d495dd34a
R4 protocol merge             fec13c28cb5d4b2490256f8a26d82f45d8af6051
R4 decision                   MIXED_STATE_ALIASING_SIGNAL
```

Development months remain `2019-01/04/07/10`; final holdout `2019-03/06/09/12` remains sealed.

No new data download, model fit, hyperparameter search, clipping, calibration or reference-model retraining is allowed.

## 3. Exact R4 replay gate

Before any new R4-D1 summary is accepted, the diagnostic must recompute the original R4-I0 analog selection using the exact frozen R4 rules:

- same development months and OOS rows;
- same horizon-label availability rule;
- same historical-only `RidgePreprocessor`;
- same exact local 15-minute clock slot;
- `MIN_CANDIDATES=10`;
- `K=3`;
- same Level/M2/M3 distances and earlier-time tie breaking;
- same M3 historical third-neighbor q95 (`higher`) support calibration;
- same supported-row set.

The recomputed public R4 aggregates must match the accepted status before the new geometry analysis is published. At minimum, verify exact counts and `np.allclose(rtol=0, atol=1e-12)` for `G_level`, `G_M2`, `G_M3`, `Y_scale`, the three skills and normalized M3 divergence at pooled, 5 horizon, 4 month and 20 month×horizon levels.

A replay mismatch terminates R4-D1 as invalid. It does not trigger a new R4 run or threshold change.

## 4. Frozen geometry spaces

The canonical feature hierarchy is cumulative:

```text
M2 raw = M1 + 6 station-state features                  = 201 raw
M3 raw = M2 + 11 session fields × 10 pooled statistics = 311 raw
```

Ridge encoding appends fixed nullable indicators.

R4-D1 uses four read-only geometry views, all with the exact fold-local preprocessing already fitted for R4:

### 4.1 Current-level coordinate

The standardized M2 `station_current_a` coordinate used by Level-Control.

For test row `i`, analog arm `a`, and its three frozen analogs `N_a(i)`:

`C_a(i) = mean_j |z_current(i)-z_current(j)|`.

### 4.2 Complete M2 geometry

`Q2_a(i) = mean_j RMS(z_M2(i)-z_M2(j))` over the frozen 204-dimensional M2 encoding.

### 4.3 M3 session-extension geometry

Use only the encoded coordinates added by M3 beyond canonical M2: the 110 raw M3 session-pool features plus their own nullable indicators. The shared M2 raw coordinates and shared M2 nullable indicators are excluded.

`QE_a(i) = mean_j RMS(z_M3_extension(i)-z_M3_extension(j))`.

The extension-coordinate mapping must be derived from the canonical feature names/nullability masks, not hard-coded from a favorable result.

### 4.4 Complete M3 geometry

`Q3_a(i) = mean_j RMS(z_M3(i)-z_M3(j))` over the frozen 391-dimensional M3 encoding.

## 5. Frozen neighbor-overlap diagnostics

For the original three analog identities from each arm, report pairwise overlap counts:

```text
O_Level_M2(i) = |N_Level(i) ∩ N_M2(i)|
O_Level_M3(i) = |N_Level(i) ∩ N_M3(i)|
O_M2_M3(i)    = |N_M2(i) ∩ N_M3(i)|
```

Each ranges from 0 to 3. No alternative analog set is constructed.

## 6. Future-outcome quantities

After the frozen analog identities are established, reuse the original target divergence only:

```text
D_Level(i,h)
D_M2(i,h)
D_M3(i,h)
```

Report descriptive differences:

```text
DeltaFuture_M3_Level = D_M3 - D_Level
DeltaFuture_M3_M2    = D_M3 - D_M2
```

Positive `DeltaFuture_M3_Level` means M3 analogs have more divergent futures than Level analogs. Negative `DeltaFuture_M3_M2` means M3 improves over M2.

No target value may alter analog identity, row inclusion, geometry space or aggregation group.

## 7. Required aggregation

For `C`, `Q2`, `QE`, `Q3`, overlaps and future-divergence differences, report only the complete preregistered groups:

- pooled overall;
- all 5 horizons;
- all 4 months;
- all 20 month × horizon cells.

For continuous geometry quantities report mean and median. For overlap counts report mean plus fractions with overlap 0/1/2/3.

Do not add selected hours, dates, current-load bins, support-ratio bins or favorable subsets after seeing the result.

## 8. Interpretation boundary

R4-D1 has no PASS/MIXED/STOP rule and cannot reopen R4-I0.

The diagnostic may support only bounded statements such as:

- M3 selection trades current-level similarity for session-state similarity;
- the magnitude/direction of that trade-off varies by horizon or month;
- M3 and Level select substantially different histories despite the common candidate pool;
- the observed R4 MIXED result is or is not consistent with a state-geometry trade-off.

It must not claim that such a trade-off is causal, optimal, or a new forecasting method.

## 9. Explicit prohibitions

R4-D1 must not:

- change K;
- change same-clock candidates or support q95;
- alter supported rows;
- learn/reweight a distance metric;
- use PCA or feature selection;
- construct a two-stage/hybrid analog rule;
- tune current-level bands;
- train a forecasting model;
- access final holdout;
- use target/error to choose geometry coordinates or subsets;
- convert descriptive geometry into a post-hoc R4 PASS.

## 10. Execution sequence

This protocol alone authorizes no local run.

Required sequence:

1. outcome + R4-D1 protocol documentation PR review/CI/merge;
2. separate zero-fit implementation PR;
3. tests for exact R4 replay, canonical M3-extension coordinate derivation, cross-arm geometry and overlap accounting;
4. full pytest/compileall/Ruff;
5. pinned development-only launcher;
6. one R4-D1 run;
7. archive diagnostic and only then select the next scientific method question.
