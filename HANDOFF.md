# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、`docs/JPL_R11_S0_BACKBONE_SCREEN_OUTCOME_20260915.md`、`docs/JPL_R11_P1_HORIZON_TARGETED_PRIVILEGED_ARRIVAL_PROTOCOL_20260915.md`、`docs/JPL_R11_P1_PRIVILEGED_ARRIVAL_OUTCOME_20260915.md` 与 `docs/JPL_R11_G0_CALTECH_INDEPENDENT_REPLICATION_PROTOCOL_20260915.md`。

## 1. Frozen scientific state

```text
R10-R0 = COMPLETE / MIXED_DEVELOPMENT_ROBUSTNESS
R11-S0 = COMPLETE / STOP_DEEP_CORE_ROUTE / 68 fits
original R11-M1 = CANCELLED
R11-P1 = COMPLETE / MIXED_PRIVILEGED_ARRIVAL_SIGNAL / 44 fits
R11-G0 = PROTOCOL FROZEN / NOT RUN
JPL final holdout = SEALED
```

Final JPL holdout remains `2019-03/06/09/12` and has not been accessed.

## 2. R11-P1 execution identity

```text
candidate PR            #110
candidate code commit   187c047596dffb74cef8a79fcc479edd55139d5f
launcher SHA256         a9655dba0de6a54ea52c39171e392533d8b5c5e2c6ce52e9e1c5656435c33c31
deep fits               24 / 24
HGB replay              20 / 20
total fits              44 / 44
holdout accessed        false
session predictors      false
```

Environment:

```text
RTX 5080
PyTorch 2.14.0+cu132
CUDA 13.2
deterministic CUDA backward smoke PASS
```

GitHub Actions monthly quota is exhausted. Repository-wide CI is unavailable until reset; do not interpret immediate no-run workflow failures as code failures. Use local targeted validation for active work and run archival full CI only after quota reset.

## 3. Frozen R11-P1 method/result

```text
15/30 min       Station-HGB
60/120/240 min  station-only TCN

Arm B  L = L_total
Arm C  L = L_total + 0.5 * L_future_arrival
```

Result:

```text
Arm B long pooled MAE  33.2304292334 A
Arm C long pooled MAE  32.6842326626 A
C-B gain                1.6437%
horizon wins            3/3
month wins              4/4
paired seed wins        3/3

Station-HGB long        33.5592843062 A
Arm C long               32.6842326626 A
Station-HGB all-5        25.8731522189 A
Arm C hybrid all-5       25.3481212328 A
```

Only frozen PASS failure:

```text
Arm B seed spread  4.8547%
Arm C seed spread  4.8494%
required           <= 3.0%
```

Decision remains `MIXED_PRIVILEGED_ARRIVAL_SIGNAL`.

Interpretation: the auxiliary signal is directionally consistent, while seed instability is essentially unchanged between B and C and therefore appears carrier-level rather than privileged-loss-specific.

## 4. What must not be done

Do not:

```text
relax the 3% seed-spread gate
relabel MIXED as PASS
add more seeds inside R11-P1
tune lambda=0.5 after seeing the result
add an existing-session auxiliary head inside R11-P1
change the 30/60 min split inside R11-P1
add another backbone to rescue R11-P1
open JPL final holdout now
```

No reset/clean/stash/force-push/automatic deletion of evidence or worktrees.

## 5. Frozen R11-G0 independent source

Independent site is now fixed:

```text
ACN-Data site_id  caltech
formal months     2019-02 / 2019-05 / 2019-08 / 2019-11
formal source     official ACN-Data REST /sessions/caltech/ts
timezone          America/Los_Angeles
```

The months are complementary to the JPL R11 development months and the sealed JPL final holdout months.

Formal Caltech acquisition must use the official API with local `ACN_API_TOKEN`; no token, raw session IDs, user IDs or absolute paths may be committed.

## 6. R11-G0 model contract

Copy R11-P1 exactly; no Caltech tuning:

```text
15/30 min       frozen-parameter Station-HGB
60/120/240 min  same station-only TCN
Arm B           L_total
Arm C           L_total + 0.5 * L_future_arrival
seeds           2026091401 / 02 / 03
fit ceiling     24 deep + 20 HGB replay = 44
```

No HGB retuning, architecture tuning, lambda sweep, extra seed, clipping, calibration, ensemble or horizon-boundary search.

Inference remains aggregate-only. Session-resolved data is allowed only for pre-fit QA and future-arrival training-label reconstruction.

## 7. Pre-fit Caltech boundary

Do **not** run Arm B/C immediately after downloading data.

First create and freeze an aggregate-only Caltech processed-row manifest containing:

```text
month
raw/session counts
QA/quarantine counts
processed snapshot SHA256
formal issue-time count
formal test-origin count
common row count per horizon
```

The exact common evaluation rows are frozen at that point. After freeze, no row removal/reweighting, month replacement or validity-threshold change is allowed.

## 8. R11-G0 decision

Frozen outcomes:

```text
REPLICATE_PRIVILEGED_ARRIVAL_SIGNAL
MIXED_INDEPENDENT_REPLICATION
FAIL_INDEPENDENT_REPLICATION
```

Replication uses the same quantitative gates as R11-P1, including:

```text
C-B median long gain >= 1%
>= 2/3 horizon wins
no horizon degradation > 1%
>= 3/4 month wins
>= 2/3 paired seed wins
C seed spread <= 3%
C long beats Station-HGB long
full hybrid beats Station-HGB all-5
all frozen rows complete
```

Do not pool JPL and Caltech into one decision statistic.

## 9. Next authorized work

Only the following is authorized next:

```text
1. implement site-general Caltech acquisition/preprocessing;
2. locally acquire 2019-02/05/08/11 from official ACN-Data API;
3. run pre-fit QA only;
4. generate the aggregate-only Caltech row/data manifest;
5. freeze/review that manifest;
6. only then authorize the 44-fit R11-G0 model experiment.
```

GitHub Actions is not a blocking gate while the monthly quota is exhausted, but branch/PR/code identity remains mandatory.
