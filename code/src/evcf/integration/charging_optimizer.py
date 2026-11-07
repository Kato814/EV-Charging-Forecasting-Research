"""Rolling linear program for hand-authored, issue-visible charging declarations."""
from dataclasses import replace
from fractions import Fraction
from math import nextafter

import numpy as np

from .charging_policy import DispatchDecision, dispatch_edf
from .charging_types import ChargeAction, step_end
from .controller_common import AdmissionError

MAX_HORIZON_STEPS = 16
SOLVER_METHOD = 'highs'
# HiGHS uses absolute row feasibility tolerances. Our rows are kW (shared
# capacity) and kWh (remaining energy), and the power bounds are in kW.
_TOLERANCE = 1e-7


def _checked_solution(result, matrix, row_limits, upper_kw, costs):
    if (getattr(result, 'success', None) is not True
            or type(getattr(result, 'status', None)) is not int or result.status != 0):
        raise AdmissionError('OPTIMIZER_FAILED', 'HiGHS did not report an optimal solution')
    try:
        powers = np.asarray(getattr(result, 'x', None))
        objective = np.asarray(getattr(result, 'fun', None))
    except (TypeError, ValueError) as exc:
        raise AdmissionError('INVALID_OPTIMIZER_SOLUTION', 'malformed solution') from exc
    if (powers.shape != upper_kw.shape or powers.dtype.kind not in 'fiu'
            or objective.shape != () or objective.dtype.kind not in 'fiu'
            or not np.isfinite(powers).all() or not np.isfinite(objective)):
        raise AdmissionError('INVALID_OPTIMIZER_SOLUTION', 'invalid solution shape or values')
    powers = powers.astype(float)
    achieved = costs @ powers
    used = matrix @ powers
    if (not np.isfinite(used).all() or not np.isfinite(achieved)
            or np.any(powers < -_TOLERANCE) or np.any(powers - upper_kw > _TOLERANCE)
            or np.any(used - row_limits > _TOLERANCE)
            or not np.isclose(achieved, objective, atol=_TOLERANCE, rtol=1e-12)):
        raise AdmissionError('INVALID_OPTIMIZER_SOLUTION', 'infeasible or inconsistent solution')
    return powers


def _solve_first_step(deadlines, requests_kwh, limits_kw, capacity_kw, hours, prefer_early):
    try:
        from scipy.optimize import linprog
        from scipy.sparse import coo_matrix
    except ImportError as exc:
        raise AdmissionError('OPTIMIZER_FAILED', 'SciPy HiGHS is required') from exc

    # Each variable is a constant kW command for one session and one interval
    # before its declared deadline. It contributes to two inequality rows.
    horizon = max(deadlines)
    session, period = np.nonzero(np.arange(horizon) < np.asarray(deadlines)[:, None])
    columns = np.arange(len(period))
    rows = np.concatenate((session, len(deadlines) + period))
    data = np.concatenate((np.full(len(period), hours), np.ones(len(period))))
    matrix = coo_matrix((data, (rows, np.tile(columns, 2))),
                        shape=(len(deadlines) + horizon, len(columns))).tocsr()
    row_limits = np.concatenate((requests_kwh, np.full(horizon, capacity_kw)))
    upper_kw = np.asarray(limits_kw)[session]
    bounds = np.column_stack((np.zeros(len(period)), upper_kw))

    def solve(costs, **equalities):
        try:
            result = linprog(costs, A_ub=matrix, b_ub=row_limits, bounds=bounds,
                             method=SOLVER_METHOD, options={'primal_feasibility_tolerance': _TOLERANCE},
                             **equalities)
        except (RuntimeError, ValueError, TypeError, OverflowError) as exc:
            raise AdmissionError('OPTIMIZER_FAILED', 'HiGHS could not solve the charging plan') from exc
        return _checked_solution(result, matrix, row_limits, upper_kw, costs)

    # The common duration makes maximizing summed power equivalent to maximizing energy.
    primary = solve(-np.ones(len(period)))
    if not prefer_early or not any(requests_kwh):
        return primary[period == 0]

    energy_rows = matrix[:len(deadlines)]
    shortfalls = np.maximum(0., requests_kwh - energy_rows @ primary)
    if shortfalls.sum() > _TOLERANCE:
        return primary[period == 0]

    # Fix the first optimum in kWh, then minimize the energy-weighted delivery
    # period (common hours can be factored out). Only the first interval executes.
    total_row = np.full((1, len(period)), hours)
    target_kwh = total_row @ primary
    early = solve(period, A_eq=total_row, b_eq=target_kwh)
    if (abs((total_row @ early)[0] - target_kwh[0]) > _TOLERANCE
            or np.maximum(0., requests_kwh - energy_rows @ early).sum() > _TOLERANCE
            or period @ early > period @ primary + _TOLERANCE):
        raise AdmissionError('INVALID_OPTIMIZER_SOLUTION', 'secondary plan lost service or delayed delivery')
    return early[period == 0]


