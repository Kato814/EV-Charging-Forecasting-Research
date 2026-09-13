# JPL/ACN R5 pre-fit geometry-audit scale repair

Date: 2026-09-13
Status: frozen before any R5 real-data model fit.

## 1. Scope

This amendment repairs only Section 11 (held-out geometry audit) of the already merged R5 FTAR protocol. It does not change:

- the R5 scientific question;
- development/final-holdout months;
- input features;
- Direct or FTAR architecture;
- target construction;
- prediction loss;
- FTAR geometry training loss or weight `0.25`;
- optimizer, epochs, batch size or seed;
- strong baselines;
- primary forecasting metrics;
- PASS/MIXED/STOP forecasting thresholds.

No R5 real-data model fit has occurred before this repair.

## 2. Reason for repair

The original protocol correctly prohibited pair construction across daily refits, because each refit produces its own latent coordinate system. A further identifiability issue remains: even for valid within-refit pairs, the **absolute scale** of latent RMS distances can differ arbitrarily between daily refits. This is especially relevant because the FTAR training loss itself compares batch-standardized distance vectors and therefore does not anchor an absolute latent-distance scale across refits.

Consequently, concatenating raw within-refit latent distances across days before a pooled Spearman calculation can introduce an artificial cross-refit scale effect even though no cross-refit pair is constructed.

## 3. Frozen repaired audit

For each daily refit/test block separately:

1. Form unordered OOS row pairs only within that same daily refit.
2. For every pair compute:
   - Direct latent RMS distance `D_direct`;
   - FTAR latent RMS distance `D_ftar`;
   - normalized future-transition RMS distance `D_future`, using that refit's training-only issue-current fill and transition location/scale.
3. Independently standardize the three pair-distance vectors **within the daily refit** using population standard deviation and `eps=1e-6`:

```text
Z_direct = (D_direct - mean(D_direct)) / (std(D_direct) + 1e-6)
Z_ftar   = (D_ftar   - mean(D_ftar))   / (std(D_ftar)   + 1e-6)
Z_future = (D_future - mean(D_future)) / (std(D_future) + 1e-6)
```

4. If a daily vector has zero or near-zero dispersion, the `eps=1e-6` denominator is still used exactly as written; the resulting standardized values remain finite. A daily block with fewer than two OOS rows contributes no pairs.
5. Within each development month, concatenate only these **daily-standardized, same-refit pair records** across its daily refits.
6. If a month has more than 20,000 valid pair records, sample 20,000 without replacement using deterministic PCG64 seed `20260913`; otherwise retain all.
7. Compute month-level Spearman between `Z_direct` and `Z_future`, and separately between `Z_ftar` and `Z_future`.
8. The pooled audit concatenates the retained, daily-standardized pair records from the four months and computes the same two Spearman correlations.

The audit remains offline and diagnostic only. OOS future labels never affect preprocessing, model fitting, prediction, pair eligibility, sampling probability, or model selection.

## 4. Decision interpretation

The R5 PASS condition “pooled held-out latent/future-transition Spearman is higher for FTAR than Direct” now refers to the repaired **daily-standardized same-refit** audit defined above.

All other PASS/MIXED/STOP conditions remain unchanged and exhaustive.

## 5. Implementation requirement

The R5 implementation must:

- record that the scale-repair amendment is bound to the run;
- unit-test that applying an arbitrary positive affine transform to all latent distances of one daily refit does not change its standardized audit values except numerical tolerance;
- unit-test that no cross-refit pair is created;
- keep Direct and FTAR sampling/pair identities identical;
- expose only aggregate audit correlations and pair counts.
