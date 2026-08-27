# Round 3 Problem-Gap Review Protocol

## 1. Review purpose

Round 3 replaces the previous “add a new OOD boundary and test it” logic with a **problem-first gap search**. A candidate direction is retained only when all five questions have concrete answers:

1. What specific charging-power/load forecasting failure is being solved?
2. Why do existing models fail on that point?
3. Which existing paper is the closest method, and what exactly does it omit?
4. Which observable data can verify the missing mechanism?
5. What result would falsify the proposed direction?

OOD, unseen-city, unseen-station and temporal holdouts may be used as robustness tests, but they are not treated as the scientific contribution unless the research question itself concerns transfer.

## 2. Inclusion focus

The round prioritizes small but substantive problems inside charging-power/load forecasting:

- information available at the rolling forecast issue time;
- active charging sessions versus future arrivals;
- zero/intermittent demand and discrete–continuous target structure;
- peak timing, peak magnitude and ramp events;
- weak transaction labels versus true metered power;
- historical charging-control contamination of the target;
- latent versus served demand under capacity/queue censoring;
- temporal aggregation consistency when it affects peaks or decisions.

Model names are not search directions. Transformer, diffusion, Mamba, foundation models, graph networks and federated learning are considered implementation options only after the problem is fixed.

## 3. Evidence levels

- **Direct evidence**: an EV charging paper demonstrates the same or adjacent failure.
- **Nearest-neighbor evidence**: an EV paper already solves part of the proposed mechanism.
- **Adjacent method evidence**: another forecasting domain formalizes the same target or metric.
- **Data evidence**: an official dataset exposes fields needed to test the mechanism.
- **Negative search evidence**: targeted searches did not retrieve a direct match. This is never interpreted as proof that no paper exists.

## 4. Candidate scoring

Each direction is scored on:

- problem specificity;
- novelty potential after nearest-neighbor subtraction;
- data feasibility;
- implementation risk;
- centrality to charging-power forecasting;
- relevance to later optimization;
- pressure from existing nearest neighbors.

High novelty with unidentifiable targets is not automatically preferred.

## 5. Minimum-gate rule

Before developing a complex model, each candidate must pass a simple gate using transparent baselines. The gate must establish that:

- the proposed information or target contains measurable value;
- the improvement cannot be reproduced by a trivial feature addition or post-processing step;
- all inputs are available at forecast issue time;
- the effect appears in at least one operational metric, not only a single average error;
- there is a documented stop condition.

## 6. Current scope decision

Round 3 sets the following policy:

> Distribution-outside generalization is retained as an optional robustness dimension. It is not the current paper core, not the direction-selection criterion and not a required word in a paper title.
