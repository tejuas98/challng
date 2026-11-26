"""Custom Declarative Netlist & DSL Compiler + 10,000x Arbitrary Variation Factory.

Allows judges, engineering teams, and automated harnesses to input ANY custom
combinational or multi-stage circuit (as JSON netlist OR shorthand arrow DSL, e.g.:
  VCC1(12V) -> SW1(CLOSED) -> F1(OK) -> U1(NAND) -> L1
  VCC1 -> SW2(OPEN) -> U_INV(NOT) -> U1
) without specifying pixel coordinates. SchemForge automatically assigns layered
columns, routes collision-free orthogonal wires with crossing bridge jumps, solves
exact formal ground truth, and can spawn 1 to 25,000+ unique variations of the
judge's own custom circuit cleanly.
"""

from __future__ import annotations

from collections import defaultdict, deque
import copy
import json
from pathlib import Path
import random
import re
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from schemforge.degradation import apply_degradation
from schemforge.generator import (
    GATE_POOL_NO_NOT,
    INVERT_TWIN_MAP,
    _make_fuse,
    _make_gate,
    _make_led,
    _make_resistor,
    _make_source,
    _make_switch,
    _route_orthogonal,
    compute_wire_topology,
)
from schemforge.netlist import (
    Component,
    ComponentKind,
    DegradationProfile,
    DifficultyTier,
    LabelMode,
    Point,
    SchematicSpec,
    TaskFamily,
    TaskPackage,
    ThemeStyle,
    WireNet,
)
from schemforge.renderer import render_schematic
from schemforge.solver import solve_logic_network, solve_task
from schemforge.validator import validate_task_package

class CustomNodeDef(BaseModel):
    id: str
    kind: Literal[
        "source", "switch", "fuse", "resistor", "led",
        "gate_and", "gate_or", "gate_nand", "gate_nor", "gate_xor", "gate_not",
    ]
    closed: Optional[bool] = True
    intact: Optional[bool] = True
    voltage_level: Optional[int] = 1
    resistance_ohm: Optional[int] = 100
    value_text: Optional[str] = None

class CustomEdgeDef(BaseModel):
    src: str
    dst: str
    dst_port: Optional[str] = None

class CustomCircuitInput(BaseModel):
    title: str = "CUSTOM INDUSTRIAL CIRCUIT"
    nodes: list[CustomNodeDef]
    edges: list[CustomEdgeDef]
    target_led: Optional[str] = None
    theme: ThemeStyle = ThemeStyle.IEEE_CLASSIC
    degradation: DegradationProfile = DegradationProfile.CLEAN
    label_mode: LabelMode = LabelMode.SYMBOL_ONLY
    seed: int = 1001

_DSL_KIND_TOKENS = {
    "AND": "gate_and",
    "OR": "gate_or",
    "NAND": "gate_nand",
    "NOR": "gate_nor",
    "XOR": "gate_xor",
    "NOT": "gate_not",
    "INV": "gate_not",
}

