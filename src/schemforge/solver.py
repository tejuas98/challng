"""Deterministic first-principles circuit & logic solvers.

Completely decoupled from vision/language models. Computes exact boolean logic
states, passive switch/bridge reachability, exact rational series-parallel
equivalent resistance (fractions.Fraction), single-fault isolation hypotheses,
and counterfactual pair diffs directly from SchematicSpec netlists.
"""

from __future__ import annotations

from collections import deque
from fractions import Fraction
from typing import Any, Optional

from schemforge.netlist import (
    Component,
    ComponentKind,
    SchematicSpec,
    SolverProof,
    TaskFamily,
)

def _component_map(spec: SchematicSpec) -> dict[str, Component]:
    return {c.id: c for c in spec.components}

def _evaluate_gate(kind: ComponentKind, inputs: list[bool]) -> bool:
    if kind == ComponentKind.GATE_NOT:
        if len(inputs) != 1:
            raise ValueError(f"NOT gate expects 1 input, got {len(inputs)}")
        return not inputs[0]
    if len(inputs) < 2:
        raise ValueError(f"{kind.value} gate expects >= 2 inputs, got {len(inputs)}")
    if kind == ComponentKind.GATE_AND:
        return all(inputs)
    if kind == ComponentKind.GATE_OR:
        return any(inputs)
    if kind == ComponentKind.GATE_NAND:
        return not all(inputs)
    if kind == ComponentKind.GATE_NOR:
        return not any(inputs)
    if kind == ComponentKind.GATE_XOR:
        res = False
        for val in inputs:
            res = res ^ val
        return res
    raise ValueError(f"Unsupported gate kind: {kind}")

