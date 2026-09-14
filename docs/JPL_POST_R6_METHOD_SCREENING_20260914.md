# Post-R6 method screening — current-session departure state before another backbone

Date: 2026-09-14
Status: method selection only; no R7 execution authorized by this document alone.

## 1. Accepted starting point

Formal development evidence is now:

```text
S1    = MIXED_STRUCTURED_SIGNAL
P1    = STOP_MECHANISM_ROUTE
R1    = MIXED_JOINT_STATE_SIGNAL
R2    = STOP_HIGHER_ORDER_SET_ROUTE
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE
R4-I0 = MIXED_STATE_ALIASING_SIGNAL
R4-D1/R4-D2 = COMPLETE diagnostics
R5    = STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE
R6-O0 = MIXED_COMPONENT_ORACLE_SIGNAL
```

R6 source status SHA256:

```text
52bf3d7753b095a0faf39bc9aaefbd07b2c11f406ab05abd4bd1534e921dacce
```

R6 shows a stable horizon transition rather than random month instability:

- 15 min: existing-session oracle replacement gain is larger in 4/4 months;
- 30 min: existing-session gain is larger in 3/4 months;
- 60/120/240 min: future-arrival gain is larger in 4/4 months at every horizon;
- pooled future-arrival replacement gain is 15.8037 A versus 5.4897 A for existing sessions.

Final holdout 2019-03/06/09/12 remains sealed.

## 2. Why the immediate next step is not a probabilistic Transformer / TPP / MoE

The external literature already contains:

- non-homogeneous Poisson-process EV arrival-intensity models;
- active-session / future-session probabilistic generation;
- conditional diffusion, TFT/quantile, Copula and meta-Informer EV load forecasting;
- horizon- and regime-aware expert systems.

Therefore generic future-arrival modeling, probabilistic forecasting, Transformer replacement, or horizon routing cannot by itself define the next scientific contribution.

Before changing model class, first test whether the current legal issue-time data already contain an omitted signal for the dominant long-horizon arrival component.

## 3. Unresolved information channel left by S1/P1

The frozen S1 arrival branch uses only M2:

- 24 h station-current history and masks;
- issue quarter-hour/day-of-week/weekend;
- current connected-session count;
- current active-charging-session count;
- station current / observed ratio;
- pilot sum / mean.

P1-A also explicitly restricted future-arrival prediction to frozen M2.

However canonical M3 contains legal issue-time summaries of active-session state, including:

```text
requested_departure_minutes_from_issue
known_kwh_requested
elapsed_connection_s
current/recent current
current pilot
cumulative current
```

No previous formal test isolated whether the **requested-departure distribution of sessions already connected at issue time** adds predictive information for future-arrival contribution.

This matters because planned departure state is available at issue time for claimed sessions and can characterize near-future station turnover. The test is predictive, not causal: a useful signal need not imply that connector release physically causes every subsequent arrival.

## 4. Selected next probe: R7-C0

R7-C0 asks:

> Does adding only the current-session requested-departure distribution to the frozen M2 arrival predictor yield stable OOS improvement in future-arrival contribution, and does that component improvement survive recombination into total station-load forecasts?

This is intentionally narrower than “use full M3” and narrower than “train a better model.”

Three matched arms are required:

### Base-M2

The accepted frozen S1 arrival branch. No retraining is needed for the reference predictions.

### Departure-Aug — primary scientific arm

Use canonical M2 plus exactly the ten existing M3 pooled statistics for:

```text
requested_departure_minutes_from_issue
```

The ten statistics are the frozen canonical pool:

```text
count, sum, mean, std, minimum, maximum, p25, p50, p75, missing_count
```

Append the same fixed nullable missing indicators used by the canonical encoder. No other M3 field is allowed in the primary arm.

Expected encoded width:

```text
M2 encoded width            204
requested-departure raw      10
requested-departure indicators 7
Departure-Aug encoded width 221
```

### Full-M3 — secondary attribution arm

Use complete canonical M3 (391 encoded dimensions) with the same learner and the same M2 parameterization. This arm is secondary only. It cannot rescue a failed Departure-Aug result or justify a larger M3 backbone.

## 5. Matched learner control

All newly fitted arms use:

- the same HistGradientBoostingRegressor class already used by the development experts;
- the exact frozen **M2 selected hyperparameters for the same horizon**;
- the same same-month daily rolling-origin fit/test rows as S1;
- the exact S1 future-arrival component target;
- no retuning, feature selection, clipping, calibration or post-hoc nonnegative projection.

Using the M2 parameter set for both Departure-Aug and Full-M3 is deliberate: the scientific variable is the added issue-time information, not an architecture/hyperparameter change.

## 6. Required total-forecast attribution

Component accuracy alone is insufficient because R6 showed material cross-branch error cancellation.

For each candidate arrival forecast A_hat_candidate, also form:

```text
Total_candidate = frozen_S1_existing_prediction + A_hat_candidate
```

Evaluate both:

1. future-arrival component MAE/RMSE/WAPE;
2. recombined total MAE/RMSE/WAPE.

Strong total references remain frozen S1 and Equal on identical rows.

## 7. Novelty boundary

R7-C0 is a mechanism probe, not the final novelty claim.

Do not claim:

- first use of requested departure information;
- first modeling of EV departures;
- first active-session-aware station forecast;
- first capacity-aware EV forecast.

Prior work already uses departure information for charging demand/scheduling, and SessionFlow explicitly treats origin-active sessions and finite connector resources. If R7 passes, later novelty still requires a separate method review.

## 8. Why this probe is preferred over a generic learner search

If Departure-Aug fails, changing HGB to Transformer/CatBoost/MLP does not answer the information question and would again confound representation with learner capacity.

If Departure-Aug passes, the project gains a specific, issue-time-observable mechanism tied to the R6 long-horizon bottleneck. A later model can then be designed around demonstrated signal rather than architecture search.

If only Full-M3 improves, current-session state contains some arrival-relevant information but planned departure state is not isolated as the mechanism; no departure-specific claim is allowed.

## 9. Execution policy

Before any R7 real-data fit:

1. freeze the exact protocol and PASS/MIXED/STOP rules;
2. implement feature-subset construction, rolling fit, cache identity and aggregation in one code PR;
3. do local targeted tests first;
4. use GitHub Actions only once for the final code PR if possible;
5. release one pinned launcher after the reviewed CI-passed head exists;
6. run exactly one development-only R7-C0 experiment;
7. archive results without opening final holdout.

Pure documentation updates do not require full GitHub Actions under the current conservation policy.
