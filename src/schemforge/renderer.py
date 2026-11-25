"""High-resolution IEEE/IEC CAD Schematic Vector Renderer.

Draws crisp, authentic engineering schematic blueprints with exact pixel
coordinate tracking (`rendered_bboxes`), orthogonal wire routing, curved bridge
hops, solid solder junction dots, ANSI logic gates, title blocks, and zone grids.
Also emits clean parallel SVG files for vector inspection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.path import Path as MplPath
from PIL import Image

from schemforge.netlist import (
    BBox,
    Component,
    ComponentKind,
    LabelMode,
    Point,
    SchematicSpec,
    ThemeStyle,
)

@dataclass(frozen=True)
class ThemePalette:
    bg: str
    paper: str
    grid_line: str
    border: str
    wire: str
    component_stroke: str
    component_fill: str
    accent: str
    text_primary: str
    text_muted: str
    dot_fill: str
    led_fill: str
    banner_bg: str

THEMES: dict[ThemeStyle, ThemePalette] = {
    ThemeStyle.IEEE_CLASSIC: ThemePalette(
        bg="#e2eefc",
        paper="#ffffff",
        grid_line="#93c5fd",
        border="#0c2461",
        wire="#091326",
        component_stroke="#091326",
        component_fill="#dbeafe",
        accent="#0369a1",
        text_primary="#091326",
        text_muted="#1e3a8a",
        dot_fill="#0c2461",
        led_fill="#fef08a",
        banner_bg="#dbeafe",
    ),
    ThemeStyle.KICAD_BLUEPRINT: ThemePalette(
        bg="#0b1526",
        paper="#0f1d32",
        grid_line="#1a2f4d",
        border="#60a5fa",
        wire="#38bdf8",
        component_stroke="#e2e8f0",
        component_fill="#162944",
        accent="#fbbf24",
        text_primary="#f8fafc",
        text_muted="#94a3b8",
        dot_fill="#fbbf24",
        led_fill="#3b2f13",
        banner_bg="#172554",
    ),
    ThemeStyle.AGED_PAPER: ThemePalette(
        bg="#f3ebd3",
        paper="#f7f1de",
        grid_line="#e3d8b8",
        border="#292524",
        wire="#1c1917",
        component_stroke="#1c1917",
        component_fill="#ede3c7",
        accent="#9a3412",
        text_primary="#1c1917",
        text_muted="#57534e",
        dot_fill="#1c1917",
        led_fill="#fde68a",
        banner_bg="#e7dec1",
    ),
    ThemeStyle.HIGH_CONTRAST_MONO: ThemePalette(
        bg="#ffffff",
        paper="#ffffff",
        grid_line="#e5e5e5",
        border="#000000",
        wire="#000000",
        component_stroke="#000000",
        component_fill="#ffffff",
        accent="#000000",
        text_primary="#000000",
        text_muted="#333333",
        dot_fill="#000000",
        led_fill="#ffffff",
        banner_bg="#f3f4f6",
    ),
}

def _record_label_bbox(
    bboxes: dict[str, BBox], key: str, x: float, y: float, text: str, fontsize: float
) -> None:
    char_w = fontsize * 0.62
    w = max(18.0, len(text) * char_w)
    h = fontsize * 1.45
    bboxes[key] = BBox(x1=x - w / 2.0, y1=y - h / 2.0, x2=x + w / 2.0, y2=y + h / 2.0)

def _draw_wire_with_bridges(
    ax: plt.Axes,
    p1: Point,
    p2: Point,
    bridges: list,
    color: str,
    lw: float,
) -> None:
    """Draw a straight orthogonal wire segment, splitting at vertical bridge jumps."""
    is_vert = abs(p1.x - p2.x) < 1e-3 and abs(p1.y - p2.y) > 1.0
    if not is_vert:
        ax.plot([p1.x, p2.x], [p1.y, p2.y], color=color, linewidth=lw, solid_capstyle="round", zorder=2)
        return

    vx = p1.x
    y_min, y_max = sorted([p1.y, p2.y])
    relevant = sorted(
        [
            b
            for b in bridges
            if abs(b.center.x - vx) < 2.0 and y_min + 4 < b.center.y < y_max - 4
        ],
        key=lambda b: b.center.y,
    )

    if not relevant:
        ax.plot([vx, vx], [y_min, y_max], color=color, linewidth=lw, solid_capstyle="round", zorder=2)
        return

    cur_y = y_min
    for b in relevant:
        r = b.radius
        cy = b.center.y
        if cy - r > cur_y:
            ax.plot([vx, vx], [cur_y, cy - r], color=color, linewidth=lw, solid_capstyle="round", zorder=2)
        arc = patches.Arc(
            (vx, cy),
            width=2.0 * r,
            height=2.0 * r,
            angle=0,
            theta1=-90,
            theta2=90,
            color=color,
            linewidth=lw,
            zorder=3,
        )
        ax.add_patch(arc)
        cur_y = cy + r

    if cur_y < y_max:
        ax.plot([vx, vx], [cur_y, y_max], color=color, linewidth=lw, solid_capstyle="round", zorder=2)

def _draw_component(
    ax: plt.Axes,
    comp: Component,
    pal: ThemePalette,
    label_mode: LabelMode,
    bboxes: dict[str, BBox],
    ox: float = 0.0,
    oy: float = 0.0,
    scale: float = 1.0,
    prefix: str = "",
) -> None:
    cx = ox + comp.center.x * scale
    cy = oy + comp.center.y * scale
    s = scale
    bboxes[f"comp:{prefix}{comp.id}"] = BBox(
        x1=cx - 34 * s, y1=cy - 26 * s, x2=cx + 34 * s, y2=cy + 26 * s
    )

    if comp.kind == ComponentKind.SOURCE:
        circ = patches.Circle((cx, cy), 18 * s, facecolor=pal.component_fill, edgecolor=pal.accent, linewidth=2.2 * s, zorder=4)
        ax.add_patch(circ)
        line_out = patches.ConnectionPatch((cx + 18 * s, cy), (cx + 26 * s, cy), "data", "data", color=pal.wire, linewidth=2.0 * s)
        ax.add_artist(line_out)
        val_txt = comp.value_text or ("5V" if comp.voltage_level else "0V")
        v_fs = (8.2 if len(val_txt) >= 3 else 9.5) * s
        ax.text(cx, cy, val_txt, color=pal.accent, fontsize=v_fs, fontweight="bold", ha="center", va="center", zorder=5, family="sans-serif")
        ax.text(cx, cy - 28 * s, comp.id, color=pal.text_primary, fontsize=10.0 * s, fontweight="bold", ha="center", va="bottom", zorder=6, family="sans-serif")
        _record_label_bbox(bboxes, f"lbl:{prefix}{comp.id}", cx, cy - 33 * s, comp.id, 10.0 * s)

    elif comp.kind == ComponentKind.SWITCH:
        p_in = cx - 30 * s
        p_out = cx + 30 * s
        c_left = cx - 18 * s
        c_right = cx + 18 * s
        ax.plot([p_in, c_left], [cy, cy], color=pal.wire, lw=2.2 * s, zorder=4)
        ax.plot([c_right, p_out], [cy, cy], color=pal.wire, lw=2.2 * s, zorder=4)
        for px in (c_left, c_right):
            ax.add_patch(patches.Circle((px, cy), 4.0 * s, facecolor=pal.paper, edgecolor=pal.component_stroke, lw=2.0 * s, zorder=5))
        if comp.closed:
            ax.plot([c_left + 3 * s, c_right - 3 * s], [cy, cy], color=pal.accent, lw=3.0 * s, zorder=6)
        else:
            ax.plot([c_left + 2 * s, c_right - 4 * s], [cy - 2 * s, cy - 20 * s], color=pal.accent, lw=3.0 * s, zorder=6)

        lbl = f"{comp.id} ({'CLOSED' if comp.closed else 'OPEN'})" if label_mode == LabelMode.ANNOTATED else comp.id
        ax.text(cx, cy + 16 * s, lbl, color=pal.text_primary, fontsize=10.0 * s, fontweight="bold", ha="center", va="top", zorder=6, family="sans-serif")
        _record_label_bbox(bboxes, f"lbl:{prefix}{comp.id}", cx, cy + 23 * s, lbl, 10.0 * s)

    elif comp.kind == ComponentKind.FUSE:
        p_in = cx - 30 * s
        p_out = cx + 30 * s
        ax.plot([p_in, cx - 18 * s], [cy, cy], color=pal.wire, lw=2.2 * s, zorder=4)
        ax.plot([cx + 18 * s, p_out], [cy, cy], color=pal.wire, lw=2.2 * s, zorder=4)
        rect = patches.FancyBboxPatch(
            (cx - 18 * s, cy - 10 * s), 36 * s, 20 * s,
            boxstyle=f"round,pad=0,rounding_size={3 * s}",
            facecolor=pal.component_fill, edgecolor=pal.component_stroke, linewidth=1.8 * s, zorder=4,
        )
        ax.add_patch(rect)
        if comp.intact:
            xs = [cx - 14 * s, cx - 6 * s, cx + 6 * s, cx + 14 * s]
            ys = [cy, cy - 4 * s, cy + 4 * s, cy]
            ax.plot(xs, ys, color=pal.accent, lw=2.0 * s, zorder=5)
        else:
            ax.plot([cx - 14 * s, cx - 5 * s], [cy, cy - 4 * s], color="#dc2626", lw=2.2 * s, zorder=5)
            ax.plot([cx + 5 * s, cx + 14 * s], [cy + 4 * s, cy], color="#dc2626", lw=2.2 * s, zorder=5)
            ax.plot([cx - 2 * s, cx + 2 * s], [cy - 5 * s, cy + 5 * s], color="#dc2626", lw=1.4 * s, linestyle=":", zorder=5)

        lbl = f"{comp.id} ({'OK' if comp.intact else 'BLOWN'})" if label_mode == LabelMode.ANNOTATED else comp.id
        ax.text(cx, cy - 16 * s, lbl, color=pal.text_primary, fontsize=10.0 * s, fontweight="bold", ha="center", va="bottom", zorder=6, family="sans-serif")
        _record_label_bbox(bboxes, f"lbl:{prefix}{comp.id}", cx, cy - 22 * s, lbl, 10.0 * s)

    elif comp.kind == ComponentKind.RESISTOR:
        p_in = cx - 34 * s
        p_out = cx + 34 * s
        z_pts_x = [p_in, cx - 22 * s, cx - 16 * s, cx - 8 * s, cx, cx + 8 * s, cx + 16 * s, cx + 22 * s, p_out]
        z_pts_y = [cy, cy, cy - 9 * s, cy + 9 * s, cy - 9 * s, cy + 9 * s, cy - 9 * s, cy, cy]
        ax.plot(z_pts_x, z_pts_y, color=pal.component_stroke, lw=2.2 * s, solid_joinstyle="miter", zorder=4)
        ax.text(cx, cy - 16 * s, comp.id, color=pal.text_primary, fontsize=10.0 * s, fontweight="bold", ha="center", va="bottom", zorder=6, family="sans-serif")
        val_lbl = comp.value_text or f"{comp.resistance_ohm} Ohm"
        ax.text(cx, cy + 16 * s, val_lbl, color=pal.accent, fontsize=9.5 * s, fontweight="bold", ha="center", va="top", zorder=6, family="sans-serif")
        _record_label_bbox(bboxes, f"lbl:{prefix}{comp.id}_id", cx, cy - 22 * s, comp.id, 10.0 * s)
        _record_label_bbox(bboxes, f"lbl:{prefix}{comp.id}_val", cx, cy + 22 * s, val_lbl, 9.5 * s)

    elif comp.kind in (
        ComponentKind.GATE_AND,
        ComponentKind.GATE_OR,
        ComponentKind.GATE_NAND,
        ComponentKind.GATE_NOR,
        ComponentKind.GATE_XOR,
        ComponentKind.GATE_NOT,
    ):
        has_bubble = comp.kind in (ComponentKind.GATE_NAND, ComponentKind.GATE_NOR, ComponentKind.GATE_NOT)
        if comp.kind == ComponentKind.GATE_NOT:
            verts = [
                (cx - 24 * s, cy - 18 * s),
                (cx + 16 * s, cy),
                (cx - 24 * s, cy + 18 * s),
                (cx - 24 * s, cy - 18 * s),
            ]
            poly = patches.Polygon(verts, closed=True, facecolor=pal.component_fill, edgecolor=pal.component_stroke, lw=2.2 * s, zorder=4)
            ax.add_patch(poly)
            ax.plot([cx - 34 * s, cx - 24 * s], [cy, cy], color=pal.wire, lw=2.0 * s, zorder=3)
            out_edge_x = cx + 16 * s
            ax.plot([cx + 28 * s, cx + 38 * s], [cy, cy], color=pal.wire, lw=2.0 * s, zorder=3)
            bubble_cx = cx + 22 * s
        else:
            ax.plot([cx - 38 * s, cx - 22 * s], [cy - 14 * s, cy - 14 * s], color=pal.wire, lw=2.0 * s, zorder=3)
            ax.plot([cx - 38 * s, cx - 22 * s], [cy + 14 * s, cy + 14 * s], color=pal.wire, lw=2.0 * s, zorder=3)

            if comp.kind in (ComponentKind.GATE_AND, ComponentKind.GATE_NAND):
                verts = [
                    (cx - 24 * s, cy - 24 * s),
                    (cx, cy - 24 * s),
                    (cx + 26 * s, cy - 24 * s),
                    (cx + 26 * s, cy),
                    (cx + 26 * s, cy + 24 * s),
                    (cx, cy + 24 * s),
                    (cx - 24 * s, cy + 24 * s),
                    (cx - 24 * s, cy - 24 * s),
                ]
                codes = [
                    MplPath.MOVETO, MplPath.LINETO,
                    MplPath.CURVE3, MplPath.CURVE3,
                    MplPath.CURVE3, MplPath.CURVE3,
                    MplPath.LINETO, MplPath.CLOSEPOLY,
                ]
                ax.add_patch(patches.PathPatch(MplPath(verts, codes), facecolor=pal.component_fill, edgecolor=pal.component_stroke, lw=2.2 * s, zorder=4))
                out_edge_x = cx + 26 * s
            else:
                verts = [
                    (cx - 26 * s, cy - 24 * s),
                    (cx + 6 * s, cy - 24 * s),
                    (cx + 26 * s, cy),
                    (cx + 6 * s, cy + 24 * s),
                    (cx - 26 * s, cy + 24 * s),
                    (cx - 15 * s, cy),
                    (cx - 26 * s, cy - 24 * s),
                ]
                codes = [
                    MplPath.MOVETO,
                    MplPath.CURVE3, MplPath.CURVE3,
                    MplPath.CURVE3, MplPath.CURVE3,
                    MplPath.CURVE3, MplPath.CURVE3,
                ]
                ax.add_patch(patches.PathPatch(MplPath(verts, codes), facecolor=pal.component_fill, edgecolor=pal.component_stroke, lw=2.2 * s, zorder=4))
                if comp.kind == ComponentKind.GATE_XOR:
                    xor_verts = [(cx - 33 * s, cy - 23 * s), (cx - 21 * s, cy), (cx - 33 * s, cy + 23 * s)]
                    xor_codes = [MplPath.MOVETO, MplPath.CURVE3, MplPath.CURVE3]
                    ax.add_patch(patches.PathPatch(MplPath(xor_verts, xor_codes), facecolor="none", edgecolor=pal.component_stroke, lw=2.2 * s, zorder=4))
                    ax.plot([cx - 38 * s, cx - 22 * s], [cy - 14 * s, cy - 14 * s], color=pal.wire, lw=2.0 * s, zorder=3)
                    ax.plot([cx - 38 * s, cx - 22 * s], [cy + 14 * s, cy + 14 * s], color=pal.wire, lw=2.0 * s, zorder=3)
                out_edge_x = cx + 26 * s

            bubble_cx = out_edge_x + 6 * s
            lead_start = out_edge_x + (12 * s if has_bubble else 0.0)
            ax.plot([lead_start, cx + 42 * s], [cy, cy], color=pal.wire, lw=2.0 * s, zorder=3)

        if has_bubble:
            ax.add_patch(patches.Circle((bubble_cx, cy), 5.5 * s, facecolor=pal.paper, edgecolor=pal.component_stroke, lw=2.2 * s, zorder=6))

        g_short = comp.kind.value.replace("gate_", "").upper()
        if label_mode == LabelMode.ANNOTATED:
            ax.text(cx - 2 * s, cy, g_short, color=pal.accent, fontsize=8.0 * s, fontweight="bold", ha="center", va="center", zorder=6, family="sans-serif")
        ax.text(cx, cy - 28 * s, comp.id, color=pal.text_primary, fontsize=10.0 * s, fontweight="bold", ha="center", va="bottom", zorder=6, family="sans-serif")
        _record_label_bbox(bboxes, f"lbl:{prefix}{comp.id}", cx, cy - 33 * s, comp.id, 10.0 * s)

    elif comp.kind == ComponentKind.LED:
        ax.plot([cx - 24 * s, cx - 15 * s], [cy, cy], color=pal.wire, lw=2.0 * s, zorder=3)
        ax.add_patch(patches.Circle((cx, cy), 15 * s, facecolor=pal.led_fill, edgecolor=pal.component_stroke, lw=2.2 * s, zorder=4))
        d = 9.5 * s
        ax.plot([cx - d, cx + d], [cy - d, cy + d], color=pal.component_stroke, lw=1.6 * s, zorder=5)
        ax.plot([cx - d, cx + d], [cy + d, cy - d], color=pal.component_stroke, lw=1.6 * s, zorder=5)
        ax.plot([cx + 15 * s, cx + 24 * s, cx + 24 * s], [cy, cy, cy + 16 * s], color=pal.wire, lw=1.8 * s, zorder=3)
        for gx, gw in [(cy + 16 * s, 10 * s), (cy + 20 * s, 6 * s), (cy + 24 * s, 2.5 * s)]:
            ax.plot([cx + 24 * s - gw, cx + 24 * s + gw], [gx, gx], color=pal.wire, lw=1.6 * s, zorder=3)
        ax.text(cx, cy - 21 * s, comp.id, color=pal.text_primary, fontsize=10.0 * s, fontweight="bold", ha="center", va="bottom", zorder=6, family="sans-serif")
        _record_label_bbox(bboxes, f"lbl:{prefix}{comp.id}", cx, cy - 26 * s, comp.id, 10.0 * s)

    elif comp.kind == ComponentKind.TEST_POINT:
        ax.add_patch(patches.Circle((cx, cy), 14 * s, facecolor=pal.component_fill, edgecolor=pal.accent, lw=2.2 * s, zorder=5))
        lbl = comp.value_text or comp.id
        ax.text(cx, cy, lbl, color=pal.accent, fontsize=10 * s, fontweight="bold", ha="center", va="center", zorder=6, family="monospace")
        _record_label_bbox(bboxes, f"lbl:{prefix}{comp.id}", cx, cy, lbl, 10 * s)

    elif comp.kind == ComponentKind.PROBE:
        badge_txt = comp.probe_label or comp.id
        col = "#16a34a" if comp.voltage_level else "#dc2626"
        bw = max(96 * s, len(badge_txt) * 7.4 * s + 18 * s)
        bh = 24 * s
        rect = patches.FancyBboxPatch(
            (cx - bw / 2, cy - bh / 2), bw, bh,
            boxstyle=f"round,pad=0,rounding_size={4 * s}",
            facecolor=col, edgecolor=pal.border, lw=1.2 * s, zorder=6,
        )
        ax.add_patch(rect)
        ax.text(cx, cy, badge_txt, color="#ffffff", fontsize=8.0 * s, fontweight="bold", ha="center", va="center", zorder=7, family="monospace")
        _record_label_bbox(bboxes, f"lbl:{prefix}{comp.id}", cx, cy, badge_txt, 8.0 * s)

def _render_single_spec(
    ax: plt.Axes,
    spec: SchematicSpec,
    pal: ThemePalette,
    bboxes: dict[str, BBox],
    ox: float = 0.0,
    oy: float = 0.0,
    scale: float = 1.0,
    panel_header: Optional[str] = None,
    prefix: str = "",
) -> None:
    if panel_header:
        ax.text(ox + 25 * scale, oy + 46 * scale, panel_header, color=pal.accent, fontsize=11 * scale, fontweight="bold", ha="left", va="center", family="monospace", zorder=6)

    for net in spec.nets:
        segs = list(net.segments)
        if not segs and len(net.points) >= 2:
            for i in range(len(net.points) - 1):
                segs.append(
                    type("Seg", (), {"p1": net.points[i], "p2": net.points[i + 1]})()
                )
        for seg in segs:
            p1 = Point(x=ox + seg.p1.x * scale, y=oy + seg.p1.y * scale)
            p2 = Point(x=ox + seg.p2.x * scale, y=oy + seg.p2.y * scale)
            scaled_bridges = [
                type("B", (), {"center": Point(x=ox + b.center.x * scale, y=oy + b.center.y * scale), "radius": b.radius * scale})()
                for b in spec.bridges
            ]
            _draw_wire_with_bridges(ax, p1, p2, scaled_bridges, pal.wire, 2.0 * scale)

        for dot in net.junction_dots:
            dx = ox + dot.x * scale
            dy = oy + dot.y * scale
            ax.add_patch(patches.Circle((dx, dy), 5.2 * scale, facecolor=pal.dot_fill, edgecolor=pal.dot_fill, zorder=5))

    for comp in spec.components:
        _draw_component(ax, comp, pal, spec.label_mode, bboxes, ox=ox, oy=oy, scale=scale, prefix=prefix)

def render_schematic(
    spec: SchematicSpec,
    out_png_path: Path,
    theme: ThemeStyle = ThemeStyle.IEEE_CLASSIC,
    out_svg_path: Optional[Path] = None,
) -> dict[str, BBox]:
    """Render SchematicSpec to crisp PNG (and optional SVG) returning pixel BBoxes."""
    pal = THEMES[theme]
    w, h = spec.canvas_width, spec.canvas_height
    dpi = 100
    fig = plt.figure(figsize=(w / dpi, h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")
    fig.patch.set_facecolor(pal.bg)
    ax.set_facecolor(pal.bg)

    ax.add_patch(patches.Rectangle((18, 18), w - 36, h - 36, facecolor=pal.paper, edgecolor=pal.border, linewidth=2.2, zorder=0))
    ax.add_patch(patches.Rectangle((36, 36), w - 72, h - 72, facecolor="none", edgecolor=pal.border, linewidth=1.1, zorder=0))

    cols = 6
    rows = 4
    col_step = (w - 72) / cols
    row_step = (h - 72) / rows
    for c_idx in range(1, cols):
        gx = 36 + c_idx * col_step
        ax.plot([gx, gx], [36, h - 36], color=pal.grid_line, linewidth=0.7, linestyle="--", zorder=0)
    for r_idx in range(1, rows):
        gy = 36 + r_idx * row_step
        ax.plot([36, w - 36], [gy, gy], color=pal.grid_line, linewidth=0.7, linestyle="--", zorder=0)
    for c_idx in range(cols):
        cx = 36 + (c_idx + 0.5) * col_step
        ax.text(cx, 27, str(c_idx + 1), color=pal.text_muted, fontsize=8, ha="center", va="center", family="monospace")
        ax.text(cx, h - 27, str(c_idx + 1), color=pal.text_muted, fontsize=8, ha="center", va="center", family="monospace")
    for r_idx, letter in enumerate(["A", "B", "C", "D"]):
        cy = 36 + (r_idx + 0.5) * row_step
        ax.text(27, cy, letter, color=pal.text_muted, fontsize=8, ha="center", va="center", family="monospace")
        ax.text(w - 27, cy, letter, color=pal.text_muted, fontsize=8, ha="center", va="center", family="monospace")

    bboxes: dict[str, BBox] = {}

    if spec.secondary_panel is not None:
        mid_x = w / 2.0
        ax.plot([mid_x, mid_x], [44, h - 105], color=pal.border, linewidth=1.8, linestyle="-.", zorder=2)
        scale = 0.62
        _render_single_spec(ax, spec, pal, bboxes, ox=25.0, oy=75.0, scale=scale, panel_header=spec.panel_labels[0], prefix="A_")
        _render_single_spec(ax, spec.secondary_panel, pal, bboxes, ox=mid_x + 15.0, oy=75.0, scale=scale, panel_header=spec.panel_labels[1], prefix="B_")
    else:
        _render_single_spec(ax, spec, pal, bboxes, ox=0.0, oy=0.0, scale=1.0)

    tb_w = 405
    tb_h = 84
    tb_x = w - 36 - tb_w
    tb_y = h - 36 - tb_h

    if spec.rule_banner:
        import textwrap
        wrap_chars = 82 if w >= 1200 else 65
        wrapped = textwrap.fill(spec.rule_banner, width=wrap_chars)
        banner_w = max(200, tb_x - 48 - 16)
        banner_rect = patches.Rectangle((48, tb_y + 2), banner_w, tb_h - 4, facecolor=pal.banner_bg, edgecolor=pal.border, linewidth=1.2, zorder=5)
        ax.add_patch(banner_rect)
        ax.text(
            60, tb_y + tb_h / 2.0, wrapped,
            color=pal.text_primary, fontsize=8.0, fontweight="bold",
            ha="left", va="center", family="monospace", zorder=6,
        )
        bboxes["lbl:rule_banner"] = BBox(x1=48, y1=tb_y + 2, x2=48 + banner_w, y2=tb_y + tb_h - 2)

    ax.add_patch(patches.Rectangle((tb_x, tb_y), tb_w, tb_h, facecolor=pal.component_fill, edgecolor=pal.border, linewidth=1.6, zorder=5))
    ax.plot([tb_x, tb_x + tb_w], [tb_y + 28, tb_y + 28], color=pal.border, linewidth=1.0, zorder=5)
    ax.plot([tb_x, tb_x + tb_w], [tb_y + 56, tb_y + 56], color=pal.border, linewidth=1.0, zorder=5)
    ax.text(tb_x + 10, tb_y + 14, spec.drawing_title[:46], color=pal.text_primary, fontsize=8.4, fontweight="bold", va="center", family="monospace", zorder=6)
    ax.text(tb_x + 10, tb_y + 42, f"DOC NO: {spec.drawing_number}   REV: {spec.revision}", color=pal.text_muted, fontsize=8.0, va="center", family="monospace", zorder=6)
    ax.text(tb_x + 10, tb_y + 70, f"LABELS: {spec.label_mode.value.upper()}   SEED: {spec.metadata.get('seed', '-')}", color=pal.accent, fontsize=7.8, fontweight="bold", va="center", family="monospace", zorder=6)
    bboxes["comp:title_block"] = BBox(x1=tb_x, y1=tb_y, x2=tb_x + tb_w, y2=tb_y + tb_h)

    out_png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_png_path), dpi=dpi)
    if out_svg_path is not None:
        out_svg_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(out_svg_path), format="svg")
    plt.close(fig)

    with Image.open(out_png_path) as im:
        rgb = im.convert("RGB")
        rgb.save(out_png_path, format="PNG")

    return bboxes
