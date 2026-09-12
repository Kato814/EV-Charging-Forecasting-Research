# Open-source idea ledger

Updated: 2026-09-12.

This ledger tracks external open-source projects and adjacent literature relevant to the JPL/ACN charging-station forecasting research. Inclusion does **not** authorize code import, model fitting, split changes, or final-holdout access. Adoption requires scientific relevance, causal observability and license review.

## 1. Current scientific constraint

Frozen development state:

- S1 remains `MIXED_STRUCTURED_SIGNAL`;
- P1 remains `STOP_MECHANISM_ROUTE` and is closed;
- R1 remains `MIXED_JOINT_STATE_SIGNAL` after its completed daily/hourly read-only diagnostic;
- final holdout 2019-03/06/09/12 remains sealed.

Accepted descriptive evidence:

- existing-session share falls from 97.38% at 15 min to 26.21% at 240 min;
- future-arrival share rises from 2.62% to 73.79%;
- 30/60 min mixed-turnover regions contain repeatable weak regimes;
- R1-Joint beats its matched Control overall by 0.523773% MAE but remains 0.424285% worse than Equal and worse than S1;
- July R1 degradation is distributed across days, not one removable outlier;
- October contains real Joint-vs-Control gains but residual gaps to Equal;
- 60 min R1 improves Equal by only 0.055223 A and is not cross-month stable at 07:00/09:00.

P1-specific conclusion remains unchanged:

- logistic continuation × Gamma mark = no stable existing-component signal;
- Poisson count × Gamma mark = no arrival-component signal and severe OOS tail fragility;
- P1 parameterization is closed and must not be rescued.

Realized future composition remains diagnostic-only and cannot be a prediction-time input.

## 2. Novelty boundaries

| Work | What it already covers | Consequence here |
| --- | --- | --- |
| Deep Sets (`manzilzaheer/DeepSets`, Apache-2.0) | permutation-invariant set encoding by shared element map + symmetric pooling | Deep Sets architecture/sum pooling is not novelty |
| Set Transformer (`juho-lee/set_transformer`, MIT) | attention-based permutation-invariant set representation | set attention / variable-cardinality handling is not novelty |
| Kwon & Zhu, HICSS 2022 / arXiv:2108.03236 | EVCS state/action aggregation for a large, time-varying number of EVs | handling variable-size EV populations is not novelty |
| `samuelBobick/StationLevelPowerForecasting`, MIT | station-level power forecasting with active-session counts and planned/active-session profile information | active-session information in station forecasting is not novelty |
| SessionFlow, SSRN 20 Aug 2026 | partially observed origin-active continuation + future served-session generation + station aggregation | existing/future session decomposition, generation and replayability are not novelty |
| TimeMoE-LoRA EV charging, IEEE Access 2026 | sparse Time-MoE + LoRA + direct multi-horizon EV charging forecasting | generic MoE / foundation-model / direct multi-horizon EV claims are unavailable |
| RCHA-MOE, IEEE Access 2026 | regime-conditioned horizon-specific expert weights | horizon-aware gate / step-specific MoE routing is not novelty by itself |
| CUP-EV, Information Sciences 2026 | lightweight residual + probabilistic multi-horizon EV forecasting | generic residual hybridization/probabilistic output is crowded |
| recent TFT/MFT/GAT-LSTM-Transformer EV forecasting | generic temporal, multiscale and spatiotemporal deep backbones | generic Transformer replacement is not a new gap |

Do not claim first active-session forecasting, first variable-session representation, first session-aware EV model, first Deep Sets/Set Transformer EV model, or first horizon-specific neural predictor.

## 3. High-value external projects

