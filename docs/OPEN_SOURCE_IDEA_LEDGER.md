# Open-source idea ledger

Updated: 2026-09-12.

This ledger tracks external open-source projects and adjacent literature relevant to the JPL/ACN charging-station forecasting research. Inclusion does **not** authorize code import, model fitting, split changes, or final-holdout access. Adoption requires scientific relevance, causal observability and license review.

## 1. Current scientific constraint

S1 remains `MIXED_STRUCTURED_SIGNAL`. P1 is frozen `STOP_MECHANISM_ROUTE`, and its single authorized read-only post-mortem is COMPLETE.

Accepted descriptive evidence remains:
- existing-session share falls from 97.38% at 15 min to 26.21% at 240 min;
- future-arrival share rises from 2.62% to 73.79%;
- 30/60 min mixed-turnover regions show cross-month weak regimes;
- 30/60/120 min near 07:00 are repeatedly weak while 09:00 can reverse direction.

P1-specific conclusion:
- logistic continuation × Gamma mark = no stable existing-component signal;
- Poisson count × Gamma mark = no arrival-component signal and severe OOS extreme-tail fragility;
- the P1 parameterization is closed and must not be rescued.

Realized future composition remains diagnostic only and cannot be a prediction-time input.

## 2. 2026 novelty boundaries added after P1

| Work | What it already covers | Consequence here |
| --- | --- | --- |
| TimeMoE-LoRA EV charging, IEEE Access 2026, DOI `10.1109/ACCESS.2026.3697488` | sparse Time-MoE foundation model + LoRA + direct multi-horizon EV charging load forecasting | generic MoE / foundation-model / direct multi-horizon EV claims are unavailable |
| RCHA-MOE, IEEE Access 2026, DOI `10.1109/ACCESS.2026.3695762` | regime-conditioned horizon-specific expert weights at inference | horizon-aware gate / step-specific MoE routing is not novelty by itself |
| CUP-EV, Information Sciences 2026, DOI `10.1016/j.ins.2026.123681` | lightweight DLinear + nonlinear residual, probabilistic multi-horizon EV forecasting | generic residual hybridization and probabilistic multi-horizon output are crowded |
| TriCast, Pattern Recognition Letters 2026, DOI `10.1016/j.patrec.2026.04.028` | causal spatial/temporal/economic multimodal EV demand forecasting | causal Transformer/multimodal fusion alone is not a new gap |
| SessionFlow, SSRN 20 Aug 2026 | partially observed origin-active session continuation + future served-session generation + station aggregation | existing/future session decomposition or session generation is not novelty |
| FAME, arXiv:2606.08896 | forecastability fingerprints and sparse expert-suitability routing | forecastability-aware expert selection is not novelty |
| MoHETS, arXiv:2601.21866 | heterogeneous forecasting experts | heterogeneous-expert design is not novelty |
| Set Transformer / Deep Sets | permutation-invariant set representation | set architecture itself is not novelty |

Generic Transformer/Mamba/diffusion/state-space replacement remains low value for the core contribution.

## 3. Current high-value external projects

| Project | Open-source role | Potential use here | Limitation / novelty risk | Current disposition |
| --- | --- | --- | --- | --- |
| `zach401/acnportal` | ACN-Data/ACN-Sim toolkit | data semantics, physical consistency, session simulation/stress tests | stochastic session generation already mature | **high-value infrastructure** |
| `caltech-netlab/acnportal-experiments` | ACN reproducible examples | scenario/evaluation organization | not forecasting novelty | **experimental reference** |
| `juho-lee/set_transformer` | official Set Transformer PyTorch | permutation-invariant session-set interactions | architecture is 2019 prior art | **candidate engineering reference** |
| `manzilzaheer/DeepSets` | original Deep Sets code | minimal permutation-invariant representation baseline | architecture itself is old prior art | **candidate low-capacity reference** |
| `Time-MoE/Time-MoE` | official Time-MoE | strong generic time-series MoE reference | direct EV adaptation already published in 2026 | **novelty boundary / possible baseline** |
| `hit636/FAME` | sparse forecastability-aware expert routing | later routing/control reference | routing concept already claimed | **later reference only** |
| `Waqar2193/CUP-EV-Cost-and-Uncertainty-aware-Probabilistic-EV-Energy-Forecasting` | public CUP-EV source | lightweight residual/probabilistic benchmark ideas | not session-population representation | **benchmark/reference** |
| `havakv/pycox` | survival toolkit | formal survival benchmark | P1 continuation route failed; not a rescue path | **deprioritized** |
| `ant-research/EasyTemporalPointProcess` | TPP toolkit | event-process benchmark | P1 arrival route failed; TPP upgrade would be rescue | **deprioritized** |

