"""Dataset Export Adapters for Industry Evaluation Standards & Archives.

Exports SchemForge audited datasets into:
  1. Hugging Face ImageFolder (`metadata.jsonl` + `README.md` Dataset Card)
  2. OpenAI Evals / Multimodal Chat-Completions JSONL
  3. Portable self-contained ZIP distribution archives
"""

from __future__ import annotations

import base64
import csv
import html
import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from schemforge.netlist import TaskPackage

def _load_packages(dataset_jsonl: Path) -> list[TaskPackage]:
    return [
        TaskPackage.model_validate_json(ln)
        for ln in dataset_jsonl.read_text().splitlines()
        if ln.strip()
    ]

def export_huggingface_imagefolder(
    dataset_jsonl: str | Path, out_dir: str | Path
) -> dict:
    """Export dataset cleanly in Hugging Face `datasets` ImageFolder format."""
    ds_path = Path(dataset_jsonl).resolve()
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    img_out = out_path / "data"
    img_out.mkdir(parents=True, exist_ok=True)

    tasks = _load_packages(ds_path)
    meta_rows: list[str] = []

    for t in tasks:
        src_img = Path(t.image_path)
        if not src_img.is_absolute() or not src_img.exists():
            src_img = (ds_path.parent / "images" / src_img.name).resolve()
        dst_rel = f"data/{src_img.name}"
        if src_img.exists():
            shutil.copy2(src_img, img_out / src_img.name)

        row = {
            "file_name": dst_rel,
            "task_id": t.task_id,
            "seed": t.seed,
            "family": t.family.value,
            "difficulty": t.difficulty.value,
            "theme": t.theme.value,
            "degradation": t.degradation.value,
            "label_mode": t.label_mode.value,
            "question": t.question,
            "answer": t.answer,
            "answer_type": t.answer_type,
            "choices": t.choices,
            "proof_steps": t.solver_proof.proof_steps,
            "mutation_description": t.mutation_description or "",
            "quality_passed": bool(t.quality_audit.passed) if t.quality_audit else True,
        }
        meta_rows.append(json.dumps(row))

    (out_path / "metadata.jsonl").write_text("\n".join(meta_rows) + "\n")
    card = f"""---
task_categories:
- visual-question-answering
language:
- en
tags:
- engineering-schematics
- multimodal-evaluation
- synthetic-vqa
- schemforge
size_categories:
- n<1K
---

# SchemForge Synthetic Visual Reasoning Benchmark

Auto-exported benchmark containing **{len(tasks)}** formally solved and quality-audited IEEE/IEC electrical schematic visual reasoning tasks across 7 task families (`state_propagation`, `bridge_vs_junction`, `equivalent_resistance`, `fault_diagnosis`, `counterfactual_pair`, `component_audit`, `whole_system`).

Load locally via Hugging Face `datasets`:
```python
from datasets import load_dataset
ds = load_dataset("imagefolder", data_dir="{out_path.name}")
```
"""
    (out_path / "README.md").write_text(card)
    return {"format": "huggingface_imagefolder", "count": len(tasks), "out_dir": str(out_path)}

def export_openai_evals_jsonl(
    dataset_jsonl: str | Path,
    out_file: str | Path,
    embed_base64: bool = False,
) -> dict:
    """Export standard Multimodal Eval JSONL compatible with OpenAI Evals / vLLM."""
    ds_path = Path(dataset_jsonl).resolve()
    out_path = Path(out_file).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tasks = _load_packages(ds_path)
    lines: list[str] = []

    for t in tasks:
        src_img = Path(t.image_path)
        if not src_img.is_absolute() or not src_img.exists():
            src_img = (ds_path.parent / "images" / src_img.name).resolve()
        if embed_base64 and src_img.exists():
            b64 = base64.b64encode(src_img.read_bytes()).decode("ascii")
            img_ref = f"data:image/png;base64,{b64}"
        else:
            img_ref = f"images/{src_img.name}"

        prompt_txt = t.question
        if t.choices:
            prompt_txt += f"\nChoices: {', '.join(t.choices)}"

        record = {
            "id": t.task_id,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt_txt},
                        {"type": "input_image", "image_url": img_ref},
                    ],
                }
            ],
            "ideal": t.answer,
            "metadata": {
                "family": t.family.value,
                "difficulty": t.difficulty.value,
                "degradation": t.degradation.value,
                "label_mode": t.label_mode.value,
                "answer_type": t.answer_type,
            },
        }
        lines.append(json.dumps(record))

    out_path.write_text("\n".join(lines) + "\n")
    return {"format": "openai_evals_jsonl", "count": len(tasks), "out_file": str(out_path)}