def solve_logic_network(
    spec: SchematicSpec,
    target_led_id: Optional[str] = None,
    fault_override: Optional[tuple[str, str]] = None,
    switch_toggle_override: Optional[str] = None,
) -> SolverProof:
    """Solve directed logic + switch/fuse netlist deterministically.

    fault_override: Optional (component_id, fault_mode) where fault_mode is one of
      'OPEN', 'STUCK_HIGH', 'STUCK_LOW', 'INVERT_BUBBLE'. Used cleanly by fault
      diagnosis without mutating the original spec.
    switch_toggle_override: Optional switch component ID treated as toggled to
      its opposite blade state during hypothetical perturbation queries.
    """
    comps = _component_map(spec)
    incoming: dict[tuple[str, str], tuple[str, str]] = {}
    for ca, pa, cb, pb in spec.connections:
        incoming[(cb, pb)] = (ca, pa)

    memo: dict[str, bool] = {}
    visiting: set[str] = set()
    steps: list[str] = []

    def eval_comp(cid: str) -> bool:
        if cid in memo:
            return memo[cid]
        if cid in visiting:
            raise ValueError(f"Combinational cycle detected at {cid}")
        visiting.add(cid)

        comp = comps[cid]
        f_mode = fault_override[1] if (fault_override and fault_override[0] == cid) else comp.stuck_fault

        val: bool
        if comp.kind == ComponentKind.SOURCE:
            if f_mode == "OPEN" or f_mode == "STUCK_LOW":
                val = False
                steps.append(f"{cid} (SOURCE, FAULT={f_mode}): output = LOW (0)")
            else:
                val = bool(comp.voltage_level if comp.voltage_level is not None else 1)
                steps.append(f"{cid} (SOURCE): supply = {'HIGH (1)' if val else 'LOW (0)'}")

        elif comp.kind == ComponentKind.GND:
            val = False
            steps.append(f"{cid} (GND): reference = LOW (0)")

        elif comp.kind == ComponentKind.SWITCH:
            src_edge = incoming.get((cid, "in"))
            upstream = eval_comp(src_edge[0]) if src_edge else True
            is_closed = bool(comp.closed)
            toggled_note = ""
            if switch_toggle_override and switch_toggle_override == cid:
                is_closed = not is_closed
                toggled_note = " [TOGGLED]"
            if f_mode == "OPEN" or f_mode == "STUCK_LOW":
                is_closed = False
            elif f_mode == "STUCK_HIGH":
                is_closed = True
            val = upstream and is_closed
            state_str = ("CLOSED" if is_closed else "OPEN") + toggled_note
            if f_mode:
                state_str += f" [FAULT:{f_mode}]"
            steps.append(
                f"{cid} (SWITCH {state_str}): upstream={'1' if upstream else '0'} -> out={'1' if val else '0'}"
            )

        elif comp.kind == ComponentKind.FUSE:
            src_edge = incoming.get((cid, "in"))
            upstream = eval_comp(src_edge[0]) if src_edge else True
            is_intact = bool(comp.intact)
            if f_mode == "OPEN" or f_mode == "STUCK_LOW":
                is_intact = False
            val = upstream and is_intact
            state_str = "INTACT" if is_intact else "BLOWN"
            if f_mode:
                state_str += f" [FAULT:{f_mode}]"
            steps.append(
                f"{cid} (FUSE {state_str}): upstream={'1' if upstream else '0'} -> out={'1' if val else '0'}"
            )

        elif comp.kind in (ComponentKind.RESISTOR, ComponentKind.TEST_POINT, ComponentKind.JUNCTION):
            src_edge = incoming.get((cid, "in")) or incoming.get((cid, "p1"))
            val = eval_comp(src_edge[0]) if src_edge else False
            steps.append(f"{cid} ({comp.kind.value}): propagates {'1' if val else '0'}")

        elif comp.kind in (
            ComponentKind.GATE_AND,
            ComponentKind.GATE_OR,
            ComponentKind.GATE_NAND,
            ComponentKind.GATE_NOR,
            ComponentKind.GATE_XOR,
            ComponentKind.GATE_NOT,
        ):
            in_ports = sorted(
                [pb for (_, _, cb, pb) in spec.connections if cb == cid]
            )
            in_vals = [eval_comp(incoming[(cid, p)][0]) for p in in_ports]
            if f_mode == "STUCK_LOW":
                val = False
            elif f_mode == "STUCK_HIGH":
                val = True
            else:
                val = _evaluate_gate(comp.kind, in_vals)
                if f_mode == "INVERT_BUBBLE":
                    val = not val
            gate_name = comp.kind.value.replace("gate_", "").upper()
            in_bits = ",".join("1" if b else "0" for b in in_vals)
            extra = f" [FAULT:{f_mode}]" if f_mode else ""
            steps.append(f"{cid} ({gate_name}{extra}): inputs=[{in_bits}] -> out={'1' if val else '0'}")

        elif comp.kind in (ComponentKind.LED, ComponentKind.PROBE):
            src_edge = incoming.get((cid, "in"))
            val = eval_comp(src_edge[0]) if src_edge else False
            steps.append(f"{cid} ({comp.kind.value}): state = {'ON (HIGH)' if val else 'OFF (LOW)'}")

        else:
            raise ValueError(f"Unhandled component kind {comp.kind}")

        visiting.remove(cid)
        memo[cid] = val
        return val

    targets = [c.id for c in spec.components if c.kind in (ComponentKind.LED, ComponentKind.PROBE)]
    for tid in targets:
        eval_comp(tid)

    if target_led_id is None:
        leds = sorted(c.id for c in spec.components if c.kind == ComponentKind.LED)
        target_led_id = leds[0] if leds else targets[0]

    target_state = memo[target_led_id]
    answer = "ON" if target_state else "OFF"
    return SolverProof(
        answer=answer,
        answer_type="binary",
        choices=["ON", "OFF"],
        node_values={k: ("ON" if v else "OFF") for k, v in sorted(memo.items())},
        proof_steps=steps,
    )

