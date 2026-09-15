# JPL/ACN R11-P1 privileged-arrival supervision outcome

Date: 2026-09-15  
Status: **COMPLETE / MIXED_PRIVILEGED_ARRIVAL_SIGNAL**

## 1. Execution identity

Exact candidate implementation:

```text
PR                     #110
candidate code commit  187c047596dffb74cef8a79fcc479edd55139d5f
launcher                evcf_r11_p1_candidate_launcher_v0_1.py
launcher SHA256         a9655dba0de6a54ea52c39171e392533d8b5c5e2c6ce52e9e1c5656435c33c31
```

Formal local environment:

```text
GPU        NVIDIA GeForce RTX 5080
PyTorch    2.14.0+cu132
CUDA       13.2
model      125,762 trainable parameters
deterministic CUDA backward smoke  PASS
```

Execution completed:

```text
deep fits               24 / 24
Station-HGB replay      20 / 20
total fits              44 / 44
status                  COMPLETE
decision                MIXED_PRIVILEGED_ARRIVAL_SIGNAL
holdout accessed        false
session predictors used false
```

GitHub Actions did not provide a usable repository-wide CI run because the account had exhausted its monthly Actions-minute quota. The candidate was therefore validated by the frozen local launcher on the exact candidate commit. Full repository CI is deferred until the quota resets; the infrastructure limitation does not change the scientific result.

## 2. Frozen scientific comparison

R11-P1 compares the same station-only long-horizon TCN under two objectives:

```text
Arm B  L = L_total
Arm C  L = L_total + 0.5 * L_future_arrival
```

The auxiliary future-arrival label is used only during training. Deployment remains aggregate-only.

Median pooled long-horizon MAE:

```text
Arm B   33.2304292334 A
Arm C   32.6842326626 A
relative improvement  1.6436639%
```

By horizon:

```text
60 min   B 26.9351872948 A   C 25.8469801698 A   improvement 4.0401%
120 min  B 33.2106616574 A   C 32.2371871698 A   improvement 2.9312%
240 min  B 40.5350216869 A   C 40.4431764306 A   improvement 0.2266%
```

Arm C wins all `3/3` long horizons.

By development month:

```text
2019-01  B 37.0040665405 A   C 35.9885421257 A   improvement 2.7444%
2019-04  B 35.1836887599 A   C 35.0291161206 A   improvement 0.4393%
2019-07  B 30.3995627172 A   C 29.9476444793 A   improvement 1.4866%
2019-10  B 31.0739536005 A   C 30.0350303547 A   improvement 3.3434%
```

Arm C wins all `4/4` development months.

Paired pooled long-horizon MAE by seed:

```text
seed 2026091401  B 32.8816489034 A   C 32.6842326626 A   improvement 0.6004%
seed 2026091402  B 34.4948897275 A   C 34.1735538536 A   improvement 0.9315%
seed 2026091403  B 33.2304292334 A   C 32.5885807264 A   improvement 1.9315%
```

Arm C wins all `3/3` paired seeds.

## 3. Absolute comparison against Station-HGB

Frozen Station-HGB long-horizon pooled MAE:

```text
33.5592843062 A
```

Arm C median long-horizon MAE is `32.6842326626 A`, a `2.6075%` improvement.

The complete five-horizon Arm C hybrid keeps Station-HGB at 15/30 min and uses the privileged-trained TCN at 60/120/240 min:

```text
Station-HGB all five horizons   25.8731522189 A
Arm C five-horizon hybrid       25.3481212328 A
relative improvement             2.0293%
```

Thus the privileged-supervision signal is not only relative to Arm B; the frozen hybrid also improves the strong same-information Station-HGB anchor on pooled development MAE.

## 4. Why the frozen decision is MIXED rather than PASS

All preregistered PASS conditions are satisfied except seed-spread stability:

```text
C vs B median pooled gain >= 1%          PASS  (+1.6437%)
C wins >= 2/3 long horizons              PASS  (3/3)
no long horizon degradation > 1%         PASS  (all improve)
C wins >= 3/4 months                     PASS  (4/4)
C wins >= 2/3 paired seeds               PASS  (3/3)
C pooled seed spread <= 3%               FAIL  (4.8494%)
C long pooled beats HGB long pooled      PASS
full five-horizon hybrid beats HGB       PASS
all folds complete / no test-row removal PASS
```

Therefore the frozen decision is correctly:

```text
MIXED_PRIVILEGED_ARRIVAL_SIGNAL
```

No threshold is relaxed after observing the result.

## 5. Stability diagnosis

The instability is not specific to the privileged auxiliary signal:

```text
Arm B pooled seed spread  4.8547%
Arm C pooled seed spread  4.8494%
```

The spreads are essentially the same, while Arm C improves Arm B under every frozen seed, every long horizon, and every development month.

The most defensible interpretation is therefore:

> Future-arrival training-only supervision provides a directionally consistent development-stage accuracy signal, but the compact long-horizon TCN carrier itself remains insufficiently seed-stable for a full PASS claim.

This result supports the scientific hypothesis more strongly than the algorithmic-readiness criterion.

## 6. Interpretation boundary

Allowed statement:

> On the frozen JPL development protocol, session-resolved future-arrival contribution labels used only during training consistently improve the same aggregate-only long-horizon station forecaster across all tested horizons, months and seeds; however, the carrier retains approximately 4.85% seed spread, so the result is classified as mixed rather than robustly passed.

Not allowed:

- changing the R11-P1 decision to PASS;
- tuning the auxiliary weight after inspection;
- adding more seeds inside R11-P1;
- changing the 30/60 min horizon boundary inside R11-P1;
- adding a new backbone to rescue R11-P1;
- claiming final holdout or independent-site generalization.

## 7. Scientific next step

Do not perform an in-protocol stability rescue.

Preferred next step is a **new, separately preregistered independent-generalization stage**, using the R11-P1 method definition unchanged. Its purpose is to determine whether the privileged-arrival gain transfers outside the adaptively explored JPL development months, rather than optimizing the current development result.

Priority order:

```text
1. identify an independent site/source with the required session-rich training labels;
2. freeze data identity, chronology, exact Arm B/C method, seeds and decision rule before fitting;
3. keep aggregate-only inference unchanged;
4. evaluate C-B paired gain and stability on that independent source;
5. keep JPL final holdout sealed until a final publication-level confirmation protocol is justified.
```

If no suitable independent session-rich site is available, freeze the current method as development-only evidence rather than tuning it further.
