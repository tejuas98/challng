"""Production FastAPI Service for SchemForge Visual Task Factory.

Provides:
  - /healthz & /readyz Kubernetes/Cloud Run health checks
  - Async Batch Factory Jobs (POST /api/batches, GET /api/batches/{id}, ZIP export download)
  - Live Interactive Generation & Custom Netlist Compilation (POST /api/from-netlist)
  - In-Browser Benchmark Evaluation Runner (POST /api/evaluate-live)
  - Multi-Batch Task Inspector & Visual Audit Studio UI
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from schemforge.config import load_settings
from schemforge.degradation import apply_degradation
from schemforge.evaluator import evaluate_dataset
from schemforge.exporters import create_batch_archive
from schemforge.generator import generate_task_spec
from schemforge.ingest import (
    CustomCircuitInput,
    compile_custom_netlist,
    estimate_custom_combinations,
    generate_custom_variations,
    parse_netlist_text,
)
from schemforge.mutation import run_mutation_suite
from schemforge.netlist import (
    DegradationProfile,
    DifficultyTier,
    LabelMode,
    SchematicSpec,
    TaskFamily,
    TaskPackage,
    ThemeStyle,
)
from schemforge.pipeline import (
    build_single_task,
    estimate_benchmark_combinations,
    generate_benchmark_dataset,
)
from schemforge.renderer import render_schematic
from schemforge.validator import validate_dataset

cfg = load_settings()
START_TIME = time.time()

app = FastAPI(title="SchemForge Production Visual Task Factory", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
if cfg.static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(cfg.static_dir)), name="static")

_JOB_LOCK = threading.Lock()
_BATCH_JOBS: dict[str, dict] = {}
_EVAL_LOCK = threading.Lock()
_EVAL_JOBS: dict[str, dict] = {}

class LiveGenerateRequest(BaseModel):
    family: TaskFamily = TaskFamily.STATE_PROPAGATION
    difficulty: DifficultyTier = DifficultyTier.MEDIUM
    theme: ThemeStyle = ThemeStyle.IEEE_CLASSIC
    degradation: DegradationProfile = DegradationProfile.CLEAN
    label_mode: LabelMode = LabelMode.SYMBOL_ONLY
    seed: int = 2026

class BatchCreateRequest(BaseModel):
    name: Optional[str] = None
    count: int = Field(default=24, ge=1, le=25000)
    seed: int = 100
    families: Optional[list[TaskFamily]] = None
    difficulties: Optional[list[DifficultyTier]] = None
    themes: Optional[list[ThemeStyle]] = None
    degradations: Optional[list[DegradationProfile]] = None
    label_modes: Optional[list[LabelMode]] = None
    include_degradations: bool = True
    include_invariance_pairs: bool = True
    emit_svg: bool = True
    run_ocr: bool = True
    lazy_render: Optional[bool] = None

class CustomTextRequest(BaseModel):
    text: str
    title: str = "CUSTOM SCHEMATIC"
    theme: ThemeStyle = ThemeStyle.IEEE_CLASSIC
    degradation: DegradationProfile = DegradationProfile.CLEAN
    label_mode: LabelMode = LabelMode.SYMBOL_ONLY
    seed: int = 1001

class CustomBatchRequest(BaseModel):
    name: Optional[str] = "custom_bench"
    text: str
    title: str = "CUSTOM SCHEMATIC"
    count: int = Field(default=100, ge=1, le=25000)
    seed: int = 1000
    degradations: Optional[list[DegradationProfile]] = None
    lazy_render: Optional[bool] = None
    run_ocr: bool = True

class LiveEvaluateRequest(BaseModel):
    batch_id: str = "default"
    provider: str = "ocr_heuristic"
    providers: Optional[list[str]] = None
    model: Optional[str] = None
    limit: int = Field(default=18, ge=1, le=200)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    persist: bool = True

class CombinationEstimateRequest(BaseModel):
    requested_count: int = Field(default=30, ge=1, le=25000)
    families: Optional[list[TaskFamily]] = None
    difficulties: Optional[list[DifficultyTier]] = None
    themes: Optional[list[ThemeStyle]] = None
    degradations: Optional[list[DegradationProfile]] = None
    label_modes: Optional[list[LabelMode]] = None
    custom_text: Optional[str] = None
    custom_title: str = "CUSTOM CIRCUIT"

_BUILTIN_PRESET_INFO = {
    "default": {
        "title": "Default Starter Mix",
        "topic_label": "All 7 Topics",
        "level_label": "Mix (Easy / Med / Hard)",
        "summary": "Balanced starter mix covering logic gates, bridge hops, ohms, faults, and comparisons.",
    },
    "starter_easy": {
        "title": "Easy Practice Pack",
        "topic_label": "All 7 Topics",
        "level_label": "Easy Only",
        "summary": "Straightforward single-stage circuits with clean and scanned pages for warm-ups.",
    },
    "starter_medium": {
        "title": "Medium Challenge Pack",
        "topic_label": "All 7 Topics",
        "level_label": "Medium Only",
        "summary": "Multi-gate branching logic, wire bridges, and parallel resistance problems.",
    },
    "starter_hard": {
        "title": "Hard Exam Pack",
        "topic_label": "All 7 Topics",
        "level_label": "Hard Only",
        "summary": "Deep multi-step schematics with symbols only and realistic scan degradations.",
    },
    "logic_gates_focus": {
        "title": "Switches & Logic Gates Lab",
        "topic_label": "Switches & Logic",
        "level_label": "Easy / Med / Hard",
        "summary": "Boolean gates, open/closed switches, fuses, and LED tracing without hint text.",
    },
    "resistors_ohms_lab": {
        "title": "Resistors & Ohms Lab",
        "topic_label": "Total Resistance",
        "level_label": "Easy / Med / Hard",
        "summary": "Clean series and parallel resistor networks solving equivalent Ohm calculations.",
    },
}

_TOPIC_NAMES = {
    "state_propagation": "Switches & Logic Gates",
    "bridge_vs_junction": "Crossing Wires",
    "equivalent_resistance": "Total Resistance (Ohms)",
    "fault_diagnosis": "Find Broken Part",
    "counterfactual_pair": "Spot Difference",
    "component_audit": "Count Parts",
    "whole_system": "Full System",
    "custom_netlist": "Custom Circuit",
}

def _describe_custom_batch(ds_path: Path) -> tuple[str, str, str]:
    """Build concise topic, difficulty, and what's-inside summary from a custom batch's first tasks."""
    if not ds_path.exists():
        return "Custom Topics", "Mixed", "Custom circuit question set generating..."
    fams: set[str] = set()
    diffs: set[str] = set()
    lmodes: set[str] = set()
    try:
        for ln in ds_path.read_text().splitlines()[:35]:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            if obj.get("family"):
                fams.add(obj["family"])
            if obj.get("difficulty"):
                diffs.add(obj["difficulty"])
            if obj.get("label_mode"):
                lmodes.add(obj["label_mode"])
    except Exception:
        return "Custom Topics", "Mixed", "Custom question bank with Quiz Booklet HTML, CSV & PNGs."
    t_lbl = "All 7 Topics" if len(fams) >= 5 else ", ".join(_TOPIC_NAMES.get(f, f) for f in sorted(fams)[:2]) or "Custom"
    d_lbl = "Mix Levels" if len(diffs) >= 2 else (next(iter(diffs)).title() + " Only" if diffs else "Mixed")
    m_note = "symbols-only visual check" if lmodes == {"symbol_only"} else ("part values shown" if lmodes == {"annotated"} else "mixed symbols & values")
    return t_lbl, d_lbl, f"Custom bank ({m_note}) ready as Quiz Booklet HTML, Excel CSV & PNGs."

def _resolve_batch_dir(batch_id: str) -> Path:
    if batch_id in ("", "default"):
        cand = cfg.artifacts_dir / "sample_dataset"
        if (cand / "dataset.jsonl").exists():
            return cand
        return cfg.showcase_dir / "sample_dataset"
    if batch_id == "showcase":
        return cfg.showcase_dir / "sample_dataset"
    safe = Path(batch_id).name
    preset_dir = (cfg.showcase_dir / "presets" / safe).resolve()
    if preset_dir.is_relative_to((cfg.showcase_dir / "presets").resolve()) and (preset_dir / "dataset.jsonl").exists():
        return preset_dir
    p = (cfg.artifacts_dir / "batches" / safe).resolve()
    if not p.is_relative_to((cfg.artifacts_dir / "batches").resolve()):
        raise HTTPException(status_code=400, detail="Invalid batch_id")
    return p

def _load_batch_tasks(batch_id: str) -> list[TaskPackage]:
    bdir = _resolve_batch_dir(batch_id)
    ds = bdir / "dataset.jsonl"
    if not ds.exists():
        return []
    return [TaskPackage.model_validate_json(ln) for ln in ds.read_text().splitlines() if ln.strip()]

def _report_root() -> Path:
    if (cfg.artifacts_dir / "validation_report.json").exists():
        return cfg.artifacts_dir
    return cfg.showcase_dir

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    idx_file = cfg.static_dir / "index.html"
    body = idx_file.read_text() if idx_file.exists() else "<h1>SchemForge Studio</h1><p>static/index.html missing.</p>"
    return HTMLResponse(content=body, headers={"Cache-Control": "no-store, max-age=0"})

@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "uptime_s": round(time.time() - START_TIME, 2),
        "tesseract_available": shutil.which("tesseract") is not None,
    }

@app.get("/readyz")
def readyz() -> dict:
    cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)
    return {
        "ready": True,
        "artifacts_dir": str(cfg.artifacts_dir),
        "default_dataset_loaded": len(_load_batch_tasks("default")) > 0,
    }

def _load_merged_evaluations(rroot: Path) -> list[dict]:
    """Load baseline evaluations merged with any live user/judge evaluation runs."""
    by_key: dict[tuple[str, str], dict] = {}
    for p in sorted(rroot.glob("eval_*.json")):
        if p.name.startswith("eval_live_"):
            continue
        data = json.loads(p.read_text())
        key = (str(data.get("provider", "")), str(data.get("model_label", "")))
        by_key[key] = data
    if cfg.artifacts_dir.exists():
        live_files = sorted(cfg.artifacts_dir.glob("eval_live_*.json"), key=lambda p: p.stat().st_mtime)
        for p in live_files:
            data = json.loads(p.read_text())
            data["_is_live"] = True
            key = (str(data.get("provider", "")), str(data.get("model_label", "")))
            by_key[key] = data
    return list(by_key.values())

@app.get("/api/overview")
def overview() -> dict:
    tasks = _load_batch_tasks("default")
    rroot = _report_root()
    val_p = rroot / "validation_report.json"
    mut_p = rroot / "mutation_report.json"
    charts_dir = rroot / "charts"
    return {
        "task_count": len(tasks),
        "max_api_batch": cfg.max_api_batch,
        "validation": json.loads(val_p.read_text()) if val_p.exists() else None,
        "mutation": json.loads(mut_p.read_text()) if mut_p.exists() else None,
        "evaluations": _load_merged_evaluations(rroot),
        "charts": sorted([p.name for p in charts_dir.glob("*.png")]) if charts_dir.exists() else [],
    }

@app.get("/api/batches")
def list_batches() -> list[dict]:
    batches: list[dict] = []
    def_dir = _resolve_batch_dir("default")
    if (def_dir / "dataset.jsonl").exists():
        info = _BUILTIN_PRESET_INFO["default"]
        batches.append({
            "batch_id": "default",
            "title": info["title"],
            "topic_label": info["topic_label"],
            "level_label": info["level_label"],
            "summary": info["summary"],
            "status": "completed",
            "count": len(_load_batch_tasks("default")),
            "source": "builtin",
        })
    p_root = cfg.showcase_dir / "presets"
    if p_root.exists():
        order = ["starter_easy", "starter_medium", "starter_hard", "logic_gates_focus", "resistors_ohms_lab"]
        dirs_by_name = {d.name: d for d in p_root.iterdir() if d.is_dir() and (d / "dataset.jsonl").exists()}
        ordered_names = [k for k in order if k in dirs_by_name] + sorted(k for k in dirs_by_name if k not in order)
        for bid in ordered_names:
            d = dirs_by_name[bid]
            ds = d / "dataset.jsonl"
            cnt = sum(1 for ln in ds.read_text().splitlines() if ln.strip())
            info = _BUILTIN_PRESET_INFO.get(bid, {})
            batches.append({
                "batch_id": bid,
                "title": info.get("title", bid.replace("_", " ").title()),
                "topic_label": info.get("topic_label", "Mixed Topics"),
                "level_label": info.get("level_label", "Mixed"),
                "summary": info.get("summary", "Ready-to-use question pack."),
                "status": "completed",
                "count": cnt,
                "source": "builtin",
                "zip_ready": True,
            })
    b_root = cfg.artifacts_dir / "batches"
    if b_root.exists():
        for d in sorted(b_root.iterdir(), reverse=True):
            if d.is_dir():
                bid = d.name
                job = _BATCH_JOBS.get(bid, {})
                ds = d / "dataset.jsonl"
                mf = d / "manifest.json"
                cnt = 0
                if mf.exists():
                    try:
                        cnt = int(json.loads(mf.read_text()).get("total_tasks", 0))
                    except Exception:
                        cnt = 0
                if cnt == 0 and ds.exists():
                    cnt = sum(1 for ln in ds.read_text().splitlines() if ln.strip())
                t_lbl, d_lbl, c_summary = _describe_custom_batch(ds)
                batches.append({
                    "batch_id": bid,
                    "title": bid,
                    "topic_label": t_lbl,
                    "level_label": d_lbl,
                    "summary": c_summary,
                    "status": job.get("status", "completed" if ds.exists() else "unknown"),
                    "completed": job.get("completed", cnt),
                    "total": job.get("total", cnt),
                    "count": cnt,
                    "source": "custom",
                    "zip_ready": (d.with_suffix(".zip")).exists(),
                })
    return batches

def _run_batch_job(batch_id: str, req: BatchCreateRequest) -> None:
    out_dir = cfg.artifacts_dir / "batches" / batch_id
    use_lazy = req.lazy_render if req.lazy_render is not None else (req.count > 120)
    started_at = _BATCH_JOBS.get(batch_id, {}).get("started_at") or time.time()
    est_per_q = 0.015 if use_lazy else 0.42
    with _JOB_LOCK:
        _BATCH_JOBS[batch_id] = {
            "batch_id": batch_id,
            "status": "running",
            "completed": 0,
            "total": req.count,
            "started_at": started_at,
            "elapsed_s": 0.0,
            "eta_seconds": round(req.count * est_per_q, 1),
            "error": None,
        }

    def on_prog(done: int, tot: int) -> None:
        with _JOB_LOCK:
            job = _BATCH_JOBS.get(batch_id)
            if not job:
                return
            elapsed = max(0.05, time.time() - job["started_at"])
            eta = round((elapsed / done) * max(0, tot - done), 1) if done > 0 else round(tot * est_per_q, 1)
            job["completed"] = done
            job["total"] = tot
            job["elapsed_s"] = round(elapsed, 1)
            job["eta_seconds"] = eta

    try:
        use_inv = req.include_invariance_pairs and not (req.themes or req.degradations)
        tasks = generate_benchmark_dataset(
            out_dir=out_dir,
            count=req.count,
            base_seed=req.seed,
            families=req.families,
            difficulties=req.difficulties,
            themes=req.themes,
            degradations=req.degradations,
            label_modes=req.label_modes,
            include_degradations=req.include_degradations,
            include_invariance_pairs=use_inv,
            run_ocr=req.run_ocr,
            emit_svg=req.emit_svg and not use_lazy,
            workers=1,
            lazy_render=use_lazy,
            progress_cb=on_prog,
        )
        val_rep = validate_dataset(tasks, run_ocr=(req.run_ocr and not use_lazy), dataset_root=out_dir)
        (out_dir / "validation_report.json").write_text(json.dumps(val_rep, indent=2))
        if not use_lazy:
            create_batch_archive(out_dir, out_dir.with_suffix(".zip"))
        with _JOB_LOCK:
            _BATCH_JOBS[batch_id]["completed"] = len(tasks)
            _BATCH_JOBS[batch_id]["total"] = len(tasks)
            _BATCH_JOBS[batch_id]["requested_count"] = req.count
            _BATCH_JOBS[batch_id]["capped_at_unique_limit"] = len(tasks) < req.count
            _BATCH_JOBS[batch_id]["elapsed_s"] = round(time.time() - started_at, 1)
            _BATCH_JOBS[batch_id]["eta_seconds"] = 0.0
            _BATCH_JOBS[batch_id]["status"] = "completed"
            _BATCH_JOBS[batch_id]["validation"] = val_rep
            _BATCH_JOBS[batch_id]["zip_ready"] = True
    except Exception as exc:
        with _JOB_LOCK:
            _BATCH_JOBS[batch_id]["elapsed_s"] = round(time.time() - started_at, 1)
            _BATCH_JOBS[batch_id]["eta_seconds"] = 0.0
            _BATCH_JOBS[batch_id]["status"] = "failed"
            _BATCH_JOBS[batch_id]["error"] = str(exc)

def _run_custom_batch_job(batch_id: str, payload: CustomCircuitInput, req: CustomBatchRequest) -> None:
    out_dir = cfg.artifacts_dir / "batches" / batch_id
    use_lazy = req.lazy_render if req.lazy_render is not None else (req.count > 120)
    with _JOB_LOCK:
        _BATCH_JOBS[batch_id] = {
            "batch_id": batch_id,
            "status": "running",
            "completed": 0,
            "total": req.count,
            "error": None,
        }

    def on_prog(done: int, tot: int) -> None:
        with _JOB_LOCK:
            _BATCH_JOBS[batch_id]["completed"] = done
            _BATCH_JOBS[batch_id]["total"] = tot

    try:
        tasks = generate_custom_variations(
            payload=payload,
            out_dir=out_dir,
            count=req.count,
            base_seed=req.seed,
            lazy_render=use_lazy,
            run_ocr=req.run_ocr and not use_lazy,
            degradations=req.degradations,
            progress_cb=on_prog,
        )
        val_rep = validate_dataset(tasks, run_ocr=False, dataset_root=out_dir)
        (out_dir / "validation_report.json").write_text(json.dumps(val_rep, indent=2))
        with _JOB_LOCK:
            _BATCH_JOBS[batch_id]["completed"] = len(tasks)
            _BATCH_JOBS[batch_id]["total"] = len(tasks)
            _BATCH_JOBS[batch_id]["requested_count"] = req.count
            _BATCH_JOBS[batch_id]["capped_at_unique_limit"] = len(tasks) < req.count
            _BATCH_JOBS[batch_id]["status"] = "completed"
            _BATCH_JOBS[batch_id]["validation"] = val_rep
            _BATCH_JOBS[batch_id]["zip_ready"] = True
    except Exception as exc:
        with _JOB_LOCK:
            _BATCH_JOBS[batch_id]["status"] = "failed"
            _BATCH_JOBS[batch_id]["error"] = str(exc)

@app.post("/api/batches")
def create_batch(req: BatchCreateRequest, bg: BackgroundTasks) -> dict:
    if req.count > cfg.max_api_batch:
        raise HTTPException(status_code=400, detail=f"count exceeds max_api_batch={cfg.max_api_batch}")
    slug = (req.name or f"batch_{req.seed}").replace(" ", "_")
    slug = "".join(ch for ch in slug if ch.isalnum() or ch in ("_", "-"))[:28] or "batch"
    batch_id = f"{slug}_{uuid.uuid4().hex[:6]}"
    use_lazy = req.lazy_render if req.lazy_render is not None else (req.count > 120)
    est_eta = round(req.count * (0.015 if use_lazy else 0.42), 1)
    with _JOB_LOCK:
        _BATCH_JOBS[batch_id] = {
            "batch_id": batch_id,
            "status": "queued",
            "completed": 0,
            "total": req.count,
            "started_at": time.time(),
            "elapsed_s": 0.0,
            "eta_seconds": est_eta,
        }
    bg.add_task(_run_batch_job, batch_id, req)
    return _BATCH_JOBS[batch_id]

@app.post("/api/from-netlist/batch")
def create_custom_batch(req: CustomBatchRequest, bg: BackgroundTasks) -> dict:
    if req.count > cfg.max_api_batch:
        raise HTTPException(status_code=400, detail=f"count exceeds max_api_batch={cfg.max_api_batch}")
    try:
        payload = parse_netlist_text(req.text, title=req.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    slug = (req.name or "custom_bench").replace(" ", "_")
    slug = "".join(ch for ch in slug if ch.isalnum() or ch in ("_", "-"))[:28] or "custom"
    batch_id = f"{slug}_{uuid.uuid4().hex[:6]}"
    with _JOB_LOCK:
        _BATCH_JOBS[batch_id] = {"batch_id": batch_id, "status": "queued", "completed": 0, "total": req.count}
    bg.add_task(_run_custom_batch_job, batch_id, payload, req)
    return _BATCH_JOBS[batch_id]

@app.post("/api/estimate-combinations")
def estimate_combinations(req: CombinationEstimateRequest) -> dict:
    if req.custom_text is not None:
        try:
            payload = parse_netlist_text(req.custom_text, title=req.custom_title)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        deg_cnt = len(req.degradations) if req.degradations else 4
        return estimate_custom_combinations(
            payload,
            requested_count=req.requested_count,
            degs_count=deg_cnt,
        )
    return estimate_benchmark_combinations(
        families=req.families,
        difficulties=req.difficulties,
        themes=req.themes,
        degradations=req.degradations,
        label_modes=req.label_modes,
        requested_count=req.requested_count,
    )

@app.delete("/api/batches/{batch_id}")
def delete_batch(batch_id: str) -> dict:
    safe = Path(batch_id).name
    if batch_id in ("", "default", "showcase") or (cfg.showcase_dir / "presets" / safe).exists():
        raise HTTPException(status_code=400, detail="Cannot delete a built-in starter question set.")
    bdir = _resolve_batch_dir(batch_id)
    if bdir.exists():
        shutil.rmtree(bdir)
    for zp in (bdir.with_suffix(".zip"), (cfg.artifacts_dir / "exports" / f"{batch_id}.zip").resolve()):
        if zp.exists():
            zp.unlink()
    with _JOB_LOCK:
        _BATCH_JOBS.pop(batch_id, None)
    return {"deleted": batch_id}

@app.get("/api/batches/{batch_id}")
def get_batch_status(batch_id: str) -> dict:
    with _JOB_LOCK:
        if batch_id in _BATCH_JOBS:
            snap = dict(_BATCH_JOBS[batch_id])
            if snap.get("status") in ("queued", "running") and snap.get("started_at"):
                snap["elapsed_s"] = round(time.time() - snap["started_at"], 1)
            return snap
    bdir = _resolve_batch_dir(batch_id)
    if (bdir / "dataset.jsonl").exists():
        return {"batch_id": batch_id, "status": "completed", "count": len(_load_batch_tasks(batch_id))}
    raise HTTPException(status_code=404, detail="Batch not found")

def _zip_has_booklet(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return "OPEN_ME_QUIZ_BOOKLET.html" in zf.namelist()
    except Exception:
        return False

@app.get("/api/batches/{batch_id}/download")
def download_batch_zip(batch_id: str) -> FileResponse:
    bdir = _resolve_batch_dir(batch_id)
    if not (bdir / "dataset.jsonl").exists():
        raise HTTPException(status_code=404, detail="Batch dataset not found")
    export_zip = (cfg.artifacts_dir / "exports" / f"{batch_id}.zip").resolve()
    direct_zip = bdir.with_suffix(".zip")
    zpath = direct_zip if _zip_has_booklet(direct_zip) else export_zip
    if not _zip_has_booklet(zpath):
        zpath = create_batch_archive(bdir, export_zip)
    return FileResponse(
        str(zpath),
        media_type="application/zip",
        filename=f"schemforge_{batch_id}.zip",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/api/tasks")
def list_tasks(
    response: Response,
    batch_id: str = "default",
    family: Optional[str] = None,
    difficulty: Optional[str] = None,
    degradation: Optional[str] = None,
    q: Optional[str] = None,
    offset: int = 0,
    limit: Optional[int] = None,
) -> list[dict]:
    tasks = _load_batch_tasks(batch_id)
    q_norm = q.strip().lower() if q else ""
    q_num = q_norm[1:] if q_norm.startswith("#") else q_norm
    filtered: list[TaskPackage] = []
    for idx, t in enumerate(tasks):
        if family and t.family.value != family:
            continue
        if difficulty and t.difficulty.value != difficulty:
            continue
        if degradation and t.degradation.value != degradation:
            continue
        if q_norm:
            idx_match = q_num.isdigit() and int(q_num) == (idx + 1)
            hay = f"{t.task_id} {t.question} {t.answer} {t.family.value} {t.difficulty.value} {t.theme.value}".lower()
            if not idx_match and q_norm not in hay:
                continue
        filtered.append(t)

    response.headers["X-Total-Count"] = str(len(filtered))
    sliced = filtered[offset : offset + limit] if limit is not None else filtered[offset:]
    out = []
    for t in sliced:
        d = t.model_dump()
        d["image_url"] = f"/api/tasks/{t.task_id}/image?batch_id={batch_id}"
        d["spec_url"] = f"/api/tasks/{t.task_id}/spec?batch_id={batch_id}"
        out.append(d)
    return out

def _materialize_lazy_task_asset(task_id: str, batch_id: str) -> Optional[Path]:
    """On-demand render & cache PNG+spec for any task inside a 10,000+ lazy batch."""
    bdir = _resolve_batch_dir(batch_id)
    ds = bdir / "dataset.jsonl"
    if not ds.exists():
        return None
    target_t: Optional[TaskPackage] = None
    for ln in ds.read_text().splitlines():
        if task_id in ln:
            cand = TaskPackage.model_validate_json(ln)
            if cand.task_id == task_id:
                target_t = cand
                break
    if target_t is None:
        return None
    img_p = bdir / "images" / f"{task_id}.png"
    spec_p = bdir / "specs" / f"{task_id}.json"
    img_p.parent.mkdir(parents=True, exist_ok=True)
    spec_p.parent.mkdir(parents=True, exist_ok=True)
    if spec_p.exists():
        spec = SchematicSpec.model_validate_json(spec_p.read_text())
    else:
        spec, _ = generate_task_spec(target_t.family, target_t.difficulty, target_t.label_mode, target_t.seed)
        spec_p.write_text(spec.model_dump_json())
    render_schematic(spec, img_p, theme=target_t.theme)
    apply_degradation(str(img_p), target_t.degradation, seed=target_t.seed + 991)
    return img_p

@app.get("/api/tasks/{task_id}/image")
def task_image(task_id: str, batch_id: str = "default") -> FileResponse:
    candidates = [
        _resolve_batch_dir(batch_id) / "images" / f"{task_id}.png",
        cfg.artifacts_dir / "live_preview" / "images" / f"{task_id}.png",
        cfg.artifacts_dir / "custom_preview" / "images" / f"{task_id}.png",
        cfg.showcase_dir / "sample_dataset" / "images" / f"{task_id}.png",
    ]
    no_cache = {"Cache-Control": "no-store, max-age=0"}
    for p in candidates:
        if p.exists():
            return FileResponse(str(p), media_type="image/png", headers=no_cache)
    lazy_p = _materialize_lazy_task_asset(task_id, batch_id)
    if lazy_p and lazy_p.exists():
        return FileResponse(str(lazy_p), media_type="image/png", headers=no_cache)
    raise HTTPException(status_code=404, detail="Task image not found")

@app.get("/api/tasks/{task_id}/spec")
def task_spec(task_id: str, batch_id: str = "default") -> dict:
    candidates = [
        _resolve_batch_dir(batch_id) / "specs" / f"{task_id}.json",
        cfg.artifacts_dir / "live_preview" / "specs" / f"{task_id}.json",
        cfg.artifacts_dir / "custom_preview" / "specs" / f"{task_id}.json",
    ]
    for p in candidates:
        if p.exists():
            return json.loads(p.read_text())
    lazy_p = _materialize_lazy_task_asset(task_id, batch_id)
    spec_p = _resolve_batch_dir(batch_id) / "specs" / f"{task_id}.json"
    if lazy_p and spec_p.exists():
        return json.loads(spec_p.read_text())
    raise HTTPException(status_code=404, detail="Task spec not found")

@app.get("/api/charts/{filename}")
def chart_file(filename: str) -> FileResponse:
    croot = (_report_root() / "charts").resolve()
    p = (croot / filename).resolve()
    if not p.is_relative_to(croot) or not p.exists():
        raise HTTPException(status_code=404, detail="Chart not found")
    return FileResponse(str(p), media_type="image/png")

@app.post("/api/generate-live")
def generate_live(req: LiveGenerateRequest) -> dict:
    live_dir = cfg.artifacts_dir / "live_preview"
    uid = uuid.uuid4().hex[:6]
    tid = f"live_{req.family.value[:6]}_{req.difficulty.value[:3]}_{req.seed}_{uid}"
    pkg = build_single_task(
        task_id=tid,
        family=req.family,
        difficulty=req.difficulty,
        theme=req.theme,
        degradation=req.degradation,
        label_mode=req.label_mode,
        seed=req.seed,
        out_dir=live_dir,
        run_ocr=True,
    )
    d = pkg.model_dump()
    d["image_url"] = f"/api/tasks/{tid}/image?cb={uid}"
    d["spec_url"] = f"/api/tasks/{tid}/spec"
    return d

@app.post("/api/from-netlist")
def compile_netlist_endpoint(payload: CustomCircuitInput) -> dict:
    custom_dir = cfg.artifacts_dir / "custom_preview"
    tid = f"custom_{payload.seed}_{uuid.uuid4().hex[:5]}"
    try:
        pkg = compile_custom_netlist(payload, out_dir=custom_dir, task_id=tid, run_ocr=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    d = pkg.model_dump()
    d["image_url"] = f"/api/tasks/{tid}/image"
    d["spec_url"] = f"/api/tasks/{tid}/spec"
    return d

@app.post("/api/from-netlist/dsl")
def compile_netlist_dsl_endpoint(req: CustomTextRequest) -> dict:
    try:
        payload = parse_netlist_text(req.text, title=req.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload.theme = req.theme
    payload.degradation = req.degradation
    payload.label_mode = req.label_mode
    payload.seed = req.seed
    custom_dir = cfg.artifacts_dir / "custom_preview"
    tid = f"custom_{payload.seed}_{uuid.uuid4().hex[:5]}"
    try:
        pkg = compile_custom_netlist(payload, out_dir=custom_dir, task_id=tid, run_ocr=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    d = pkg.model_dump()
    d["image_url"] = f"/api/tasks/{tid}/image"
    d["spec_url"] = f"/api/tasks/{tid}/spec"
    return d

_PROVIDER_SPECS = {
    "gemini": {"label": "Google Gemini", "env_var": "GEMINI_API_KEY", "free_tier": True, "default_model": "gemini-3.1-flash-lite"},
    "openrouter": {"label": "OpenRouter Vision", "env_var": "OPENROUTER_API_KEY", "free_tier": True, "default_model": "nvidia/nemotron-3.5-super-vl:free"},
    "openai": {"label": "OpenAI GPT-4o", "env_var": "OPENAI_API_KEY", "free_tier": False, "default_model": "gpt-4o"},
    "anthropic": {"label": "Anthropic Claude", "env_var": "ANTHROPIC_API_KEY", "free_tier": False, "default_model": "claude-sonnet-4-5"},
    "ollama": {"label": "Local Ollama (Offline)", "env_var": None, "free_tier": True, "default_model": "qwen2.5vl:3b"},
    "custom": {"label": "Custom Vision API", "env_var": "CUSTOM_API_KEY", "free_tier": False, "default_model": "gpt-4o"},
}

_ALLOWED_ENV_KEYS = {spec["env_var"] for spec in _PROVIDER_SPECS.values() if spec["env_var"]} | {"CUSTOM_API_BASE", "CUSTOM_API_MODEL"}

class SaveProviderKeyRequest(BaseModel):
    provider: str
    api_key: str
    base_url: Optional[str] = None
    default_model: Optional[str] = None

def _provider_has_key(pid: str, extra_key: Optional[str] = None) -> bool:
    spec = _PROVIDER_SPECS.get(pid)
    if not spec:
        return True
    if pid == "ollama":
        return shutil.which("ollama") is not None
    env_var = spec["env_var"]
    if not env_var:
        return True
    if extra_key and extra_key.strip():
        return True
    return bool(os.environ.get(env_var) or (pid == "gemini" and os.environ.get("GOOGLE_API_KEY")))

def _write_env_vars(updates: dict[str, Optional[str]]) -> None:
    """Safely update or delete allowed keys inside local git-ignored .env (chmod 0600)."""
    env_file = (cfg.project_root / ".env").resolve()
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    rm_prefixes = {f"{k}=" for k in updates}
    new_lines = [ln for ln in lines if not any(ln.strip().startswith(p) for p in rm_prefixes)]
    for k, v in updates.items():
        if v is not None and v.strip():
            clean_v = v.strip().replace("\r", "").replace("\n", "")
            new_lines.append(f"{k}={clean_v}")
            os.environ[k] = clean_v
        else:
            os.environ.pop(k, None)
    env_file.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
    try:
        os.chmod(env_file, 0o600)
    except OSError:
        pass

@app.get("/api/providers/status")
def providers_status() -> dict:
    """Return ONLY non-secret booleans showing which Vision AI providers have private keys ready in .env."""
    status = {}
    for pid, meta in _PROVIDER_SPECS.items():
        env_var = meta["env_var"]
        def_model = (os.environ.get("CUSTOM_API_MODEL") or meta["default_model"]) if pid == "custom" else meta["default_model"]
        status[pid] = {
            "label": meta["label"],
            "env_var": env_var or "LOCAL",
            "free_tier": meta["free_tier"],
            "default_model": def_model,
            "configured": _provider_has_key(pid),
        }
    return status

@app.post("/api/providers/key")
def save_provider_key(req: SaveProviderKeyRequest) -> dict:
    """Persist an API key ONLY to local git-ignored .env (chmod 0600); never echo or commit."""
    if os.environ.get("SCHEMFORGE_PROTECT_ENV_KEYS") == "1":
        raise HTTPException(status_code=403, detail="Host-managed API keys cannot be overwritten on a shared public deployment.")
    pid = req.provider.lower().strip()
    spec = _PROVIDER_SPECS.get(pid)
    if not spec or not spec["env_var"]:
        raise HTTPException(status_code=400, detail="Selected provider does not use an API key.")
    env_var = spec["env_var"]
    if env_var not in _ALLOWED_ENV_KEYS:
        raise HTTPException(status_code=400, detail="Unsupported key name.")
    val = req.api_key.strip().replace("\r", "").replace("\n", "")
    if not val or any(ch in val for ch in ('"', "'", "`", "$")):
        raise HTTPException(status_code=400, detail="Invalid API key format.")
    updates: dict[str, Optional[str]] = {env_var: val}
    if pid == "custom":
        if req.base_url and req.base_url.strip():
            bu = req.base_url.strip()
            if not (bu.startswith("https://") or bu.startswith("http://")) or any(ch in bu for ch in ('"', "'", "`", "$")):
                raise HTTPException(status_code=400, detail="Custom Base URL must start with http:// or https://")
            updates["CUSTOM_API_BASE"] = bu
        if req.default_model and req.default_model.strip():
            updates["CUSTOM_API_MODEL"] = req.default_model.strip()
    _write_env_vars(updates)
    return {"env_var": env_var, "configured": True}

@app.delete("/api/providers/key/{provider}")
def delete_provider_key(provider: str) -> dict:
    """Remove a saved provider API key from local .env without affecting other keys."""
    if os.environ.get("SCHEMFORGE_PROTECT_ENV_KEYS") == "1":
        raise HTTPException(status_code=403, detail="Host-managed API keys cannot be removed on a shared public deployment.")
    pid = provider.lower().strip()
    spec = _PROVIDER_SPECS.get(pid)
    if not spec or not spec["env_var"]:
        raise HTTPException(status_code=400, detail="Selected provider does not store an API key.")
    updates: dict[str, Optional[str]] = {spec["env_var"]: None}
    if pid == "custom":
        updates["CUSTOM_API_BASE"] = None
        updates["CUSTOM_API_MODEL"] = None
    _write_env_vars(updates)
    return {"env_var": spec["env_var"], "configured": False}

_EST_SEC_PER_TASK = {
    "ollama": 3.5,
    "gemini": 1.6,
    "openrouter": 3.0,
    "openai": 2.2,
    "anthropic": 2.5,
    "custom": 2.5,
    "ocr_heuristic": 0.25,
    "blind_random": 0.02,
    "oracle_solver": 0.02,
}

def _persist_eval_report(report: dict) -> Optional[Path]:
    """Persist mostly-valid evaluation report metrics (never credentials) so charts stay updated."""
    tot = int(report.get("total_tasks", 0))
    valid = int(report.get("valid_calls", tot))
    if tot == 0 or valid == 0 or valid * 2 < tot:
        return None
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", f"{report.get('provider', 'model')}_{report.get('model_label', 'run')}").strip("_")
    out_p = cfg.artifacts_dir / f"eval_live_{slug}.json"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    to_save = dict(report)
    to_save["_saved_at"] = round(time.time(), 2)
    out_p.write_text(json.dumps(to_save, indent=2))
    return out_p

def _ensure_eval_images(batch_id: str, ds_path: Path, limit: int) -> int:
    """Materialize any lazy-rendered images for the first `limit` tasks so live eval always works."""
    lines = [ln for ln in ds_path.read_text().splitlines() if ln.strip()][:limit]
    for ln in lines:
        t = TaskPackage.model_validate_json(ln)
        img_p = Path(t.image_path)
        if not img_p.is_absolute():
            img_p = (ds_path.parent / img_p).resolve()
        if not img_p.exists():
            _materialize_lazy_task_asset(t.task_id, batch_id)
    return len(lines)

def _run_eval_job_worker(job_id: str, req: LiveEvaluateRequest, ds_path: Path, provider_list: list[str], tasks_per_model: int) -> None:
    grand_total = tasks_per_model * len(provider_list)
    completed_prior_tasks = 0
    prior_correct = 0
    reports: list[dict] = []
    errors: list[dict] = []

    try:
        _ensure_eval_images(req.batch_id, ds_path, req.limit)
        for m_idx, prov in enumerate(provider_list):
            with _EVAL_LOCK:
                job = _EVAL_JOBS.get(job_id)
                if job:
                    job["current_model"] = _PROVIDER_SPECS.get(prov, {}).get("label", prov)
                    job["current_model_index"] = m_idx + 1

            def on_progress(done: int, _tot: int, correct_n: int, base_done: int = completed_prior_tasks, base_ok: int = prior_correct) -> None:
                with _EVAL_LOCK:
                    job = _EVAL_JOBS.get(job_id)
                    if not job:
                        return
                    overall_done = base_done + done
                    elapsed = max(0.05, time.time() - job["started_at"])
                    eta = round((elapsed / overall_done) * max(0, grand_total - overall_done), 1) if overall_done > 0 else None
                    job["completed"] = overall_done
                    job["total"] = grand_total
                    job["correct_so_far"] = base_ok + correct_n
                    job["elapsed_s"] = round(elapsed, 1)
                    job["eta_seconds"] = eta

            try:
                use_model = req.model if len(provider_list) == 1 else None
                rep = evaluate_dataset(
                    dataset_path=ds_path,
                    provider=prov,
                    model=use_model,
                    limit=req.limit,
                    api_key=req.api_key,
                    base_url=req.base_url if prov == "custom" else None,
                    progress_cb=on_progress,
                )
                if req.persist:
                    _persist_eval_report(rep)
                reports.append(rep)
                prior_correct += round(rep["overall_accuracy"] * rep["total_tasks"])
            except Exception as model_exc:
                errors.append({"provider": prov, "error": str(model_exc)})
            completed_prior_tasks += tasks_per_model

        with _EVAL_LOCK:
            job = _EVAL_JOBS[job_id]
            job["status"] = "completed" if reports else "failed"
            job["completed"] = grand_total
            job["total"] = grand_total
            job["correct_so_far"] = prior_correct
            job["elapsed_s"] = round(time.time() - job["started_at"], 1)
            job["eta_seconds"] = 0.0
            job["reports"] = reports
            job["report"] = reports[0] if reports else None
            job["model_errors"] = errors
            if not reports and errors:
                job["error"] = errors[0]["error"]
    except Exception as exc:
        with _EVAL_LOCK:
            job = _EVAL_JOBS[job_id]
            job["status"] = "failed"
            job["error"] = str(exc)
            job["elapsed_s"] = round(time.time() - job["started_at"], 1)
            job["eta_seconds"] = 0.0

def _enforce_eval_limit(provider_list: list[str], limit: int) -> None:
    """Enforce configurable per-run question cap when hosted AI keys are exposed publicly."""
    max_eval_cap = int(os.environ.get("SCHEMFORGE_EVAL_MAX_LIMIT", "200"))
    if any(p not in ("ocr_heuristic", "blind_random", "oracle_solver") for p in provider_list) and limit > max_eval_cap:
        raise HTTPException(
            status_code=400,
            detail=f"AI test limit is capped at {max_eval_cap} questions per run to protect host quota.",
        )

@app.post("/api/evaluate-live")
def evaluate_live(req: LiveEvaluateRequest) -> dict:
    _enforce_eval_limit([req.provider], req.limit)
    bdir = _resolve_batch_dir(req.batch_id)
    ds = bdir / "dataset.jsonl"
    if not ds.exists():
        raise HTTPException(status_code=404, detail=f"Batch '{req.batch_id}' not found")
    _ensure_eval_images(req.batch_id, ds, req.limit)
    rep = evaluate_dataset(
        dataset_path=ds,
        provider=req.provider,
        model=req.model,
        limit=req.limit,
        api_key=req.api_key,
        base_url=req.base_url if req.provider == "custom" else None,
    )
    if req.persist:
        _persist_eval_report(rep)
    return rep

@app.post("/api/evaluate-jobs")
def start_evaluate_job(req: LiveEvaluateRequest, background_tasks: BackgroundTasks) -> dict:
    bdir = _resolve_batch_dir(req.batch_id)
    ds = bdir / "dataset.jsonl"
    if not ds.exists():
        raise HTTPException(status_code=404, detail=f"Batch '{req.batch_id}' not found")
    provider_list = list(dict.fromkeys(p.strip() for p in (req.providers or [req.provider]) if p and p.strip()))
    if not provider_list:
        raise HTTPException(status_code=400, detail="Select at least one model to test")
    _enforce_eval_limit(provider_list, req.limit)
    for pid in provider_list:
        spec = _PROVIDER_SPECS.get(pid)
        if spec and spec["env_var"] and not _provider_has_key(pid, req.api_key):
            raise HTTPException(
                status_code=400,
                detail=f"{spec['label']} requires an API key ({spec['env_var']}). Add your key in Model & Key Setup first.",
            )
    tasks_per_model = min(req.limit, len([ln for ln in ds.read_text().splitlines() if ln.strip()]))
    if tasks_per_model == 0:
        raise HTTPException(status_code=400, detail="Selected batch has 0 questions")
    grand_total = tasks_per_model * len(provider_list)
    job_id = f"eval_{uuid.uuid4().hex[:8]}"
    init_eta = round(sum(_EST_SEC_PER_TASK.get(p, 2.0) * tasks_per_model for p in provider_list), 1)
    now = time.time()
    first_label = _PROVIDER_SPECS.get(provider_list[0], {}).get("label", provider_list[0])
    with _EVAL_LOCK:
        _EVAL_JOBS[job_id] = {
            "job_id": job_id,
            "status": "running",
            "provider": provider_list[0],
            "providers": provider_list,
            "current_model": first_label,
            "current_model_index": 1,
            "total_models": len(provider_list),
            "model": req.model,
            "completed": 0,
            "total": grand_total,
            "correct_so_far": 0,
            "started_at": now,
            "elapsed_s": 0.0,
            "eta_seconds": init_eta,
            "report": None,
            "reports": [],
            "model_errors": [],
            "error": None,
        }
    background_tasks.add_task(_run_eval_job_worker, job_id, req, ds, provider_list, tasks_per_model)
    return {
        "job_id": job_id,
        "status": "running",
        "completed": 0,
        "total": grand_total,
        "total_models": len(provider_list),
        "current_model": first_label,
        "current_model_index": 1,
        "eta_seconds": init_eta,
    }

@app.get("/api/evaluate-jobs/{job_id}")
def get_evaluate_job(job_id: str) -> dict:
    with _EVAL_LOCK:
        job = _EVAL_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Evaluation job not found")
        snap = dict(job)
        if snap["status"] == "running":
            snap["elapsed_s"] = round(time.time() - snap["started_at"], 1)
        return snap

@app.post("/api/evaluate-reset")
def reset_live_evaluations() -> dict:
    """Remove persisted live evaluation runs so charts revert cleanly to default baselines."""
    removed = 0
    if cfg.artifacts_dir.exists():
        for p in cfg.artifacts_dir.glob("eval_live_*.json"):
            p.unlink(missing_ok=True)
            removed += 1
    return {"removed": removed}

@app.post("/api/mutate-test")
def run_mutations() -> dict:
    rep = run_mutation_suite()
    out_p = cfg.artifacts_dir / "mutation_report.json"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(rep, indent=2))
    return rep