def solve_conductivity_graph(spec: SchematicSpec) -> SolverProof:
    """Solve multi-rail undirected switch/fuse/bridge conductivity network.

    Determines which target lamps/test-points are energized by an active VCC source.
    Switches that are CLOSED and fuses that are INTACT act as conducting edges.
    Only explicit `spec.connections` carry current (bridge crossings are isolated).
    """
    comps = _component_map(spec)
    adj: dict[str, list[str]] = {c.id: [] for c in spec.components}

    def is_conducting(comp: Component) -> bool:
        if comp.kind == ComponentKind.SWITCH:
            return bool(comp.closed)
        if comp.kind == ComponentKind.FUSE:
            return bool(comp.intact)
        return True

    for ca, _, cb, _ in spec.connections:
        if is_conducting(comps[ca]) and is_conducting(comps[cb]):
            adj[ca].append(cb)
            adj[cb].append(ca)

    sources = [
        c.id
        for c in spec.components
        if c.kind == ComponentKind.SOURCE and (c.voltage_level is None or c.voltage_level > 0)
    ]

    visited: set[str] = set()
    parent: dict[str, Optional[str]] = {}
    q: deque[str] = deque()
    for s in sources:
        visited.add(s)
        parent[s] = None
        q.append(s)

    while q:
        curr = q.popleft()
        for nxt in sorted(adj[curr]):
            if nxt not in visited:
                visited.add(nxt)
                parent[nxt] = curr
                q.append(nxt)

    lamps = sorted(c.id for c in spec.components if c.kind == ComponentKind.LED)
    energized = [lid for lid in lamps if lid in visited]

    steps: list[str] = [f"Active VCC sources: {', '.join(sources)}"]
    for lid in lamps:
        if lid in visited:
            path = []
            cur: Optional[str] = lid
            while cur is not None:
                path.append(cur)
                cur = parent[cur]
            path.reverse()
            steps.append(f"{lid}: ENERGIZED via path {' -> '.join(path)}")
        else:
            steps.append(f"{lid}: ISOLATED (blocked by OPEN switch, BLOWN fuse, or non-connected bridge crossing)")

    target_lamp = spec.metadata.get("target_lamp")
    if target_lamp:
        ans = "YES" if target_lamp in energized else "NO"
        return SolverProof(
            answer=ans,
            answer_type="binary",
            choices=["YES", "NO"],
            node_values={lid: (lid in visited) for lid in lamps},
            proof_steps=steps,
        )

    ans_str = ", ".join(energized) if energized else "NONE"
    choices = spec.metadata.get("mcq_choices", [])
    return SolverProof(
        answer=ans_str,
        answer_type="mcq" if choices else "list",
        choices=choices,
        node_values={lid: (lid in visited) for lid in lamps},
        proof_steps=steps,
    )

def eval_resistance_tree(tree: dict[str, Any], switch_states: dict[str, bool]) -> tuple[Optional[Fraction], list[str]]:
    """Exact rational computation of a Series-Parallel switched resistor tree.

    Tree schema:
      {"type": "resistor", "id": "R1", "ohm": 60, "switch": Optional["SW1"]}
      {"type": "series", "children": [...]}
      {"type": "parallel", "children": [...]}

    Returns (Fraction or None if open-circuit infinite resistance, proof_steps).
    """
    steps: list[str] = []

    def _eval(node: dict[str, Any], label: str) -> Optional[Fraction]:
        ntype = node["type"]
        if ntype == "resistor":
            rid = node["id"]
            ohm = Fraction(int(node["ohm"]))
            sw = node.get("switch")
            if sw is not None and not switch_states.get(sw, True):
                steps.append(f"Branch {rid} ({ohm} Ohm): switch {sw} is OPEN -> open circuit (ignored)")
                return None
            sw_note = f" (via CLOSED {sw})" if sw else ""
            steps.append(f"Element {rid}{sw_note} = {int(ohm)} Ohm")
            return ohm

        if ntype == "series":
            total = Fraction(0)
            parts: list[str] = []
            for idx, child in enumerate(node["children"]):
                val = _eval(child, f"{label}.S{idx}")
                if val is None:
                    steps.append(f"Series group {label}: contains an OPEN element -> OPEN CIRCUIT")
                    return None
                total += val
                parts.append(str(val))
            steps.append(f"Series sum ({' + '.join(parts)}) = {total} Ohm")
            return total

        if ntype == "parallel":
            inv_sum = Fraction(0)
            active_vals: list[Fraction] = []
            for idx, child in enumerate(node["children"]):
                val = _eval(child, f"{label}.P{idx}")
                if val is not None:
                    if val == 0:
                        steps.append(f"Parallel group {label}: 0 Ohm short path -> 0 Ohm")
                        return Fraction(0)
                    active_vals.append(val)
                    inv_sum += Fraction(1, 1) / val
            if not active_vals:
                steps.append(f"Parallel group {label}: all branches OPEN -> OPEN CIRCUIT")
                return None
            if len(active_vals) == 1:
                steps.append(f"Parallel group {label}: single active branch = {active_vals[0]} Ohm")
                return active_vals[0]
            req = Fraction(1, 1) / inv_sum
            branch_str = " || ".join(str(v) for v in active_vals)
            steps.append(f"Parallel combine ({branch_str}) = {req} Ohm")
            return req

        raise ValueError(f"Unknown resistance node type: {ntype}")

    result = _eval(tree, "ROOT")
    return result, steps

