# Open-source idea ledger

Updated: 2026-09-11.

This ledger tracks external open-source projects that may provide reusable components, benchmark implementations, diagnostic ideas, or scientific contrasts for the JPL/ACN charging-station forecasting research. Inclusion does **not** authorize importing code, changing the frozen split, or accessing the final holdout. Adoption requires scientific-relevance, causal-observability and license review first.

## 1. Current scientific constraint

S1 remains `MIXED_STRUCTURED_SIGNAL`. Two completed read-only diagnostics show that the main weakness is not a generic binary-arrival problem or a monotone composition threshold. The strongest reproducible evidence is a **horizon-conditioned session-turnover regime**:

- 30 min / realized arrival share 25–50% is worse than Equal in 4/4 development months;
- 60 min / realized arrival share 50–75% is worse in 4/4 months;
- 60 min / realized arrival share 0–25% is better in 4/4 months;
- 30/60/120 min around local 07:00 are consistently weak, while the same horizons around 09:00 are consistently stronger.

Realized future composition is diagnostic only and cannot be a prediction-time input.

Known novelty boundary remains unchanged: current/pilot phase identification, existing+arrival decomposition, generic gating, generic Transformer/Mamba/state-space backbones, survival libraries, TPP libraries and stochastic session generation are not sufficient novelty claims by themselves.

## 2. Candidate projects

| Project | Open-source role | Potential use here | Limitation / novelty risk | Current disposition |
| --- | --- | --- | --- | --- |
| `zach401/acnportal` | ACN-Data/ACN-Sim research toolkit | Data semantics, causal session replay, physical consistency, simulation stress tests; its `StochasticEvents` also supplies a mature stochastic-session reference | Already supports joint stochastic arrival-time / duration / energy modeling; this family is therefore not novel by itself | **High-value infrastructure and simple stochastic reference** |
| `caltech-netlab/acnportal-experiments` | Reproducible ACN research examples | Experiment organization, practical JPL scenario evaluation and stress testing | Charging-control/infrastructure focus, not the forecasting contribution | **High-value experimental reference** |
| `havakv/pycox` | PyTorch survival/time-to-event toolkit | Later benchmark if current-session continuation evidence supports formal survival/hazard | Too complex for the first probe; DeepSurv/pycox use alone is not novelty | **Deferred benchmark; not authorized in P1** |
| `ant-research/EasyTemporalPointProcess` | TPP benchmark/toolkit | Later RMTPP/NHP/THP/intensity-free arrival-process benchmark | Current evidence does not justify neural TPP complexity; backbone itself is not novelty | **Deferred watchlist; not authorized in P1** |
| `fffahim/Deep-learning-for-electric-vehicle-charging-load-forecasting` | LSTM/BiLSTM/Residual Seq2Seq EV examples | Conventional deep-learning comparison family if later required | Does not address the turnover mechanism | **Comparison-only** |
| `anujgs/Forecasting-EV-Charging-Station-Load` | CNN-LSTM/clustering example | Conventional preprocessing/comparison ideas | Small direct time-series project; no session mechanism | **Low-priority comparison** |

## 3. Reuse / license notes

- `acnportal`: BSD-style redistribution terms; preserve required notices if code is reused.
- `pycox`: BSD 2-Clause.
- `EasyTemporalPointProcess`: Apache-2.0 according to project documentation; inspect `NOTICE` / third-party components before copying files.
- Other repositories require explicit license review before reuse.
- Public visibility is not permission to copy code without license review.

## 4. What ACN Portal already solves

ACN Portal contains `StochasticEvents` infrastructure that can fit/sample stochastic session variables and includes a Gaussian-mixture implementation around arrival time, session duration and energy demand. This is useful as an engineering/reference baseline, but it narrows our novelty space:

> “jointly modeling charging-session arrival time, duration and energy” is not a defensible novelty claim by itself.

If used later, ACN stochastic-event machinery should be a comparison/stress-test component rather than the claimed contribution.

## 5. Evidence-driven method ranking

### Rank 1 — current-session continuation × positive-current mark

The existing-session contribution increasingly transitions toward zero with horizon, but an EV session may temporarily pause charging and later resume. A strict terminal survival process would therefore impose an unverified monotonicity assumption in the first probe.

P1 first uses a simple horizon-specific logistic probability that a currently connected session still contributes positive current in the target window, multiplied by a Gamma positive-current mark. This tests the continuation mechanism without adding a large model or forcing irreversible termination. Formal hazard/survival becomes a later candidate only if continuation×mark demonstrates stable development signal.

### Rank 2 — future-arrival count × mark

Future-arrival contribution is highly zero-inflated at short horizons and becomes dominant at long horizons. A binary any-arrival hurdle is insufficient because the 60-min failure occurs on both zero-arrival and positive-arrival subsets.

The next candidate is therefore **contributing-session count/intensity × positive current mark**, initially using fixed Poisson/Gamma GLMs. Neural TPP is deferred.

### Rank 3 — formal survival / neural TPP benchmark

Only if low-complexity P1 shows stable component/total signal may later work evaluate formal hazard/survival, pycox or EasyTPP as benchmark implementations. A larger neural model must not be introduced merely to rescue a weak mechanism.

## 6. Frozen next-step protocol

See `docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md`.

Primary candidate:

```text
P1-EA = logistic continuation × Gamma mark existing contribution
      + Poisson count × Gamma mark future-arrival contribution
```

`P1-Eonly` and `P1-Aonly` are attribution diagnostics only. No post-hoc best-of-three headline is allowed.

The P1 protocol freezes development months, rolling-origin/common-row rules, fixed model parameters and decision thresholds before any fit.

## 7. Standing search policy

Future method-design cycles should search GitHub and the literature before implementation. For every promising external project, record:

- repository / paper identity;
- reusable component;
- scientific assumptions;
- compatibility with ACN/JPL causal observability;
- license / third-party restrictions;
- what is already solved and therefore cannot be claimed as novelty;
- remaining limitation/gap that may support a defensible contribution.

The objective is to reuse mature engineering while concentrating original work on the empirically supported horizon-dependent charging-session turnover mechanism.