def parse_netlist_text(raw_text: str, title: str = "CUSTOM DSL SCHEMATIC") -> CustomCircuitInput:
    """Parse either JSON CustomCircuitInput OR shorthand arrow DSL into CustomCircuitInput.

    Supported DSL line examples:
      VCC1(12V) -> SW_DOOR(CLOSED) -> F1(OK) -> U_LOCK(AND) -> ALARM_LED
      VCC1 -> SW_ESTOP(OPEN) -> U_INV(NOT) -> U_LOCK
    """
    stripped = raw_text.strip()
    if not stripped:
        raise ValueError("Empty netlist specification.")
    if stripped.startswith("{"):
        return CustomCircuitInput.model_validate_json(stripped)

    nodes_by_id: dict[str, CustomNodeDef] = {}
    edges: list[CustomEdgeDef] = []
    seen_edges: set[tuple[str, str]] = set()
    first_led: Optional[str] = None
    parsed_title = title

    for raw_ln in stripped.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        if ln.upper().startswith("# TITLE:"):
            parsed_title = ln.split(":", 1)[1].strip() or parsed_title
            continue
        if ln.startswith("#") or ln.startswith("//"):
            continue
        parts = [p.strip() for p in re.split(r"->|=>", ln) if p.strip()]
        if len(parts) < 1:
            continue

        line_ids: list[str] = []
        for token in parts:
            m = re.match(r"^([A-Za-z0-9_]+)(?:\(([^)]*)\))?$", token)
            if not m:
                raise ValueError(f"Cannot parse netlist token '{token}'. Expected ID or ID(SPEC).")
            nid = m.group(1)
            arg = (m.group(2) or "").strip().upper()
            line_ids.append(nid)

            if nid not in nodes_by_id:
                up_id = nid.upper()
                kind = "switch"
                closed = True
                intact = True
                volt_lvl = 1
                ohm = 100
                val_txt: Optional[str] = None

                if arg in _DSL_KIND_TOKENS:
                    kind = _DSL_KIND_TOKENS[arg]
                elif arg in ("CLOSED", "ON", "OPEN", "OFF"):
                    if up_id.startswith("F"):
                        kind = "fuse"
                        intact = arg in ("CLOSED", "ON", "OK", "INTACT")
                    else:
                        kind = "switch"
                        closed = arg in ("CLOSED", "ON")
                elif arg in ("OK", "INTACT", "BLOWN"):
                    kind = "fuse"
                    intact = arg != "BLOWN"
                elif arg.endswith("V") and arg[:-1].isdigit():
                    kind = "source"
                    volts = int(arg[:-1])
                    volt_lvl = 1 if volts > 0 else 0
                    val_txt = f"{volts}V"
                elif "OHM" in arg or arg.endswith("R"):
                    kind = "resistor"
                    digits = re.findall(r"\d+", arg)
                    ohm = int(digits[0]) if digits else 100
                elif up_id.startswith(("VCC", "VIN", "BUS", "PWR", "SRC")):
                    kind = "source"
                    val_txt = arg or "5V"
                elif up_id.startswith(("SW", "S_")):
                    kind = "switch"
                elif up_id.startswith(("F", "FUSE")):
                    kind = "fuse"
                elif up_id.startswith(("L", "LED", "LAMP", "OUT", "ALARM")):
                    kind = "led"
                elif up_id.startswith("R"):
                    kind = "resistor"
                elif up_id.startswith(("U_NOT", "INV")):
                    kind = "gate_not"
                elif up_id.startswith("U"):
                    kind = "gate_and"

                if kind == "led" and first_led is None:
                    first_led = nid
                nodes_by_id[nid] = CustomNodeDef(
                    id=nid,
                    kind=kind,
                    closed=closed,
                    intact=intact,
                    voltage_level=volt_lvl,
                    resistance_ohm=ohm,
                    value_text=val_txt,
                )

        for src_id, dst_id in zip(line_ids[:-1], line_ids[1:]):
            if (src_id, dst_id) not in seen_edges:
                seen_edges.add((src_id, dst_id))
                edges.append(CustomEdgeDef(src=src_id, dst=dst_id))

    if not nodes_by_id or not edges:
        raise ValueError("Custom netlist must specify at least 2 connected nodes.")
    return CustomCircuitInput(
        title=parsed_title,
        nodes=list(nodes_by_id.values()),
        edges=edges,
        target_led=first_led,
    )