_EXPORT_TOPIC_NAMES = {
    "state_propagation": "Switches & Logic Gates",
    "bridge_vs_junction": "Crossing Wires (Bridge vs Dot)",
    "equivalent_resistance": "Total Resistance (Ohms)",
    "fault_diagnosis": "Find the Broken Part",
    "counterfactual_pair": "Spot the Difference (A vs B)",
    "component_audit": "Count & Read Parts",
    "whole_system": "Full System (Power + Gates + Ohms)",
}

def export_human_quiz_files(
    dataset_jsonl: str | Path,
    batch_dir: str | Path,
    max_html_cards: int = 200,
) -> None:
    """Write human-friendly CSV, printable offline HTML Quiz Booklet, and README inside batch_dir."""
    ds_path = Path(dataset_jsonl).resolve()
    root_dir = Path(batch_dir).resolve()
    tasks = _load_packages(ds_path)

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow([
        "Question #",
        "Question ID",
        "Topic",
        "Difficulty",
        "Paper Style",
        "Question",
        "Correct Answer",
        "Choices",
        "Step-by-Step Solution",
        "Image File",
    ])
    for idx, t in enumerate(tasks, start=1):
        rel_img = f"images/{Path(t.image_path).name}"
        has_img = (root_dir / rel_img).exists()
        steps_txt = " | ".join(t.solver_proof.proof_steps) if t.solver_proof else ""
        writer.writerow([
            idx,
            t.task_id,
            _EXPORT_TOPIC_NAMES.get(t.family.value, t.family.value),
            t.difficulty.value.title(),
            t.theme.value,
            t.question,
            t.answer,
            ", ".join(t.choices) if t.choices else "",
            steps_txt,
            rel_img if has_img else "(on-demand in web viewer)",
        ])
    (root_dir / "questions_and_answers.csv").write_text("\ufeff" + csv_buf.getvalue(), encoding="utf-8")

    mat_count = sum(1 for t in tasks if (root_dir / "images" / Path(t.image_path).name).exists())
    readme = (
        f"SchemForge Question Set Export ({len(tasks)} Questions)\n"
        + "=" * 54
        + "\n\n"
        "What is inside this ZIP folder:\n"
        "  1. OPEN_ME_QUIZ_BOOKLET.html  -- Double-click to open an offline quiz & answer key in Chrome/Safari.\n"
        "                                   Includes interactive Show/Hide Answers and Print/Save as PDF.\n"
        "  2. questions_and_answers.csv  -- Open in Excel, Numbers, or Google Sheets for all questions & solutions.\n"
        f"  3. images/                    -- Circuit diagram PNG images ({mat_count} pre-rendered in this archive).\n"
        "  4. dataset.jsonl / exports/   -- Standard AI benchmark formats (Hugging Face ImageFolder & OpenAI Evals).\n"
    )
    (root_dir / "README_WHAT_IS_INSIDE.txt").write_text(readme, encoding="utf-8")

    cards_html: list[str] = []
    shown = 0
    for idx, t in enumerate(tasks, start=1):
        img_name = Path(t.image_path).name
        rel_img = f"images/{img_name}"
        if not (root_dir / rel_img).exists():
            continue
        if shown >= max_html_cards:
            break
        shown += 1
        topic = html.escape(_EXPORT_TOPIC_NAMES.get(t.family.value, t.family.value))
        diff = html.escape(t.difficulty.value.title())
        q_txt = html.escape(t.question)
        ans_txt = html.escape(t.answer)
        steps_li = "".join(f"<li>{html.escape(s)}</li>" for s in (t.solver_proof.proof_steps if t.solver_proof else []))
        choices_html = ""
        if t.choices:
            choices_html = '<div class="choices">' + "".join(
                f'<span class="choice">{html.escape(c)}</span>' for c in t.choices
            ) + "</div>"
        cards_html.append(
            f'<div class="card">'
            f'<div class="card-head"><b>Question #{idx}</b> &middot; <span>{topic}</span> &middot; <span>{diff}</span></div>'
            f'<img src="{html.escape(rel_img)}" alt="{html.escape(t.task_id)}" />'
            f'<p class="q">{q_txt}</p>'
            f'{choices_html}'
            f'<details class="ans"><summary>Show Verified Answer &amp; Steps</summary>'
            f'<div class="ans-box"><b>Answer: {ans_txt}</b><ol>{steps_li}</ol></div>'
            f'</details></div>'
        )

    note_banner = ""
    if len(tasks) > shown:
        note_banner = (
            f'<div class="note">Showing {shown} pre-rendered visual circuit sheets below out of {len(tasks)} total questions. '
            f'Every single question and answer (all {len(tasks)}) is included in <code>questions_and_answers.csv</code>.</div>'
        )

    booklet_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SchemForge Printable Quiz Booklet ({len(tasks)} Questions)</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 960px; margin: 24px auto; padding: 0 18px; color: #1c1917; background: #f8f6f0; }}
  .top {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; border-bottom: 2px solid #1c1917; padding-bottom: 12px; margin-bottom: 18px; }}
  button {{ padding: 8px 14px; font-weight: 600; cursor: pointer; border: 1.5px solid #1c1917; background: #fff; }}
  button.primary {{ background: #9a3412; color: #fff; }}
  .note {{ background: #fef3c7; border: 1.5px solid #1c1917; padding: 10px 14px; margin-bottom: 18px; font-size: 13.5px; }}
  .card {{ background: #fff; border: 1.5px solid #1c1917; padding: 16px; margin-bottom: 18px; page-break-inside: avoid; }}
  .card-head {{ font-size: 13px; color: #57534e; margin-bottom: 10px; border-bottom: 1px dashed #d6ceb8; padding-bottom: 6px; }}
  img {{ max-width: 100%; height: auto; border: 1px solid #d6ceb8; display: block; margin: 0 auto 12px auto; }}
  .q {{ font-size: 15px; line-height: 1.5; margin: 8px 0; }}
  .choices {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px 0; }}
  .choice {{ background: #eee8d8; border: 1px solid #1c1917; padding: 4px 10px; font-size: 13px; font-family: monospace; }}
  details.ans summary {{ cursor: pointer; font-weight: 700; color: #9a3412; margin-top: 8px; }}
  .ans-box {{ background: #dcfce7; border: 1px solid #15803d; padding: 10px 14px; margin-top: 8px; font-size: 13.5px; }}
  @media print {{ .no-print {{ display: none; }} body {{ background: #fff; }} }}
</style>
</head>
<body>
<div class="top">
  <div>
    <h1 style="margin:0; font-size:22px;">Circuit Quiz Booklet ({len(tasks)} Questions)</h1>
    <div style="font-size:13px; color:#57534e;">Verified answers &amp; step-by-step solutions included</div>
  </div>
  <div class="no-print" style="display:flex; gap:8px;">
    <button onclick="document.querySelectorAll('details.ans').forEach(d=>d.open=true)">Show All Answers</button>
    <button onclick="document.querySelectorAll('details.ans').forEach(d=>d.open=false)">Hide All Answers</button>
    <button class="primary" onclick="window.print()">Print / Save PDF</button>
  </div>
</div>
{note_banner}
{"".join(cards_html) if cards_html else '<div class="note">Open <code>questions_and_answers.csv</code> in Excel or use the web viewer to render images on demand.</div>'}
</body>
</html>
"""
    (root_dir / "OPEN_ME_QUIZ_BOOKLET.html").write_text(booklet_html, encoding="utf-8")

def create_batch_archive(
    batch_dir: str | Path,
    out_zip_path: Optional[str | Path] = None,
) -> Path:
    """Create a self-contained portable ZIP bundle of a dataset directory."""
    src_dir = Path(batch_dir).resolve()
    zip_path = Path(out_zip_path).resolve() if out_zip_path else src_dir.with_suffix(".zip")
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    ds_jsonl = src_dir / "dataset.jsonl"
    if ds_jsonl.exists():
        export_human_quiz_files(ds_jsonl, src_dir)
        hf_dir = src_dir / "exports" / "huggingface"
        if not hf_dir.exists():
            export_huggingface_imagefolder(ds_jsonl, hf_dir)
        oai_file = src_dir / "exports" / "openai_evals.jsonl"
        if not oai_file.exists():
            export_openai_evals_jsonl(ds_jsonl, oai_file, embed_base64=False)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src_dir.rglob("*")):
            if p.is_file() and p != zip_path:
                zf.write(p, arcname=str(p.relative_to(src_dir)))
    return zip_path
