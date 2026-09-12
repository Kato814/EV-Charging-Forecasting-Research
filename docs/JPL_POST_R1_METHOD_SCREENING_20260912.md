# Post-R1 method screening — 2026-09-12

## Status

This document records the method-selection step after the accepted R1 `MIXED_JOINT_STATE_SIGNAL` outcome and its completed read-only daily/hourly diagnostic. It is not a model implementation and does not authorize final-holdout access.

Accepted scientific state entering this screening:

- S1 = `MIXED_STRUCTURED_SIGNAL`;
- P1 = `STOP_MECHANISM_ROUTE`, closed after its read-only post-mortem;
- R1 = `MIXED_JOINT_STATE_SIGNAL`, with the daily/hourly failure analysis closed;
- final holdout 2019-03/06/09/12 remains sealed.

## 1. What the internal evidence now says

The development evidence supports a narrower question than a generic architecture search.

1. The composition of station current changes strongly with horizon: origin-existing sessions dominate short horizons, while future arrivals dominate long horizons.
2. S1 showed that explicit existing/arrival decomposition contains signal but is not month-stable, with the most persistent weakness around the turnover transition.
3. P1 showed that replacing aggregate branches with independent continuation/count × mark models is not a stable solution; both components failed and the arrival count route also exhibited severe OOS extrapolation.
4. R1 controlled model capacity and missingness while adding 55 pairwise Pearson joint-state features. It improved the matched Control overall by 0.523773%, but remained 0.424285% worse than Equal and 1.5566% worse than S1. The signal was not stable across months/days.
5. The completed R1 diagnostic showed that July degradation is distributed across multiple days, while October contains both real improvements over Control and residual gaps to Equal. The weak result cannot be explained by deleting one pathological day.

Therefore, the next question should not be “which larger backbone should replace HGB?” The unresolved representation question is whether **higher-order nonlinear joint structure in the currently connected session population** contains stable predictive information beyond the same field-wise marginals.

## 2. External collision check and novelty boundary

### 2.1 Deep Sets / Set Transformer

Permutation-invariant set learning is established prior art. `manzilzaheer/DeepSets` is the original Deep Sets codebase (Apache-2.0), and `juho-lee/set_transformer` is a public Set Transformer implementation (MIT). A set encoder, attention over a set, sum pooling, or variable-cardinality handling is therefore not a novelty claim.

Engineering references:

- https://github.com/manzilzaheer/DeepSets
- https://github.com/juho-lee/set_transformer

### 2.2 Variable-size EV populations are not new

Kwon and Zhu, *Efficient Representation for Electric Vehicle Charging Station Operations using Reinforcement Learning* (HICSS 2022; arXiv:2108.03236), explicitly addresses the large and time-varying EV state/action dimension and proposes EV-state aggregation. Hence “handling a varying number of connected EVs” is not a novelty claim.

### 2.3 Active-session information in station-level forecasting is not new

The public Berkeley repository `samuelBobick/StationLevelPowerForecasting` (MIT) contains station-level forecasting code and uses active-session information. Its forecasting formulation includes active-session counts and, in the optimization context, planned/future active-session power profiles. The repository also contains utilities that aggregate future profiles of all active sessions.

Engineering reference:

- https://github.com/samuelBobick/StationLevelPowerForecasting

Therefore, R2 cannot claim first use of active sessions, active-session counts, or session-aware station-level forecasting.

### 2.4 Explicit origin-active / future-session generation is already claimed

The 2026 SSRN preprint *Session-Replayable Probabilistic EV Charging Power Forecasting from Partially Observed Sessions* (SessionFlow, posted 20 Aug 2026) explicitly continues origin-active sessions, generates future served sessions under resource limits, and aggregates session-level charging paths into station power. Its reuse is all-rights-reserved without permission.

Therefore, existing/future session decomposition, session continuation, future-session generation, or replayability cannot be presented as the new core contribution here.

### 2.5 Generic EV forecasting backbones are crowded

Recent EV forecasting literature already contains TFT, multi-scale Transformer, probabilistic/residual hybrids, spatiotemporal GAT/LSTM/Transformer methods, and horizon/regime-aware MoE variants. Generic Transformer/Mamba/MoE replacement is not a defensible gap by itself.