def _format_fraction_unit(val: Fraction, unit: str) -> str:
    if val.denominator == 1:
        return f"{val.numerator} {unit}"
    return f"{round(float(val), 2):g} {unit}"

def solve_equivalent_resistance(spec: SchematicSpec) -> SolverProof:
    tree = spec.metadata.get("resistance_tree")
    if not tree:
        raise ValueError("SchematicSpec missing metadata['resistance_tree']")

    comps = _component_map(spec)
    switch_states = {
        c.id: bool(c.closed)
        for c in comps.values()
        if c.kind == ComponentKind.SWITCH
    }
    fuses_ok = all(bool(c.intact) for c in comps.values() if c.kind == ComponentKind.FUSE)

    req, steps = eval_resistance_tree(tree, switch_states)
    supply_volts = spec.metadata.get("supply_volts")
    if spec.metadata.get("question_variant") == "current_ma" and supply_volts:
        if not fuses_ok:
            steps.append("Main protection fuse is BLOWN -> 0 mA")
            answer = "0 mA"
            exact_ma = "0"
        elif req is None or req == 0:
            steps.append("Load network is OPEN CIRCUIT -> 0 mA")
            answer = "0 mA"
            exact_ma = "0"
        else:
            curr_ma = Fraction(int(supply_volts) * 1000, 1) / req
            answer = _format_fraction_unit(curr_ma, "mA")
            exact_ma = str(curr_ma)
            steps.append(f"Ohm's Law: I = {supply_volts}V / ({req} Ohm) = {answer}")
        return SolverProof(
            answer=answer,
            answer_type="numeric",
            choices=spec.metadata.get("mcq_choices", []),
            node_values={
                "equivalent_resistance_exact": str(req),
                "current_ma_exact": exact_ma,
                "switch_states": switch_states,
            },
            proof_steps=steps,
        )

    if req is None:
        answer = "OPEN"
    else:
        answer = _format_fraction_unit(req, "Ohm")

    return SolverProof(
        answer=answer,
        answer_type="numeric",
        choices=spec.metadata.get("mcq_choices", []),
        node_values={"equivalent_resistance_exact": str(req), "switch_states": switch_states},
        proof_steps=steps,
    )

def solve_fault_diagnosis(spec: SchematicSpec) -> SolverProof:
    """Verify exact probe readings match one unique fault candidate."""
    probes: dict[str, str] = spec.metadata.get("visible_probes", {})
    candidates: list[dict[str, str]] = spec.metadata.get("fault_candidates", [])
    if not probes or not candidates:
        raise ValueError("Fault diagnosis spec requires visible_probes and fault_candidates")

    matching: list[tuple[dict[str, str], SolverProof]] = []
    all_steps: list[str] = [
        f"Observed visual probes: {', '.join(f'{k}={v}' for k, v in sorted(probes.items()))}"
    ]

    for cand in candidates:
        cid = cand["component_id"]
        fmode = cand["fault_mode"]
        label = cand["label"]
        res = solve_logic_network(spec, fault_override=(cid, fmode))
        matches = all(res.node_values.get(pk) == pv for pk, pv in probes.items())
        probe_out = ", ".join(f"{pk}={res.node_values.get(pk)}" for pk in sorted(probes))
        all_steps.append(f"Hypothesis {label} ({cid} {fmode}): predicts [{probe_out}] -> {'MATCH' if matches else 'REJECT'}")
        if matches:
            matching.append((cand, res))

    if len(matching) != 1:
        raise ValueError(
            f"Fault diagnosis ambiguity error: expected exactly 1 matching fault, got {len(matching)}"
        )

    winner = matching[0][0]
    return SolverProof(
        answer=winner["label"],
        answer_type="mcq",
        choices=[c["label"] for c in candidates],
        node_values={"probes": probes, "winning_fault": winner},
        proof_steps=all_steps,
    )

