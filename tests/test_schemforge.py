"""Comprehensive unit, solver, counterfactual, rendering, and mutation tests."""

from __future__ import annotations

import copy
from pathlib import Path

from schemforge.evaluator import answers_match, evaluate_dataset, normalize_answer
from schemforge.generator import generate_task_spec
from schemforge.mutation import run_mutation_suite
from schemforge.netlist import (
    DegradationProfile,
    DifficultyTier,
    LabelMode,
    SchematicSpec,
    TaskFamily,
    ThemeStyle,
)
from schemforge.pipeline import build_single_task, generate_benchmark_dataset
from schemforge.renderer import render_schematic
from schemforge.solver import eval_resistance_tree, solve_task
from schemforge.validator import validate_dataset

def test_deterministic_seed_reproducibility(tmp_path: Path) -> None:
    p1 = build_single_task(
        "t1", TaskFamily.STATE_PROPAGATION, DifficultyTier.HARD,
        ThemeStyle.IEEE_CLASSIC, DegradationProfile.CLEAN, LabelMode.SYMBOL_ONLY,
        seed=901, out_dir=tmp_path / "a", run_ocr=False,
    )
    p2 = build_single_task(
        "t1", TaskFamily.STATE_PROPAGATION, DifficultyTier.HARD,
        ThemeStyle.IEEE_CLASSIC, DegradationProfile.CLEAN, LabelMode.SYMBOL_ONLY,
        seed=901, out_dir=tmp_path / "b", run_ocr=False,
    )
    assert p1.answer == p2.answer
    assert p1.question == p2.question
    assert p1.solver_proof.proof_steps == p2.solver_proof.proof_steps

def test_all_task_families_generate_render_and_validate(tmp_path: Path) -> None:
    for idx, fam in enumerate(TaskFamily):
        for diff in (DifficultyTier.EASY, DifficultyTier.MEDIUM, DifficultyTier.HARD):
            pkg = build_single_task(
                f"test_{fam.value}_{diff.value}",
                fam,
                diff,
                ThemeStyle.IEEE_CLASSIC,
                DegradationProfile.CLEAN,
                LabelMode.SYMBOL_ONLY,
                seed=500 + idx * 13 + len(diff.value),
                out_dir=tmp_path,
                run_ocr=True,
            )
            assert Path(pkg.image_path).exists()
            assert pkg.quality_audit is not None
            assert pkg.quality_audit.passed, f"Quality gate failed for {fam}/{diff}: {pkg.quality_audit.notes}"
            assert pkg.quality_audit.bbox_collisions == 0

def test_exact_resistance_series_parallel_solver() -> None:
    tree = {
        "type": "series",
        "children": [
            {"type": "resistor", "id": "R1", "ohm": 40},
            {
                "type": "parallel",
                "children": [
                    {"type": "resistor", "id": "R2", "ohm": 60, "switch": "SW1"},
                    {"type": "resistor", "id": "R3", "ohm": 60},
                ],
            },
        ],
    }
    req_closed, _ = eval_resistance_tree(tree, {"SW1": True})
    assert req_closed == 70

    req_open, _ = eval_resistance_tree(tree, {"SW1": False})
    assert req_open == 100

def test_invariance_transforms_preserve_ground_truth(tmp_path: Path) -> None:
    anchor = build_single_task(
        "anc", TaskFamily.BRIDGE_VS_JUNCTION, DifficultyTier.HARD,
        ThemeStyle.IEEE_CLASSIC, DegradationProfile.CLEAN, LabelMode.SYMBOL_ONLY,
        seed=888, out_dir=tmp_path, run_ocr=False,
    )
    noisy = build_single_task(
        "deg", TaskFamily.BRIDGE_VS_JUNCTION, DifficultyTier.HARD,
        ThemeStyle.KICAD_BLUEPRINT, DegradationProfile.MOBILE_PHOTO, LabelMode.ANNOTATED,
        seed=888, out_dir=tmp_path, run_ocr=False,
    )
    assert anchor.answer == noisy.answer
    assert Path(noisy.image_path).exists()

def test_answer_normalizer_handles_real_vlm_formats() -> None:
    assert answers_match(normalize_answer("Looking at U1... FINAL ANSWER: ON", "binary"), "ON", "binary")
    assert answers_match(normalize_answer(r"The final answer is $\boxed{ON}$.", "binary"), "ON", "binary")
    assert answers_match(normalize_answer("70 ohms", "numeric"), "70 Ohm", "numeric")
    assert answers_match(normalize_answer("109.29 Ohm.", "numeric"), "109.29 Ohm", "numeric")
    assert answers_match(normalize_answer("55.8 mA", "numeric"), "55.81 mA", "numeric")
    assert not answers_match(normalize_answer("171.82 Ohm", "numeric"), "180 Ohm", "numeric")
    assert not answers_match(normalize_answer("200 Ohm", "numeric"), "200 mA", "numeric")
    assert answers_match(normalize_answer(r"$\boxed{180 \text{ Ohm}}$", "numeric"), "180 Ohm", "numeric")
    assert answers_match(normalize_answer(r"$\boxed{200 \text{ mA}}$", "numeric"), "200 mA", "numeric")
    assert answers_match(normalize_answer("ANSWER: L1=ON, L2=OFF", "mcq"), "L1=ON, L2=OFF", "mcq")
    assert answers_match(normalize_answer("ANSWER: L3, L1", "mcq"), "L1, L3", "mcq")
    assert answers_match(normalize_answer("Therefore option C is broken. ANSWER: C", "mcq"), "C", "mcq")
    assert answers_match(normalize_answer("ON -> OFF", "mcq"), "ON -> OFF", "mcq")

