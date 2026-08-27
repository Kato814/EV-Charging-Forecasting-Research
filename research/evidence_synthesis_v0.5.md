# Round 3 Evidence Synthesis — v0.5

## 1. Scope correction

The previous repository version placed substantial weight on unseen-city, unseen-station and structural-OOD settings. That was a valid deployment question but did not meet the present research preference: identify a concrete unresolved forecasting problem rather than create novelty by adding a harder boundary condition.

Round 3 therefore demotes OOD to optional validation and reopens the forecasting problem itself.

## 2. Evidence around real-time information

Three mature fragments already exist:

1. **Ongoing-session state**: elapsed occupation and live connector state improve remaining-duration prediction (`P0063`).
2. **Partial charging curve**: a real DC fast-charging profile and duration can be updated from the first power/SOC observations (`P0035`).
3. **Future event generation**: arrivals, durations and powers can be generated with compound Poisson/Cox or queue models (`P0049`, `P0045`).

Probabilistic direct and bottom-up EV-load forecasting also exists (`P0065`), and occupancy/load can be predicted jointly (`P0064`). The remaining candidate gap is therefore not any one of these fragments. It is their forecast-time-consistent integration:

\[
\text{active-session remainder}
+
\text{not-yet-arrived session load}
\rightarrow
\text{station probabilistic power trajectory}.
\]

The two components should not share an undifferentiated uncertainty model. Near-term uncertainty should be dominated by active-session continuation; farther horizons should increasingly depend on future arrivals. This decomposition is falsifiable and produces interpretable failure analysis.

## 3. Evidence around label quality

`P0065` reconstructs load from session characteristics under a constant-power assumption. `P0066` demonstrates that linear charging profiles can create material modelling errors and that measurement-based nonlinear profiles are more accurate. `P0035`, ACN and D0015 show that high-resolution real power and state trajectories exist for a smaller number of contexts.

This supports a multi-fidelity problem:

- large transaction datasets provide weak integral labels;
- small metered datasets provide curve shape and control information;
- the model reconstructs a distribution over latent curves, not one deterministic rectangle.

The decisive risk is identifiability. Energy and duration alone do not determine a unique curve.

## 4. Evidence around operational errors

`P0067` reports substantial peak magnitude and peak timing errors even when a whole 96-step curve is forecast. `M0045` formalizes peak timing and peak shape as distinct forecasting tasks. This supports event-aware evaluation and a backup method direction.

The repository now requires all short-term/day-ahead experiments to report, where applicable:

- peak magnitude error;
- peak timing error with a tolerance window;
- ramp-event precision/recall;
- high-quantile or threshold exceedance score;
- average curve metrics.

## 5. Evidence around endogenous targets

ACN and D0015 contain both control-related signals and realized power. The NBER field experiment `F0020` shows that managed charging changes the time distribution of observed load. Consequently, a forecast trained on realized controlled load can learn the previous controller rather than the underlying charging need.

This issue is scientifically strong but should follow, not precede, the simpler dual-source gate. A valid study must have either cross-policy data, known control actions, or an external reference sufficient to test counterfactual claims.

## 6. Current evidence-based decision

The repository no longer recommends an OOD-centered paper. The preferred next experiment is:

> **At each rolling issue time, decompose future station power into the continuation of currently active sessions and the stochastic contribution of future arrivals; model both probabilistically and aggregate them without future leakage.**

The exact neural backbone is deliberately left open. Candidate modules include neural survival, conditional sequence models, marked temporal point processes, conditional normalizing flows and differentiable aggregation, but none is treated as the innovation by itself.

## 7. Claims that remain prohibited

- “No previous study considered active and future sessions” — not established by targeted search alone.
- “Physical consistency is the main innovation” — insufficient.
- “A neural point process is new for EV charging” — contradicted by event-process prior work.
- “Constant-power reconstruction is ground truth” — not defensible for nonlinear or controlled charging.
- “Better MAE proves better dispatch value” — not established.
- “A harder city/station split is the contribution” — outside the current direction policy.
