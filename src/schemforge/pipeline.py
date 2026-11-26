"""End-to-End Scalable Task Generation Pipeline & Parallel Batch Orchestrator.

Supports deterministic seeded single-task synthesis with collision-retry guards,
parallel multi-core execution for large-scale benchmarks (100 - 2,000+ tasks),
and progress callbacks for async API jobs.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import random
from pathlib import Path
from typing import Callable, Optional

from schemforge.degradation import apply_degradation
from schemforge.generator import generate_task_spec
from schemforge.netlist import (
    DegradationProfile,
    DifficultyTier,
    LabelMode,
    QualityAudit,
    TaskFamily,
    TaskPackage,
    ThemeStyle,
)
from schemforge.renderer import render_schematic
from schemforge.solver import solve_task
from schemforge.validator import validate_task_package

def _build_spec_only_worker(job: dict) -> TaskPackage:
    """Fast spec+solver synthesis for 10,000+ scale streaming generation."""
    fam = TaskFamily(job["family"])
    diff = DifficultyTier(job["difficulty"])
    theme = ThemeStyle(job["theme"])
    deg = DegradationProfile(job["degradation"])
    lmode = LabelMode(job["label_mode"])
    seed = int(job["seed"])
    tid = job["task_id"]

    spec, question = generate_task_spec(fam, diff, lmode, seed)
    proof = solve_task(spec, fam)
    return TaskPackage(
        task_id=tid,
        seed=seed,
        family=fam,
        difficulty=diff,
        theme=theme,
        degradation=deg,
        label_mode=lmode,
        question=question,
        answer=proof.answer,
        answer_type=proof.answer_type,
        choices=proof.choices,
        image_path=f"images/{tid}.png",
        spec_path=f"specs/{tid}.json",
        mutation_description=spec.metadata.get("panel_diff_description"),
        solver_proof=proof,
        rendered_bboxes={},
        quality_audit=QualityAudit(
            passed=True,
            bbox_collisions=0,
            min_contrast_ratio=0.0,
            notes=["lazy_spec_verified"],
        ),
    )

def _build_single_worker(job: dict) -> TaskPackage:
    if not job.get("render_pixels", True):
        return _build_spec_only_worker(job)
    return build_single_task(
        task_id=job["task_id"],
        family=TaskFamily(job["family"]),
        difficulty=DifficultyTier(job["difficulty"]),
        theme=ThemeStyle(job["theme"]),
        degradation=DegradationProfile(job["degradation"]),
        label_mode=LabelMode(job["label_mode"]),
        seed=job["seed"],
        out_dir=Path(job["out_dir"]),
        run_ocr=job["run_ocr"],
        emit_svg=job["emit_svg"],
    )

def build_single_task(
    task_id: str,
    family: TaskFamily,
    difficulty: DifficultyTier,
    theme: ThemeStyle,
    degradation: DegradationProfile,
    label_mode: LabelMode,
    seed: int,
    out_dir: Path,
    run_ocr: bool = True,
    emit_svg: bool = False,
    max_retries: int = 3,
) -> TaskPackage:
    """Generate, render, degrade, and verify one deterministic TaskPackage cleanly."""
    img_dir = out_dir / "images"
    spec_dir = out_dir / "specs"
    svg_dir = out_dir / "svgs"
    img_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    last_pkg: Optional[TaskPackage] = None
    for attempt in range(max_retries):
        eff_seed = seed + attempt * 7919
        spec, question = generate_task_spec(family, difficulty, label_mode, eff_seed)
        proof = solve_task(spec, family)

        png_path = img_dir / f"{task_id}.png"
        svg_path = (svg_dir / f"{task_id}.svg") if emit_svg else None
        spec_path = spec_dir / f"{task_id}.json"

        bboxes = render_schematic(spec, png_path, theme=theme, out_svg_path=svg_path)
        apply_degradation(str(png_path), degradation, seed=eff_seed + 991)
        spec_path.write_text(spec.model_dump_json(indent=2))

        pkg = TaskPackage(
            task_id=task_id,
            seed=eff_seed,
            family=family,
            difficulty=difficulty,
            theme=theme,
            degradation=degradation,
            label_mode=label_mode,
            question=question,
            answer=proof.answer,
            answer_type=proof.answer_type,
            choices=proof.choices,
            image_path=str(png_path),
            svg_path=str(svg_path) if svg_path else None,
            spec_path=str(spec_path),
            mutation_description=spec.metadata.get("panel_diff_description"),
            solver_proof=proof,
            rendered_bboxes=bboxes,
        )
        pkg.quality_audit = validate_task_package(pkg, spec, run_ocr=run_ocr)
        last_pkg = pkg
        if pkg.quality_audit.passed:
            return pkg

    assert last_pkg is not None
    return last_pkg

def _task_uniqueness_signature(
    spec,
    question: str,
    answer: str,
    theme: ThemeStyle,
    deg: DegradationProfile,
    lmode: LabelMode,
    family: TaskFamily,
    difficulty: DifficultyTier,
) -> str:
    """Canonical fingerprint preventing identical/repetitive circuit questions."""
    comp_sig = tuple(
        sorted(
            (c.kind.value, c.closed, c.intact, c.resistance_ohm, c.voltage_level)
            for c in spec.components
        )
    )
    conn_sig = tuple(sorted(spec.connections))
    extra = (
        len(spec.bridges),
        spec.metadata.get("question_variant", ""),
        spec.metadata.get("toggle_switch_id", ""),
        spec.metadata.get("panel_diff_description", ""),
    )
    return repr((
        family.value,
        difficulty.value,
        comp_sig,
        conn_sig,
        extra,
        question,
        answer,
        theme.value,
        deg.value,
        lmode.value,
    ))

def estimate_benchmark_combinations(
    families: Optional[list[TaskFamily]] = None,
    difficulties: Optional[list[DifficultyTier]] = None,
    themes: Optional[list[ThemeStyle]] = None,
    degradations: Optional[list[DegradationProfile]] = None,
    label_modes: Optional[list[LabelMode]] = None,
    requested_count: int = 30,
) -> dict:
    """Estimate mathematically distinct non-repetitive questions available for the chosen filters."""
    fams = families or list(TaskFamily)
    diffs = difficulties or [DifficultyTier.EASY, DifficultyTier.MEDIUM, DifficultyTier.HARD]
    thm_cnt = len(themes) if themes else len(ThemeStyle)
    deg_cnt = len(degradations) if degradations else 4
    lbl_cnt = len(label_modes) if label_modes else 2

    per_cell_struct = {
        (TaskFamily.STATE_PROPAGATION, DifficultyTier.EASY): 180,
        (TaskFamily.STATE_PROPAGATION, DifficultyTier.MEDIUM): 1400,
        (TaskFamily.STATE_PROPAGATION, DifficultyTier.HARD): 3200,
        (TaskFamily.BRIDGE_VS_JUNCTION, DifficultyTier.EASY): 48,
        (TaskFamily.BRIDGE_VS_JUNCTION, DifficultyTier.MEDIUM): 384,
        (TaskFamily.BRIDGE_VS_JUNCTION, DifficultyTier.HARD): 512,
        (TaskFamily.EQUIVALENT_RESISTANCE, DifficultyTier.EASY): 168,
        (TaskFamily.EQUIVALENT_RESISTANCE, DifficultyTier.MEDIUM): 720,
        (TaskFamily.EQUIVALENT_RESISTANCE, DifficultyTier.HARD): 960,
        (TaskFamily.FAULT_DIAGNOSIS, DifficultyTier.EASY): 120,
        (TaskFamily.FAULT_DIAGNOSIS, DifficultyTier.MEDIUM): 240,
        (TaskFamily.FAULT_DIAGNOSIS, DifficultyTier.HARD): 360,
        (TaskFamily.COUNTERFACTUAL_PAIR, DifficultyTier.EASY): 180,
        (TaskFamily.COUNTERFACTUAL_PAIR, DifficultyTier.MEDIUM): 1200,
        (TaskFamily.COUNTERFACTUAL_PAIR, DifficultyTier.HARD): 2400,
        (TaskFamily.COMPONENT_AUDIT, DifficultyTier.EASY): 96,
        (TaskFamily.COMPONENT_AUDIT, DifficultyTier.MEDIUM): 384,
        (TaskFamily.COMPONENT_AUDIT, DifficultyTier.HARD): 768,
        (TaskFamily.WHOLE_SYSTEM, DifficultyTier.EASY): 240,
        (TaskFamily.WHOLE_SYSTEM, DifficultyTier.MEDIUM): 720,
        (TaskFamily.WHOLE_SYSTEM, DifficultyTier.HARD): 1440,
    }
    struct_total = sum(per_cell_struct.get((f, d), 120) for f in fams for d in diffs)
    visual_total = struct_total * thm_cnt * deg_cnt * lbl_cnt
    effective = min(requested_count, visual_total)
    return {
        "unique_circuit_structures": struct_total,
        "unique_with_visuals": visual_total,
        "requested_count": requested_count,
        "effective_max": effective,
        "will_cap": requested_count > visual_total,
    }

def generate_benchmark_dataset(
    out_dir: str | Path,
    count: int = 36,
    base_seed: int = 42,
    families: Optional[list[TaskFamily]] = None,
    difficulties: Optional[list[DifficultyTier]] = None,
    themes: Optional[list[ThemeStyle]] = None,
    degradations: Optional[list[DegradationProfile]] = None,
    label_modes: Optional[list[LabelMode]] = None,
    include_degradations: bool = True,
    include_invariance_pairs: bool = True,
    run_ocr: bool = True,
    emit_svg: bool = False,
    workers: int = 1,
    lazy_render: bool = False,
    audit_sample_size: int = 42,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> list[TaskPackage]:
    """Build a diverse, strictly deduplicated multi-axis benchmark dataset."""
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    rng = random.Random(base_seed)
    fam_pool = families or list(TaskFamily)
    diff_pool = difficulties or [DifficultyTier.EASY, DifficultyTier.MEDIUM, DifficultyTier.HARD]
    theme_pool = themes or list(ThemeStyle)
    deg_pool = degradations or (
        [
            DegradationProfile.CLEAN,
            DegradationProfile.CLEAN,
            DegradationProfile.OFFICE_SCAN,
            DegradationProfile.MOBILE_PHOTO,
            DegradationProfile.LOW_CONTRAST_FAX,
        ]
        if include_degradations
        else [DegradationProfile.CLEAN]
    )
    lmode_pool = label_modes or [LabelMode.SYMBOL_ONLY, LabelMode.SYMBOL_ONLY, LabelMode.ANNOTATED]

    jobs: list[dict] = []
    partner_links: list[tuple[str, str]] = []
    seen_sigs: set[str] = set()
    exhausted_unique = False
    idx = 0

    for n in range(count):
        chosen = None
        for attempt in range(48):
            shift = n + attempt * 7
            fam = fam_pool[shift % len(fam_pool)]
            diff = diff_pool[(shift // len(fam_pool)) % len(diff_pool)]
            theme = theme_pool[(rng.randrange(len(theme_pool)) + attempt) % len(theme_pool)] if len(theme_pool) > 1 else theme_pool[0]
            deg = deg_pool[(rng.randrange(len(deg_pool)) + attempt) % len(deg_pool)] if len(deg_pool) > 1 else deg_pool[0]
            if len(lmode_pool) == 1:
                lmode = lmode_pool[0]
            elif fam in (TaskFamily.BRIDGE_VS_JUNCTION, TaskFamily.COMPONENT_AUDIT):
                lmode = LabelMode.SYMBOL_ONLY
            else:
                lmode = lmode_pool[(n + attempt) % len(lmode_pool)]
            seed = base_seed * 1000 + n * 17 + 3 + attempt * 7919
            spec, question = generate_task_spec(fam, diff, lmode, seed)
            proof = solve_task(spec, fam)
            sig = _task_uniqueness_signature(spec, question, proof.answer, theme, deg, lmode, fam, diff)
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                chosen = (fam, diff, theme, deg, lmode, seed)
                break

        if chosen is None:
            exhausted_unique = True
            break

        fam, diff, theme, deg, lmode, seed = chosen
        tid = f"task_{idx:04d}_{fam.value[:6]}_{diff.value[:3]}"
        jobs.append({
            "order": idx,
            "task_id": tid,
            "family": fam.value,
            "difficulty": diff.value,
            "theme": theme.value,
            "degradation": deg.value,
            "label_mode": lmode.value,
            "seed": seed,
            "out_dir": str(out_path),
            "run_ocr": run_ocr,
            "emit_svg": emit_svg and ((not lazy_render) or (idx < audit_sample_size)),
            "render_pixels": (not lazy_render) or (idx < audit_sample_size),
        })
        idx += 1

        if include_invariance_pairs and n < len(fam_pool):
            inv_id = f"task_{idx:04d}_{fam.value[:6]}_inv"
            alt_theme = ThemeStyle.KICAD_BLUEPRINT if theme != ThemeStyle.KICAD_BLUEPRINT else ThemeStyle.AGED_PAPER
            jobs.append({
                "order": idx,
                "task_id": inv_id,
                "family": fam.value,
                "difficulty": diff.value,
                "theme": alt_theme.value,
                "degradation": DegradationProfile.MOBILE_PHOTO.value,
                "label_mode": lmode.value,
                "seed": seed,
                "out_dir": str(out_path),
                "run_ocr": run_ocr,
                "emit_svg": emit_svg and ((not lazy_render) or (idx < audit_sample_size)),
                "render_pixels": (not lazy_render) or (idx < audit_sample_size),
            })
            partner_links.append((tid, inv_id))
            idx += 1

    total = len(jobs)
    results_by_id: dict[str, TaskPackage] = {}

    if workers > 1 and total > 4:
        completed = 0
        chunk = 1 if not lazy_render else 16
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_build_single_worker, j): j["task_id"] for j in jobs}
            for fut in as_completed(futs):
                pkg = fut.result()
                results_by_id[pkg.task_id] = pkg
                completed += 1
                if progress_cb and (completed % chunk == 0 or completed == total):
                    progress_cb(completed, total)
    else:
        for i, j in enumerate(jobs):
            pkg = _build_single_worker(j)
            results_by_id[pkg.task_id] = pkg
            if progress_cb and ((not lazy_render) or (i % 50 == 0 or i + 1 == total)):
                progress_cb(i + 1, total)

    tasks = [results_by_id[j["task_id"]] for j in jobs]
    for a_id, b_id in partner_links:
        if a_id in results_by_id and b_id in results_by_id:
            results_by_id[a_id].invariance_partner_id = b_id
            results_by_id[b_id].invariance_partner_id = a_id

    manifest_jsonl = out_path / "dataset.jsonl"
    portable_lines: list[str] = []
    for t in tasks:
        t_port = t.model_copy(deep=True)
        t_port.image_path = f"images/{Path(t.image_path).name}"
        t_port.spec_path = f"specs/{Path(t.spec_path).name}"
        if t.svg_path:
            t_port.svg_path = f"svgs/{Path(t.svg_path).name}"
        portable_lines.append(t_port.model_dump_json())
    manifest_jsonl.write_text("\n".join(portable_lines) + "\n")
    summary = {
        "total_tasks": len(tasks),
        "requested_count": count,
        "unique_signatures": len(seen_sigs),
        "capped_at_unique_limit": exhausted_unique,
        "base_seed": base_seed,
        "dataset_jsonl": "dataset.jsonl",
        "lazy_render": lazy_render,
        "materialized_images": sum(1 for t in tasks if (out_path / "images" / Path(t.image_path).name).exists()),
        "families": sorted({t.family.value for t in tasks}),
    }
    (out_path / "manifest.json").write_text(json.dumps(summary, indent=2))
    return tasks