| Project | Open-source role | Potential use here | Limitation / novelty risk | Current disposition |
| --- | --- | --- | --- | --- |
| `zach401/acnportal` | ACN-Data/ACN-Sim toolkit | data semantics, physical consistency, stress tests | stochastic session generation already mature | **high-value infrastructure** |
| `caltech-netlab/acnportal-experiments` | reproducible ACN examples | scenario/evaluation organization | not forecasting novelty | **experimental reference** |
| `manzilzaheer/DeepSets` | original Deep Sets code, Apache-2.0 | minimal permutation-invariant engineering reference | architecture is prior art | **R2 engineering reference only** |
| `juho-lee/set_transformer` | Set Transformer PyTorch, MIT | possible later interaction encoder | architecture is prior art; not authorized in R2 | **later reference only** |
| `samuelBobick/StationLevelPowerForecasting` | station-level EV forecasting, MIT | active-session forecasting baseline/feature precedent | uses active-session information; future/planned profiles are not legal R2 predictors | **novelty boundary / forecasting reference** |
| `Time-MoE/Time-MoE` | generic time-series MoE | strong generic baseline reference | direct EV adaptation already published | **novelty boundary** |
| `hit636/FAME` | forecastability-aware expert routing | later routing reference | routing concept already claimed | **later reference only** |
| `havakv/pycox` | survival toolkit | survival benchmark | P1 continuation route failed; rescue not allowed | **deprioritized** |
| `ant-research/EasyTemporalPointProcess` | TPP toolkit | event-process benchmark | P1 arrival route failed; deep TPP would be rescue | **deprioritized** |

SessionFlow is literature/conceptual prior art only; its SSRN record is all-rights-reserved and does not authorize code/text reuse.

## 4. Internal representation gap after R1

Frozen M3 has 11 legal connected-session fields and reduces each field independently to ten fixed marginal statistics. It does not retain full same-session tuple structure.

R1 added 55 pairwise Pearson correlations under a matched availability control. R1 demonstrated a small overall increment over Control but failed the practical stability conditions. Its failure does **not** prove that all higher-order joint structure is useless; it shows that hand-designed second-order Pearson summaries are insufficiently stable.

The remaining controlled question is narrower:

> Does the higher-order nonlinear joint configuration of the origin-active session population contain stable issue-time predictive information beyond exactly the same per-field marginals?

## 5. Selected R2 hypothesis

R2 uses a marginal-preserving counterfactual control rather than comparing a neural model directly against a different tree feature set.

### R2-Joint

- exact M2 issue-time station context;
- true variable-length set of same-session 11-field legal M3 tuples;
- small fixed Deep-Sets-style encoder;
- direct aggregate `station_current_mean_a` target.

### R2-Permuted control

- same M2 context;
- same session count;
- exact same value and missing/observed multiset for every one of the 11 session fields at each issue time;
- independent deterministic within-issue field permutations destroy real same-session alignment;
- exact same network, preprocessing, initialization schedule, optimization and OOS rows as Joint.

Primary scientific comparison: `R2-Joint vs R2-Permuted`.

This is intended to isolate the predictive value of higher-order tuple alignment. It is not a claim that Deep Sets is new.

Full frozen specification: `docs/JPL_R2_HIGHER_ORDER_SESSION_SET_PROTOCOL_20260912.md`.

## 6. Why larger alternatives remain deferred

- **Set Transformer / attention**: not authorized until a lower-capacity higher-order representation demonstrates stable signal.
- **MoE / horizon routing / time-of-day gate**: crowded prior art and would conflate representation with routing.
- **TPP / survival / future-session generation**: risks rescuing the stopped P1 route; SessionFlow already covers explicit session continuation/generation.
- **generic Transformer/Mamba/diffusion**: does not address the identified representation question.
- **post-hoc pair selection or new correlations**: would rescue R1 after observing errors.

## 7. R2 engineering boundary

R2 implementation, if the protocol PR merges, must use a separate environment and not mutate `evcf-gate1-pilot`.

Formal target:

```text
Python 3.11.16
PyTorch 2.14.0
CUDA wheel cu132
formal device cuda:0 / NVIDIA GeForce RTX 5080
```

PyTorch 2.14 officially supports CUDA 13.2. The formal development launcher must fail before fitting if the approved GPU is unavailable; CI may run CPU unit tests only. No mixed precision, automatic CPU fallback or backend substitution is allowed in the first R2 probe.

## 8. Standing search / reuse policy

For every future candidate record:

- paper/repository identity;
- reusable component;
- scientific assumptions;
- causal-observability compatibility;
- license/third-party restrictions;
- what is already solved and cannot be novelty;
- remaining gap tied to our own development evidence.

No new local fit is authorized until a separate scientific protocol, implementation PR/CI, environment preflight and pinned launcher are complete. Final holdout remains sealed.