def test_whole_system_multi_domain_variants(tmp_path: Path) -> None:
    for vseed in (710, 711, 712):
        pkg = build_single_task(
            f"ws_{vseed}",
            TaskFamily.WHOLE_SYSTEM,
            DifficultyTier.HARD,
            ThemeStyle.IEEE_CLASSIC,
            DegradationProfile.CLEAN,
            LabelMode.SYMBOL_ONLY,
            seed=vseed,
            out_dir=tmp_path,
            run_ocr=True,
        )
        assert pkg.quality_audit is not None
        assert pkg.quality_audit.passed, f"Whole-system quality failure ({vseed}): {pkg.quality_audit.notes}"
        assert pkg.quality_audit.bbox_collisions == 0

def test_full_mutation_kill_suite_passes_100_percent() -> None:
    rep = run_mutation_suite()
    assert rep["total_mutants"] == 12
    assert rep["mutants_killed"] == 12
    assert rep["mutation_score"] == 1.0

def test_end_to_end_pipeline_validation_and_baselines(tmp_path: Path) -> None:
    tasks = generate_benchmark_dataset(
        tmp_path / "ds", count=12, base_seed=7, run_ocr=True, include_invariance_pairs=True
    )
    assert len(tasks) > 12
    val_rep = validate_dataset(tasks, run_ocr=True)
    assert val_rep["pass_rate"] == 1.0
    assert val_rep["invariance_pairs_checked"] > 0
    assert val_rep["invariance_pairs_consistent"] == val_rep["invariance_pairs_checked"]

    ds_jsonl = tmp_path / "ds" / "dataset.jsonl"
    oracle_rep = evaluate_dataset(ds_jsonl, provider="oracle_solver")
    assert oracle_rep["overall_accuracy"] == 1.0

    blind_rep = evaluate_dataset(ds_jsonl, provider="blind_random")
    assert 0.0 <= blind_rep["overall_accuracy"] < 0.75

    ocr_rep = evaluate_dataset(ds_jsonl, provider="ocr_heuristic")
    assert 0.0 <= ocr_rep["overall_accuracy"] < 0.75

def test_custom_netlist_compiler_and_exporters(tmp_path: Path) -> None:
    import zipfile
    from schemforge.exporters import create_batch_archive, export_huggingface_imagefolder, export_openai_evals_jsonl
    from schemforge.ingest import CustomCircuitInput, compile_custom_netlist

    payload = CustomCircuitInput.model_validate_json(
        (Path(__file__).resolve().parents[1] / "examples" / "safety_interlock_netlist.json").read_text()
    )
    pkg = compile_custom_netlist(payload, out_dir=tmp_path / "custom", run_ocr=True)
    assert pkg.answer == "ON"
    assert pkg.quality_audit is not None and pkg.quality_audit.passed

    tasks = generate_benchmark_dataset(tmp_path / "par_ds", count=6, base_seed=31, workers=2, run_ocr=False)
    assert len(tasks) > 6
    hf_res = export_huggingface_imagefolder(tmp_path / "par_ds" / "dataset.jsonl", tmp_path / "hf")
    assert hf_res["count"] == len(tasks)
    assert (tmp_path / "hf" / "metadata.jsonl").exists()
    oai_res = export_openai_evals_jsonl(tmp_path / "par_ds" / "dataset.jsonl", tmp_path / "oai.jsonl")
    assert oai_res["count"] == len(tasks)
    zip_p = create_batch_archive(tmp_path / "par_ds", tmp_path / "bundle.zip")
    assert zip_p.exists() and zip_p.stat().st_size > 1000
    with zipfile.ZipFile(zip_p, "r") as zf:
        names = set(zf.namelist())
        assert "OPEN_ME_QUIZ_BOOKLET.html" in names
        assert "questions_and_answers.csv" in names
        assert "README_WHAT_IS_INSIDE.txt" in names

