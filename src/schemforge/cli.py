"""Command-line entry point for SchemForge Track 2 Visual Task Factory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from schemforge.analytics import generate_eval_charts
from schemforge.config import load_settings
from schemforge.evaluator import evaluate_dataset
from schemforge.exporters import (
    create_batch_archive,
    export_huggingface_imagefolder,
    export_openai_evals_jsonl,
)
from schemforge.ingest import CustomCircuitInput, compile_custom_netlist, generate_custom_variations, parse_netlist_text
from schemforge.mutation import run_mutation_suite
from schemforge.netlist import TaskPackage
from schemforge.pipeline import generate_benchmark_dataset
from schemforge.validator import validate_dataset


def main() -> None:
    cfg = load_settings()
    parser = argparse.ArgumentParser(
        prog="schemforge",
        description="SchemForge: Production Visual Task Factory for Engineering Schematic Evaluation",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate", help="Generate a seeded multi-family synthetic dataset")
    p_gen.add_argument("--count", type=int, default=36)
    p_gen.add_argument("--seed", type=int, default=42)
    p_gen.add_argument("--workers", type=int, default=cfg.default_workers)
    p_gen.add_argument("--out", type=str, default="artifacts/sample_dataset")
    p_gen.add_argument("--no-ocr", action="store_true")
    p_gen.add_argument("--emit-svg", action="store_true")
    p_gen.add_argument("--lazy-render", action="store_true", help="High-throughput spec+proof streaming with sampled PNG verification (ideal for 10,000+)")

    p_val = sub.add_parser("validate", help="Run independent 5-gate validation checks over dataset")
    p_val.add_argument("--dataset", type=str, default="artifacts/sample_dataset/dataset.jsonl")
    p_val.add_argument("--out", type=str, default="artifacts/validation_report.json")
    p_val.add_argument("--no-ocr", action="store_true")

    p_mut = sub.add_parser("mutate-test", help="Run solver/validator mutation kill suite")
    p_mut.add_argument("--out", type=str, default="artifacts/mutation_report.json")

    p_eval = sub.add_parser("evaluate", help="Evaluate baseline or frontier VLM on dataset")
    p_eval.add_argument("--dataset", type=str, default="artifacts/sample_dataset/dataset.jsonl")
    p_eval.add_argument(
        "--provider",
        type=str,
        default="ocr_heuristic",
        choices=["blind_random", "ocr_heuristic", "oracle_solver", "gemini", "openai", "anthropic", "openrouter", "ollama"],
    )
    p_eval.add_argument("--model", type=str, default=None)
    p_eval.add_argument("--limit", type=int, default=None)
    p_eval.add_argument("--delay", type=float, default=0.0, help="Optional pacing delay in seconds between tasks")
    p_eval.add_argument("--out", type=str, default=None)

    p_exp = sub.add_parser("export", help="Export dataset into Hugging Face ImageFolder, OpenAI Evals, or ZIP")
    p_exp.add_argument("--dataset", type=str, default="artifacts/sample_dataset/dataset.jsonl")
    p_exp.add_argument("--format", type=str, default="huggingface", choices=["huggingface", "openai-evals", "zip"])
    p_exp.add_argument("--out", type=str, required=True)
    p_exp.add_argument("--embed-base64", action="store_true")

    p_net = sub.add_parser("from-netlist", help="Compile a user JSON or DSL netlist into 1..25,000 audited VQA tasks")
    p_net.add_argument("--input", type=str, required=True)
    p_net.add_argument("--out", type=str, default="artifacts/custom_tasks")
    p_net.add_argument("--count", type=int, default=1, help="Number of structural/optical variations to synthesize")
    p_net.add_argument("--seed", type=int, default=1001)
    p_net.add_argument("--lazy-render", action="store_true")
    p_net.add_argument("--no-ocr", action="store_true")

    p_charts = sub.add_parser("charts", help="Render diagnostic analytics PNG figures from JSON reports")
    p_charts.add_argument("--reports", nargs="*", default=[])
    p_charts.add_argument("--validation", type=str, default="artifacts/validation_report.json")
    p_charts.add_argument("--mutation", type=str, default="artifacts/mutation_report.json")
    p_charts.add_argument("--out", type=str, default="artifacts/charts")

    p_srv = sub.add_parser("serve", help="Launch Interactive Production Web Inspector Studio")
    p_srv.add_argument("--host", type=str, default=cfg.host)
    p_srv.add_argument("--port", type=int, default=cfg.port)

    args = parser.parse_args()

    if args.cmd == "generate":
        tasks = generate_benchmark_dataset(
            out_dir=args.out,
            count=args.count,
            base_seed=args.seed,
            workers=max(1, args.workers),
            run_ocr=not args.no_ocr,
            emit_svg=args.emit_svg,
            lazy_render=args.lazy_render,
        )
        passed = sum(1 for t in tasks if t.quality_audit and t.quality_audit.passed)
        print(f"Generated {len(tasks)} tasks in {args.out} ({passed}/{len(tasks)} passed quality gates, workers={args.workers}, lazy={args.lazy_render}).")

    elif args.cmd == "validate":
        ds_p = Path(args.dataset).resolve()
        lines = [ln for ln in ds_p.read_text().splitlines() if ln.strip()]
        tasks = [TaskPackage.model_validate_json(ln) for ln in lines]
        rep = validate_dataset(tasks, run_ocr=not args.no_ocr, dataset_root=ds_p.parent)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(rep, indent=2))
        print(json.dumps({k: v for k, v in rep.items() if k != "answer_distribution_by_family"}, indent=2))

    elif args.cmd == "mutate-test":
        rep = run_mutation_suite()
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(rep, indent=2))
        print(f"Mutation Suite: {rep['mutants_killed']}/{rep['total_mutants']} mutants killed ({rep['mutation_score']*100:.1f}%).")

    elif args.cmd == "evaluate":
        out_file = args.out or f"artifacts/eval_{args.provider}.json"
        rep = evaluate_dataset(
            dataset_path=args.dataset,
            provider=args.provider,
            model=args.model,
            limit=args.limit,
            out_report_path=out_file,
            delay_s=args.delay,
        )
        print(f"[{rep['model_label']}] Accuracy: {rep['overall_accuracy']*100:.2f}% over {rep['total_tasks']} tasks -> {out_file}")
        print(json.dumps(rep["by_family"], indent=2))

    elif args.cmd == "export":
        if args.format == "huggingface":
            res = export_huggingface_imagefolder(args.dataset, args.out)
            print(json.dumps(res, indent=2))
        elif args.format == "openai-evals":
            res = export_openai_evals_jsonl(args.dataset, args.out, embed_base64=args.embed_base64)
            print(json.dumps(res, indent=2))
        elif args.format == "zip":
            zp = create_batch_archive(Path(args.dataset).parent, args.out)
            print(json.dumps({"format": "zip", "archive": str(zp)}, indent=2))

    elif args.cmd == "from-netlist":
        payload = parse_netlist_text(Path(args.input).read_text())
        if args.count > 1:
            tasks = generate_custom_variations(
                payload,
                out_dir=args.out,
                count=args.count,
                base_seed=args.seed,
                lazy_render=True if args.lazy_render else None,
                run_ocr=not args.no_ocr,
            )
            print(json.dumps({
                "mode": "custom_batch",
                "title": payload.title,
                "count": len(tasks),
                "out_dir": args.out,
                "sample_answer": tasks[0].answer if tasks else None,
            }, indent=2))
        else:
            pkg = compile_custom_netlist(payload, out_dir=args.out, run_ocr=not args.no_ocr)
            print(json.dumps({
                "task_id": pkg.task_id,
                "answer": pkg.answer,
                "image_path": pkg.image_path,
                "passed": pkg.quality_audit.passed if pkg.quality_audit else True,
                "proof_steps": pkg.solver_proof.proof_steps,
            }, indent=2))

    elif args.cmd == "charts":
        eval_reps = [json.loads(Path(p).read_text()) for p in args.reports if Path(p).exists()]
        val_rep = json.loads(Path(args.validation).read_text()) if Path(args.validation).exists() else None
        mut_rep = json.loads(Path(args.mutation).read_text()) if Path(args.mutation).exists() else None
        out_files = generate_eval_charts(eval_reps, val_rep, mut_rep, args.out)
        print("Generated charts:", out_files)

    elif args.cmd == "serve":
        import uvicorn
        from schemforge.server import app

        uvicorn.run(app, host=args.host, port=args.port, log_level=cfg.log_level.lower())


if __name__ == "__main__":
    main()
