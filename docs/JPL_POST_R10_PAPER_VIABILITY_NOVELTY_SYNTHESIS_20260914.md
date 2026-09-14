# Post-R10 paper-viability and novelty synthesis

Date: 2026-09-14  
Status: **`CONDITIONAL_MECHANISM_PAPER_VIABILITY`**  
Scope: frozen JPL development evidence + current nearest-neighbor literature review. This document authorizes **no model fit and no final-holdout access**.

## 1. Executive decision

The current line is **not strong enough to be presented as a new forecasting-algorithm paper**. The accepted R7 `Departure-Aug / TotalDeparture` arm is deliberately simple, its pooled total-load improvement over S1 is only `+0.5575%`, and R10-R0 formally returned `MIXED_DEVELOPMENT_ROBUSTNESS` because local-day wins versus S1 were `26/55 = 47.27%`, below the frozen 50% READY threshold.

However, the line should **not be archived yet**. The combined S1/R4/R6/R7/R7-D1/R8/R9/R10 evidence supports a narrower problem/mechanism contribution that is more defensible than the R7 feature increment alone:

> **The dominant source of short-term charging-station forecast error changes with forecast horizon. Under the frozen JPL decomposition, evolution of sessions already connected at issue time is the larger removable error source at 15–30 min, whereas future-arrival uncertainty becomes the larger removable source at 60–240 min. Numerical requested-departure timing from currently connected sessions carries incremental issue-time predictive information for the future-arrival component beyond declaration availability alone, but the resulting total-load gain is bounded and not a majority-day improvement versus S1.**

This is a candidate **forecastability / information-availability result**, not a claim that existing/future-session decomposition, departure modeling, or probabilistic EV forecasting is new.

Formal viability summary:

```text
new forecasting-algorithm paper          NOT SUPPORTED AS-IS
problem/mechanism paper                  CONDITIONAL
independent generalization               NOT ESTABLISHED
final-holdout readiness                  NOT ESTABLISHED (R10 = MIXED)
current method line                      FROZEN
next scientific need                     independent mechanism replication
```

## 2. What the frozen JPL evidence actually establishes

### 2.1 Horizon-dependent composition

The offline S1 decomposition shows the fraction of future station current attributable to issue-time connected sessions falls strongly with horizon:

```text
horizon      existing-session share    future-arrival share
15 min              97.38%                   2.62%
30 min              90.61%                   9.39%
60 min              78.10%                  21.90%
120 min             56.52%                  43.48%
240 min             26.21%                  73.79%
```

This by itself is descriptive and is not a novelty claim.

### 2.2 Legal issue-time state is informative but not sufficient

R4-I0 is `MIXED_STATE_ALIASING_SIGNAL`. Supported close M3 states still have substantial future divergence (`normalized M3 divergence = 0.297930`). M3 improves the frozen analog metric relative to M2 by `8.19%` pooled and is positive in `19/20` month×horizon cells, but M3 does not stably beat the current-load Level-Control. Thus richer issue-time session state contains incremental information, while substantial outcome ambiguity remains.

### 2.3 The dominant removable error source crosses over between 30 and 60 min

R6-O0 is zero-fit and uses the frozen S1 component truths only as offline oracles. The oracle replacement gains are:

```text
horizon      G_existing (A)      G_arrival (A)      larger source
15 min           4.63784             1.15816         existing
30 min           5.69349             4.38389         existing
60 min           6.12154            12.10481         arrival
120 min          6.80800            23.16122         arrival
240 min          4.18779            38.21044         arrival
```

The same ordering is cross-month stable at the decisive horizons: existing > arrival in `4/4` months at 15 min and `3/4` at 30 min; arrival > existing in `4/4` months at each of 60/120/240 min.

The paper-level value of R6 is therefore not the generic use of an oracle ablation. It is the quantitative identification of a forecast-horizon-dependent error-source transition under a fixed online information boundary.

### 2.4 Requested-departure timing is a bounded legal information channel

R7-D1 separates metadata availability from numerical timing information:

```text
Availability vs Base-M2 arrival MAE        +0.2138%
Departure-Aug vs Availability arrival MAE   +1.3318%
Departure-Aug vs Base-M2 arrival MAE        +1.5428%
TotalDeparture vs S1 total MAE              +0.5575%
```

The timing increment is positive in 3/5 horizons and 3/4 months, strongest at 60 min, and reverses in October. This supports the bounded statement that numerical requested-departure timing contains incremental predictive information beyond missingness/availability. It does not support a causal connector-release or future-arrival claim.

### 2.5 More explicit departure engineering did not improve stability

R8 and R9 tested more explicit horizon-aligned / forecast-grid encodings and failed their frozen stability gates. `STOP_DEPARTURE_REPRESENTATION_REFINEMENT` remains binding. The project must not reinterpret those failures as an invitation to tune another departure representation.

### 2.6 R10 establishes reproducibility of the small mean gain, not broad daily superiority

R10 exact replay passed. TotalDeparture remains better than S1 and Equal after deleting any one development month and after deleting any one forecast horizon:

