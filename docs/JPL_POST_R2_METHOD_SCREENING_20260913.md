# Post-R2 method screening — problem-first selection

Date: 2026-09-13

## 1. Accepted starting point

The formal R2 higher-order session-set probe is COMPLETE and frozen `STOP_HIGHER_ORDER_SET_ROUTE`.

Accepted development evidence now reads:

- S1 structured existing/arrival decomposition: `MIXED_STRUCTURED_SIGNAL`;
- P1 explicit continuation/arrival mechanism: `STOP_MECHANISM_ROUTE`;
- R1 low-order same-session joint summaries: `MIXED_JOINT_STATE_SIGNAL`;
- R2 nonlinear higher-order same-session set: `STOP_HIGHER_ORDER_SET_ROUTE`.

R2-Joint pooled MAE was 33.566025 A versus 33.329417 A for the marginal-preserving R2-Permuted control. Joint won only 2/5 horizons and 1/4 development months. The frozen STOP rule therefore closes the current higher-order session-set route. No Set Transformer, attention, MoE, larger Deep Sets, pair engineering or result-dependent session-feature rescue is authorized.

Final holdout 2019-03/06/09/12 remains sealed.

## 2. Candidate classes rejected after R2

### 2.1 Larger session-set / trajectory backbone

Rejected as immediate next core.

Reason:

- R2 directly tested whether true same-session alignment contains stable predictive value beyond exactly matched field marginals and failed the preregistered gate;
- earlier M4 work already exposed causal current/pilot trajectory summaries and was not retained as the stable main route;
- 2025–2026 literature now directly covers partial charging-profile prediction and session-replayable active-session continuation.

Deep Sets, Set Transformer, Transformer, LSTM, ChargeFormer-style trajectory encoders and SessionFlow-style session replay are therefore not new scientific questions here.

### 2.2 Horizon/time-of-day expert gating

Rejected as core novelty.

R1 diagnostics show real 07:00/09:00 and horizon-conditioned reversals, but 2026 RCHA-MOE, FAME and related multi-expert work already make horizon-/forecastability-aware routing a crowded method class. A gate may later be an engineering device only after a distinct mechanism is established.

### 2.3 Generic residual/ramp correction

Rejected as core novelty.

CUP-EV and 2026 forecast-time-safe residual correction already cover residual, probabilistic and ramp/peak-oriented correction. Recasting the current task as another residual network would not answer why session-aware routes failed.

### 2.4 Historical arrival/departure climatology

Deprioritized.

Arrival/departure distributions, mixture arrival rates, occupancy and queueing conversion to EV load have mature prior art. A nonparametric turnover prior may be useful as a baseline but is too weak as the central research gap.

## 3. Selected post-R2 question: control endogeneity of the observed load

ACN/JPL exposes two distinct causal quantities for active charging sessions:

- measured charging current (`chargingCurrent`);
- EVSE pilot/current limit (`pilotSignal`).

The realized station load is therefore not purely an exogenous user-demand process. It is the electrical response after a charging-control limit has been issued. For one active session, actual current can be below the pilot because the vehicle/BMS is limiting its draw; when actual current is near the pilot, the EVSE/control limit is more likely to be binding.

The key forecasting problem is narrower than generic controlled charging:

> When the future control path is not supplied as a forecast-time input, does the issue-time control-binding state identify a stable change in the forecastability of future realized station current?

This is a target/data-generating-process question, not a request to add another neural backbone.

### Why this question follows from S1/P1/R1/R2

All four routes attempted to improve prediction by representing the charging-session population or its future composition more explicitly. None established a stable route beyond the strong Equal/S1 references.

One plausible reason is that the target mixes at least two sources of uncertainty:

1. user/vehicle charging demand and session turnover;
2. charging-control actions that reshape the realized current.

If future control actions are not known to the forecaster, representation improvements on current sessions can have limited value even when they describe user state accurately.

## 4. Nearest-neighbor / novelty boundary

This screening does **not** claim first use of pilot/control information.

Closest known adjacent work includes:

- ACN-Data / ACN-Sim: exposes measured current, pilot signals and charging-control simulation semantics;
- Berkeley `StationLevelPowerForecasting`: uses planned active-user power profiles when such schedules are available;
- controlled-charging scenario models (e.g. Powell et al., Energy 2022): show charging control can materially reshape aggregate EV load;
- 2026 OCPP forecasting/scheduling frameworks: combine load forecasting with charging control;
- SessionFlow 2026: conditions session-replayable forecasts on finite connector capacity and active/future sessions.

The remaining question under test is different:

> **forecastability under missing future control path** — whether the current pilot-versus-actual operating regime systematically stratifies error of already-frozen station-current forecasts when future pilot actions are not predictors.

Targeted searches on 2026-09-13 did not retrieve a direct EV station-load paper using this exact issue-time control-endogeneity gate. This is negative search evidence only, not proof of absence.

## 5. Why a diagnostic gate comes before a new model

A new control-aware model is unjustified unless the accepted development data first show that control state is related to forecast error in a stable, nontrivial way.

Therefore the next authorized step is **R3-C0**, a no-fit development-only mechanism gate:

- read accepted development M3 issue-time current/pilot rows;
- reuse frozen Equal and S1 OOS predictions;
- derive a target-independent issue-time control-utilization state;
- compare forecast errors after matching on current station-load level;
- make no causal claim from the diagnostic alone;
- do not train, tune, clip, calibrate, gate or access final holdout.

If the gate fails, the control-endogeneity route is closed without a model experiment.

If the gate passes, a separate protocol must define what future control information is realistically observable and what control-conditioned target/model can be evaluated. PASS does not itself authorize such a model or the final holdout.

## 6. Execution policy

No local command is authorized by this screening document alone.

Before any R3-C0 run:

1. freeze the exact control-state definition, matching construction and PASS/MIXED/STOP criteria;
2. implement the read-only diagnostic in an isolated PR;
3. run full CI;
4. release one pinned development-only diagnostic launcher.

Long-run console output policy is simplified from this point forward: stage, month/horizon and coarse completed-count progress only; do not print per-epoch spam.