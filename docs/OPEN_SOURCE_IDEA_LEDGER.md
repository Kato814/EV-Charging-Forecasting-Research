# Open-source idea ledger

Updated: 2026-09-11.

This ledger tracks external open-source projects that may provide reusable components, benchmark implementations, diagnostic ideas, or scientific contrasts for the JPL/ACN charging-station forecasting research. Inclusion here does **not** authorize importing code into the main method, changing the frozen data split, or accessing the final holdout. Any adoption must first pass scientific relevance, causal-boundary, license, and protocol review.

## 1. Current scientific constraint

The completed S1 v1.3 development run is `MIXED_STRUCTURED_SIGNAL`. S1 improves pooled MAE versus both M3 and Equal, but only 2/4 development months beat Equal. The main weak region is the 30-120 min session-turnover band, especially 60 min. Therefore external ideas are screened primarily for whether they can explain or model **horizon-dependent transition between current-session continuity, session turnover, and future-arrival dominance**.

Known novelty boundary remains unchanged: current/pilot phase identification, existing-session + future-arrival decomposition, generic Transformer/Mamba/state-space backbones, and ordinary gating are not sufficient novelty claims by themselves.

## 2. Candidate projects

| Project | Open-source role | Potential use here | Main limitation / novelty risk | Current disposition |
| --- | --- | --- | --- | --- |
| `zach401/acnportal` | Caltech ACN-Data/ACN-Sim research toolkit | Data semantics, session replay, physical consistency checks, simulation-based stress tests, practical pilot/current behavior | Primarily infrastructure/simulation tooling rather than a forecasting method; cannot itself supply forecasting novelty | **High-value infrastructure reference** |
| `caltech-netlab/acnportal-experiments` | Reproducible ACN research examples | Reuse experiment organization; inspect practical-model and JPL scenario evaluation patterns; potentially stress-test future forecasting methods under realistic charging behavior | Focus is charging control/infrastructure evaluation, not load forecasting | **High-value experimental reference** |
| `havakv/pycox` | PyTorch survival / time-to-event toolkit | Model current-session continuation/termination through discrete or continuous hazard; directly relevant to remaining-duration uncertainty of issue-time active sessions | Medical/general survival toolkit, not EV-specific; using DeepSurv alone would not be novel | **Strong candidate component for an existing-session mechanism probe** |
| `ant-research/EasyTemporalPointProcess` | ICLR 2024 temporal point-process benchmark/toolkit | Model future charging-session arrivals as event times/marks; provides RMTPP/NHP/THP/intensity-free references and reproducible benchmarks | Considerably more complex than current evidence warrants; a TPP backbone itself is not novelty; must avoid replacing mechanism analysis with generic deep event modeling | **Watchlist; later candidate for arrival-process benchmarking** |
| `fffahim/Deep-learning-for-electric-vehicle-charging-load-forecasting` | EV load forecasting examples using LSTM/BiLSTM/Residual Seq2Seq/PCA | Useful as a conventional deep-learning comparison family if required later | Generic backbone replacement; does not address session-turnover mechanism | **Comparison-only, not core direction** |
| `anujgs/Forecasting-EV-Charging-Station-Load` | CNN-LSTM / clustering EV station-load example | May provide conventional preprocessing/clustering comparison ideas | Small project; direct time-series forecasting without current-session/future-arrival mechanism | **Low-priority comparison reference** |

## 3. Reuse and license notes

- `acnportal`: BSD-style redistribution terms; preserve copyright/license notices if code is reused.
- `pycox`: BSD 2-Clause.
- `EasyTemporalPointProcess`: Apache License 2.0 according to the project documentation; it also contains third-party components listed in `NOTICE`, so any copied component requires per-file/license review.
- For all other repositories, license must be checked before any code reuse. No code should be copied based only on repository visibility.

## 4. Ideas suggested by the current S1 evidence

### A. Current-session continuation as survival / hazard

Instead of directly regressing future existing-session aggregate current at every horizon, represent each issue-time active session through a conditional survival probability over the future horizon. A low-complexity discrete hazard model is the first candidate; neural survival models are optional later. The scientific value would come from linking elapsed time, current/pilot state, and remaining charging probability to the observed horizon transition, not from the survival library itself.

### B. Future arrivals as an event process

Treat future arrivals as a count/time/mark process rather than a single aggregate-current regression target. A simple Poisson/negative-binomial or discrete arrival-intensity baseline should precede neural TPPs. TPP libraries are useful mainly as benchmark implementations if the simple event-process probe shows signal.

### C. Horizon-dependent transition mechanism

The final method, if this route survives, should not be “two branches + a generic gate.” A more defensible target is a mechanism in which the expected contribution of current sessions decays through survival/termination while the expected contribution of future sessions grows through an arrival process, with the relative importance changing explicitly with horizon. The transition must be validated across development months, especially the current failure region around 30-120 min.

## 5. Next low-complexity probe before any deep model

1. **Existing-session probe:** evaluate simple discrete survival/hazard targets for active sessions using only issue-time legal features; report horizon-wise continuation calibration and aggregate-current reconstruction.
2. **Arrival-process probe:** decompose the arrival branch into future session count and conditional current/mark magnitude; compare direct aggregate regression with simple count × mark expectation.
3. **Transition robustness:** evaluate both probes by leave-one-development-month-out direction/stability, with special attention to Apr-60, Apr-120, Jul-120, and Oct-120.
4. Do not access 2019-03/06/09/12 and do not introduce a large neural model unless these low-complexity mechanism probes demonstrate stable development signal.

## 6. Standing search policy

Future method-design cycles should search GitHub and the literature before implementing from scratch. For each promising external project, record:

- exact repository / paper identity;
- what component is reusable;
- what scientific assumption it makes;
- whether the assumption matches ACN/JPL causal observability;
- license / third-party restrictions;
- what it already solves, so it is **not** incorrectly claimed as novelty;
- what limitation or gap remains that may support a defensible contribution.

The objective is to reuse mature engineering and benchmark implementations where appropriate while concentrating original work on the empirically supported forecasting mechanism.