## 3. Candidate routes considered after R1

### A. More hand-designed pair statistics

Rejected as the immediate route. R1 already tested a low-order matched joint representation and obtained only MIXED evidence. Selecting pairs, changing Pearson to Spearman/Kendall/covariance, or tuning minimum session counts after seeing R1 errors would be post-hoc rescue.

### B. Horizon/time-of-day gating or MoE

Deprioritized. S1/R1 show horizon/time-of-day heterogeneity, but current literature already contains horizon-conditioned and regime-conditioned expert routing. More importantly, a gate would not answer whether the underlying session representation itself contains usable information.

### C. Survival / TPP / future-session generation

Rejected for the current route. P1 continuation/count parameterizations failed, and SessionFlow already occupies the explicit origin-active + future-session generation space. Jumping to a deeper survival/TPP model would be a P1 rescue rather than a clean new test.

### D. Low-capacity permutation-invariant joint-session representation

Selected as the next scientific probe, with a stronger control than R1.

The key idea is not “use Deep Sets.” It is to isolate **joint tuple information** from all per-field marginals using a marginal-preserving counterfactual control:

- `R2-Joint`: use the real set of same-session 11-field issue-time tuples;
- `R2-Permuted`: at each issue time, independently permute each field across the same connected sessions, preserving cardinality, every per-field value/missing multiset and station context while destroying cross-field same-session alignment;
- use exactly the same small Deep-Sets-style encoder, initialization schedule, optimizer and rolling-origin rows for both arms.

If R2-Joint cannot beat that matched control, a larger Set Transformer is not justified simply because it is more expressive.

## 4. Selected scientific question

> Does the higher-order nonlinear joint configuration of the origin-active charging-session population contain stable issue-time predictive information beyond exactly the same per-field marginals, and can that information improve direct aggregate multi-horizon station-current forecasting?

The contribution under test is therefore the **forecasting problem formulation and controlled evidence about higher-order origin-active session state**, not the Deep Sets architecture itself.

Safe eventual wording, only if supported by results:

- higher-order joint state of the origin-active session population;
- marginal-preserving counterfactual control;
- direct aggregate multi-horizon forecast under issue-time observability.

Do not claim:

- first active-session EV forecasting;
- first variable-size EV representation;
- first Deep Sets / Set Transformer EV model;
- first session-aware forecast;
- first horizon-specific neural model;
- first existing/future-session decomposition.

## 5. Why a minimal Deep-Sets-style probe comes before Set Transformer

R1 is MIXED, not PASS. A large attention model would confound two explanations:

1. higher-order joint session information is genuinely useful; or
2. a larger neural learner simply has more capacity than the frozen tree baseline.

R2 therefore uses a small, fixed, permutation-invariant sum encoder in both matched arms. The only scientific difference is whether true same-session tuple alignment is retained or destroyed while marginals remain unchanged.

A Set Transformer, horizon-query attention, MoE, learned gate, session generator, residual stacking or hyperparameter search is not authorized during R2.

## 6. Open-source reuse policy for R2

- Deep Sets and Set Transformer repositories are engineering references only; their architectures are prior art.
- Berkeley station-level forecasting is a forecasting/feature prior-art reference; do not copy its future active-session profile feature because R2 is restricted to issue-time observable information.
- SessionFlow is conceptual prior art only; no code or text reuse is authorized.
- Any PyTorch implementation must be written against the frozen R2 protocol and independently tested for causal observability and matched-control identity.

## 7. Selected next step

Freeze a separate `R2` protocol before implementation. The protocol must lock:

- the exact 11 legal session fields;
- exact M2 issue-time context;
- deterministic marginal-preserving permutation construction;
- identical Joint/Permuted architecture and optimization;
- rolling-origin rows and direct aggregate target;
- development-only decision rules;
- GPU/environment behavior;
- PASS/MIXED/STOP rules.

No R2 fit, new data download, final-holdout access, feature selection or architecture tuning is authorized by this screening document alone.
