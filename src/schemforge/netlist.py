"""Formal schematic netlist, layout geometry, and task package schemas.

Every generated visual task starts from a deterministic, strongly-typed
SchematicSpec graph. Ground-truth answers are computed solely from this model
before rendering any pixels, ensuring strict independence from evaluated VLMs.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

class TaskFamily(str, Enum):
    STATE_PROPAGATION = "state_propagation"
    BRIDGE_VS_JUNCTION = "bridge_vs_junction"
    EQUIVALENT_RESISTANCE = "equivalent_resistance"
    FAULT_DIAGNOSIS = "fault_diagnosis"
    COUNTERFACTUAL_PAIR = "counterfactual_pair"
    COMPONENT_AUDIT = "component_audit"
    WHOLE_SYSTEM = "whole_system"

class DifficultyTier(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

class ThemeStyle(str, Enum):
    IEEE_CLASSIC = "ieee_classic"
    KICAD_BLUEPRINT = "kicad_blueprint"
    AGED_PAPER = "aged_paper"
    HIGH_CONTRAST_MONO = "high_contrast_mono"

class DegradationProfile(str, Enum):
    CLEAN = "clean"
    OFFICE_SCAN = "office_scan"
    MOBILE_PHOTO = "mobile_photo"
    LOW_CONTRAST_FAX = "low_contrast_fax"

class LabelMode(str, Enum):
    ANNOTATED = "annotated"
    SYMBOL_ONLY = "symbol_only"

class ComponentKind(str, Enum):
    SOURCE = "source"
    GND = "gnd"
    SWITCH = "switch"
    FUSE = "fuse"
    RESISTOR = "resistor"
    LED = "led"
    GATE_AND = "gate_and"
    GATE_OR = "gate_or"
    GATE_NAND = "gate_nand"
    GATE_NOR = "gate_nor"
    GATE_XOR = "gate_xor"
    GATE_NOT = "gate_not"
    PROBE = "probe"
    JUNCTION = "junction"
    TEST_POINT = "test_point"

class Point(BaseModel):
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

class BBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    def intersects(self, other: "BBox", padding: float = 0.0) -> bool:
        return not (
            self.x2 + padding <= other.x1
            or other.x2 + padding <= self.x1
            or self.y2 + padding <= other.y1
            or other.y2 + padding <= self.y1
        )

class Port(BaseModel):
    name: str
    pos: Point

class Component(BaseModel):
    id: str
    kind: ComponentKind
    center: Point
    orientation: Literal[0, 90, 180, 270] = 0
    ports: dict[str, Point] = Field(default_factory=dict)
    closed: Optional[bool] = None
    intact: Optional[bool] = None
    resistance_ohm: Optional[int] = None
    voltage_level: Optional[int] = None
    probe_label: Optional[str] = None
    stuck_fault: Optional[Literal["HIGH", "LOW", "OPEN"]] = None
    value_text: Optional[str] = None
    display_tag: Optional[str] = None

class WireSegment(BaseModel):
    net_id: str
    p1: Point
    p2: Point

class BridgeJump(BaseModel):
    center: Point
    axis: Literal["vertical", "horizontal"] = "vertical"
    radius: float = 11.0

class WireNet(BaseModel):
    net_id: str
    points: list[Point]
    segments: list[WireSegment] = Field(default_factory=list)
    junction_dots: list[Point] = Field(default_factory=list)
    color_hint: Optional[str] = None

class SchematicSpec(BaseModel):
    """Formal schematic layout and electrical topology specification."""
    canvas_width: int = 1280
    canvas_height: int = 800
    drawing_title: str = "SCHEMFORGE SYNTHETIC CIRCUIT"
    drawing_number: str = "SF-0001"
    revision: str = "A"
    rule_banner: Optional[str] = None
    label_mode: LabelMode = LabelMode.SYMBOL_ONLY
    components: list[Component] = Field(default_factory=list)
    nets: list[WireNet] = Field(default_factory=list)
    bridges: list[BridgeJump] = Field(default_factory=list)
    connections: list[tuple[str, str, str, str]] = Field(
        default_factory=list,
        description="Explicit electrical edges: (comp_a, port_a, comp_b, port_b)",
    )
    secondary_panel: Optional["SchematicSpec"] = None
    panel_labels: tuple[str, str] = ("PANEL A: BASELINE", "PANEL B: REVISION")
    metadata: dict[str, Any] = Field(default_factory=dict)

class SolverProof(BaseModel):
    answer: str
    answer_type: Literal["binary", "numeric", "mcq", "identifier", "list"]
    choices: list[str] = Field(default_factory=list)
    node_values: dict[str, Any] = Field(default_factory=dict)
    proof_steps: list[str] = Field(default_factory=list)

class QualityAudit(BaseModel):
    passed: bool
    bbox_collisions: int = 0
    collision_pairs: list[tuple[str, str]] = Field(default_factory=list)
    min_contrast_ratio: float = 0.0
    ocr_detected_tokens: list[str] = Field(default_factory=list)
    ocr_target_recall: float = 0.0
    notes: list[str] = Field(default_factory=list)

class TaskPackage(BaseModel):
    task_id: str
    seed: int
    family: TaskFamily
    difficulty: DifficultyTier
    theme: ThemeStyle
    degradation: DegradationProfile
    label_mode: LabelMode
    question: str
    answer: str
    answer_type: Literal["binary", "numeric", "mcq", "identifier", "list"]
    choices: list[str] = Field(default_factory=list)
    image_path: str
    svg_path: Optional[str] = None
    spec_path: str
    counterfactual_partner_id: Optional[str] = None
    invariance_partner_id: Optional[str] = None
    mutation_description: Optional[str] = None
    solver_proof: SolverProof
    quality_audit: Optional[QualityAudit] = None
    rendered_bboxes: dict[str, BBox] = Field(default_factory=dict)