def test_production_fastapi_endpoints() -> None:
    from fastapi.testclient import TestClient
    from schemforge.server import app

    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/api/overview").status_code == 200
    net_payload = (Path(__file__).resolve().parents[1] / "examples" / "safety_interlock_netlist.json").read_text()
    resp = client.post("/api/from-netlist", content=net_payload, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["answer"] == "ON"

    dsl_resp = client.post(
        "/api/from-netlist/dsl",
        json={"text": "VCC(12V) -> SW1(CLOSED) -> U1(AND) -> L1\nVCC -> SW2(CLOSED) -> U1", "title": "DSL TEST"},
    )
    assert dsl_resp.status_code == 200
    assert dsl_resp.json()["answer"] == "ON"

    page_resp = client.get("/api/tasks?batch_id=default&offset=0&limit=5")
    assert page_resp.status_code == 200
    assert len(page_resp.json()) == 5
    assert int(page_resp.headers["X-Total-Count"]) >= 12

    batches_resp = client.get("/api/batches")
    assert batches_resp.status_code == 200
    batch_items = batches_resp.json()
    batch_ids = {b["batch_id"] for b in batch_items}
    assert {"default", "starter_easy", "starter_medium", "starter_hard"}.issubset(batch_ids)
    assert all("summary" in b and "topic_label" in b and "level_label" in b for b in batch_items)
    hard_tasks = client.get("/api/tasks?batch_id=starter_hard&offset=0&limit=5")
    assert hard_tasks.status_code == 200 and len(hard_tasks.json()) == 5
    assert all(t["difficulty"] == "hard" for t in hard_tasks.json())

    search_resp = client.get("/api/tasks?batch_id=default&q=Ohm")
    assert search_resp.status_code == 200
    assert len(search_resp.json()) >= 1
    assert all("ohm" in (t["question"] + " " + t["answer"]).lower() for t in search_resp.json())

    st_resp = client.get("/api/providers/status")
    assert st_resp.status_code == 200
    st = st_resp.json()
    assert "gemini" in st and "anthropic" in st and "openai" in st and "ollama" in st and "custom" in st
    assert all(set(v.keys()) == {"label", "env_var", "free_tier", "default_model", "configured"} for v in st.values())

    import os as _os
    if not _os.environ.get("ANTHROPIC_API_KEY"):
        miss_resp = client.post("/api/evaluate-jobs", json={"batch_id": "default", "provider": "anthropic", "providers": ["anthropic"], "limit": 2})
        assert miss_resp.status_code == 400
        assert "ANTHROPIC_API_KEY" in miss_resp.json()["detail"]

    import time as _time
    job_resp = client.post(
        "/api/evaluate-jobs",
        json={"batch_id": "default", "provider": "blind_random", "providers": ["blind_random", "oracle_solver"], "limit": 4, "persist": True},
    )
    assert job_resp.status_code == 200
    jid = job_resp.json()["job_id"]
    snap = None
    for _ in range(50):
        poll = client.get(f"/api/evaluate-jobs/{jid}")
        assert poll.status_code == 200
        snap = poll.json()
        if snap["status"] == "completed":
            break
        _time.sleep(0.05)
    assert snap is not None and snap["status"] == "completed"
    assert snap["completed"] == 8 and snap["total"] == 8
    assert len(snap["reports"]) == 2
    assert snap["report"]["total_tasks"] == 4

    ov_after = client.get("/api/overview").json()
    assert any(e.get("_is_live") and e.get("total_tasks") == 4 for e in ov_after["evaluations"])
    rst = client.post("/api/evaluate-reset")
    assert rst.status_code == 200 and rst.json()["removed"] >= 1

def test_custom_dsl_and_scalable_lazy_1000_batch(tmp_path: Path) -> None:
    from schemforge.ingest import generate_custom_variations, parse_netlist_text

    tasks_1k = generate_benchmark_dataset(
        tmp_path / "scale_1k",
        count=1000,
        base_seed=99,
        workers=2,
        lazy_render=True,
        audit_sample_size=14,
        run_ocr=False,
    )
    assert len(tasks_1k) > 1000
    val_rep = validate_dataset(tasks_1k, run_ocr=False, dataset_root=tmp_path / "scale_1k")
    assert val_rep["pass_rate"] == 1.0

    parsed = parse_netlist_text("VCC1(24V) -> SW1(CLOSED) -> U1(NAND) -> L1\nVCC1 -> SW2(OPEN) -> U_INV(NOT) -> U1")
    custom_500 = generate_custom_variations(parsed, tmp_path / "cust_500", count=500, base_seed=200, lazy_render=True, run_ocr=False)
    assert len(custom_500) == 500
    c_val = validate_dataset(custom_500, run_ocr=False, dataset_root=tmp_path / "cust_500")
    assert c_val["pass_rate"] == 1.0

    tiny = parse_netlist_text("VCC1(12V) -> SW1(CLOSED) -> L1")
    est = __import__("schemforge.ingest", fromlist=["estimate_custom_combinations"]).estimate_custom_combinations(tiny, requested_count=5000)
    assert est["will_cap"] is True
    assert est["unique_with_visuals"] < 500
    tiny_gen = generate_custom_variations(tiny, tmp_path / "cust_tiny", count=5000, base_seed=77, lazy_render=True, run_ocr=False)
    assert len(tiny_gen) <= est["unique_with_visuals"]
    sigs = {
        (t.question, t.answer, t.theme.value, t.degradation.value, t.label_mode.value)
        for t in tiny_gen
    }
    assert len(sigs) == len(tiny_gen)