def solve_component_audit(spec: SchematicSpec) -> SolverProof:
    """Solve deterministic compliance & component counting queries from spec."""
    audit_query = spec.metadata.get("audit_query", {})
    qtype = audit_query.get("type")
    comps = spec.components
    steps: list[str] = []

    if qtype == "count_resistors_min_ohm":
        threshold = int(audit_query["threshold_ohm"])
        matches = sorted(
            c.id
            for c in comps
            if c.kind == ComponentKind.RESISTOR and (c.resistance_ohm or 0) >= threshold
        )
        steps.append(
            f"Resistors with value >= {threshold} Ohm: {', '.join(matches) if matches else 'none'} (count={len(matches)})"
        )
        return SolverProof(
            answer=str(len(matches)),
            answer_type="numeric",
            node_values={"matching_ids": matches},
            proof_steps=steps,
        )

    if qtype == "count_inverting_gates":
        inverting_kinds = {ComponentKind.GATE_NOT, ComponentKind.GATE_NAND, ComponentKind.GATE_NOR}
        matches = sorted(c.id for c in comps if c.kind in inverting_kinds)
        steps.append(
            f"Gates with IEEE inversion bubble (NOT/NAND/NOR): {', '.join(matches)} (count={len(matches)})"
        )
        return SolverProof(
            answer=str(len(matches)),
            answer_type="numeric",
            node_values={"matching_ids": matches},
            proof_steps=steps,
        )

    if qtype == "count_closed_switches":
        matches = sorted(c.id for c in comps if c.kind == ComponentKind.SWITCH and c.closed)
        all_sw = sorted(c.id for c in comps if c.kind == ComponentKind.SWITCH)
        steps.append(
            f"All switches: {', '.join(all_sw)}; switches in CLOSED position: {', '.join(matches)} (count={len(matches)})"
        )
        return SolverProof(
            answer=str(len(matches)),
            answer_type="numeric",
            node_values={"matching_ids": matches},
            proof_steps=steps,
        )

    if qtype == "count_open_switches":
        matches = sorted(c.id for c in comps if c.kind == ComponentKind.SWITCH and not c.closed)
        all_sw = sorted(c.id for c in comps if c.kind == ComponentKind.SWITCH)
        steps.append(
            f"All switches: {', '.join(all_sw)}; switches in OPEN position: {', '.join(matches)} (count={len(matches)})"
        )
        return SolverProof(
            answer=str(len(matches)),
            answer_type="numeric",
            node_values={"matching_ids": matches},
            proof_steps=steps,
        )

    raise ValueError(f"Unsupported audit query type: {qtype}")

def solve_whole_system(spec: SchematicSpec) -> SolverProof:
    """Solve integrated whole-board electromechanical + digital + Ohm's law circuit."""
    variant = spec.metadata.get("question_variant", "system_current_ma")

    if variant == "what_if_switch_toggle":
        sw_id = spec.metadata["toggle_switch_id"]
        target = spec.metadata.get("target_led", "L1")
        base_proof = solve_logic_network(spec, target_led_id=target)
        toggled_proof = solve_logic_network(spec, target_led_id=target, switch_toggle_override=sw_id)
        steps = [
            f"Baseline {target} = {base_proof.answer}",
            f"Suppose {sw_id} is toggled to opposite position:",
            *toggled_proof.proof_steps,
            f"Final state of {target} after toggling {sw_id} = {toggled_proof.answer}",
        ]
        return SolverProof(
            answer=toggled_proof.answer,
            answer_type="binary",
            choices=["ON", "OFF"],
            node_values={"baseline": base_proof.answer, "toggled": toggled_proof.answer, "switch": sw_id},
            proof_steps=steps,
        )

    if variant == "multi_led_vector":
        proof = solve_logic_network(spec)
        l1 = proof.node_values["L1"]
        l2 = proof.node_values["L2"]
        ans = f"L1={l1}, L2={l2}"
        steps = [*proof.proof_steps, f"Combined indicator vector: {ans}"]
        return SolverProof(
            answer=ans,
            answer_type="mcq",
            choices=["L1=ON, L2=ON", "L1=ON, L2=OFF", "L1=OFF, L2=ON", "L1=OFF, L2=OFF"],
            node_values=proof.node_values,
            proof_steps=steps,
        )

    target = spec.metadata.get("target_led", "L1")
    logic_proof = solve_logic_network(spec, target_led_id=target)
    tree = spec.metadata.get("resistance_tree")
    supply_volts = int(spec.metadata.get("supply_volts", 12))
    steps = [*logic_proof.proof_steps]
    if logic_proof.answer != "ON":
        steps.append(f"Load relay {target} is OFF -> load resistor bank disconnected -> 0 mA")
        return SolverProof(
            answer="0 mA",
            answer_type="numeric",
            node_values={"driver_enabled": False, "current_ma_exact": "0"},
            proof_steps=steps,
        )
    if not tree:
        raise ValueError("WHOLE_SYSTEM current_ma requires metadata['resistance_tree']")
    req, rsteps = eval_resistance_tree(tree, {})
    steps.extend(rsteps)
    if req is None or req == 0:
        steps.append("Load bank open-circuit -> 0 mA")
        return SolverProof(
            answer="0 mA",
            answer_type="numeric",
            node_values={"driver_enabled": True, "current_ma_exact": "0"},
            proof_steps=steps,
        )
    curr_ma = Fraction(supply_volts * 1000, 1) / req
    ans = _format_fraction_unit(curr_ma, "mA")
    steps.append(f"Load driver {target}=ON; Ohm's Law: I = {supply_volts}V / ({req} Ohm) = {ans}")
    return SolverProof(
        answer=ans,
        answer_type="numeric",
        node_values={"driver_enabled": True, "equivalent_resistance_exact": str(req), "current_ma_exact": str(curr_ma)},
        proof_steps=steps,
    )