```text
leave-one-month-out wins     4/4 vs S1; 4/4 vs Equal
leave-one-horizon-out wins   5/5 vs S1; 5/5 vs Equal
```

But versus S1:

```text
local-day wins               26/55 = 47.27%
mean daily delta             -0.16134 A
median daily delta           +0.05723 A
top-5 positive-gain share     60.66%
```

Therefore the correct claim is a reproducible average development-stage signal with limited day-level breadth.

## 3. Nearest-neighbor literature: what is already occupied

The literature review was performed to subtract existing concepts before defining any contribution.

### 3.1 “Forecast accuracy depends on horizon” is already established

Unterluggauer et al., *IET Electrical Systems in Transportation*, 2021, DOI `10.1049/els2.12028`, compared 1 h and 24 h multi-step EV charging-site forecasts and reported substantially better accuracy at the shorter horizon. Therefore this project cannot claim novelty merely from horizon-dependent forecast accuracy.

### 3.2 Current versus future EV/session uncertainty is not new as a conceptual split

Recent EV scheduling work explicitly distinguishes currently connected EVs, whose parameters are known at decision time, from future arrivals that are not yet connected and are more uncertain. For example, the 2025 PATCH framework (`10.1080/15568318.2025.2500550`) is built around asynchronous arrivals/departures and heterogeneous horizons. The distinction between present and future populations is therefore not itself novel.

### 3.3 Active-session information in station-level forecasting is prior art

Cambronne, Bobick, Zeng and Moura, *Joint Price and Power MPC for Peak Power Reduction at Workplace EV Charging Stations* (arXiv:2507.12703; ACC 2026), uses a station-level forecasting codebase that can aggregate future power profiles of all currently active sessions. Thus “use active-session information for station forecasting” is unavailable as a novelty claim.

### 3.4 Existing/future-session decomposition plus probabilistic session generation is directly occupied

SessionFlow, *Session-Replayable Probabilistic EV Charging Power Forecasting from Partially Observed Sessions* (SSRN 7316940, posted 20 Aug 2026), explicitly continues origin-active sessions and generates future served sessions under finite connector resources, then aggregates both into station-power scenarios. Therefore this project must not claim first existing/future-session decomposition, first session replay, or first probabilistic future-arrival modeling.

### 3.5 Generic decomposition/fusion is also occupied

Ullah et al., *IEEE Transactions on Smart Grid*, 2026, DOI `10.1109/TSG.2026.3677496`, decomposes EV load and trains component-specific learners followed by a stacked meta-learner, including evaluation on ACN. A learned component reconciler added now solely to improve R7 total MAE would be a weak post-hoc rescue rather than a clean novelty.

### 3.6 Requested departure is an established EV datum

ACN-Data explicitly provides user-entered `requestedDeparture` and `kWhRequested`, and prior ACN studies use requested departure for profiling, scheduling and charging optimization. Hence “use requested departure information” is not novel by itself.

The narrower point not directly reproduced in the targeted review is the combination of:

1. an online station-load decomposition at forecast issue time;
2. a quantitative horizon-by-horizon crossover in the dominant removable error source;
3. attribution showing current-session numerical requested-departure timing adds information specifically to the future-arrival component beyond declaration availability;
4. frozen negative results showing increasingly explicit departure encodings do not automatically improve robustness.

This is **negative search evidence only**. It is not proof that no prior paper has made the same observation.

## 4. Novelty judgment after subtraction

### Strongest remaining contribution: problem characterization

The best remaining contribution is not a model architecture. It is a structured empirical explanation of *why* a single deterministic short-term station forecaster becomes difficult as the horizon expands: the dominant error source moves from evolution of observed sessions toward the unobserved future-arrival population.

This is materially narrower than generic “longer horizons are harder” and different from simply proposing a model that generates future sessions.

### Secondary contribution: issue-time information attribution

R7/R7-D1 provides a concrete legal signal linking current-session state to the later-arrival component: requested-departure timing distribution. This is useful as evidence that the long-horizon arrival problem is not completely disconnected from current state. Its contribution is empirical attribution, not a new feature family.

### Weak contribution: forecasting method

`Departure-Aug` is HGB with a fixed ten-stat requested-departure pool. Its total-load gain over S1 is small and R10 is MIXED. It should not be marketed as a major new forecasting algorithm.

## 5. Evidence sufficiency and the main unresolved weakness

The JPL development evidence is unusually well audited for an exploratory line:

- four development months (`2019-01/04/07/10`);
- five fixed horizons (`15/30/60/120/240 min`);
- daily rolling OOS evaluation;
- 20 month×horizon cells;
- matched component and total-load comparisons;
- zero-fit R4/R6/R10 diagnostics;
- R7-D1 attribution control;
- frozen STOP decisions for R8/R9;
- leave-one-month/horizon robustness and deterministic bootstrap in R10.

