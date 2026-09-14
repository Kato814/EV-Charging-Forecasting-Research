# Post-R10 method screening — stop result-driven rescue and freeze the current method line

Date: 2026-09-14  
Status: scientific-route screening only; **no new experiment is authorized by this document**.

## 1. Frozen starting point

R10-R0 is COMPLETE with decision `MIXED_DEVELOPMENT_ROBUSTNESS`.

Accepted development-stage candidate remains R7 `Departure-Aug / TotalDeparture`:

```text
TotalDeparture MAE                  28.4354542901 A
S1 MAE                              28.5948815297 A
Equal MAE                           28.9172859886 A
pooled improvement vs S1            +0.5575%
pooled improvement vs Equal         +1.6662%
original month wins vs S1/Equal     3/4 / 3/4
original horizon wins vs S1/Equal   4/5 / 4/5
leave-one-month-out wins            4/4 / 4/4
leave-one-horizon-out wins          5/5 / 5/5
local-day win rate                  47.27% vs S1; 56.36% vs Equal
```

R10 is MIXED only because the frozen READY rule requires `>=50%` local-day wins against both references and the observed rate versus S1 is `26/55 = 47.27%`. This result must not be converted into a tuning target.

R9 `STOP_DEPARTURE_REPRESENTATION_REFINEMENT` remains binding. Final holdout `2019-03/06/09/12` remains sealed.

## 2. What R10 changes scientifically

R10 rules out two opposite readings.

### Not a fragile one-cell gain

The candidate remains better than both S1 and Equal after deleting any one development month and after deleting any one forecast horizon. The pooled signal is therefore not explained by a single favorable month or horizon.

### Not broad enough for holdout readiness

Relative to S1, only 26 of 55 local days improve, the median daily delta is slightly unfavorable (`+0.05723 A`), and the five largest favorable days contribute about 60.66% of total positive daily gain.

The correct interpretation is therefore bounded:

> requested-departure timing carries reproducible incremental predictive information, but its point-forecast total-load benefit is not sufficiently broad across development days to justify final-holdout access under the frozen readiness rule.

## 3. Evidence chain now established

The current line has already answered several narrower questions:

1. **Horizon-dependent composition:** existing-session contribution falls strongly with horizon while future-arrival contribution grows.
2. **Information sufficiency:** R4 shows substantial future divergence remains among similar legal issue-time states; richer M3 state is informative relative to M2 but not stably sufficient relative to current-load continuity.
3. **Component bottleneck:** R6 shows existing-session error is the larger removable source at 15–30 min, while future-arrival error dominates at 60–240 min in all four development months.
4. **Legal incremental signal:** R7 isolates current-session requested-departure timing as an issue-time-observable signal for the future-arrival component, beyond declaration availability alone.
5. **Representation closure:** R8/R9 show more explicit horizon-aligned and forecast-grid departure encodings do not provide a stable replacement for the generic R7 departure pool.
6. **Robustness limit:** R10 shows the small total-load gain survives month/horizon deletion but is not a majority-day win versus S1.

This chain is now more informative than another architecture comparison.

## 4. Candidate routes screened after R10

### 4.1 Optimize specifically for the R10 day-win threshold

**Rejected.**

Examples include reweighting difficult days, month-specific tuning, robust loss selected after seeing R10, or any rule designed to move `26/55` above `28/55`. This would convert a preregistered audit into a post-hoc optimization target and invalidate the purpose of R10.

### 4.2 Further requested-departure engineering or routing

**Rejected by frozen route closure.**

New bins, ratios, weights, embeddings, horizon/month routing, gates and MoE are R9/R10 rescue paths and remain prohibited.

### 4.3 Generic probabilistic EV-load forecasting

**Scientifically relevant but rejected as the immediate novelty core.**

The literature is already crowded with EV-specific probabilistic multi-horizon forecasting, diffusion/quantile approaches, cost-aware probabilistic forecasting and online probabilistic adaptation. Recent 2026 examples include CUP-EV, meta-learning-enhanced Informer probabilistic forecasting, and behavior-guided online probabilistic forecasting.

Most importantly, `Session-Replayable Probabilistic EV Charging Power Forecasting from Partially Observed Sessions` (SessionFlow, posted 20 Aug 2026) explicitly separates origin-active continuation from future served sessions under finite connector resources and produces probabilistic station-power paths. Therefore neither “existing + future-session decomposition” nor “probabilistic future-arrival modeling” is a clean novelty claim for this project.

A probabilistic formulation could still be useful later, but only if a distinct problem and contribution survive a new nearest-neighbor review. R10 does not authorize such a model.

### 4.4 Component-specific fusion / reconciliation

**Rejected as an immediate core method.**

R6/R9 show component error interaction is real, but generic component decomposition followed by learned fusion is already represented in recent EV-load forecasting work; for example, `Decomposition and Stacked Meta-Learning for Short-Term Electric Vehicle Load Forecasting` (IEEE Transactions on Smart Grid, 2026) uses component-specific learners and a meta-learner for fusion across multiple EV datasets including ACN.

Using a learned blender merely because R7 improves the arrival component more than the recombined total would also be a post-hoc rescue unless a distinct, preregistered mechanism is first established.

### 4.5 Add standard known-future covariates

**Not selected as a novelty core.**

Weather, traffic, tariffs, calendar/context features and arrival-rate covariates are established in EV charging forecasting. They can be engineering inputs in another study, but the current evidence does not justify treating their addition as the central scientific contribution.

## 5. Selected next action

No new forecasting model is selected after R10.

The current method line enters a **method-freeze / contribution-synthesis stage**. The next task is to determine whether the existing evidence chain is strong and novel enough for a paper centered on the forecasting problem rather than on a new backbone.

The candidate contribution to review is:

> **horizon-dependent observability transition in online charging-station forecasting:** short horizons are governed mainly by the evolution of sessions already connected at forecast issue time, whereas future-arrival uncertainty becomes the dominant removable error source from 60 min onward; issue-time requested-departure timing provides a measurable but bounded incremental signal for that long-horizon arrival component.

This framing deliberately does **not** claim first session decomposition, first departure modeling, first probabilistic EV forecasting, or first active-session-aware prediction.

## 6. Paper-viability questions to resolve before any new compute

A contribution synthesis must answer all of the following using frozen evidence and current literature:

1. **Problem novelty:** Is the horizon-dependent observability transition itself sufficiently distinct from SessionFlow, generic session-based forecasting and existing predictability studies?
2. **Method contribution:** Is R7 `Departure-Aug` more than a feature ablation when presented together with the R4/R6 mechanism evidence, or is the method contribution too weak for the target venue?
3. **Evidence sufficiency:** Can a development-only paper be defended with four-month rolling OOS, 20 month×horizon cells, R6 oracle analysis and R10 robustness, while explicitly stating that final holdout remains sealed?
4. **Claim boundary:** Can the paper make a useful forecasting claim without converting predictive requested-departure information into a causal connector-release claim?
5. **Falsification:** If the nearest-neighbor review shows the same horizon-dependent active/future-session mechanism has already been demonstrated, or if the contribution would reduce to “add requested departure as a feature,” this line should be archived rather than rescued.

## 7. Execution boundary

Until the contribution synthesis is complete:

- do not rerun R10;
- do not open final holdout;
- do not refit/tune R7 or references;
- do not optimize day-win rate;
- do not introduce another departure representation;
- do not build a probabilistic model, gate, MoE, router or learned reconciliation layer;
- do not create another local launcher.

The next output should be a paper-viability / novelty synthesis document, not a status JSON.