def solve_task(spec: SchematicSpec, family: TaskFamily) -> SolverProof:
    """Unified dispatcher computing independent deterministic ground truth."""
    if family == TaskFamily.STATE_PROPAGATION:
        variant = spec.metadata.get("question_variant")
        target = spec.metadata.get("target_led")
        if variant == "what_if_switch_toggle":
            sw_id = spec.metadata["toggle_switch_id"]
            base_p = solve_logic_network(spec, target_led_id=target)
            tog_p = solve_logic_network(spec, target_led_id=target, switch_toggle_override=sw_id)
            return SolverProof(
                answer=tog_p.answer,
                answer_type="binary",
                choices=["ON", "OFF"],
                node_values={"baseline": base_p.answer, **tog_p.node_values},
                proof_steps=[f"Baseline {target}={base_p.answer}", f"Toggle {sw_id}:", *tog_p.proof_steps],
            )
        if variant == "multi_led_vector":
            p = solve_logic_network(spec)
            ans = f"L1={p.node_values['L1']}, L2={p.node_values['L2']}"
            return SolverProof(
                answer=ans,
                answer_type="mcq",
                choices=["L1=ON, L2=ON", "L1=ON, L2=OFF", "L1=OFF, L2=ON", "L1=OFF, L2=OFF"],
                node_values=p.node_values,
                proof_steps=[*p.proof_steps, f"Combined output: {ans}"],
            )
        return solve_logic_network(spec, target_led_id=target)

    if family == TaskFamily.BRIDGE_VS_JUNCTION:
        return solve_conductivity_graph(spec)

    if family == TaskFamily.EQUIVALENT_RESISTANCE:
        return solve_equivalent_resistance(spec)

    if family == TaskFamily.FAULT_DIAGNOSIS:
        return solve_fault_diagnosis(spec)

    if family == TaskFamily.COMPONENT_AUDIT:
        return solve_component_audit(spec)

    if family == TaskFamily.WHOLE_SYSTEM:
        return solve_whole_system(spec)

    if family == TaskFamily.COUNTERFACTUAL_PAIR:
        if spec.secondary_panel is None:
            raise ValueError("COUNTERFACTUAL_PAIR requires secondary_panel")
        target = spec.metadata.get("target_led")
        proof_a = solve_logic_network(spec, target_led_id=target)
        proof_b = solve_logic_network(spec.secondary_panel, target_led_id=target)
        changed = proof_a.answer != proof_b.answer
        diff_summary = spec.metadata.get("panel_diff_description", "")
        steps = [
            f"Panel A target LED ({target}) = {proof_a.answer}",
            f"Panel B target LED ({target}) = {proof_b.answer}",
            f"Structural mutation: {diff_summary}",
            f"Did {target} change state between Panel A and Panel B? -> {'YES' if changed else 'NO'}",
        ]
        if spec.metadata.get("ask_panel_b_state"):
            return SolverProof(
                answer=f"{proof_a.answer} -> {proof_b.answer}",
                answer_type="mcq",
                choices=["ON -> OFF", "OFF -> ON", "ON -> ON", "OFF -> OFF"],
                node_values={"panel_a": proof_a.answer, "panel_b": proof_b.answer},
                proof_steps=steps,
            )
        return SolverProof(
            answer="YES" if changed else "NO",
            answer_type="binary",
            choices=["YES", "NO"],
            node_values={"panel_a": proof_a.answer, "panel_b": proof_b.answer},
            proof_steps=steps,
        )

    raise ValueError(f"Unsupported task family: {family}")
