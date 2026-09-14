# Post-R7 method screening

Date: 2026-09-14

## Accepted evidence

R7-C0 formally passed. The primary `Departure-Aug` arm (M2 plus the canonical ten-stat `requested_departure_minutes_from_issue` pool) improved the frozen future-arrival component by 1.5428% pooled MAE, won 5/5 horizons and 3/4 months, and improved recombined total MAE vs S1 by 0.5575% with 4/5 horizon and 3/4 month wins.

The result is predictive, not causal. The canonical departure pool contains both timing-distribution statistics and declaration-availability information (`count`, `missing_count`).

## Collision boundary

Arrival/departure forecasting, parking-duration forecasting, occupancy-aware charging management, stochastic session generation and general probabilistic EV-demand forecasting are established research areas. Therefore none of the following is sufficient novelty by itself:

- predicting EV departure time;
- using arrival/departure data as generic model inputs;
- replacing HGB with LSTM/Transformer/attention;
- introducing a TPP/survival model merely because future arrivals dominate long horizons;
- adding a gate or horizon router.

R7 only establishes a narrow empirical information channel inside the frozen JPL short-term forecasting problem.

## Selected next question

Before designing a scheduled-release or capacity-aware mechanism, separate two explanations of the R7 PASS:

1. **declaration-availability explanation** — whether a session has a nonmissing requested departure may proxy user/session regime and account for the gain;
2. **timing-distribution explanation** — the actual numerical requested-departure values carry incremental information beyond availability.

The selected next step is therefore a one-arm development-only ablation, `R7-D1`.

No new deep model, event-process model, survival model, gate, MoE or final-holdout access is justified before R7-D1 resolves this attribution.
