# JPL/ACN post-P1 method screening

Date: 2026-09-12

Status: **research screening only**. This document does not authorize a new model fit, does not change the frozen P1 `STOP_MECHANISM_ROUTE` decision, and does not authorize final-holdout access.

## 1. Evidence that the next method must explain

The post-P1 method search starts from the accepted development evidence rather than from a preferred neural architecture.

1. True load composition shifts strongly with forecast horizon: existing-session share falls from 97.38% at 15 min to 26.21% at 240 min, while future-arrival share rises from 2.62% to 73.79%.
2. S1 target decomposition has some pooled signal but fails cross-month stability and is frozen `MIXED_STRUCTURED_SIGNAL`.
3. P1 continuation×mark and Poisson count×mark both fail their component criteria; the combined route is frozen `STOP_MECHANISM_ROUTE`.
4. The strongest reproducible diagnostic evidence is horizon × turnover × local-hour structure, including 30/60 min mixed-turnover weak regions and repeated 07:00→09:00 sign reversals.
5. The P1-A post-mortem shows severe OOS extreme-tail fragility of the fixed Poisson route; however Probe E independently fails, so P1 cannot be rescued by fixing only the arrival branch.

Therefore the next method should **not** be designed as a more powerful version of P1. It should revisit how the legal issue-time session population is represented for aggregate forecasting.

## 2. Internal representation gap: what M3 currently discards

The frozen M3 feature tier contains 11 legal issue-time session fields:

- elapsed connection time;
- elapsed charging-time proxy;
- current current;
- recent mean current;
- recent peak current;
- recent-current observed ratio;
- cumulative current Ah;
- cumulative-current observed ratio;
- current pilot;
- requested departure minutes from issue;
- known requested kWh.

For each field, M3 independently stores the same 10 marginal pool statistics:

```text
count, sum, mean, std, min, max, p25, p50, p75, missing_count
```

This gives 110 M3 session-pool features, but each field is pooled separately. Consequently M3 does not preserve the **joint per-session state**. For example, two issue times can have almost identical marginal distributions of elapsed time, current and requested departure while differing in which high-current sessions are old/young or near/far from requested departure. Such joint alignment is directly relevant to session turnover.

P1-E takes the opposite extreme: it models sessions independently and sums expected future contributions. It therefore preserves each session tuple but does not learn interactions across the simultaneously connected session population, and its decomposed future-contribution target failed empirically.

This leaves a specific open representation question between M3 and P1:

> Can the current connected-session population be represented as an unordered set of joint session states and used directly for aggregate multi-horizon load forecasting, without predicting per-session future contributions or future-arrival identities?

## 3. 2026 literature / open-source collision check

### 3.1 Direct EV charging forecasting already occupies generic architecture claims

- **TimeMoE-LoRA for EV charging load forecasting**, IEEE Access 2026, DOI `10.1109/ACCESS.2026.3697488`, already adapts sparse Time-MoE to direct multi-horizon EV charging-load forecasting. Therefore “MoE for EV load”, “time-series foundation model for EV load”, and “direct multi-horizon MoE” are not available novelty claims.
- **CUP-EV**, Information Sciences 2026, DOI `10.1016/j.ins.2026.123681`, already combines DLinear + nonlinear residual modeling for lightweight probabilistic multi-horizon EV forecasting. Therefore generic residual hybridization / multi-horizon probabilistic output is also crowded.
- **TriCast**, Pattern Recognition Letters 2026, DOI `10.1016/j.patrec.2026.04.028`, already targets causal multi-horizon EV demand forecasting through spatial, temporal and economic modalities.
- 2026 EV studies also cover TFT, multi-scale Transformer, XGBoost–BiLSTM stacking, graph/recurrent regional forecasting and multimodal/LLM-MoE variants. Generic backbone replacement is therefore a weak contribution route.

### 3.2 Horizon-aware routing is already explicitly published

- **Regime-Conditioned Horizon-Aware Mixture-of-Experts (RCHA-MOE)**, IEEE Access 2026, DOI `10.1109/ACCESS.2026.3695762`, uses a Horizon-Conditioned Regime Gate that produces step-specific expert weights from the input regime.
- **FAME**, arXiv:2606.08896, learns forecastability fingerprints and sparse expert suitability routing.
- **MoHETS**, arXiv:2601.21866, uses heterogeneous forecasting experts.
- FreqMoE, M2FMoE and related 2025–2026 work cover frequency/exreme-adaptive MoE designs.

Therefore “horizon-specific gate”, “regime-conditioned MoE”, “heterogeneous expert routing” or “forecastability-aware routing” cannot be the central novelty claim here.

### 3.3 Session-aware / generative forecasting is also adjacent

- **Session-Replayable Probabilistic EV Charging Power Forecasting from Partially Observed Sessions (SessionFlow)**, SSRN posted 20 Aug 2026, explicitly continues origin-active sessions, generates future served sessions and reconstructs station power. This further confirms that existing-session + future-session decomposition/generation itself is not novel.
- ACN Portal already contains mature stochastic charging-session generation infrastructure.

Hence a new method should not claim novelty from “using current sessions”, “separating future arrivals”, “survival”, or “TPP” alone.