## 4. Internal representation gap discovered after screening

Frozen M3 has 11 legal connected-session fields and reduces **each field independently** to:

```text
count, sum, mean, std, min, max, p25, p50, p75, missing_count
```

Thus M3 has 110 session-pool features but preserves only marginal summaries. It does not retain which elapsed time, current, pilot, cumulative charge and requested-departure values belong to the same session.

This matters because turnover is a joint-state question. For example, two issue times can have similar marginal current and elapsed-time distributions but differ in whether the high-current sessions are old/young or near/far from their requested departure.

P1-E preserves each session tuple but learns sessions independently and sums future contribution estimates. It therefore does not model the simultaneously connected session population as an interacting set, and its decomposed target failed empirically.

This creates a narrower and better motivated gap than generic MoE:

> represent the currently connected session population as an unordered set of **joint issue-time session states**, and use it directly to forecast aggregate station current.

## 5. Post-P1 candidate ranking

### Rank 1 — connected-session set representation for aggregate multi-horizon forecasting

Recommended scientific question:

> Does preserving the joint issue-time state of the currently connected session population as a permutation-invariant set reveal horizon-dependent predictive information that fixed marginal pooling discards, and can that information stably improve aggregate charging-current forecasts without explicitly predicting future session identities or decomposed future contributions?

Key distinctions:
- not M3 marginal pooling;
- not P1 per-session future-contribution prediction;
- not S1 existing/arrival target decomposition;
- not SessionFlow generative replay;
- not generic MoE routing.

Current targeted searches found no directly matching EV charging-load paper using the connected session population as a permutation-invariant issue-time set to directly predict aggregate multi-horizon load. This is a screening result, not proof of absence.

### Rank 2 — horizon-conditioned expert routing

May become useful after a stronger session representation exists, but RCHA-MOE/FAME/MoHETS make it a poor immediate novelty core.

### Rank 3 — probabilistic/session-generative extension

Useful later for uncertainty or operational extensions, but TimeMoE-LoRA, CUP-EV, SessionFlow and existing arrival/survival work make it crowded and it would risk becoming a post-hoc P1 rescue.

## 6. Recommended next experiment class

Do not jump directly to a large Set Transformer.

First run a **matched-capacity representation probe** after a new protocol is frozen:

- `Pool-control`: legal M2 context + existing M3 marginal pools + small fixed-capacity nonlinear head;
- `Set-probe`: same M2 context + minimal permutation-invariant encoder over raw legal connected-session tuples + comparable-capacity head;
- target remains aggregate `station_current_mean_a`;
- no existing/arrival component targets;
- identical OOS rows and 15/30/60/120/240 min horizons;
- compare additionally to frozen M2/M3/Equal/S1.

A minimal Deep-Sets-style encoder is preferable for the first signal test. Full Set Transformer/horizon-query attention should be authorized only if the set representation itself demonstrates stable development signal.

See `docs/JPL_POST_P1_METHOD_SCREENING_20260912.md` for the complete collision analysis.

## 7. Standing search / reuse policy

For every future candidate record:
- paper/repository identity;
- reusable component;
- scientific assumptions;
- causal-observability compatibility;
- license/third-party restrictions;
- what is already solved and cannot be novelty;
- remaining gap tied to our own development evidence.

Before any new local fit, freeze a separate protocol with exact legal predictors, matched controls, OOS rules and PASS/MIXED/STOP criteria. Final holdout remains sealed.