But this does **not** create independent confirmation. The same four development months have supported a long adaptive sequence from S1 through R10. R10 is a rigorous read-only audit of that development evidence, not a new untouched validation set. The final JPL holdout `2019-03/06/09/12` remains sealed and R10 did not authorize its release.

Therefore:

> A paper claiming general station-level superiority or final generalization is not currently supportable.

A development-only manuscript could be written only as a bounded case study / mechanism analysis. For a stronger paper, an independent replication is the most valuable next evidence.

## 6. Recommended next scientific stage

### `R11-V0`: independent mechanism-replication feasibility and protocol design

R11-V0 is **not a model rescue** and is not yet authorized to run. Its purpose is to determine whether the core mechanism evidence can be replicated on a source that has not participated in the JPL development chain.

The repository-tracked formal configurations are JPL-specific (`acn_jpl_*`). No Caltech or Office1 configuration is currently recorded in the main tree. The official ACN schema exposes the required `requestedDeparture`, pilot and charging-current fields for ACN sites, while noting that user-input fields are not present for every session. This makes another ACN site a plausible replication source, but not automatically an eligible one.

Before selecting a site or downloading data, R11-V0 must freeze an **unused-data audit** that answers:

1. Has the candidate site/source ever been used in this repository, local experiments, exploratory notebooks or prior decisions?
2. Are `chargingCurrent`, `pilotSignal`, `requestedDeparture` and the session timestamps available at sufficient coverage under the same issue-time legality rules?
3. Can the existing/future decomposition be reconstructed without changing the target definition?
4. Can the five horizons and 15-min grid be retained without favorable filtering?
5. Can the same evaluation logic be applied without tuning to the replication outcome?

Only after these questions are resolved should a separate preregistered replication protocol be frozen.

### What a later replication should test

The minimal scientific replication should target the evidence chain, not the exact JPL score:

- direction of existing-session and future-arrival composition with horizon;
- R6-style dominant oracle-error-source crossover;
- incremental requested-departure timing information versus availability-only control;
- aggregate stability across predefined time blocks/horizons.

It should not optimize the external site to make R7 pass, and it should not modify the frozen JPL R10 decision.

### Decisive consequence

```text
independent replication supports the same mechanism
    -> proceed to manuscript design with cross-source evidence

independent replication contradicts the mechanism materially
    -> archive the current method line; do not rescue with another backbone
```

## 7. Final claim boundary

Allowed, subject to independent replication:

- horizon-dependent shift in the dominant forecast-error source under issue-time information;
- bounded predictive value of current-session requested-departure timing for the future-arrival component;
- empirical consequences for how short- and longer-horizon charging-station forecasting should be evaluated.

Not allowed:

- first active-session-aware EV forecast;
- first existing/future-session decomposition;
- first use of departure information;
- first probabilistic EV charging forecast;
- causal claim that requested departure releases connectors or causes future arrivals;
- final generalization from the current four JPL development months;
- claim that R7 is READY for the sealed JPL final holdout.

## 8. Literature identities used in this synthesis

- Unterluggauer, T., Rauma, K., Järventausta, P., Rehtanz, C. (2021). *Short-term load forecasting at electric vehicle charging sites using a multivariate multi-step long short-term memory: A case study from Finland*. IET Electrical Systems in Transportation. DOI: `10.1049/els2.12028`.
- Kreft, M., Brudermueller, T., Fleisch, E., Staake, T. (2024). *Predictability of electric vehicle charging: Explaining extensive user behavior-specific heterogeneity*. Applied Energy 370, 123544. DOI: `10.1016/j.apenergy.2024.123544`.
- Liu, X., Ji, Z. (2025). *Real-time charging scheduling of aggregated electric vehicles: A novel PATCH framework addressing asynchronous plug-in dynamics*. International Journal of Sustainable Transportation. DOI: `10.1080/15568318.2025.2500550`.
- Cambronne, T., Bobick, S., Zeng, W., Moura, S. (2025/2026). *Joint Price and Power MPC for Peak Power Reduction at Workplace EV Charging Stations*. arXiv:2507.12703; ACC 2026.
- Ullah, S. S. et al. (2026). *Decomposition and Stacked Meta-Learning for Short-Term Electric Vehicle Load Forecasting*. IEEE Transactions on Smart Grid 17(5), 4426–4437. DOI: `10.1109/TSG.2026.3677496`.
- Guo, F., Guo, X., Michael, S. (2026). *Session-Replayable Probabilistic EV Charging Power Forecasting from Partially Observed Sessions*. SSRN 7316940. DOI: `10.2139/ssrn.7316940`.
- ACN-Data official dataset/schema: `https://ev.caltech.edu/dataset`.

## 9. Freeze decision

The contribution synthesis is complete with decision:

```text
CONDITIONAL_MECHANISM_PAPER_VIABILITY
```

No new forecasting architecture is selected. Final JPL holdout remains sealed. The only selected next activity is **R11-V0 unused-source/site feasibility audit and preregistered independent mechanism-replication protocol design**. No data acquisition or compute is authorized by this synthesis alone.