### 3.4 Set representation boundary

General set modeling is mature:
- Deep Sets (2017);
- Set Transformer (ICML 2019; official PyTorch implementation `juho-lee/set_transformer`);
- recent work studies permutation-invariant temporal/event sets and channel-permutation-invariant forecasting.

The **set architecture itself is not novel**.

However, in the targeted search completed on 2026-09-12, no directly matching EV charging-load forecasting work was found that uses the **currently connected session population as a permutation-invariant set of issue-time session states, queried/conditioned by forecast horizon, to directly forecast aggregate station load**. This is a search result, not proof of absence; a formal novelty claim would require a broader literature review before paper submission.

## 4. Candidate ranking after P1

### Rank 1 — horizon-conditioned connected-session set representation

**Scientific idea:** preserve the connected sessions as an unordered population of joint state tuples, combine that representation with M2 station history/calendar, and condition the aggregate prediction on the requested horizon.

What makes this different from prior stages:
- vs M3: retains joint within-session state relationships rather than independent marginal pools;
- vs P1-E: does not predict each session’s future contribution and sum them independently;
- vs P1-A/S1: does not explicitly forecast future-arrival contribution or future session identity;
- vs generic MoE: expert routing is not required for the core hypothesis;
- vs SessionFlow: does not claim session-replayable generative forecasting.

Most defensible scientific question:

> **Does preserving the joint issue-time state of the currently connected session population as a permutation-invariant set reveal horizon-dependent predictive information that fixed marginal pooling discards, and can that information stably improve aggregate charging-current forecasts without explicitly predicting future session identities or decomposed future contributions?**

This question follows directly from the observed turnover evidence and from a concrete limitation of M3.

### Rank 2 — horizon-conditioned expert routing

Potentially useful as a later mechanism **after** a session-population representation demonstrates signal. It is not recommended as the immediate core route because RCHA-MOE, FAME and other 2026 work already occupy generic horizon/regime/expert-routing claims.

### Rank 3 — probabilistic/session-generative models

CUP-EV, SessionFlow, Time-MoE and existing arrival/survival literature make this area crowded. It may later provide baselines or uncertainty extensions, but it should not be used to rescue P1 or become the immediate novelty route.

## 5. Recommended next probe before a full Set Transformer

Do **not** jump directly to a large Set Transformer. First establish whether the missing *joint session-population representation* has development signal.

Recommended next stage: a **low-capacity session-set representation probe** with two deliberately matched representations:

1. `Pool-control`: legal M2 context + the existing frozen M3 marginal session pools, passed through a small fixed-capacity nonlinear head.
2. `Set-probe`: the same legal M2 context + a permutation-invariant encoder over raw issue-time connected-session tuples, with a parameter budget comparable to the pool-control.

The target remains aggregate `station_current_mean_a`; there is no existing/arrival decomposition. Five horizons remain 15/30/60/120/240 min. The set-probe should initially use a minimal Deep-Sets-style encoder rather than full self-attention so that the first experiment tests representation, not model capacity.

If and only if the set representation shows stable signal, a later model can introduce horizon-query attention / Set Transformer interactions to test whether explicit session-session relations improve beyond simple permutation-invariant pooling.

## 6. Design constraints for the future protocol

Any implementation protocol derived from this screening should freeze before model fitting:

- development months remain 2019-01/04/07/10;
- final holdout remains sealed;
- only issue-time legal predictors;
- no realized future arrival share/composition as predictor or gate;
- no future session identity;
- no removal of pathological P1 rows to make a new method look better;
- direct aggregate target, not P1 component targets;
- explicit matched-capacity pool-vs-set ablation;
- comparison against M2/M3/Equal/S1 on identical OOS rows;
- horizon- and month-stability requirements preregistered;
- no test-selected clipping/calibration;
- bounded/stable output design should be structural, not chosen after seeing test errors.

## 7. Open-source engineering references

Potential references, not novelty claims:

| Project | Role | Notes |
| --- | --- | --- |
| `juho-lee/set_transformer` | official Set Transformer PyTorch implementation | architectural reference; old dependency stack, likely reimplement minimal blocks rather than copy wholesale |
| `manzilzaheer/DeepSets` | original Deep Sets code | conceptual/reference baseline |
| `Time-MoE/Time-MoE` | official Time-MoE | comparison / novelty boundary |
| `hit636/FAME` | forecastability-aware expert routing | later routing reference only |
| `Waqar2193/CUP-EV-Cost-and-Uncertainty-aware-Probabilistic-EV-Energy-Forecasting` | lightweight EV multi-horizon probabilistic model | benchmark / robust residual-design reference |
| `zach401/acnportal` | ACN session/data semantics | infrastructure and physical-consistency reference |

Any actual code reuse still requires license and third-party dependency review.

## 8. Screening decision

**Recommended direction:** connected-session set representation for direct aggregate multi-horizon forecasting.

**Not yet authorized:** model implementation or local experiment. The next repository action should be a separate frozen protocol defining the exact representation probe, matched-capacity controls and PASS/MIXED/STOP criteria. Only after that protocol is reviewed should code/CI/local execution begin.
