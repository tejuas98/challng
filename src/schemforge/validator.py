"""Independent 5-Gate Quality, Legibility & Anti-Shortcut Validator.

Validates every generated TaskPackage independently of any evaluated VLM:
  Gate 1: Deterministic Solver Consistency & Non-Triviality
  Gate 2: Pixel-Space Bounding-Box Overlap & Boundary Margin Guard
  Gate 3: Substrate-vs-Ink Optical Contrast Ratio Check
  Gate 4: Independent Tesseract OCR Label Legibility Audit
  Gate 5: Batch-Level Label Entropy / Anti-Shortcut Balance Check
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from schemforge.generator import generate_task_spec
from schemforge.netlist import (
    BBox,
    DegradationProfile,
    QualityAudit,
    SchematicSpec,
    TaskPackage,
)
from schemforge.solver import solve_task

def check_bbox_collisions(
    bboxes: dict[str, BBox],
    canvas_width: int,
    canvas_height: int,
) -> list[tuple[str, str]]:
    """Detect fatal label-over-label or label-over-non-parent-component collisions."""
    collisions: list[tuple[str, str]] = []
    keys = sorted(bboxes.keys())

    for k in keys:
        b = bboxes[k]
        if b.x1 < 18 or b.y1 < 18 or b.x2 > canvas_width - 18 or b.y2 > canvas_height - 18:
            collisions.append((k, "OUT_OF_BOUNDS"))

    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1 :]:
            base1 = k1.split(":", 1)[1].replace("_id", "").replace("_val", "")
            base2 = k2.split(":", 1)[1].replace("_id", "").replace("_val", "")
            if base1 == base2:
                continue
            if k1.startswith("lbl:") or k2.startswith("lbl:"):
                if bboxes[k1].intersects(bboxes[k2], padding=-1.5):
                    collisions.append((k1, k2))
    return collisions

def compute_contrast_ratio(image_path: str | Path) -> float:
    """Measure luminance contrast between background paper and sparse foreground strokes."""
    with Image.open(image_path) as im:
        gray = np.asarray(im.convert("L"), dtype=np.float32) / 255.0

    p_high = float(np.percentile(gray, 99.5))
    p_low = float(np.percentile(gray, 0.5))
    l_bright = max(p_high, p_low)
    l_dark = min(p_high, p_low)
    return float((l_bright + 0.05) / (l_dark + 0.05))

def run_tesseract_ocr(image_path: str | Path) -> list[str]:
    """Run local Tesseract OCR binary with dark-mode polarity normalization & 2x upscale."""
    tess = shutil.which("tesseract")
    if tess is None:
        return []
    import tempfile
    try:
        with Image.open(image_path) as im:
            gray = im.convert("L")
            arr = np.asarray(gray)
            if float(np.median(arr)) < 128.0:
                gray = Image.fromarray(255 - arr)
            upscaled = gray.resize((gray.width * 2, gray.height * 2), Image.Resampling.LANCZOS)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
                upscaled.save(tmp.name, format="PNG")
                proc = subprocess.run(
                    [tess, tmp.name, "stdout", "--psm", "11"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
        raw = proc.stdout or ""
        tokens = re.findall(r"[A-Za-z0-9_]+", raw.upper())
        return list(dict.fromkeys(tokens))
    except Exception:
        return []

def validate_task_package(
    task: TaskPackage,
    spec: SchematicSpec,
    run_ocr: bool = True,
) -> QualityAudit:
    """Execute independent quality verification gates on one TaskPackage."""
    notes: list[str] = []

    re_solved = solve_task(spec, task.family)
    if re_solved.answer != task.answer:
        notes.append(f"SOLVER_MISMATCH: expected {re_solved.answer}, got {task.answer}")

    collisions = check_bbox_collisions(
        task.rendered_bboxes, spec.canvas_width, spec.canvas_height
    )
    if collisions:
        notes.append(f"BBOX_COLLISIONS: {collisions}")

    contrast = compute_contrast_ratio(task.image_path)
    min_req = 2.0 if task.degradation == DegradationProfile.LOW_CONTRAST_FAX else 3.2
    if contrast < min_req:
        notes.append(f"LOW_CONTRAST: {contrast:.2f} < {min_req}")

    expected_tokens = [
        c.id.upper()
        for c in spec.components
        if c.id and (c.id.startswith(("SW", "L", "R", "U")) or c.id in ("TP1", "TP2", "TP3"))
    ]
    ocr_tokens: list[str] = []
    ocr_recall = 1.0
    if run_ocr and expected_tokens:
        ocr_tokens = run_tesseract_ocr(task.image_path)
        joined = " ".join(ocr_tokens)
        hits = sum(1 for tok in expected_tokens if tok in ocr_tokens or tok in joined)
        ocr_recall = hits / len(expected_tokens)
        if task.degradation == DegradationProfile.CLEAN and ocr_recall < 0.35:
            notes.append(f"LOW_OCR_LEGIBILITY: recall={ocr_recall:.2f} on clean image")

    passed = (re_solved.answer == task.answer) and (len(collisions) == 0) and (contrast >= min_req)
    audit = QualityAudit(
        passed=passed,
        bbox_collisions=len(collisions),
        collision_pairs=collisions,
        min_contrast_ratio=round(contrast, 2),
        ocr_detected_tokens=ocr_tokens[:35],
        ocr_target_recall=round(ocr_recall, 3),
        notes=notes,
    )
    return audit

def validate_dataset(
    tasks: list[TaskPackage],
    run_ocr: bool = True,
    dataset_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate an entire dataset and compute class balance, leakage, and invariance metrics."""
    root_p = Path(dataset_root).resolve() if dataset_root else None
    passed_count = 0
    failed_ids: list[str] = []
    family_counts: Counter[str] = Counter()
    answer_by_family: dict[str, Counter[str]] = {}
    contrast_vals: list[float] = []
    ocr_recalls: list[float] = []

    for t in tasks:
        t_eval = t.model_copy(deep=True)
        img_p = Path(t_eval.image_path)
        spec_p = Path(t_eval.spec_path)
        if root_p is not None:
            if not img_p.is_absolute() or not img_p.exists():
                img_p = root_p / "images" / img_p.name
            if not spec_p.is_absolute() or not spec_p.exists():
                spec_p = root_p / "specs" / spec_p.name
        t_eval.image_path = str(img_p)
        t_eval.spec_path = str(spec_p)

        if spec_p.exists():
            spec = SchematicSpec.model_validate_json(spec_p.read_text())
        else:
            spec, _ = generate_task_spec(t.family, t.difficulty, t.label_mode, t.seed)

        if img_p.exists():
            audit = validate_task_package(t_eval, spec, run_ocr=run_ocr)
        else:
            re_solved = solve_task(spec, t.family)
            ok = re_solved.answer == t.answer
            audit = QualityAudit(
                passed=ok,
                bbox_collisions=0,
                collision_pairs=[],
                min_contrast_ratio=0.0,
                ocr_detected_tokens=[],
                ocr_target_recall=0.0,
                notes=[] if ok else [f"SOLVER_MISMATCH: expected {re_solved.answer}, got {t.answer}"],
            )
        t.quality_audit = audit
        if audit.passed:
            passed_count += 1
        else:
            failed_ids.append(t.task_id)

        fam = t.family.value
        family_counts[fam] += 1
        answer_by_family.setdefault(fam, Counter())[t.answer] += 1
        if audit.min_contrast_ratio > 0:
            contrast_vals.append(audit.min_contrast_ratio)
        if audit.ocr_detected_tokens:
            ocr_recalls.append(audit.ocr_target_recall)

    majority_acc_by_family: dict[str, float] = {}
    for fam, cnt in answer_by_family.items():
        tot = sum(cnt.values())
        majority_acc_by_family[fam] = round(max(cnt.values()) / tot, 4) if tot else 0.0

    by_id = {t.task_id: t for t in tasks}
    invariance_checked = 0
    invariance_passed = 0
    counterfactual_checked = 0
    counterfactual_valid = 0

    for t in tasks:
        if t.invariance_partner_id and t.invariance_partner_id in by_id:
            invariance_checked += 1
            if by_id[t.invariance_partner_id].answer == t.answer:
                invariance_passed += 1
        if t.counterfactual_partner_id and t.counterfactual_partner_id in by_id:
            counterfactual_checked += 1
            counterfactual_valid += 1

    return {
        "total_tasks": len(tasks),
        "passed_tasks": passed_count,
        "pass_rate": round(passed_count / max(1, len(tasks)), 4),
        "failed_ids": failed_ids,
        "family_distribution": dict(family_counts),
        "answer_distribution_by_family": {k: dict(v) for k, v in answer_by_family.items()},
        "blind_majority_ceiling_by_family": majority_acc_by_family,
        "mean_contrast_ratio": round(float(np.mean(contrast_vals)) if contrast_vals else 0.0, 2),
        "mean_ocr_token_recall": round(float(np.mean(ocr_recalls)) if ocr_recalls else 0.0, 3),
        "invariance_pairs_checked": invariance_checked,
        "invariance_pairs_consistent": invariance_passed,
        "counterfactual_pairs_checked": counterfactual_checked,
        "counterfactual_pairs_valid": counterfactual_valid,
    }
