# R3-C0 control-endogeneity gate protocol

Date: 2026-09-13
Status: **frozen before any R3-C0 data run**.

R3-C0 is a development-only, **0-fit** mechanism diagnostic. It does not reopen R2, authorize a control-aware model, or authorize final-holdout access.

## 1. Scientific question

The accepted target is realized station current. ACN/JPL observes both measured charging current and the EVSE pilot/current limit, so realized load is generated after a charging-control action rather than by user demand alone.

R3-C0 asks:

> When the future control path is unavailable at forecast issue time, does the issue-time pilot-versus-actual operating state stably stratify forecast error of already-frozen strong station-current predictors after matching on current station-load level?

This is a descriptive forecastability gate, not a causal test and not a novelty claim for pilot/current data.

## 2. Frozen scope

Target: `station_current_mean_a` [A].

Development only: `2019-01`, `2019-04`, `2019-07`, `2019-10`.

Final holdout remains sealed: `2019-03`, `2019-06`, `2019-09`, `2019-12`.

Horizons: `15/30/60/120/240 min`.

Frozen development snapshot SHA256:

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

Primary frozen prediction references: `Equal` and `S1`. `R1-Joint` may be reported secondarily but cannot affect the decision. No reference model is retrained.

## 3. Legal issue-time inputs

From each accepted M3 issue-time group use only:

```text
current_current_a
current_pilot_a
```

`anonymous_session_index` is allowed only for deterministic alignment and is never a predictor/public output.

Use accepted M2 `station_current_a` only for current-load matching.

Forbidden inputs include future pilot/current, future arrivals, realized departure, future composition, final delivered energy, test error and offline outcomes.

## 4. Frozen control-utilization state

For one issue time with `N` connected M3 rows, a row is paired-valid iff:

- `current_current_a` is finite;
- `current_pilot_a` is finite;
- `current_pilot_a > 0`.

Let `K` be paired-valid count and define over paired-valid rows:

```text
C = sum(current_current_a)
P = sum(current_pilot_a)
U = C / P
coverage = K / N
```

An issue time is R3-C0 valid iff:

```text
N > 0
K > 0
coverage >= 0.80
P >= 6.0 A
M2 station_current_a is finite
U is finite
```

`U` is **not clipped** to `[0,1]`.

Secondary descriptive-only statistic:

```text
binding_fraction_90 = mean(current_current_a >= 0.90 * current_pilot_a)
```

It cannot affect PASS/MIXED/STOP.

## 5. Target-independent current-level matching

Matching uses issue-time variables only; truth/error never enters matching.

For each development month independently:

1. collect all R3-C0-valid issue times;
2. stable-sort by M2 `station_current_a`, tie by issue UTC time;
3. assign five equal-count current-level bins by rank (`0..4`), sizes differ by at most one;
4. within each bin stable-sort by `U`, tie by issue UTC time;
5. split into lower-`U` and upper-`U` halves;
6. if bin cardinality is odd, retain the single median row for support reporting but omit it from paired contrast;
7. separately sort both halves by `station_current_a` and pair by rank.

The same month-level pairs are reused for every horizon and every frozen model. No horizon-specific rematching.

## 6. Error contrast

For model `m`, matched pair `j`, horizon `h`:

```text
AE_low  = abs(pred_low  - truth_low)
AE_high = abs(pred_high - truth_high)
d_j     = AE_low - AE_high
b_j     = (AE_low + AE_high) / 2
```

For an aggregation cell:

```text
delta_mae_a = mean(d_j)
base_mae_a = mean(b_j)
delta_fraction = delta_mae_a / base_mae_a
```

Interpretation:

- `delta_fraction > 0`: lower utilization has larger error;
- `delta_fraction < 0`: higher utilization has larger error.

The test is two-sided; no direction is preselected.

For Equal and S1 report pooled overall, pooled by horizon, pooled by month, all 20 month×horizon cells, matched-pair counts, valid-state support and `binding_fraction_90`. R1-Joint may use the same tables as secondary evidence only.

## 7. Frozen support requirements

Let `valid_issue_fraction` be valid issue times divided by all common accepted OOS issue times for that month before horizon replication.

Required:

```text
overall valid_issue_fraction >= 0.70
every development month valid_issue_fraction >= 0.50
every development month matched issue-time pairs >= 100
```

If any fails: `STOP_CONTROL_ENDOGENEITY_ROUTE`, reason `INSUFFICIENT_CONTROL_STATE_SUPPORT`. Thresholds cannot be relaxed after results.

## 8. Frozen decision rules

An aggregate sign is positive or negative according to `delta_fraction`; exact zero has no sign.

### PASS_CONTROL_ENDOGENEITY_SIGNAL

All must hold:

1. Section 7 support passes;
2. Equal pooled `abs(delta_fraction) >= 0.05`;
3. S1 pooled `abs(delta_fraction) >= 0.05`;
4. Equal/S1 pooled signs agree and are non-zero;
5. Equal >=3/5 horizon aggregates share pooled sign;
6. S1 >=3/5 horizon aggregates share pooled sign;
7. Equal >=3/4 month aggregates share pooled sign;
8. S1 >=3/4 month aggregates share pooled sign;
9. at 60 min, Equal and S1 share the pooled sign in >=3/4 development months.

Meaning only: issue-time control utilization stably stratifies forecastability enough to justify a separately frozen modeling/target-design stage. PASS is not causal proof, does not authorize a model and does not open holdout.

### MIXED_CONTROL_ENDOGENEITY_SIGNAL

Use MIXED only when support passes and all hold:

- Equal/S1 pooled signs agree and are non-zero;
- at least one of Equal/S1 has pooled `abs(delta_fraction) >= 0.03`;
- both Equal and S1 have >=2/5 horizon aggregates sharing pooled sign;
- both Equal and S1 have >=2/4 month aggregates sharing pooled sign;
- at least one PASS condition fails.

Only separately scoped read-only failure analysis may follow.

### STOP_CONTROL_ENDOGENEITY_ROUTE

Use STOP when any holds:

- support fails;
- Equal/S1 pooled signs disagree or either pooled contrast is exactly zero;
- both Equal and S1 pooled `abs(delta_fraction) < 0.03`;
- either Equal or S1 has <=1/5 horizon aggregates sharing its pooled sign;
- either Equal or S1 has <=1/4 month aggregates sharing its pooled sign.

STOP closes the route without building a control-aware model from these results.

## 9. Explicit prohibitions

During R3-C0 do not:

- fit/retrain any model;
- access final holdout;
- use future pilot/control path;
- alter Equal/S1 predictions;
- clip/calibrate/post-process predictions;
- tune coverage, 6 A floor, five bins, utilization formula or matching after results;
- filter hours/horizons/dates/sessions based on outcomes;
- make p-value/CI claims treating repeated horizons as independent;
- rescue R2 or run Set Transformer/MoE/trajectory experiments.

## 10. Engineering gate before one local run

Implementation must be isolated in a separate PR. Tests must verify:

1. exact development months and holdout rejection;
2. exact current/pilot field whitelist;
3. issue-time-only state construction;
4. deterministic, target/error-independent matching;
5. identical pairs across horizons/models;
6. accepted Equal/S1 row/truth identity reconstructed first;
7. support/decision rules independently testable;
8. `fit_count = 0`;
9. processed data and private reference caches unchanged after run;
10. no private IDs/absolute local paths in public status;
11. full pytest/compileall/Ruff pass;
12. console output limited to stage/month/coarse completed-count progress.

No local user command is authorized until this protocol merges, implementation CI passes and one pinned launcher is released.