def build_spec_from_custom_input(
    payload: CustomCircuitInput,
    question_mode: str = "state",
    layout_shuffle_seed: Optional[int] = None,
) -> tuple[SchematicSpec, str, TaskFamily]:
    """Compile declarative CustomCircuitInput into SchematicSpec, Question, and TaskFamily."""
    node_map = {n.id: n for n in payload.nodes}
    if len(node_map) != len(payload.nodes):
        raise ValueError("Duplicate node IDs detected in custom netlist.")

    indeg: dict[str, int] = {n.id: 0 for n in payload.nodes}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in payload.edges:
        if e.src not in node_map or e.dst not in node_map:
            raise ValueError(f"Unknown endpoint in edge {e.src} -> {e.dst}")
        adj[e.src].append(e.dst)
        indeg[e.dst] += 1

    layer: dict[str, int] = {nid: 0 for nid in node_map}
    q = deque([nid for nid, d in indeg.items() if d == 0])
    visited = 0
    while q:
        u = q.popleft()
        visited += 1
        for v in adj[u]:
            layer[v] = max(layer[v], layer[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    if visited != len(payload.nodes):
        raise ValueError("Cyclic circuit detected in custom netlist; combinational DAG required.")

    max_layer = max(layer.values()) if layer else 1
    by_layer: dict[int, list[CustomNodeDef]] = defaultdict(list)
    for n in payload.nodes:
        by_layer[layer[n.id]].append(n)

    if layout_shuffle_seed is not None:
        lrng = random.Random(layout_shuffle_seed)
        for group in by_layer.values():
            if len(group) > 1:
                lrng.shuffle(group)

    x_start, x_end = 95.0, 1110.0
    col_span = (x_end - x_start) / max(1, max_layer)
    y_top, y_bot = 130.0, 565.0

    comps: list[Component] = []
    comp_lookup: dict[str, Component] = {}

    for lyr_idx, group in sorted(by_layer.items()):
        cx = round(x_start + lyr_idx * col_span, 1)
        row_step = (y_bot - y_top) / max(1, len(group) - 1) if len(group) > 1 else 0.0
        for r_idx, nd in enumerate(group):
            cy = round(340.0 if len(group) == 1 else y_top + r_idx * row_step, 1)
            k = ComponentKind(nd.kind)
            if k == ComponentKind.SOURCE:
                c = _make_source(nd.id, cx, cy, level=1 if nd.voltage_level is None else nd.voltage_level)
                if nd.value_text:
                    c.value_text = nd.value_text
            elif k == ComponentKind.SWITCH:
                c = _make_switch(nd.id, cx, cy, closed=True if nd.closed is None else nd.closed)
            elif k == ComponentKind.FUSE:
                c = _make_fuse(nd.id, cx, cy, intact=True if nd.intact is None else nd.intact)
            elif k == ComponentKind.RESISTOR:
                c = _make_resistor(nd.id, cx, cy, ohm=nd.resistance_ohm or 100)
            elif k == ComponentKind.LED:
                c = _make_led(nd.id, cx, cy)
            else:
                c = _make_gate(nd.id, k, cx, cy)
            comps.append(c)
            comp_lookup[nd.id] = c

    conns: list[tuple[str, str, str, str]] = []
    nets: list[WireNet] = []
    used_gate_ports: dict[str, int] = defaultdict(int)

    for idx, e in enumerate(payload.edges):
        src_c = comp_lookup[e.src]
        dst_c = comp_lookup[e.dst]
        if e.dst_port and e.dst_port in dst_c.ports:
            dport = e.dst_port
        elif dst_c.kind in (
            ComponentKind.GATE_AND,
            ComponentKind.GATE_OR,
            ComponentKind.GATE_NAND,
            ComponentKind.GATE_NOR,
            ComponentKind.GATE_XOR,
        ):
            p_idx = used_gate_ports[dst_c.id]
            dport = "in0" if p_idx == 0 else "in1"
            used_gate_ports[dst_c.id] += 1
        elif dst_c.kind == ComponentKind.GATE_NOT:
            dport = "in0"
        elif "in" in dst_c.ports:
            dport = "in"
        else:
            dport = "p1"

        conns.append((e.src, "out", e.dst, dport))
        p_out = src_c.ports["out"]
        p_in = dst_c.ports[dport]
        gap = max(24.0, p_in.x - p_out.x)
        mid_x = round(p_out.x + gap * (0.28 + 0.44 * ((idx % 5) / 4.0)), 1)
        pts = _route_orthogonal(f"CE_{idx}", p_out, p_in, mid_x=mid_x)
        nets.append(WireNet(net_id=f"NET_{e.src}", points=pts))

    nets, bridges = compute_wire_topology(nets)
    leds = [c.id for c in comps if c.kind == ComponentKind.LED]
    switches = [c.id for c in comps if c.kind == ComponentKind.SWITCH]
    if not leds:
        raise ValueError("Custom netlist must include at least one 'led' output component.")
    target_led = payload.target_led if payload.target_led in leds else leds[0]

    meta: dict = {"target_led": target_led, "seed": payload.seed, "custom_netlist": True}
    if question_mode == "what_if_toggle" and switches:
        tog_sw = random.Random(payload.seed).choice(switches)
        meta["question_variant"] = "what_if_switch_toggle"
        meta["toggle_switch_id"] = tog_sw
        question = (
            f"Inspect the custom schematic '{payload.title}'. Suppose switch {tog_sw} is toggled to the OPPOSITE "
            f"of its drawn position while every other component remains unchanged. Will indicator {target_led} be ON or OFF? "
            f"Reply with ON or OFF."
        )
    else:
        question = (
            f"Inspect the custom schematic '{payload.title}'. Trace all power rails, switches, fuses, and IEEE gates. "
            f"Is indicator {target_led} ON or OFF? Reply with ON or OFF."
        )

    spec = SchematicSpec(
        drawing_title=payload.title[:46].upper(),
        drawing_number=f"SF-CUST-{payload.seed:05d}",
        label_mode=payload.label_mode,
        components=comps,
        nets=nets,
        bridges=bridges,
        connections=conns,
        metadata=meta,
    )
    return spec, question, TaskFamily.STATE_PROPAGATION

def compile_custom_netlist(
    payload: CustomCircuitInput,
    out_dir: str | Path,
    task_id: Optional[str] = None,
    run_ocr: bool = True,
    lazy_render: bool = False,
) -> TaskPackage:
    """Compile arbitrary declarative DAG netlist into an audited TaskPackage."""
    out_path = Path(out_dir)
    img_dir = out_path / "images"
    spec_dir = out_path / "specs"
    img_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    spec, question, fam = build_spec_from_custom_input(payload)
    proof = solve_task(spec, fam)

    tid = task_id or f"custom_{payload.seed}"
    png_path = img_dir / f"{tid}.png"
    spec_path = spec_dir / f"{tid}.json"
    spec_path.write_text(spec.model_dump_json())

    bboxes: dict = {}
    if not lazy_render:
        bboxes = render_schematic(spec, png_path, theme=payload.theme)
        apply_degradation(str(png_path), payload.degradation, seed=payload.seed + 77)

    pkg = TaskPackage(
        task_id=tid,
        seed=payload.seed,
        family=fam,
        difficulty=DifficultyTier.HARD if len(spec.components) >= 8 else DifficultyTier.MEDIUM,
        theme=payload.theme,
        degradation=payload.degradation,
        label_mode=payload.label_mode,
        question=question,
        answer=proof.answer,
        answer_type=proof.answer_type,
        choices=proof.choices,
        image_path=str(png_path),
        spec_path=str(spec_path),
        solver_proof=proof,
        rendered_bboxes=bboxes,
    )
    if not lazy_render:
        pkg.quality_audit = validate_task_package(pkg, spec, run_ocr=run_ocr)
    return pkg

def estimate_custom_combinations(
    payload: CustomCircuitInput,
    requested_count: int = 100,
    themes_count: int = 4,
    degs_count: int = 4,
    label_modes_count: int = 2,
) -> dict:
    """Compute exact combinatorial state space of a user custom circuit without duplicates."""
    n_sw = sum(1 for nd in payload.nodes if nd.kind == "switch")
    n_fuse = sum(1 for nd in payload.nodes if nd.kind == "fuse")
    n_gates = sum(1 for nd in payload.nodes if nd.kind in ("gate_and", "gate_or", "gate_nand", "gate_nor", "gate_xor"))
    n_res = sum(1 for nd in payload.nodes if nd.kind == "resistor")
    q_modes = 2 if n_sw > 0 else 1

    circuit_states = (2 ** n_sw) * (2 ** n_fuse) * (5 ** n_gates) * (6 ** n_res)
    total_unique = min(10_000_000, circuit_states * q_modes * themes_count * degs_count * label_modes_count)
    effective = min(requested_count, total_unique)
    return {
        "unique_circuit_structures": circuit_states * q_modes,
        "unique_with_visuals": total_unique,
        "requested_count": requested_count,
        "effective_max": effective,
        "will_cap": requested_count > total_unique,
        "switches": n_sw,
        "fuses": n_fuse,
        "gates": n_gates,
        "resistors": n_res,
    }

def _coprime_stride(mod_n: int, rng: random.Random) -> int:
    import math
    if mod_n <= 2:
        return 1
    cand = max(1, (mod_n * 618033) // 1000000 + rng.randrange(min(17, mod_n)))
    while math.gcd(cand, mod_n) != 1:
        cand += 1
    return cand % mod_n

def generate_custom_variations(
    payload: CustomCircuitInput,
    out_dir: str | Path,
    count: int = 100,
    base_seed: int = 1000,
    lazy_render: Optional[bool] = None,
    run_ocr: bool = True,
    degradations: Optional[list[DegradationProfile]] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> list[TaskPackage]:
    """Generate unique, non-repetitive variations via full-period Cartesian indexing + dedup."""
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    img_dir = out_path / "images"
    spec_dir = out_path / "specs"
    img_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    use_lazy = (count > 120) if lazy_render is None else lazy_render
    rng = random.Random(base_seed)
    themes = list(ThemeStyle)
    degs = degradations or [
        DegradationProfile.CLEAN,
        DegradationProfile.OFFICE_SCAN,
        DegradationProfile.MOBILE_PHOTO,
        DegradationProfile.LOW_CONTRAST_FAX,
    ]
    lmodes = [LabelMode.SYMBOL_ONLY, LabelMode.ANNOTATED]
    gate_choices = ["gate_and", "gate_or", "gate_nand", "gate_nor", "gate_xor"]
    res_choices = [40, 60, 80, 100, 120, 150]

    sw_indices = [idx for idx, nd in enumerate(payload.nodes) if nd.kind == "switch"]
    fuse_indices = [idx for idx, nd in enumerate(payload.nodes) if nd.kind == "fuse"]
    gate_indices = [idx for idx, nd in enumerate(payload.nodes) if nd.kind in gate_choices]
    res_indices = [idx for idx, nd in enumerate(payload.nodes) if nd.kind == "resistor"]

    radices: list[tuple[str, int, int]] = []
    for idx in sw_indices:
        radices.append(("sw", idx, 2))
    for idx in fuse_indices:
        radices.append(("fuse", idx, 2))
    for idx in gate_indices:
        radices.append(("gate", idx, len(gate_choices)))
    for idx in res_indices:
        radices.append(("res", idx, len(res_choices)))
    qmodes = ["state", "what_if_toggle"] if sw_indices else ["state"]
    radices.append(("qmode", 0, len(qmodes)))
    radices.append(("theme", 0, len(themes)))
    radices.append(("deg", 0, len(degs)))
    radices.append(("lmode", 0, len(lmodes)))

    total_space = 1
    for _, _, base in radices:
        total_space *= base

    target_count = min(count, total_space)
    capped = target_count < count
    stride = _coprime_stride(total_space, rng)
    offset = rng.randrange(total_space) if total_space > 1 else 0

    tasks: list[TaskPackage] = []
    manifest_lines: list[str] = []
    seen_sigs: set[str] = set()

    for step in range(total_space):
        if len(tasks) >= target_count:
            break
        combo_idx = (offset + step * stride) % total_space
        rem = combo_idx
        var_in = payload.model_copy(deep=True)
        seed_i = base_seed + len(tasks)
        var_in.seed = seed_i
        qmode = "state"

        for rtype, node_i, base in radices:
            val = rem % base
            rem //= base
            if rtype == "sw":
                var_in.nodes[node_i].closed = bool(val)
            elif rtype == "fuse":
                var_in.nodes[node_i].intact = bool(val)
            elif rtype == "gate":
                var_in.nodes[node_i].kind = gate_choices[val]
            elif rtype == "res":
                var_in.nodes[node_i].resistance_ohm = res_choices[val]
            elif rtype == "qmode":
                qmode = qmodes[val]
            elif rtype == "theme":
                var_in.theme = themes[val]
            elif rtype == "deg":
                var_in.degradation = degs[val]
            elif rtype == "lmode":
                var_in.label_mode = lmodes[val]

        i = len(tasks)
        tid = f"cust_{i:05d}_{seed_i}"
        spec, question, fam = build_spec_from_custom_input(
            var_in,
            question_mode=qmode,
            layout_shuffle_seed=(seed_i if i > 0 else None),
        )
        proof = solve_task(spec, fam)
        sig = repr((
            tuple((nd.kind, nd.closed, nd.intact, nd.resistance_ohm) for nd in var_in.nodes),
            qmode,
            question,
            proof.answer,
            var_in.theme.value,
            var_in.degradation.value,
            var_in.label_mode.value,
        ))
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)

        spec_path = spec_dir / f"{tid}.json"
        png_path = img_dir / f"{tid}.png"

        should_render = (not use_lazy) or (i < 40)
        bboxes: dict = {}
        if should_render:
            spec_path.write_text(spec.model_dump_json())
            bboxes = render_schematic(spec, png_path, theme=var_in.theme)
            apply_degradation(str(png_path), var_in.degradation, seed=seed_i + 77)
        else:
            spec_path.write_text(spec.model_dump_json())

        pkg = TaskPackage(
            task_id=tid,
            seed=seed_i,
            family=fam,
            difficulty=DifficultyTier.HARD if len(spec.components) >= 8 else DifficultyTier.MEDIUM,
            theme=var_in.theme,
            degradation=var_in.degradation,
            label_mode=var_in.label_mode,
            question=question,
            answer=proof.answer,
            answer_type=proof.answer_type,
            choices=proof.choices,
            image_path=f"images/{tid}.png",
            spec_path=f"specs/{tid}.json",
            solver_proof=proof,
            rendered_bboxes=bboxes,
        )
        if should_render:
            pkg_abs = pkg.model_copy(deep=True)
            pkg_abs.image_path = str(png_path)
            pkg_abs.spec_path = str(spec_path)
            pkg.quality_audit = validate_task_package(pkg_abs, spec, run_ocr=run_ocr)
        tasks.append(pkg)
        manifest_lines.append(pkg.model_dump_json())
        if progress_cb and (len(tasks) % 50 == 0 or len(tasks) == target_count):
            progress_cb(len(tasks), target_count)

    (out_path / "dataset.jsonl").write_text("\n".join(manifest_lines) + "\n")
    (out_path / "manifest.json").write_text(
        json.dumps(
            {
                "total_tasks": len(tasks),
                "requested_count": count,
                "unique_combinations_available": total_space,
                "capped_at_unique_limit": capped,
                "base_seed": base_seed,
                "custom_title": payload.title,
                "lazy_render": use_lazy,
            },
            indent=2,
        )
    )
    return tasks
