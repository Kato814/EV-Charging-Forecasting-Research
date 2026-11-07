"""Opt-in, dataset-free numerical probes; these are not dispatch policies."""

import math


class NumericalCheckError(RuntimeError):
    """A numerical probe did not satisfy its explicit acceptance conditions."""


def _finite(value) -> float:
    if value is None or isinstance(value, bool):
        raise NumericalCheckError("Expected a finite numerical result")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise NumericalCheckError("Expected a finite numerical result") from exc
    if not math.isfinite(result):
        raise NumericalCheckError("Expected a finite numerical result")
    return result


def _soc_action(status, value) -> dict | None:
    """Discard stale values for every status other than exact optimal."""
    return {"t": _finite(value)} if status == "optimal" else None


def run_soc_parameter_probe(solver: str = "CLARABEL") -> dict:
    """Solve two known norms and a deliberately infeasible synthetic problem."""
    import cvxpy as cp

    tolerance = 1e-6
    a = cp.Parameter(2, name="synthetic_vector")
    t = cp.Variable(name="toy_epigraph")
    problem = cp.Problem(cp.Minimize(t), [cp.SOC(t, a)])
    if not problem.is_dcp() or not problem.is_dpp():
        raise NumericalCheckError("SOC problem must satisfy DCP and DPP")

    def solve(candidate):
        try:
            candidate.solve(solver=solver, enforce_dpp=True)
        except cp.error.SolverError as exc:
            raise NumericalCheckError(f"SOC solver {solver!r} failed: {exc}") from exc

    cases = []
    for vector in ([3.0, 4.0], [6.0, 8.0]):
        a.value = vector
        solve(problem)
        action = _soc_action(problem.status, t.value)
        if action is None:
            raise NumericalCheckError(f"SOC solver returned {problem.status!r}; no action")
        expected = math.hypot(*vector)
        objective = _finite(problem.value)
        error = abs(objective - expected)
        residual = max(0.0, expected - action["t"])
        if max(error, residual, abs(action["t"] - objective)) > tolerance:
            raise NumericalCheckError("SOC objective or primal residual exceeds tolerance")
        cases.append({"a": vector, "status": str(problem.status), "objective": objective,
                      "expected_objective": expected, "absolute_error": error,
                      "primal_residual": residual, "action": action})

    a.value = [3.0, 4.0]
    infeasible = cp.Problem(cp.Minimize(t), [cp.SOC(t, a), t <= 4.0])
    solve(infeasible)
    rejected_action = _soc_action(infeasible.status, t.value)
    if infeasible.status != cp.INFEASIBLE or rejected_action is not None:
        raise NumericalCheckError(f"Expected exact infeasible status, got {infeasible.status!r}")
    return {
        "synthetic_only": True, "solver": solver,
        "is_dcp": bool(problem.is_dcp()), "is_dpp": bool(problem.is_dpp()),
        "cases": cases,
        "infeasible_case": {"a": [3.0, 4.0], "upper_bound": 4.0,
                            "status": str(infeasible.status), "action": None},
        "tolerances": {"objective_absolute": tolerance, "primal_residual": tolerance},
    }


def run_two_bus_powerflow_probe() -> dict:
    """Run a hand-built feeder; all ratings are assumed, not IEEE33 metadata."""
    import pandapower as pp

    assumed = {
        "bus_voltage_kv": 0.4, "slack_voltage_pu": 1.0, "line_length_km": 0.1,
        "line_r_ohm_per_km": 0.4, "line_x_ohm_per_km": 0.08,
        "line_c_nf_per_km": 0.0, "line_max_i_ka": 0.2,
        "load_cases_kw_kvar": [[5.0, 1.0], [10.0, 2.0]],
    }
    tolerance = 1e-8
    net = pp.create_empty_network()
    sending = pp.create_bus(net, vn_kv=assumed["bus_voltage_kv"])
    receiving = pp.create_bus(net, vn_kv=assumed["bus_voltage_kv"])
    pp.create_ext_grid(net, bus=sending, vm_pu=assumed["slack_voltage_pu"])
    pp.create_line_from_parameters(
        net, from_bus=sending, to_bus=receiving, length_km=assumed["line_length_km"],
        r_ohm_per_km=assumed["line_r_ohm_per_km"],
        x_ohm_per_km=assumed["line_x_ohm_per_km"],
        c_nf_per_km=assumed["line_c_nf_per_km"], max_i_ka=assumed["line_max_i_ka"],
    )
    load = pp.create_load(net, bus=receiving, p_mw=5.0 / 1000.0, q_mvar=1.0 / 1000.0)
    cases = []
    for load_kw, load_kvar in assumed["load_cases_kw_kvar"]:
        net.load.at[load, "p_mw"] = load_kw / 1000.0
        net.load.at[load, "q_mvar"] = load_kvar / 1000.0
        try:
            pp.runpp(net, numba=False)
        except pp.LoadflowNotConverged as exc:
            raise NumericalCheckError("Synthetic power flow did not converge") from exc
        if not net.converged:
            raise NumericalCheckError("Synthetic power flow did not converge")
        slack = _finite(net.res_ext_grid.p_mw.sum())
        demand = _finite(net.res_load.at[load, "p_mw"])
        reactive = _finite(net.res_load.at[load, "q_mvar"])
        loss = _finite(net.res_line.pl_mw.sum())
        voltage = _finite(net.res_bus.at[receiving, "vm_pu"])
        residual = abs(slack - demand - loss)
        if not (loss > 0 and slack > demand and 0.9 < voltage < 1.0 and residual < tolerance):
            raise NumericalCheckError("Power-flow sign, voltage or conservation check failed")
        cases.append({
            "load_kw": load_kw, "load_kvar": load_kvar, "load_p_mw": demand,
            "load_q_mvar": reactive, "status": "converged", "converged": bool(net.converged),
            "slack_p_mw": slack, "line_loss_mw": loss, "receiving_voltage_pu": voltage,
            "voltage_drop_pu": 1.0 - voltage, "power_balance_residual_mw": residual,
        })
    low, high = cases
    if not (high["line_loss_mw"] > low["line_loss_mw"]
            and high["voltage_drop_pu"] > low["voltage_drop_pu"]):
        raise NumericalCheckError("Larger load must increase losses and voltage drop")
    return {"synthetic_only": True, "assumed_parameters": assumed, "cases": cases,
            "tolerances": {"power_balance_absolute_mw": tolerance}}
