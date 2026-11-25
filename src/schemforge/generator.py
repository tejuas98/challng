"""Procedural multi-family schematic generator with counterfactual & invariance pairing.

Each task family constructs a mathematically sound SchematicSpec graph with clean
orthogonal Manhattan channels, automatically computed crossing bridge jumps and
solder junction dots, zero hidden assumptions, and independent exact solver proof.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Optional

from schemforge.netlist import (
    BridgeJump,
    Component,
    ComponentKind,
    DegradationProfile,
    LabelMode,
    Point,
    SchematicSpec,
    TaskFamily,
    ThemeStyle,
    DifficultyTier,
    WireNet,
    WireSegment,
)
from schemforge.solver import (
    eval_resistance_tree,
    solve_conductivity_graph,
    solve_logic_network,
    solve_task,
)

PARALLEL_PAIRS_EXACT: list[tuple[int, int]] = [
    (60, 60),
    (40, 40),
    (100, 100),
    (120, 60),
    (60, 30),
    (120, 40),
    (80, 80),
    (150, 100),
    (120, 120),
    (90, 180),
    (200, 200),
    (240, 80),
]

WHOLE_LOAD_PRESETS: list[tuple[int, int, int, int]] = [
    (12, 30, 60, 60),
    (24, 40, 120, 60),
    (12, 30, 120, 40),
    (24, 10, 100, 100),
    (12, 20, 120, 120),
    (24, 60, 120, 120),
]

SINGLE_RESISTOR_VALUES: list[int] = [10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 240]

GATE_POOL_NO_NOT = [
    ComponentKind.GATE_AND,
    ComponentKind.GATE_OR,
    ComponentKind.GATE_NAND,
    ComponentKind.GATE_NOR,
    ComponentKind.GATE_XOR,
]

INVERT_TWIN_MAP = {
    ComponentKind.GATE_AND: ComponentKind.GATE_NAND,
    ComponentKind.GATE_NAND: ComponentKind.GATE_AND,
    ComponentKind.GATE_OR: ComponentKind.GATE_NOR,
    ComponentKind.GATE_NOR: ComponentKind.GATE_OR,
}

def compute_wire_topology(nets: list[WireNet]) -> tuple[list[WireNet], list[BridgeJump]]:
    """Decompose polylines into segments and compute exact cross-net bridge jumps."""
    all_segments: list[WireSegment] = []
    for net in nets:
        segs: list[WireSegment] = []
        pts = net.points
        for i in range(len(pts) - 1):
            p1, p2 = pts[i], pts[i + 1]
            if abs(p1.x - p2.x) < 1e-6 and abs(p1.y - p2.y) < 1e-6:
                continue
            segs.append(WireSegment(net_id=net.net_id, p1=p1, p2=p2))
        for s in net.segments:
            if s not in segs:
                segs.append(s)
        net.segments = segs
        all_segments.extend(segs)

    bridges: list[BridgeJump] = []
    seen_centers: set[tuple[int, int]] = set()

    for i, s1 in enumerate(all_segments):
        for s2 in all_segments[i + 1 :]:
            if s1.net_id == s2.net_id:
                continue
            s1_horiz = abs(s1.p1.y - s1.p2.y) < 1e-3 and abs(s1.p1.x - s1.p2.x) > 1.0
            s1_vert = abs(s1.p1.x - s1.p2.x) < 1e-3 and abs(s1.p1.y - s1.p2.y) > 1.0
            s2_horiz = abs(s2.p1.y - s2.p2.y) < 1e-3 and abs(s2.p1.x - s2.p2.x) > 1.0
            s2_vert = abs(s2.p1.x - s2.p2.x) < 1e-3 and abs(s2.p1.y - s2.p2.y) > 1.0

            h_seg, v_seg = (None, None)
            if s1_horiz and s2_vert:
                h_seg, v_seg = s1, s2
            elif s2_horiz and s1_vert:
                h_seg, v_seg = s2, s1

            if h_seg and v_seg:
                hx_min, hx_max = sorted([h_seg.p1.x, h_seg.p2.x])
                vy_min, vy_max = sorted([v_seg.p1.y, v_seg.p2.y])
                vx = v_seg.p1.x
                hy = h_seg.p1.y
                if hx_min + 8 < vx < hx_max - 8 and vy_min + 8 < hy < vy_max - 8:
                    key = (round(vx), round(hy))
                    if key not in seen_centers:
                        seen_centers.add(key)
                        bridges.append(BridgeJump(center=Point(x=vx, y=hy), axis="vertical", radius=10.0))

    return nets, bridges

def _make_source(cid: str, x: float, y: float, level: int = 1, volts: int = 5) -> Component:
    return Component(
        id=cid,
        kind=ComponentKind.SOURCE,
        center=Point(x=x, y=y),
        voltage_level=level,
        value_text=f"{volts}V" if level else "0V",
        ports={"out": Point(x=x + 26, y=y)},
    )

def _make_switch(cid: str, x: float, y: float, closed: bool) -> Component:
    return Component(
        id=cid,
        kind=ComponentKind.SWITCH,
        center=Point(x=x, y=y),
        closed=closed,
        ports={"in": Point(x=x - 30, y=y), "out": Point(x=x + 30, y=y)},
    )

def _make_fuse(cid: str, x: float, y: float, intact: bool) -> Component:
    return Component(
        id=cid,
        kind=ComponentKind.FUSE,
        center=Point(x=x, y=y),
        intact=intact,
        value_text="2A",
        ports={"in": Point(x=x - 30, y=y), "out": Point(x=x + 30, y=y)},
    )

def _make_resistor(cid: str, x: float, y: float, ohm: int) -> Component:
    return Component(
        id=cid,
        kind=ComponentKind.RESISTOR,
        center=Point(x=x, y=y),
        resistance_ohm=ohm,
        value_text=f"{ohm} Ohm",
        ports={"in": Point(x=x - 34, y=y), "p1": Point(x=x - 34, y=y), "out": Point(x=x + 34, y=y), "p2": Point(x=x + 34, y=y)},
    )

def _make_gate(cid: str, kind: ComponentKind, x: float, y: float) -> Component:
    if kind == ComponentKind.GATE_NOT:
        ports = {"in0": Point(x=x - 34, y=y), "out": Point(x=x + 38, y=y)}
    else:
        ports = {
            "in0": Point(x=x - 38, y=y - 14),
            "in1": Point(x=x - 38, y=y + 14),
            "out": Point(x=x + 42, y=y),
        }
    return Component(id=cid, kind=kind, center=Point(x=x, y=y), ports=ports)

def _make_led(cid: str, x: float, y: float) -> Component:
    return Component(
        id=cid,
        kind=ComponentKind.LED,
        center=Point(x=x, y=y),
        ports={"in": Point(x=x - 24, y=y), "gnd": Point(x=x + 24, y=y)},
    )

def _route_orthogonal(
    net_id: str, p_start: Point, p_end: Point, mid_x: float
) -> list[Point]:
    if abs(p_start.y - p_end.y) < 1e-3:
        return [p_start, p_end]
    return [p_start, Point(x=mid_x, y=p_start.y), Point(x=mid_x, y=p_end.y), p_end]

def _generate_arbitrary_dag_core(
    rng: random.Random,
    difficulty: DifficultyTier,
    label_mode: LabelMode,
    seed: int,
) -> tuple[SchematicSpec, str, list[str]]:
    """Synthesize a genuinely unscripted multi-layer random combinational DAG circuit."""
    n_inputs = 3 if difficulty == DifficultyTier.EASY else (4 if difficulty == DifficultyTier.MEDIUM else 5)
    n_hidden_layers = 2 if difficulty == DifficultyTier.EASY else 3
    y_min, y_max = 125.0, 565.0
    x_cols = [
        round(100.0 + i * (980.0 / (n_hidden_layers + 2)), 1)
        for i in range(n_hidden_layers + 3)
    ]

    comps: list[Component] = []
    conns: list[tuple[str, str, str, str]] = []
    nets: list[WireNet] = []

    vcc_y = 140.0
    vcc = _make_source("VCC", 75.0, vcc_y, level=1)
    comps.append(vcc)

    input_nodes: list[Component] = []
    sw_ids: list[str] = []
    bus_x = round((75.0 + x_cols[1]) * 0.52, 1)
    sw_step = (y_max - y_min) / max(1, n_inputs - 1)
    bus_ys = [round(y_min + i * sw_step, 1) for i in range(n_inputs)]
    bus_segs: list[WireSegment] = [
        WireSegment(net_id="NET_VCC", p1=vcc.ports["out"], p2=Point(x=bus_x, y=vcc_y)),
        WireSegment(net_id="NET_VCC", p1=Point(x=bus_x, y=vcc_y), p2=Point(x=bus_x, y=bus_ys[-1])),
    ]
    bus_dots: list[Point] = [Point(x=bus_x, y=vcc_y)]

    for i, sy in enumerate(bus_ys):
        sw_id = f"SW{i + 1}"
        sw = _make_switch(sw_id, x_cols[1], sy, closed=rng.choice([True, False]))
        comps.append(sw)
        sw_ids.append(sw_id)
        conns.append(("VCC", "out", sw_id, "in"))
        if 0 < i < n_inputs - 1:
            bus_dots.append(Point(x=bus_x, y=sy))
        bus_segs.append(WireSegment(net_id="NET_VCC", p1=Point(x=bus_x, y=sy), p2=sw.ports["in"]))

        if i == 0 and rng.random() < 0.65:
            f1 = _make_fuse("F1", round((x_cols[1] + x_cols[2]) * 0.45, 1), sy, intact=rng.choices([True, False], weights=[0.8, 0.2])[0])
            comps.append(f1)
            conns.append((sw_id, "out", "F1", "in"))
            nets.append(WireNet(net_id=f"N_{sw_id}_F1", points=[sw.ports["out"], f1.ports["in"]]))
            input_nodes.append(f1)
        else:
            input_nodes.append(sw)

    nets.append(WireNet(net_id="NET_VCC", points=[], segments=bus_segs, junction_dots=bus_dots))

    prev_layer = list(input_nodes)
    gate_idx = 1
    wire_idx = 1

    for lyr in range(n_hidden_layers):
        col_x = x_cols[lyr + 2]
        is_last_gate_layer = lyr == n_hidden_layers - 1
        n_gates = 1 if is_last_gate_layer else rng.randint(2, 3)
        gy_step = (y_max - y_min) / max(1, n_gates - 1) if n_gates > 1 else 0.0
        cur_layer: list[Component] = []
        pool_no_not = GATE_POOL_NO_NOT
        pool_all = GATE_POOL_NO_NOT + [ComponentKind.GATE_NOT]

        for gi in range(n_gates):
            gy = round(340.0 if n_gates == 1 else (y_min + 35.0 + gi * (gy_step * 0.85)), 1)
            gkind = rng.choice(pool_no_not if (is_last_gate_layer or len(prev_layer) >= 2) else pool_all)
            if not is_last_gate_layer and lyr == 0 and gi == n_gates - 1 and rng.random() < 0.4:
                gkind = ComponentKind.GATE_NOT
            gid = f"U{gate_idx}"
            gate_idx += 1
            gate = _make_gate(gid, gkind, col_x, gy)
            comps.append(gate)
            cur_layer.append(gate)

            n_in = 1 if gkind == ComponentKind.GATE_NOT else 2
            srcs = rng.sample(prev_layer, k=n_in) if len(prev_layer) >= n_in else [prev_layer[0], prev_layer[-1]]
            for p_i, src_comp in enumerate(srcs):
                dport = f"in{p_i}"
                conns.append((src_comp.id, "out", gid, dport))
                gap = max(24.0, gate.ports[dport].x - src_comp.ports["out"].x)
                mx = round(src_comp.ports["out"].x + gap * (0.28 + 0.44 * ((wire_idx % 4) / 3.0)), 1)
                wire_idx += 1
                nets.append(
                    WireNet(
                        net_id=f"ND_{src_comp.id}_{gid}_{dport}",
                        points=_route_orthogonal(f"ND_{src_comp.id}_{gid}_{dport}", src_comp.ports["out"], gate.ports[dport], mx),
                    )
                )
        prev_layer = cur_layer

    final_gate = prev_layer[0]
    l1 = _make_led("L1", 1095.0, final_gate.center.y)
    comps.append(l1)
    conns.append((final_gate.id, "out", "L1", "in"))
    nets.append(WireNet(net_id="ND_OUT_L1", points=[final_gate.ports["out"], l1.ports["in"]]))

    nets, bridges = compute_wire_topology(nets)
    spec = SchematicSpec(
        drawing_title="ARBITRARY PROCEDURAL LOGIC TOPOLOGY",
        drawing_number=f"SF-ARB-{seed:06d}",
        label_mode=label_mode,
        components=comps,
        nets=nets,
        bridges=bridges,
        connections=conns,
        metadata={"target_led": "L1", "arbitrary_dag": True},
    )
    return spec, "L1", sw_ids

def _generate_state_propagation(
    rng: random.Random,
    difficulty: DifficultyTier,
    label_mode: LabelMode,
    seed: int,
) -> tuple[SchematicSpec, str]:
    arb_prob = 0.40 if difficulty == DifficultyTier.EASY else 0.55
    if rng.random() < arb_prob:
        spec, target_led, sw_ids = _generate_arbitrary_dag_core(rng, difficulty, label_mode, seed)
        if rng.random() < 0.45:
            tog_sw = rng.choice(sw_ids)
            spec.metadata["question_variant"] = "what_if_switch_toggle"
            spec.metadata["toggle_switch_id"] = tog_sw
            q = (
                f"Examine the procedurally routed combinational DAG schematic as drawn. Suppose switch {tog_sw} "
                f"is toggled to the OPPOSITE of its shown blade position while every other switch stays unchanged. "
                f"Will indicator LED {target_led} be ON or OFF? Reply with ON or OFF."
            )
            return spec, q
        q = (
            f"Trace the custom multi-layer power, switch, fuse, and IEEE logic gate topology in the schematic. "
            f"Is indicator LED {target_led} ON or OFF? Reply with exactly one word: ON or OFF."
        )
        return spec, q

    comps: list[Component] = []
    conns: list[tuple[str, str, str, str]] = []
    nets: list[WireNet] = []

    if difficulty == DifficultyTier.EASY:
        n_sw = 2
        y_inputs = [250.0, 420.0]
    elif difficulty == DifficultyTier.MEDIUM:
        n_sw = 3
        y_inputs = [175.0, 325.0, 475.0]
    else:
        n_sw = 4
        y_inputs = [145.0, 275.0, 405.0, 535.0]

    rail_x = 125.0
    vcc = _make_source("VCC", 85.0, y_inputs[0], level=1)
    comps.append(vcc)

    sw_ids: list[str] = []
    sw_out_comps: list[str] = []
    rail_pts: list[WireSegment] = []
    rail_dots: list[Point] = []

    for idx, y in enumerate(y_inputs):
        sw_id = f"SW{idx + 1}"
        sw = _make_switch(sw_id, 215.0, y, closed=rng.choice([True, False]))
        comps.append(sw)
        sw_ids.append(sw_id)
        conns.append(("VCC", "out", sw_id, "in"))

        if idx == 0:
            rail_pts.append(WireSegment(net_id="NET_VCC", p1=vcc.ports["out"], p2=sw.ports["in"]))
        else:
            branch_pt = Point(x=rail_x, y=y)
            if idx < len(y_inputs) - 1:
                rail_dots.append(branch_pt)
            rail_pts.append(WireSegment(net_id="NET_VCC", p1=branch_pt, p2=sw.ports["in"]))

        include_fuse = (difficulty == DifficultyTier.HARD and idx == 0) or (
            difficulty in (DifficultyTier.EASY, DifficultyTier.MEDIUM) and idx == 0 and rng.random() < 0.45
        )
        if include_fuse:
            f1 = _make_fuse("F1", 325.0, y, intact=rng.choices([True, False], weights=[0.78, 0.22])[0])
            comps.append(f1)
            conns.append((sw_id, "out", "F1", "in"))
            nets.append(WireNet(net_id=f"N_{sw_id}_F1", points=[sw.ports["out"], f1.ports["in"]]))
            sw_out_comps.append("F1")
        else:
            sw_out_comps.append(sw_id)

    if len(y_inputs) > 1:
        rail_pts.append(
            WireSegment(
                net_id="NET_VCC",
                p1=Point(x=rail_x, y=y_inputs[0]),
                p2=Point(x=rail_x, y=y_inputs[-1]),
            )
        )
        rail_dots.append(Point(x=rail_x, y=y_inputs[0]))
    nets.append(WireNet(net_id="NET_VCC", points=[], segments=rail_pts, junction_dots=rail_dots))

    comp_map = {c.id: c for c in comps}

    if difficulty == DifficultyTier.EASY:
        g1_kind = rng.choice(GATE_POOL_NO_NOT)
        g2_kind = rng.choice(GATE_POOL_NO_NOT)
        use_not = rng.random() < 0.45
        if use_not:
            u_not = _make_gate("U_NOT", ComponentKind.GATE_NOT, 420.0, y_inputs[1])
            u1 = _make_gate("U1", g1_kind, 610.0, 335.0)
            l1 = _make_led("L1", 885.0, 335.0)
            comps.extend([u_not, u1, l1])
            comp_map.update({"U_NOT": u_not, "U1": u1, "L1": l1})
            conns.append((sw_out_comps[1], "out", "U_NOT", "in0"))
            nets.append(WireNet(net_id="N_SW2_NOT", points=[comp_map[sw_out_comps[1]].ports["out"], u_not.ports["in0"]]))
            order_pairs = [(sw_out_comps[0], "in0"), ("U_NOT", "in1")]
            if rng.random() < 0.5:
                order_pairs = [("U_NOT", "in0"), (sw_out_comps[0], "in1")]
            for p_idx, (src_id, dport) in enumerate(order_pairs):
                conns.append((src_id, "out", "U1", dport))
                nets.append(
                    WireNet(
                        net_id=f"N_{src_id}_{dport}",
                        points=_route_orthogonal(
                            f"N_{src_id}_{dport}",
                            comp_map[src_id].ports["out"],
                            u1.ports[dport],
                            mid_x=495.0 + p_idx * 35.0,
                        ),
                    )
                )
            conns.append(("U1", "out", "L1", "in"))
            nets.append(WireNet(net_id="N_U1_L1", points=[u1.ports["out"], l1.ports["in"]]))
        else:
            u1_y = rng.choice([295.0, 335.0, 375.0])
            u1 = _make_gate("U1", g1_kind, 535.0, u1_y)
            l1 = _make_led("L1", 845.0, u1_y)
            comps.extend([u1, l1])
            comp_map.update({"U1": u1, "L1": l1})

            order = [0, 1]
            if rng.random() < 0.5:
                order = [1, 0]
            for port_i, src_idx in enumerate(order):
                src_id = sw_out_comps[src_idx]
                port_name = f"in{port_i}"
                conns.append((src_id, "out", "U1", port_name))
                nets.append(
                    WireNet(
                        net_id=f"N_{src_id}_{port_name}",
                        points=_route_orthogonal(
                            f"N_{src_id}_{port_name}",
                            comp_map[src_id].ports["out"],
                            u1.ports[port_name],
                            mid_x=375.0 + port_i * 45.0,
                        ),
                    )
                )
            conns.append(("U1", "out", "L1", "in"))
            nets.append(WireNet(net_id="N_U1_L1", points=[u1.ports["out"], l1.ports["in"]]))
        target_led = "L1"

    elif difficulty == DifficultyTier.MEDIUM:
        u1 = _make_gate("U1", rng.choice(GATE_POOL_NO_NOT), 495.0, 235.0)
        u2 = _make_gate("U2", rng.choice(GATE_POOL_NO_NOT), 495.0, 420.0)
        u3 = _make_gate("U3", rng.choice(GATE_POOL_NO_NOT), 775.0, 330.0)
        l1 = _make_led("L1", 1015.0, 330.0)
        comps.extend([u1, u2, u3, l1])
        comp_map.update({"U1": u1, "U2": u2, "U3": u3, "L1": l1})

        bindings = [
            (sw_out_comps[0], "U1", "in0", 355.0),
            (sw_out_comps[1], "U1", "in1", 390.0),
            (sw_out_comps[1], "U2", "in0", 390.0),
            (sw_out_comps[2], "U2", "in1", 425.0),
        ]
        if rng.random() < 0.45:
            bindings[0], bindings[3] = (sw_out_comps[2], "U1", "in0", 360.0), (sw_out_comps[0], "U2", "in1", 420.0)

        for idx, (src_id, dst_id, dport, mx) in enumerate(bindings):
            conns.append((src_id, "out", dst_id, dport))
            pts = _route_orthogonal(
                f"NET_{src_id}",
                comp_map[src_id].ports["out"],
                comp_map[dst_id].ports[dport],
                mid_x=mx,
            )
            nets.append(WireNet(net_id=f"NET_{src_id}", points=pts))

        conns.extend([("U1", "out", "U3", "in0"), ("U2", "out", "U3", "in1"), ("U3", "out", "L1", "in")])
        nets.append(WireNet(net_id="N_U1_U3", points=_route_orthogonal("N_U1_U3", u1.ports["out"], u3.ports["in0"], 640.0)))
        nets.append(WireNet(net_id="N_U2_U3", points=_route_orthogonal("N_U2_U3", u2.ports["out"], u3.ports["in1"], 675.0)))
        nets.append(WireNet(net_id="N_U3_L1", points=[u3.ports["out"], l1.ports["in"]]))
        target_led = "L1"

    else:
        u_not = _make_gate("U_NOT", ComponentKind.GATE_NOT, 440.0, 275.0)
        u1 = _make_gate("U1", rng.choice(GATE_POOL_NO_NOT), 600.0, 200.0)
        u2 = _make_gate("U2", rng.choice(GATE_POOL_NO_NOT), 600.0, 455.0)
        u3 = _make_gate("U3", rng.choice(GATE_POOL_NO_NOT), 850.0, 325.0)
        l1 = _make_led("L1", 1075.0, 250.0)
        l2 = _make_led("L2", 1075.0, 440.0)
        comps.extend([u_not, u1, u2, u3, l1, l2])
        comp_map.update({"U_NOT": u_not, "U1": u1, "U2": u2, "U3": u3, "L1": l1, "L2": l2})

        conns.append((sw_out_comps[1], "out", "U_NOT", "in0"))
        nets.append(WireNet(net_id="N_SW2_NOT", points=[comp_map[sw_out_comps[1]].ports["out"], u_not.ports["in0"]]))

        raw_wires = [
            (sw_out_comps[0], "U1", "in0", 495.0),
            ("U_NOT", "U1", "in1", 525.0),
            (sw_out_comps[2], "U2", "in0", 470.0),
            (sw_out_comps[3], "U2", "in1", 510.0),
        ]
        if rng.random() < 0.65:
            raw_wires[1] = ("U_NOT", "U2", "in0", 525.0)
            raw_wires[2] = (sw_out_comps[2], "U1", "in1", 495.0)

        for src_id, dst_id, dport, mx in raw_wires:
            conns.append((src_id, "out", dst_id, dport))
            nets.append(
                WireNet(
                    net_id=f"N_{src_id}_{dst_id}_{dport}",
                    points=_route_orthogonal(f"N_{src_id}_{dst_id}_{dport}", comp_map[src_id].ports["out"], comp_map[dst_id].ports[dport], mx),
                )
            )

        conns.extend([
            ("U1", "out", "U3", "in0"),
            ("U2", "out", "U3", "in1"),
            ("U3", "out", "L1", "in"),
            ("U2", "out", "L2", "in"),
        ])
        nets.append(WireNet(net_id="N_U1_U3", points=_route_orthogonal("N_U1_U3", u1.ports["out"], u3.ports["in0"], 735.0)))
        nets.append(WireNet(net_id="N_U2_MAIN", points=_route_orthogonal("N_U2_MAIN", u2.ports["out"], u3.ports["in1"], 765.0)))
        nets.append(WireNet(net_id="N_U3_L1", points=_route_orthogonal("N_U3_L1", u3.ports["out"], l1.ports["in"], 975.0)))
        nets.append(WireNet(net_id="N_U2_L2", points=_route_orthogonal("N_U2_L2", u2.ports["out"], l2.ports["in"], 765.0)))
        target_led = rng.choice(["L1", "L2"])

    nets, bridges = compute_wire_topology(nets)
    meta: dict[str, Any] = {"target_led": target_led}
    spec = SchematicSpec(
        drawing_title="MULTI-HOP BOOLEAN LOGIC SCHEMATIC",
        drawing_number=f"SF-LOG-{seed:04d}",
        label_mode=label_mode,
        components=comps,
        nets=nets,
        bridges=bridges,
        connections=conns,
        metadata=meta,
    )

    leds = [c.id for c in comps if c.kind == ComponentKind.LED]
    if len(leds) >= 2 and rng.random() < 0.48:
        spec.metadata["question_variant"] = "multi_led_vector"
        question = (
            "Trace the power supply, fuse, switches, and all IEEE logic gates across the full schematic. "
            "What are the combined steady-state outputs of L1 and L2? "
            "Choose exactly one: 'L1=ON, L2=ON', 'L1=ON, L2=OFF', 'L1=OFF, L2=ON', or 'L1=OFF, L2=OFF'."
        )
    elif difficulty != DifficultyTier.EASY and rng.random() < 0.4:
        tog_sw = rng.choice(sw_ids)
        spec.metadata["question_variant"] = "what_if_switch_toggle"
        spec.metadata["toggle_switch_id"] = tog_sw
        question = (
            f"Trace the whole control circuit as shown. If switch {tog_sw} is toggled to the OPPOSITE "
            f"of its drawn position while every other switch and fuse stays unchanged, will LED {target_led} be ON or OFF? "
            f"Reply with exactly one word: ON or OFF."
        )
    else:
        question = (
            f"Trace the power supply, switch states, fuses, and IEEE logic gates in the schematic. "
            f"Is indicator LED {target_led} ON or OFF? Reply with exactly one word: ON or OFF."
        )
    return spec, question

def _generate_bridge_vs_junction(
    rng: random.Random,
    difficulty: DifficultyTier,
    label_mode: LabelMode,
    seed: int,
) -> tuple[SchematicSpec, str]:
    """Crossbar bus architecture where dot vs bridge jump governs lamp energization."""
    comps: list[Component] = []
    conns: list[tuple[str, str, str, str]] = []
    nets: list[WireNet] = []

    n_rails = 2 if difficulty == DifficultyTier.EASY else 3
    n_cols = 2 if difficulty == DifficultyTier.EASY else 3
    rail_ys = [170.0 + i * 75.0 for i in range(n_rails)]
    col_xs = [310.0 + j * 270.0 for j in range(n_cols)]

    rail_active = [True] + [False] * (n_rails - 1)
    active_idx = rng.randrange(n_rails)
    rail_active = [i == active_idx for i in range(n_rails)]

    for i, ry in enumerate(rail_ys):
        src_id = f"BUS{i + 1}"
        lvl = 1 if rail_active[i] else 0
        src = _make_source(src_id, 115.0, ry, level=lvl)
        comps.append(src)
        nets.append(
            WireNet(
                net_id=f"NET_RAIL_{i}",
                points=[src.ports["out"], Point(x=col_xs[-1] + 40.0, y=ry)],
                junction_dots=[],
            )
        )

    for j, cx in enumerate(col_xs):
        lamp_id = f"L{j + 1}"
        sw_id = f"SW{j + 1}"
        sw_closed = rng.choices([True, False], weights=[0.75, 0.25])[0]
        sw = Component(
            id=sw_id,
            kind=ComponentKind.SWITCH,
            center=Point(x=cx, y=445.0),
            closed=sw_closed,
            ports={"in": Point(x=cx - 30, y=445.0), "out": Point(x=cx + 30, y=445.0)},
        )
        lamp = _make_led(lamp_id, cx + 145.0, 525.0)
        comps.extend([sw, lamp])

        drop_x = cx - 48.0
        connected_rail = rng.randrange(n_rails)
        tap_y = rail_ys[connected_rail]
        net_id = f"NET_RAIL_{connected_rail}"
        for n in nets:
            if n.net_id == net_id:
                n.junction_dots.append(Point(x=drop_x, y=tap_y))
                n.segments.append(WireSegment(net_id=net_id, p1=Point(x=drop_x, y=tap_y), p2=Point(x=drop_x, y=445.0)))
                n.segments.append(WireSegment(net_id=net_id, p1=Point(x=drop_x, y=445.0), p2=sw.ports["in"]))

        conns.append((f"BUS{connected_rail + 1}", "out", sw_id, "in"))

        if difficulty != DifficultyTier.EASY and j % 2 == 1:
            fid = f"F{j + 1}"
            f_intact = rng.choices([True, False], weights=[0.7, 0.3])[0]
            fuse = _make_fuse(fid, cx + 82.0, 445.0, intact=f_intact)
            comps.append(fuse)
            conns.append((sw_id, "out", fid, "in"))
            conns.append((fid, "out", lamp_id, "in"))
            nets.append(WireNet(net_id=f"N_{sw_id}_{fid}", points=[sw.ports["out"], fuse.ports["in"]]))
            nets.append(
                WireNet(
                    net_id=f"N_{fid}_{lamp_id}",
                    points=_route_orthogonal(f"N_{fid}_{lamp_id}", fuse.ports["out"], lamp.ports["in"], cx + 116.0),
                )
            )
        else:
            conns.append((sw_id, "out", lamp_id, "in"))
            nets.append(
                WireNet(
                    net_id=f"N_{sw_id}_{lamp_id}",
                    points=_route_orthogonal(f"N_{sw_id}_{lamp_id}", sw.ports["out"], lamp.ports["in"], cx + 65.0),
                )
            )

    nets, bridges = compute_wire_topology(nets)
    use_multi_lamp = (difficulty != DifficultyTier.EASY and rng.random() < 0.65) or (rng.random() < 0.35)
    if use_multi_lamp:
        lamp_ids = [f"L{j + 1}" for j in range(n_cols)]
        probe_spec = SchematicSpec(
            drawing_title="WIRE CROSSING BRIDGE VS JUNCTION TOPOLOGY",
            drawing_number=f"SF-BRJ-{seed:04d}",
            label_mode=label_mode,
            components=comps,
            nets=nets,
            bridges=bridges,
            connections=conns,
            metadata={},
        )
        true_ans = solve_conductivity_graph(probe_spec).answer
        candidates_pool: list[str] = [true_ans, "NONE", ", ".join(lamp_ids)]
        for lid in lamp_ids:
            candidates_pool.append(lid)
        if len(lamp_ids) >= 2:
            candidates_pool.append(f"{lamp_ids[0]}, {lamp_ids[1]}")
        if len(lamp_ids) >= 3:
            candidates_pool.append(f"{lamp_ids[0]}, {lamp_ids[2]}")
            candidates_pool.append(f"{lamp_ids[1]}, {lamp_ids[2]}")
        distractors = [c for c in dict.fromkeys(candidates_pool) if c != true_ans]
        rng.shuffle(distractors)
        choices = [true_ans] + distractors[:3]
        rng.shuffle(choices)
        spec = SchematicSpec(
            drawing_title="WIRE CROSSING BRIDGE VS JUNCTION TOPOLOGY",
            drawing_number=f"SF-BRJ-{seed:04d}",
            label_mode=label_mode,
            components=comps,
            nets=nets,
            bridges=bridges,
            connections=conns,
            metadata={"question_variant": "multi_lamp_subset", "mcq_choices": choices},
        )
        question = (
            f"Carefully trace every solid solder junction dot (connected) versus curved bridge jump (isolated crossing), "
            f"switches, and fuses across the entire bus grid. Which exact indicator lamps ({', '.join(lamp_ids)}) "
            f"receive 5V power?"
        )
        return spec, question

    target_lamp = f"L{rng.randrange(1, n_cols + 1)}"
    spec = SchematicSpec(
        drawing_title="WIRE CROSSING BRIDGE VS JUNCTION TOPOLOGY",
        drawing_number=f"SF-BRJ-{seed:04d}",
        label_mode=label_mode,
        components=comps,
        nets=nets,
        bridges=bridges,
        connections=conns,
        metadata={"target_lamp": target_lamp},
    )
    question = (
        f"Carefully distinguish solid solder junction dots (electrically connected) from curved bridge jumps "
        f"(isolated wire crossings) along the horizontal buses. Does 5V power reach indicator lamp {target_lamp}? "
        f"Reply with exactly YES or NO."
    )
    return spec, question

def _generate_equivalent_resistance(
    rng: random.Random,
    difficulty: DifficultyTier,
    label_mode: LabelMode,
    seed: int,
) -> tuple[SchematicSpec, str]:
    """Generate clean horizontal series-parallel switched resistor schematic."""
    comps: list[Component] = []
    nets: list[WireNet] = []
    conns: list[tuple[str, str, str, str]] = []

    use_ohms_law = rng.random() < 0.45
    supply_volts = rng.choice([12, 24])

    if use_ohms_law:
        term_a = _make_source("VCC", 80.0, 340.0, level=1, volts=supply_volts)
        term_b = Component(
            id="GND_REF",
            kind=ComponentKind.TEST_POINT,
            center=Point(x=1150.0, y=340.0),
            value_text="0V",
            ports={"in": Point(x=1130.0, y=340.0)},
        )
        prev_anchor = term_a.ports["out"]
    else:
        term_a = Component(
            id="TERM_A",
            kind=ComponentKind.TEST_POINT,
            center=Point(x=85.0, y=340.0),
            value_text="A",
            ports={"out": Point(x=105.0, y=340.0)},
        )
        term_b = Component(
            id="TERM_B",
            kind=ComponentKind.TEST_POINT,
            center=Point(x=1150.0, y=340.0),
            value_text="B",
            ports={"in": Point(x=1130.0, y=340.0)},
        )
        prev_anchor = term_a.ports["out"]
    comps.extend([term_a, term_b])

    r_idx = 1
    sw_idx = 1
    stage_trees: list[dict[str, Any]] = []

    if difficulty == DifficultyTier.EASY:
        if rng.random() < 0.5:
            stages_xs = [(290.0, "single"), (660.0, "parallel2")]
        else:
            stages_xs = [(440.0, "parallel2"), (820.0, "single")]
    elif difficulty == DifficultyTier.MEDIUM:
        stages_xs = rng.choice([
            [(265.0, "single"), (605.0, "parallel2_sw"), (945.0, "parallel2")],
            [(340.0, "parallel2_sw"), (685.0, "single"), (935.0, "parallel2")],
            [(265.0, "parallel2"), (605.0, "single"), (915.0, "parallel2_sw")],
        ])
    else:
        stages_xs = rng.choice([
            [(265.0, "parallel2_sw"), (615.0, "parallel2_sw"), (960.0, "single")],
            [(250.0, "single"), (535.0, "parallel2_sw"), (905.0, "parallel2_sw")],
        ])

    switch_states: dict[str, bool] = {}

    for st_pos, (cx, kind_st) in enumerate(stages_xs):
        if kind_st == "single":
            val = rng.choice(SINGLE_RESISTOR_VALUES)
            rid = f"R{r_idx}"
            r_idx += 1
            res = _make_resistor(rid, cx, 340.0, val)
            comps.append(res)
            nets.append(WireNet(net_id=f"NR_{st_pos}", points=[prev_anchor, res.ports["p1"]]))
            prev_anchor = res.ports["p2"]
            stage_trees.append({"type": "resistor", "id": rid, "ohm": val})

        else:
            r_top_val, r_bot_val = rng.choice(PARALLEL_PAIRS_EXACT)
            rid_t, rid_b = f"R{r_idx}", f"R{r_idx + 1}"
            r_idx += 2

            left_x = cx - 125.0
            right_x = cx + 125.0
            top_y, bot_y = 225.0, 455.0

            nets.append(WireNet(net_id=f"NP_IN_{st_pos}", points=[prev_anchor, Point(x=left_x, y=340.0)]))
            split_dots = [Point(x=left_x, y=340.0)]
            join_dots = [Point(x=right_x, y=340.0)]

            has_sw = "sw" in kind_st
            top_sw_closed = rng.choice([True, False]) if has_sw else True
            bot_sw_closed = True if (has_sw and not top_sw_closed) else rng.choice([True, True, False])

            top_branch_node: dict[str, Any]
            if has_sw:
                sid = f"SW{sw_idx}"
                sw_idx += 1
                sw = _make_switch(sid, cx - 50.0, top_y, closed=top_sw_closed)
                res_t = _make_resistor(rid_t, cx + 52.0, top_y, r_top_val)
                comps.extend([sw, res_t])
                switch_states[sid] = top_sw_closed
                nets.append(WireNet(net_id=f"NT_{st_pos}_1", points=[Point(x=left_x, y=340.0), Point(x=left_x, y=top_y), sw.ports["in"]], junction_dots=split_dots))
                nets.append(WireNet(net_id=f"NT_{st_pos}_2", points=[sw.ports["out"], res_t.ports["p1"]]))
                nets.append(WireNet(net_id=f"NT_{st_pos}_3", points=[res_t.ports["p2"], Point(x=right_x, y=top_y), Point(x=right_x, y=340.0)], junction_dots=join_dots))
                top_branch_node = {"type": "resistor", "id": rid_t, "ohm": r_top_val, "switch": sid}
            else:
                res_t = _make_resistor(rid_t, cx, top_y, r_top_val)
                comps.append(res_t)
                nets.append(WireNet(net_id=f"NT_{st_pos}_1", points=[Point(x=left_x, y=340.0), Point(x=left_x, y=top_y), res_t.ports["p1"]], junction_dots=split_dots))
                nets.append(WireNet(net_id=f"NT_{st_pos}_2", points=[res_t.ports["p2"], Point(x=right_x, y=top_y), Point(x=right_x, y=340.0)], junction_dots=join_dots))
                top_branch_node = {"type": "resistor", "id": rid_t, "ohm": r_top_val}

            res_b = _make_resistor(rid_b, cx, bot_y, r_bot_val)
            comps.append(res_b)
            nets.append(WireNet(net_id=f"NB_{st_pos}_1", points=[Point(x=left_x, y=340.0), Point(x=left_x, y=bot_y), res_b.ports["p1"]]))
            nets.append(WireNet(net_id=f"NB_{st_pos}_2", points=[res_b.ports["p2"], Point(x=right_x, y=bot_y), Point(x=right_x, y=340.0)]))

            children = [top_branch_node, {"type": "resistor", "id": rid_b, "ohm": r_bot_val}]
            if difficulty == DifficultyTier.HARD and st_pos == 1:
                mid_val = rng.choice([60, 120])
                rid_m = f"R{r_idx}"
                r_idx += 1
                sid_m = f"SW{sw_idx}"
                sw_idx += 1
                sw_m_closed = rng.choice([True, False])
                sw_m = _make_switch(sid_m, cx - 50.0, 340.0, closed=sw_m_closed)
                res_m = _make_resistor(rid_m, cx + 52.0, 340.0, mid_val)
                comps.extend([sw_m, res_m])
                switch_states[sid_m] = sw_m_closed
                nets.append(WireNet(net_id=f"NM_{st_pos}_1", points=[Point(x=left_x, y=340.0), sw_m.ports["in"]]))
                nets.append(WireNet(net_id=f"NM_{st_pos}_2", points=[sw_m.ports["out"], res_m.ports["p1"]]))
                nets.append(WireNet(net_id=f"NM_{st_pos}_3", points=[res_m.ports["p2"], Point(x=right_x, y=340.0)]))
                children.append({"type": "resistor", "id": rid_m, "ohm": mid_val, "switch": sid_m})

            stage_trees.append({"type": "parallel", "children": children})
            prev_anchor = Point(x=right_x, y=340.0)

    nets.append(WireNet(net_id="NR_OUT", points=[prev_anchor, term_b.ports["in"]]))
    nets, bridges = compute_wire_topology(nets)
    tree = {"type": "series", "children": stage_trees}
    req_exact, _ = eval_resistance_tree(tree, switch_states)

    if use_ohms_law:
        spec = SchematicSpec(
            drawing_title="POWERED SERIES-PARALLEL OHM'S LAW NETWORK",
            drawing_number=f"SF-RES-{seed:04d}",
            rule_banner=f"OHM'S LAW CIRCUIT: Trace CLOSED switches and find load current from {supply_volts}V VCC to 0V GND",
            label_mode=label_mode,
            components=comps,
            nets=nets,
            bridges=bridges,
            connections=conns,
            metadata={
                "question_variant": "current_ma",
                "supply_volts": supply_volts,
                "resistance_tree": tree,
                "expected_fraction": str(req_exact),
            },
        )
        question = (
            f"Examine the {supply_volts}V supply and every switch position (CLOSED switches conduct; OPEN switches "
            f"disconnect their branch). Calculate the total current drawn from VCC to 0V in milliamps "
            f"(e.g. '150 mA', or '0 mA' if open-circuit)."
        )
        return spec, question

    spec = SchematicSpec(
        drawing_title="SERIES-PARALLEL RESISTANCE NETWORK",
        drawing_number=f"SF-RES-{seed:04d}",
        label_mode=label_mode,
        components=comps,
        nets=nets,
        bridges=bridges,
        connections=conns,
        metadata={"resistance_tree": tree, "expected_fraction": str(req_exact)},
    )
    question = (
        "Examine every switch position (CLOSED switches conduct; OPEN switches disconnect their branch). "
        "Calculate the exact equivalent resistance between Terminal A and Terminal B in Ohms "
        "(e.g. '70 Ohm')."
    )
    return spec, question

def _generate_fault_diagnosis(
    rng: random.Random,
    difficulty: DifficultyTier,
    label_mode: LabelMode,
    seed: int,
) -> tuple[SchematicSpec, str]:
    """Generate a single-fault isolation task where 3 visible probes uniquely identify 1 fault."""
    comps: list[Component] = []
    conns: list[tuple[str, str, str, str]] = []
    nets: list[WireNet] = []

    vcc1 = _make_source("VCC1", 85.0, 210.0, level=1)
    vcc2_lvl = 1 if rng.random() < 0.8 else 0
    vcc2 = _make_source("VCC2", 85.0, 410.0, level=vcc2_lvl)
    fuse_intact = True
    f1 = _make_fuse("F1", 210.0, 210.0, intact=fuse_intact)
    sw1 = _make_switch("SW1", 345.0, 210.0, closed=rng.choices([True, False], weights=[0.85, 0.15])[0])
    sw2 = _make_switch("SW2", 250.0, 410.0, closed=rng.choices([True, False], weights=[0.85, 0.15])[0])

    if difficulty == DifficultyTier.EASY:
        u1_y, u2_y = 260.0, 390.0
    elif difficulty == DifficultyTier.MEDIUM and seed % 2 == 1:
        u1_y, u2_y = 335.0, 260.0
    else:
        u1_y, u2_y = 290.0, 355.0

    g1_kind = rng.choice(GATE_POOL_NO_NOT)
    g2_kind = rng.choice(GATE_POOL_NO_NOT)
    u1 = _make_gate("U1", g1_kind, 540.0, u1_y)
    u2 = _make_gate("U2", g2_kind, 760.0, u2_y)
    l1 = _make_led("L1", 985.0, u2_y)

    tp1 = Component(id="TP1", kind=ComponentKind.PROBE, center=Point(x=280.0, y=155.0), ports={"in": Point(x=280.0, y=210.0)})
    tp2 = Component(id="TP2", kind=ComponentKind.PROBE, center=Point(x=635.0, y=u1_y - 60.0), ports={"in": Point(x=635.0, y=u1_y)})
    tp3 = Component(id="TP3", kind=ComponentKind.PROBE, center=Point(x=870.0, y=u2_y - 65.0), ports={"in": Point(x=870.0, y=u2_y)})

    comps.extend([vcc1, vcc2, f1, sw1, sw2, u1, u2, l1, tp1, tp2, tp3])
    conns.extend([
        ("VCC1", "out", "F1", "in"),
        ("F1", "out", "SW1", "in"),
        ("SW1", "out", "U1", "in0"),
        ("VCC2", "out", "SW2", "in"),
        ("SW2", "out", "U1", "in1"),
        ("U1", "out", "U2", "in0"),
        ("SW2", "out", "U2", "in1"),
        ("U2", "out", "L1", "in"),
        ("F1", "out", "TP1", "in"),
        ("U1", "out", "TP2", "in"),
        ("U2", "out", "TP3", "in"),
    ])

    swap_hard_inputs = difficulty == DifficultyTier.HARD and rng.random() < 0.5
    u1_sw2_mx = 455.0 if swap_hard_inputs else 415.0
    nets.extend([
        WireNet(net_id="N1", points=[vcc1.ports["out"], f1.ports["in"]]),
        WireNet(net_id="N2", points=[f1.ports["out"], sw1.ports["in"]], junction_dots=[Point(x=280.0, y=210.0)]),
        WireNet(net_id="N3", points=_route_orthogonal("N3", sw1.ports["out"], u1.ports["in0"], 445.0)),
        WireNet(net_id="N4", points=[vcc2.ports["out"], sw2.ports["in"]]),
        WireNet(net_id="N5", points=_route_orthogonal("N5", sw2.ports["out"], u1.ports["in1"], u1_sw2_mx), junction_dots=[Point(x=u1_sw2_mx, y=410.0)]),
        WireNet(net_id="N6", points=_route_orthogonal("N6", u1.ports["out"], u2.ports["in0"], 650.0), junction_dots=[Point(x=635.0, y=u1_y)]),
        WireNet(net_id="N7", points=_route_orthogonal("N7", sw2.ports["out"], u2.ports["in1"], 415.0)),
        WireNet(net_id="N8", points=[u2.ports["out"], l1.ports["in"]], junction_dots=[Point(x=870.0, y=u2_y)]),
        WireNet(net_id="NTP1", points=[Point(x=280.0, y=210.0), Point(x=280.0, y=170.0)]),
        WireNet(net_id="NTP2", points=[Point(x=635.0, y=u1_y), Point(x=635.0, y=u1_y - 45.0)]),
        WireNet(net_id="NTP3", points=[Point(x=870.0, y=u2_y), Point(x=870.0, y=u2_y - 50.0)]),
    ])

    pool_candidates = [
        {"label": "A", "component_id": "F1", "fault_mode": "OPEN", "text": "A: Fuse F1 blown open"},
        {"label": "B", "component_id": "U1", "fault_mode": "STUCK_LOW", "text": "B: Gate U1 output stuck LOW"},
        {"label": "C", "component_id": "U1", "fault_mode": "STUCK_HIGH", "text": "C: Gate U1 output stuck HIGH"},
        {"label": "D", "component_id": "U2", "fault_mode": "STUCK_LOW", "text": "D: Gate U2 output stuck LOW"},
        {"label": "E", "component_id": "U2", "fault_mode": "STUCK_HIGH", "text": "E: Gate U2 output stuck HIGH"},
        {"label": "F", "component_id": "SW1", "fault_mode": "OPEN", "text": "F: Switch SW1 stuck OPEN"},
        {"label": "G", "component_id": "SW2", "fault_mode": "OPEN", "text": "G: Switch SW2 stuck OPEN"},
        {"label": "H", "component_id": "U2", "fault_mode": "INVERT_BUBBLE", "text": "H: Gate U2 output inverted"},
    ]
    rng.shuffle(pool_candidates)

    temp_spec = SchematicSpec(components=comps, nets=nets, connections=conns)
    signatures: dict[tuple[str, str, str], dict[str, str]] = {}
    for cand in pool_candidates:
        proof = solve_logic_network(temp_spec, fault_override=(cand["component_id"], cand["fault_mode"]))
        sig = (proof.node_values["TP1"], proof.node_values["TP2"], proof.node_values["TP3"])
        if sig not in signatures:
            signatures[sig] = cand

    distinct_cands = list(signatures.values())[:4]
    rng.shuffle(distinct_cands)
    relabelled: list[dict[str, str]] = []
    letters = ["A", "B", "C", "D"]
    for idx, cand in enumerate(distinct_cands):
        desc_body = cand["text"].split(": ", 1)[1]
        relabelled.append({
            "label": letters[idx],
            "component_id": cand["component_id"],
            "fault_mode": cand["fault_mode"],
            "text": f"{letters[idx]}: {desc_body}",
        })

    winner = rng.choice(relabelled)
    win_proof = solve_logic_network(temp_spec, fault_override=(winner["component_id"], winner["fault_mode"]))
    visible_probes = {
        "TP1": win_proof.node_values["TP1"],
        "TP2": win_proof.node_values["TP2"],
        "TP3": win_proof.node_values["TP3"],
    }

    for tp in (tp1, tp2, tp3):
        val = visible_probes[tp.id]
        tp.probe_label = f"{tp.id}: {'5V (HIGH)' if val == 'ON' else '0V (LOW)'}"
        tp.voltage_level = 1 if val == "ON" else 0

    rule_lines = " | ".join(c["text"] for c in relabelled)
    nets, bridges = compute_wire_topology(nets)
    spec = SchematicSpec(
        drawing_title="PROBE-ASSISTED FAULT ISOLATION",
        drawing_number=f"SF-FLT-{seed:04d}",
        rule_banner=f"CANDIDATE FAULTS -> {rule_lines}",
        label_mode=label_mode,
        components=comps,
        nets=nets,
        bridges=bridges,
        connections=conns,
        metadata={"visible_probes": visible_probes, "fault_candidates": relabelled},
    )
    question = (
        "Inspect the schematic topology and the voltage probe badges printed at TP1, TP2, and TP3. "
        "Which single fault option shown in the Candidate Faults banner uniquely explains all observed probe readings? "
        f"Reply with {' or '.join(c['label'] for c in relabelled)}."
    )
    return spec, question

def _generate_counterfactual_pair(
    rng: random.Random,
    difficulty: DifficultyTier,
    label_mode: LabelMode,
    seed: int,
) -> tuple[SchematicSpec, str]:
    """Side-by-side Panel A vs Panel B with exactly 1 surgical visual mutation."""
    base_spec, _ = _generate_state_propagation(rng, difficulty, label_mode, seed)
    panel_b = copy.deepcopy(base_spec)
    panel_b.drawing_number = f"SF-PAIR-B-{seed:04d}"

    mutation_desc = ""
    swappable_gates = [c for c in panel_b.components if c.kind in INVERT_TWIN_MAP]
    switches = [c for c in panel_b.components if c.kind == ComponentKind.SWITCH]
    fuses = [c for c in panel_b.components if c.kind == ComponentKind.FUSE]

    if fuses and rng.random() < 0.25:
        fu = rng.choice(fuses)
        fu.intact = not fu.intact
        mutation_desc = f"Fuse {fu.id} changed from {'BLOWN' if fu.intact else 'INTACT'} to {'INTACT' if fu.intact else 'BLOWN'}"
    elif swappable_gates and rng.random() < 0.55:
        gate = rng.choice(swappable_gates)
        old_k = gate.kind.value.replace("gate_", "").upper()
        gate.kind = INVERT_TWIN_MAP[gate.kind]
        new_k = gate.kind.value.replace("gate_", "").upper()
        mutation_desc = f"Gate {gate.id} changed from {old_k} to {new_k} (inversion bubble)"
    elif switches:
        sw = rng.choice(switches)
        sw.closed = not sw.closed
        mutation_desc = f"Switch {sw.id} toggled from {'OPEN' if sw.closed else 'CLOSED'} to {'CLOSED' if sw.closed else 'OPEN'}"

    target_led = base_spec.metadata.get("target_led", "L1")
    ask_transition = rng.random() < 0.5

    spec = copy.deepcopy(base_spec)
    spec.metadata.pop("question_variant", None)
    spec.metadata.pop("toggle_switch_id", None)
    spec.canvas_width = 1600
    spec.canvas_height = 760
    spec.drawing_title = "COUNTERFACTUAL TWIN (PANEL A vs PANEL B)"
    spec.drawing_number = f"SF-DIFF-{seed:04d}"
    spec.secondary_panel = panel_b
    spec.panel_labels = ("PANEL A: BASELINE CIRCUIT", "PANEL B: REVISED CIRCUIT")
    spec.metadata["panel_diff_description"] = mutation_desc
    spec.metadata["ask_panel_b_state"] = ask_transition

    if ask_transition:
        question = (
            f"Compare Panel A (left) and Panel B (right) carefully for subtle switch, fuse, or gate-bubble differences. "
            f"How does the state of LED {target_led} transition from Panel A to Panel B? "
            f"Choose one: 'ON -> OFF', 'OFF -> ON', 'ON -> ON', or 'OFF -> OFF'."
        )
    else:
        question = (
            f"Compare Panel A (left) and Panel B (right) carefully. Does the final state of LED {target_led} change "
            f"between Panel A and Panel B? Reply with exactly YES or NO."
        )
    return spec, question

def _generate_component_audit(
    rng: random.Random,
    difficulty: DifficultyTier,
    label_mode: LabelMode,
    seed: int,
) -> tuple[SchematicSpec, str]:
    """Mixed multi-row grid schematic for precise symbol recognition & compliance counting."""
    comps: list[Component] = []
    nets: list[WireNet] = []
    conns: list[tuple[str, str, str, str]] = []

    n_rows = 2 if difficulty == DifficultyTier.EASY else (3 if difficulty == DifficultyTier.MEDIUM else 4)
    r_cnt = 1
    sw_cnt = 1
    g_cnt = 1

    for row in range(n_rows):
        ry = 145.0 + row * 125.0
        vcc = _make_source(f"VCC{row + 1}", 95.0, ry, level=1)
        sw = _make_switch(f"SW{sw_cnt}", 235.0, ry, closed=rng.choice([True, False]))
        sw_cnt += 1

        res_val = rng.choice([47, 68, 82, 100, 120, 220, 330, 470])
        res = _make_resistor(f"R{r_cnt}", 415.0, ry, res_val)
        r_cnt += 1

        g_kind = rng.choice(GATE_POOL_NO_NOT + [ComponentKind.GATE_NOT])
        gate = _make_gate(f"U{g_cnt}", g_kind, 650.0, ry)
        g_cnt += 1

        res2_val = rng.choice([47, 68, 100, 150, 220, 470])
        res2 = _make_resistor(f"R{r_cnt}", 850.0, ry, res2_val)
        r_cnt += 1

        led = _make_led(f"L{row + 1}", 1055.0, ry)
        comps.extend([vcc, sw, res, gate, res2, led])

        nets.append(WireNet(net_id=f"NA_{row}_1", points=[vcc.ports["out"], sw.ports["in"]]))
        nets.append(WireNet(net_id=f"NA_{row}_2", points=[sw.ports["out"], res.ports["p1"]]))
        if g_kind == ComponentKind.GATE_NOT:
            nets.append(WireNet(net_id=f"NA_{row}_3", points=[res.ports["p2"], gate.ports["in0"]]))
        else:
            nets.append(
                WireNet(
                    net_id=f"NA_{row}_3",
                    points=[res.ports["p2"], Point(x=545.0, y=ry), Point(x=545.0, y=ry - 14), gate.ports["in0"]],
                    junction_dots=[Point(x=545.0, y=ry)],
                    segments=[WireSegment(net_id=f"NA_{row}_3", p1=Point(x=545.0, y=ry), p2=Point(x=545.0, y=ry + 14)), WireSegment(net_id=f"NA_{row}_3", p1=Point(x=545.0, y=ry + 14), p2=gate.ports["in1"])],
                )
            )
        nets.append(WireNet(net_id=f"NA_{row}_4", points=[gate.ports["out"], res2.ports["p1"]]))
        nets.append(WireNet(net_id=f"NA_{row}_5", points=[res2.ports["p2"], led.ports["in"]]))

    query_type = rng.choice(
        ["count_resistors_min_ohm", "count_inverting_gates", "count_closed_switches", "count_open_switches"]
    )
    if query_type == "count_resistors_min_ohm":
        thresh = rng.choice([100, 150])
        audit_query = {"type": query_type, "threshold_ohm": thresh}
        banner = f"COMPLIANCE AUDIT RULE: Flag all resistors R* with resistance >= {thresh} Ohm"
        question = (
            f"Inspect every resistor label across all branches of the schematic. "
            f"How many resistors have a resistance value greater than or equal to {thresh} Ohm? Reply with an integer."
        )
    elif query_type == "count_inverting_gates":
        audit_query = {"type": query_type}
        banner = "COMPLIANCE AUDIT RULE: Count all IEEE inverting gates (NOT, NAND, NOR with output bubble)"
        question = (
            "Inspect every logic gate symbol visually across the schematic. "
            "How many inverting gates (NOT, NAND, or NOR gates carrying an output inversion bubble) are present? "
            "Reply with an integer."
        )
    elif query_type == "count_closed_switches":
        audit_query = {"type": query_type}
        banner = "COMPLIANCE AUDIT RULE: Count all switches whose contact blade is visibly CLOSED"
        question = (
            "Inspect every SPST switch symbol across the schematic. "
            "How many switches are visually in the CLOSED position? Reply with an integer."
        )
    else:
        audit_query = {"type": query_type}
        banner = "COMPLIANCE AUDIT RULE: Count all switches whose contact blade is visibly OPEN (tilted)"
        question = (
            "Inspect every SPST switch symbol across the schematic. "
            "How many switches are visually in the OPEN (disconnected) position? Reply with an integer."
        )

    nets, bridges = compute_wire_topology(nets)
    spec = SchematicSpec(
        drawing_title="DESIGN COMPLIANCE & SYMBOL AUDIT SHEET",
        drawing_number=f"SF-AUD-{seed:04d}",
        rule_banner=banner,
        label_mode=label_mode,
        components=comps,
        nets=nets,
        bridges=bridges,
        connections=conns,
        metadata={"audit_query": audit_query},
    )
    return spec, question

def _generate_whole_system(
    rng: random.Random,
    difficulty: DifficultyTier,
    label_mode: LabelMode,
    seed: int,
) -> tuple[SchematicSpec, str]:
    """Generate an end-to-end electromechanical control + load resistor board.

    Combines DC source, main protection fuse F1, interlock switches SW1..SWn,
    multi-stage combinational IEEE logic, indicator LEDs (L1, L2), and a
    switched parallel/series load resistor bank to GND, supporting multi-domain
    questions (Ohm's Law mA current, hypothetical switch-flip what-if, LED vector).
    """
    comps: list[Component] = []
    conns: list[tuple[str, str, str, str]] = []
    nets: list[WireNet] = []

    supply_v, r_ser, r_p1, r_p2 = rng.choice(WHOLE_LOAD_PRESETS)
    if difficulty == DifficultyTier.EASY:
        y_inputs = [150.0, 295.0, 440.0]
    elif difficulty == DifficultyTier.MEDIUM:
        y_inputs = [150.0, 295.0, 440.0]
    else:
        y_inputs = [140.0, 265.0, 390.0, 515.0]

    vcc = _make_source("VCC", 78.0, y_inputs[0], level=1, volts=supply_v)
    fuse = _make_fuse("F1", 175.0, y_inputs[0], intact=rng.choices([True, False], weights=[0.82, 0.18])[0])
    comps.extend([vcc, fuse])
    conns.append(("VCC", "out", "F1", "in"))
    nets.append(WireNet(net_id="NW_VCC_F1", points=[vcc.ports["out"], fuse.ports["in"]]))

    bus_x = 232.0
    sw_ids: list[str] = []
    bus_segs: list[WireSegment] = [WireSegment(net_id="NW_BUS", p1=fuse.ports["out"], p2=Point(x=bus_x, y=y_inputs[0]))]
    bus_dots: list[Point] = [Point(x=bus_x, y=y_inputs[0])]
    if len(y_inputs) > 1:
        bus_segs.append(WireSegment(net_id="NW_BUS", p1=Point(x=bus_x, y=y_inputs[0]), p2=Point(x=bus_x, y=y_inputs[-1])))

    for idx, y in enumerate(y_inputs):
        sw_id = f"SW{idx + 1}"
        sw = _make_switch(sw_id, 305.0, y, closed=rng.choice([True, False]))
        comps.append(sw)
        sw_ids.append(sw_id)
        conns.append(("F1", "out", sw_id, "in"))
        if idx == 0:
            bus_segs.append(WireSegment(net_id="NW_BUS", p1=Point(x=bus_x, y=y), p2=sw.ports["in"]))
        else:
            if idx < len(y_inputs) - 1:
                bus_dots.append(Point(x=bus_x, y=y))
            bus_segs.append(WireSegment(net_id="NW_BUS", p1=Point(x=bus_x, y=y), p2=sw.ports["in"]))

    nets.append(WireNet(net_id="NW_BUS", points=[], segments=bus_segs, junction_dots=bus_dots))
    comp_map = {c.id: c for c in comps}

    if difficulty == DifficultyTier.EASY:
        u1 = _make_gate("U1", rng.choice(GATE_POOL_NO_NOT), 515.0, 215.0)
        u2 = _make_gate("U2", rng.choice(GATE_POOL_NO_NOT), 705.0, 325.0)
        comps.extend([u1, u2])
        wires = [
            ("SW1", "U1", "in0", 390.0),
            ("SW2", "U1", "in1", 425.0),
            ("U1", "U2", "in0", 615.0),
            ("SW3", "U2", "in1", 590.0),
        ]
        if rng.random() < 0.45:
            wires[0], wires[1] = ("SW2", "U1", "in0", 405.0), ("SW1", "U1", "in1", 435.0)
        u_out = u2
        u_aux = u1
    elif difficulty == DifficultyTier.MEDIUM:
        u_not = _make_gate("U_NOT", ComponentKind.GATE_NOT, 420.0, 295.0)
        u1 = _make_gate("U1", rng.choice(GATE_POOL_NO_NOT), 565.0, 215.0)
        u2 = _make_gate("U2", rng.choice(GATE_POOL_NO_NOT), 735.0, 320.0)
        comps.extend([u_not, u1, u2])
        conns.append(("SW2", "out", "U_NOT", "in0"))
        nets.append(WireNet(net_id="NW_SW2_NOT", points=[comp_map["SW2"].ports["out"], u_not.ports["in0"]]))
        comp_map["U_NOT"] = u_not
        wires = [
            ("SW1", "U1", "in0", 485.0),
            ("U_NOT", "U1", "in1", 495.0),
            ("U1", "U2", "in0", 650.0),
            ("SW3", "U2", "in1", 625.0),
        ]
        u_out = u2
        u_aux = u1
    else:
        u_not = _make_gate("U_NOT", ComponentKind.GATE_NOT, 420.0, 265.0)
        u1 = _make_gate("U1", rng.choice(GATE_POOL_NO_NOT), 565.0, 195.0)
        u2 = _make_gate("U2", rng.choice(GATE_POOL_NO_NOT), 565.0, 420.0)
        u3 = _make_gate("U3", rng.choice(GATE_POOL_NO_NOT), 740.0, 305.0)
        comps.extend([u_not, u1, u2, u3])
        conns.append(("SW2", "out", "U_NOT", "in0"))
        nets.append(WireNet(net_id="NW_SW2_NOT", points=[comp_map["SW2"].ports["out"], u_not.ports["in0"]]))
        comp_map["U_NOT"] = u_not
        wires = [
            ("SW1", "U1", "in0", 480.0),
            ("U_NOT", "U1", "in1", 495.0),
            ("SW3", "U2", "in0", 470.0),
            ("SW4", "U2", "in1", 500.0),
        ]
        if rng.random() < 0.5:
            wires[1], wires[2] = ("U_NOT", "U2", "in0", 495.0), ("SW3", "U1", "in1", 475.0)
        conns.extend([("U1", "out", "U3", "in0"), ("U2", "out", "U3", "in1")])
        nets.append(WireNet(net_id="NW_U1_U3", points=_route_orthogonal("NW_U1_U3", u1.ports["out"], u3.ports["in0"], 655.0)))
        nets.append(WireNet(net_id="NW_U2_U3", points=_route_orthogonal("NW_U2_U3", u2.ports["out"], u3.ports["in1"], 680.0)))
        u_out = u3
        u_aux = u1

    comp_map.update({c.id: c for c in comps})
    for sid, did, dport, mx in wires:
        conns.append((sid, "out", did, dport))
        nets.append(
            WireNet(
                net_id=f"NW_{sid}_{did}_{dport}",
                points=_route_orthogonal(f"NW_{sid}_{did}_{dport}", comp_map[sid].ports["out"], comp_map[did].ports[dport], mx),
            )
        )

    l1 = _make_led("L1", 950.0, 175.0)
    l2 = _make_led("L2", 950.0, 285.0)
    comps.extend([l1, l2])
    conns.extend([(u_out.id, "out", "L1", "in"), (u_aux.id, "out", "L2", "in")])
    nets.append(WireNet(net_id="NW_AUX_L2", points=_route_orthogonal("NW_AUX_L2", u_aux.ports["out"], l2.ports["in"], 815.0)))

    drv_x = 855.0
    y_out = u_out.ports["out"].y
    drv_dots = [Point(x=drv_x, y=y_out)]
    nets.append(
        WireNet(
            net_id="NW_OUT_DRV",
            points=[u_out.ports["out"], Point(x=drv_x, y=y_out), Point(x=drv_x, y=l1.ports["in"].y), l1.ports["in"]],
            junction_dots=drv_dots,
            segments=[WireSegment(net_id="NW_OUT_DRV", p1=Point(x=drv_x, y=y_out), p2=Point(x=drv_x, y=495.0))],
        )
    )

    top_y, bot_y = 430.0, 560.0
    if difficulty == DifficultyTier.HARD:
        r1 = _make_resistor("R1", 915.0, 495.0, r_ser)
        left_x, right_x = 970.0, 1110.0
        r2 = _make_resistor("R2", 1040.0, top_y, r_p1)
        r3 = _make_resistor("R3", 1040.0, bot_y, r_p2)
        gnd_pt = Component(id="LOAD_GND", kind=ComponentKind.TEST_POINT, center=Point(x=1170.0, y=495.0), value_text="0V", ports={"in": Point(x=1150.0, y=495.0)})
        comps.extend([r1, r2, r3, gnd_pt])
        nets.append(WireNet(net_id="NW_L_IN", points=[Point(x=drv_x, y=495.0), r1.ports["p1"]]))
        nets.append(WireNet(net_id="NW_L_S", points=[r1.ports["p2"], Point(x=left_x, y=495.0)]))
        nets.append(WireNet(net_id="NW_L_T", points=[Point(x=left_x, y=495.0), Point(x=left_x, y=top_y), r2.ports["p1"]], junction_dots=[Point(x=left_x, y=495.0)]))
        nets.append(WireNet(net_id="NW_L_T2", points=[r2.ports["p2"], Point(x=right_x, y=top_y), Point(x=right_x, y=495.0)], junction_dots=[Point(x=right_x, y=495.0)]))
        nets.append(WireNet(net_id="NW_L_B", points=[Point(x=left_x, y=495.0), Point(x=left_x, y=bot_y), r3.ports["p1"]]))
        nets.append(WireNet(net_id="NW_L_B2", points=[r3.ports["p2"], Point(x=right_x, y=bot_y), Point(x=right_x, y=495.0)]))
        nets.append(WireNet(net_id="NW_L_OUT", points=[Point(x=right_x, y=495.0), gnd_pt.ports["in"]]))
        res_tree = {
            "type": "series",
            "children": [
                {"type": "resistor", "id": "R1", "ohm": r_ser},
                {"type": "parallel", "children": [{"type": "resistor", "id": "R2", "ohm": r_p1}, {"type": "resistor", "id": "R3", "ohm": r_p2}]},
            ],
        }
    else:
        easy_pairs = [(12, 60, 60), (12, 120, 40), (24, 120, 60), (24, 120, 120)]
        supply_v, r_p1, r_p2 = easy_pairs[seed % len(easy_pairs)]
        vcc.value_text = f"{supply_v}V"
        left_x, right_x = 925.0, 1105.0
        r1 = _make_resistor("R1", 1015.0, top_y, r_p1)
        r2 = _make_resistor("R2", 1015.0, bot_y, r_p2)
        gnd_pt = Component(id="LOAD_GND", kind=ComponentKind.TEST_POINT, center=Point(x=1170.0, y=495.0), value_text="0V", ports={"in": Point(x=1150.0, y=495.0)})
        comps.extend([r1, r2, gnd_pt])
        nets.append(WireNet(net_id="NW_L_IN", points=[Point(x=drv_x, y=495.0), Point(x=left_x, y=495.0)]))
        nets.append(WireNet(net_id="NW_L_T", points=[Point(x=left_x, y=495.0), Point(x=left_x, y=top_y), r1.ports["p1"]], junction_dots=[Point(x=left_x, y=495.0)]))
        nets.append(WireNet(net_id="NW_L_T2", points=[r1.ports["p2"], Point(x=right_x, y=top_y), Point(x=right_x, y=495.0)], junction_dots=[Point(x=right_x, y=495.0)]))
        nets.append(WireNet(net_id="NW_L_B", points=[Point(x=left_x, y=495.0), Point(x=left_x, y=bot_y), r2.ports["p1"]]))
        nets.append(WireNet(net_id="NW_L_B2", points=[r2.ports["p2"], Point(x=right_x, y=bot_y), Point(x=right_x, y=495.0)]))
        nets.append(WireNet(net_id="NW_L_OUT", points=[Point(x=right_x, y=495.0), gnd_pt.ports["in"]]))
        res_tree = {"type": "parallel", "children": [{"type": "resistor", "id": "R1", "ohm": r_p1}, {"type": "resistor", "id": "R2", "ohm": r_p2}]}

    variants = ["system_current_ma", "what_if_switch_toggle", "multi_led_vector"]
    q_var = variants[seed % len(variants)]
    tog_sw = rng.choice(sw_ids)
    banner = f"LOAD DRIVER RULE: When L1=ON ({u_out.id}=HIGH & F1 intact), {supply_v}V VCC powers R-bank to 0V; when L1=OFF, load current = 0 mA."

    nets, bridges = compute_wire_topology(nets)
    spec = SchematicSpec(
        drawing_title="INTEGRATED SYSTEM CONTROL & LOAD BOARD",
        drawing_number=f"SF-SYS-{seed:04d}",
        rule_banner=banner,
        label_mode=label_mode,
        components=comps,
        nets=nets,
        bridges=bridges,
        connections=conns,
        metadata={
            "question_variant": q_var,
            "target_led": "L1",
            "toggle_switch_id": tog_sw,
            "supply_volts": supply_v,
            "resistance_tree": res_tree,
        },
    )

    if q_var == "system_current_ma":
        question = (
            f"Trace the whole board from {supply_v}V VCC through fuse F1, switches {', '.join(sw_ids)}, and logic gates to load relay L1. "
            f"If L1 is ON, calculate the total current flowing from {supply_v}V through the load resistor bank (R1..R{'3' if difficulty == DifficultyTier.HARD else '2'}) in mA "
            f"(0 mA if L1 is OFF or F1 blown). Reply with exact current (e.g. '200 mA')."
        )
    elif q_var == "what_if_switch_toggle":
        question = (
            f"Examine the complete control circuit from VCC and F1 through all switches and gates to indicator L1. "
            f"If switch {tog_sw} is toggled to the OPPOSITE of its shown blade position while all other parts stay as drawn, "
            f"does L1 become ON or OFF? Reply with exactly one word: ON or OFF."
        )
    else:
        question = (
            f"Trace the entire integrated board from {supply_v}V VCC through fuse F1, switches {', '.join(sw_ids)}, and all gates. "
            f"What are the combined steady-state outputs of both L1 and L2? "
            f"Choose one: 'L1=ON, L2=ON', 'L1=ON, L2=OFF', 'L1=OFF, L2=ON', or 'L1=OFF, L2=OFF'."
        )
    return spec, question

def generate_task_spec(
    family: TaskFamily,
    difficulty: DifficultyTier,
    label_mode: LabelMode,
    seed: int,
) -> tuple[SchematicSpec, str]:
    """Generate a single deterministic SchematicSpec and prompt question."""
    rng = random.Random(seed)

    if family == TaskFamily.STATE_PROPAGATION:
        spec, q = _generate_state_propagation(rng, difficulty, label_mode, seed)
    elif family == TaskFamily.BRIDGE_VS_JUNCTION:
        spec, q = _generate_bridge_vs_junction(rng, difficulty, label_mode, seed)
    elif family == TaskFamily.EQUIVALENT_RESISTANCE:
        spec, q = _generate_equivalent_resistance(rng, difficulty, label_mode, seed)
    elif family == TaskFamily.FAULT_DIAGNOSIS:
        spec, q = _generate_fault_diagnosis(rng, difficulty, label_mode, seed)
    elif family == TaskFamily.COUNTERFACTUAL_PAIR:
        spec, q = _generate_counterfactual_pair(rng, difficulty, label_mode, seed)
    elif family == TaskFamily.COMPONENT_AUDIT:
        spec, q = _generate_component_audit(rng, difficulty, label_mode, seed)
    elif family == TaskFamily.WHOLE_SYSTEM:
        spec, q = _generate_whole_system(rng, difficulty, label_mode, seed)
    else:
        raise ValueError(f"Unsupported family: {family}")

    spec.metadata["seed"] = seed
    spec.metadata["family"] = family.value
    spec.metadata["difficulty"] = difficulty.value
    return spec, q