def dispatch_optimized(view, feedback, *, site_id, cluster_id, device_limits_kw,
                       capacity_kw, step_seconds=900) -> DispatchDecision:
    """Maximize energy service under fixed visible declarations; issue only step one.

    Recompute at each issue with the same admission, feedback, and uncertainty
    diagnostics as EDF. All admitted deadlines must fit the 16-interval horizon.
    """
    return _dispatch(view, feedback, site_id, cluster_id, device_limits_kw, capacity_kw,
                     step_seconds, prefer_early=False)


def dispatch_early(view, feedback, *, site_id, cluster_id, device_limits_kw,
                   capacity_kw, step_seconds=900) -> DispatchDecision:
    """Prefer earlier aggregate delivery among plans serving all admitted requests.

    At each issue, retain the primary-only allocation if those requests cannot
    all be met by their currently declared deadlines.
    """
    return _dispatch(view, feedback, site_id, cluster_id, device_limits_kw, capacity_kw,
                     step_seconds, prefer_early=True)


def _dispatch(view, feedback, site_id, cluster_id, device_limits_kw, capacity_kw,
              step_seconds, *, prefer_early):
    admitted = dispatch_edf(view, feedback, site_id=site_id, cluster_id=cluster_id,
                            device_limits_kw=device_limits_kw, capacity_kw=capacity_kw,
                            step_seconds=step_seconds)
    if not admitted.remaining_kwh:
        return admitted
    issue = admitted.issue_time_utc
    end = step_end(issue, step_seconds)
    visible = {item.state.session_id: item.state for item in view.sessions}
    states = [visible[sid] for sid, _ in admitted.remaining_kwh]
    requests = [remaining for _, remaining in admitted.remaining_kwh]
    deadlines = [(s.declaration.departure_time_utc - issue) // (end - issue) for s in states]
    if max(deadlines) > MAX_HORIZON_STEPS:
        raise AdmissionError('OPTIMIZER_HORIZON', 'declared departure exceeds 16 steps')
    limits = [float(device_limits_kw[s.device_id]) for s in states]
    hours = step_seconds / 3600.0
    planned = _solve_first_step(deadlines, requests, limits, float(capacity_kw), hours, prefer_early)

    # Remove accepted solver roundoff before emitting a command. Exact binary
    # headroom prevents a series of decimal kW values from exceeding the site
    # limit. Bound energy under both exact duration and the plant's float hours.
    budget = Fraction(float(capacity_kw))
    duration = max(Fraction(step_seconds, 3600), Fraction(hours))
    actions = []
    for state, request, limit, power in zip(states, requests, limits, planned):
        bounded = max(0, min(Fraction(float(power)), Fraction(limit),
                             Fraction(request) / duration, budget))
        kw = float(bounded)
        if Fraction(kw) > bounded:
            kw = nextafter(kw, 0.0)
        if kw > 0:
            actions.append(ChargeAction(state.session_id, state.device_id, issue, end, kw))
            budget -= Fraction(kw)
    return replace(admitted, actions=tuple(actions))
