"""Multimodal Evaluation Framework & Deterministic Local Baselines.

Supports:
  1. Blind Chance / Question-Only Baseline (proves zero text-only leakage)
  2. Tesseract OCR + Regex Heuristic Baseline (quantifies why raw OCR fails
     without visual topology, bridge-vs-dot, and IEEE symbol reasoning)
  3. Pluggable Frontier & Local VLM Providers:
     - gemini (Google GenAI SDK)
     - openai (OpenAI SDK)
     - anthropic (Anthropic SDK)
     - openrouter (OpenAI-compatible endpoint)
     - ollama (local VLM server via HTTP)
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel

from schemforge.netlist import TaskPackage
from schemforge.validator import run_tesseract_ocr

class PredictionRecord(BaseModel):
    task_id: str
    family: str
    difficulty: str
    theme: str
    degradation: str
    label_mode: str
    ground_truth: str
    raw_response: str
    normalized_prediction: str
    correct: bool
    latency_ms: float
    invariance_partner_id: Optional[str] = None
    error: Optional[str] = None

def normalize_answer(raw: str, answer_type: str) -> str:
    """Canonicalize model outputs cleanly (including LaTeX \\boxed{...} wrappers)."""
    if not raw:
        return ""
    txt = raw.strip()
    m_box = re.search(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}", txt)
    if m_box:
        txt = m_box.group(1).strip()
    else:
        m_ans = re.search(r"(?:FINAL\s*ANSWER|ANSWER)\s*[:\-]\s*([^\n]+)", txt, flags=re.IGNORECASE)
        if m_ans:
            txt = m_ans.group(1).strip()
        else:
            lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            if lines:
                txt = lines[-1]

    cleaned = re.sub(r"[`*\"'()$\\]", "", txt).strip().rstrip(".")
    upper = cleaned.upper()

    if answer_type == "binary":
        if "ON" in upper.split() and "OFF" not in upper.split():
            return "ON"
        if "OFF" in upper.split() and "ON" not in upper.split():
            return "OFF"
        if "YES" in upper.split() and "NO" not in upper.split():
            return "YES"
        if "NO" in upper.split() and "YES" not in upper.split():
            return "NO"
        for tok in ("ON", "OFF", "YES", "NO"):
            if upper.startswith(tok):
                return tok
        return upper

    if answer_type == "mcq":
        m_vec = re.search(r"L1\s*=\s*(ON|OFF)\s*[,; ]+\s*L2\s*=\s*(ON|OFF)", upper)
        if m_vec:
            return f"L1={m_vec.group(1)}, L2={m_vec.group(2)}"
        m_trans = re.search(r"\b(ON|OFF)\s*(?:->|TO)\s*(ON|OFF)\b", upper)
        if m_trans:
            return f"{m_trans.group(1)} -> {m_trans.group(2)}"
        if not re.search(r"\b[ABCD]\s*[:\.\)]\s*", upper):
            lamps = sorted(set(re.findall(r"\b(L[1-4])\b", upper)))
            if lamps:
                return ", ".join(lamps)
            if upper.strip() in ("NONE", "NO LAMPS", "NONE OF THEM"):
                return "NONE"
        m_opt = re.search(r"\b([ABCD])\b", upper)
        if m_opt:
            return m_opt.group(1)
        return upper

    if answer_type == "numeric":
        if "OPEN" in upper:
            return "OPEN"
        m_num = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:MA|MILLIAMP|MILLIAMPS|OHM|OHMS|Ω)?", upper)
        if m_num:
            num_str = m_num.group(1)
            val = float(num_str)
            num_norm = str(int(val)) if val.is_integer() else f"{val:g}"
            word_tokens = set(re.findall(r"[A-Z]+", upper))
            if "MA" in word_tokens or "MILLIAMP" in upper:
                return f"{num_norm} mA"
            if "OHM" in upper or "Ω" in txt.upper():
                return f"{num_norm} Ohm"
            return num_norm
        return cleaned

    return cleaned

def answers_match(pred: str, gt: str, answer_type: str) -> bool:
    if answer_type == "numeric":
        p_u = pred.strip().upper()
        g_u = gt.strip().upper()
        if "MA" in g_u or "OHM" in g_u:
            unit = " MA" if "MA" in g_u else " OHM"
            if ("MA" in p_u and "OHM" in g_u) or ("OHM" in p_u and "MA" in g_u):
                return False
            p_raw = p_u.replace(" MA", "").replace(" OHM", "").strip()
            g_raw = g_u.replace(unit, "").strip()
            if p_raw == g_raw:
                return True
            try:
                p_f, g_f = float(p_raw), float(g_raw)
                return abs(p_f - g_f) <= max(0.05, 0.005 * abs(g_f))
            except ValueError:
                return False
        return p_u == g_u
    return pred.strip().upper() == gt.strip().upper()

def _baseline_blind_random(task: TaskPackage, seed_offset: int = 0) -> str:
    """Blind text-only baseline: has zero image input, samples uniformly over valid options."""
    rng = random.Random(task.seed + seed_offset)
    if task.choices:
        return rng.choice(task.choices)
    if task.answer_type == "numeric":
        if "mA" in task.answer:
            return f"{rng.choice([0, 150, 200, 300])} mA"
        if "Ohm" in task.answer:
            return f"{rng.choice([30, 50, 70, 90, 120])} Ohm"
        return str(rng.randint(1, 5))
    return rng.choice(["ON", "OFF"])

def _baseline_ocr_heuristic(task: TaskPackage) -> str:
    """Tesseract OCR + Regex heuristic baseline without visual spatial/symbol parsing.

    Reads OCR text tokens from pixels cleanly using Tesseract, then tries naive
    keyword & number heuristics. Intentionally demonstrates why OCR breaks on
    bridge hops, symbol-only blades/bubbles, and switched parallel paths.
    """
    tokens = run_tesseract_ocr(task.image_path)
    joined = " ".join(tokens)
    q = task.question.upper()

    if task.family.value == "component_audit":
        m_thresh = re.search(r">=\s*(\d+)", q)
        if m_thresh:
            thresh = int(m_thresh.group(1))
            nums = [int(x) for x in re.findall(r"\b(\d+)\b", joined)]
            res_vals = [n for n in nums if 20 <= n <= 1000]
            return str(sum(1 for n in res_vals if n >= thresh))
        if "INVERTING GATES" in q:
            hits = sum(1 for t in tokens if t in ("NOT", "NAND", "NOR"))
            return str(hits)
        if "CLOSED" in q:
            hits = sum(1 for t in tokens if t == "CLOSED")
            return str(hits)

    if task.family.value == "equivalent_resistance":
        if "MILLIAMPS" in q or "MA)" in q or " IN MA " in q:
            return "100 mA"
        nums = [int(x) for x in re.findall(r"\b(10|15|20|25|30|40|50|60|80|90|100|120|150|180|200|240)\b", joined)]
        if nums:
            return f"{sum(nums[:4])} Ohm"
        return "60 Ohm"

    if task.family.value == "whole_system":
        if task.choices:
            return task.choices[0]
        if "MA" in q:
            return "200 mA"
        return "ON"

    if task.family.value == "fault_diagnosis":
        if "0V" in joined or "LOW" in joined:
            return "B"
        return "A"

    if task.family.value == "counterfactual_pair":
        if task.choices and "ON -> OFF" in task.choices:
            return "ON -> ON"
        return "NO"

    closed_cnt = tokens.count("CLOSED")
    open_cnt = tokens.count("OPEN")
    if task.choices == ["YES", "NO"]:
        return "YES" if closed_cnt >= open_cnt else "NO"
    if task.choices and len(task.choices) == 4:
        return task.choices[0]
    return "ON" if closed_cnt > open_cnt else "OFF"

def _encode_image_b64(image_path: str) -> str:
    return base64.b64encode(Path(image_path).read_bytes()).decode("ascii")

def _call_gemini(image_path: str, prompt: str, model: str, api_key: Optional[str] = None) -> str:
    from google import genai
    from google.genai import types

    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY or pass session API key to evaluate Gemini models.")
    client = genai.Client(api_key=key)
    img_bytes = Path(image_path).read_bytes()
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                    prompt,
                ],
            )
            return resp.text or ""
        except Exception as exc:
            msg = str(exc)
            if attempt < 2 and ("503" in msg or "429" in msg or "UNAVAILABLE" in msg):
                time.sleep(3.0 * (attempt + 1))
                continue
            raise
    return ""

def _call_openai_compat(
    image_path: str,
    prompt: str,
    model: str,
    base_url: Optional[str] = None,
    api_key_env: str = "OPENAI_API_KEY",
    api_key: Optional[str] = None,
) -> str:
    from openai import OpenAI

    key = api_key or os.environ.get(api_key_env)
    if not key:
        raise RuntimeError(f"Set {api_key_env} or pass session API key to evaluate {model}.")
    kwargs: dict[str, Any] = {"api_key": key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    b64 = _encode_image_b64(image_path)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.0,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
                    }
                ],
            )
            msg = resp.choices[0].message
            txt = msg.content or ""
            if not txt.strip():
                extra = getattr(msg, "model_extra", {}) or {}
                txt = extra.get("reasoning") or extra.get("reasoning_content") or ""
            return txt
        except Exception as exc:
            s = str(exc)
            if attempt < 2 and ("429" in s or "503" in s or "502" in s or "rate" in s.lower()):
                time.sleep(3.0 * (attempt + 1))
                continue
            raise
    return ""

def _call_anthropic(image_path: str, prompt: str, model: str, api_key: Optional[str] = None) -> str:
    import anthropic

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Set ANTHROPIC_API_KEY or pass session API key to evaluate Claude models.")
    client = anthropic.Anthropic(api_key=key)
    b64 = _encode_image_b64(image_path)
    resp = client.messages.create(
        model=model,
        max_tokens=512,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": b64},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return "".join(getattr(block, "text", "") for block in resp.content)

def _call_ollama(image_path: str, prompt: str, model: str) -> str:
    import httpx

    b64 = _encode_image_b64(image_path)
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    resp = httpx.post(
        f"{host}/api/chat",
        json={
            "model": model,
            "stream": False,
            "options": {"temperature": 0.0},
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "")

def build_eval_prompt(task: TaskPackage) -> str:
    suffix = " End your response with 'ANSWER: <your exact answer>'."
    if task.choices:
        opts = ", ".join(task.choices)
        return f"{task.question}\nValid options: [{opts}].{suffix}"
    return f"{task.question}{suffix}"

def _resolve_predictor(
    provider: str,
    model: Optional[str],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> tuple[str, Callable[[TaskPackage], str]]:
    p = provider.lower().strip()
    if p == "blind_random":
        return "blind_random", lambda t: _baseline_blind_random(t)
    if p == "ocr_heuristic":
        return "ocr_tesseract_heuristic", lambda t: _baseline_ocr_heuristic(t)
    if p == "oracle_solver":
        return "oracle_solver", lambda t: t.answer
    if p == "gemini":
        m = model or "gemini-3.1-flash-lite"
        return f"gemini:{m}", lambda t: _call_gemini(t.image_path, build_eval_prompt(t), m, api_key=api_key)
    if p == "groq":
        m = model or "meta-llama/llama-4-scout-17b-16e-instruct"
        return f"groq:{m}", lambda t: _call_openai_compat(
            t.image_path,
            build_eval_prompt(t),
            m,
            base_url="https://api.groq.com/openai/v1",
            api_key_env="GROQ_API_KEY",
            api_key=api_key,
        )
    if p == "mistral":
        m = model or "pixtral-12b-2409"
        return f"mistral:{m}", lambda t: _call_openai_compat(
            t.image_path,
            build_eval_prompt(t),
            m,
            base_url="https://api.mistral.ai/v1",
            api_key_env="MISTRAL_API_KEY",
            api_key=api_key,
        )
    if p == "huggingface":
        m = model or "Qwen/Qwen3-VL-8B-Instruct"
        return f"hf:{m}", lambda t: _call_openai_compat(
            t.image_path,
            build_eval_prompt(t),
            m,
            base_url="https://router.huggingface.co/v1",
            api_key_env="HF_TOKEN",
            api_key=api_key,
        )
    if p == "openai":
        m = model or "gpt-4o"
        return f"openai:{m}", lambda t: _call_openai_compat(t.image_path, build_eval_prompt(t), m, api_key=api_key)
    if p == "openrouter":
        m = model or "nvidia/nemotron-3.5-super-vl:free"
        return f"openrouter:{m}", lambda t: _call_openai_compat(
            t.image_path,
            build_eval_prompt(t),
            m,
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            api_key=api_key,
        )
    if p == "anthropic":
        m = model or "claude-sonnet-4-5"
        return f"anthropic:{m}", lambda t: _call_anthropic(t.image_path, build_eval_prompt(t), m, api_key=api_key)
    if p == "ollama":
        m = model or "qwen2.5vl:3b"
        return f"ollama:{m}", lambda t: _call_ollama(t.image_path, build_eval_prompt(t), m)
    if p == "custom":
        m = model or os.environ.get("CUSTOM_API_MODEL") or "gpt-4o"
        b = base_url or os.environ.get("CUSTOM_API_BASE") or None
        return f"custom:{m}", lambda t: _call_openai_compat(
            t.image_path,
            build_eval_prompt(t),
            m,
            base_url=b,
            api_key_env="CUSTOM_API_KEY",
            api_key=api_key,
        )
    raise ValueError(f"Unsupported provider '{provider}'")

def evaluate_dataset(
    dataset_path: str | Path,
    provider: str = "ocr_heuristic",
    model: Optional[str] = None,
    limit: Optional[int] = None,
    out_report_path: Optional[str | Path] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    delay_s: float = 0.0,
    progress_cb: Optional[Callable[[int, int, int], None]] = None,
) -> dict[str, Any]:
    """Run standardized benchmark evaluation across dataset and compute failure breakdown."""
    ds_file = Path(dataset_path).resolve()
    lines = [ln for ln in ds_file.read_text().splitlines() if ln.strip()]
    tasks = [TaskPackage.model_validate_json(ln) for ln in lines]
    for t in tasks:
        if not Path(t.image_path).is_absolute():
            t.image_path = str((ds_file.parent / t.image_path).resolve())
    if limit is not None:
        tasks = tasks[:limit]

    run_label, predict_fn = _resolve_predictor(provider, model, api_key=api_key, base_url=base_url)
    records: list[PredictionRecord] = []

    for idx, t in enumerate(tasks):
        if delay_s > 0.0 and idx > 0:
            time.sleep(delay_s)
        t0 = time.perf_counter()
        err: Optional[str] = None
        try:
            raw = predict_fn(t)
        except Exception as exc:
            raw = ""
            err = str(exc)
        dt = (time.perf_counter() - t0) * 1000.0
        norm_pred = normalize_answer(raw, t.answer_type)
        is_ok = answers_match(norm_pred, t.answer, t.answer_type)
        records.append(
            PredictionRecord(
                task_id=t.task_id,
                family=t.family.value,
                difficulty=t.difficulty.value,
                theme=t.theme.value,
                degradation=t.degradation.value,
                label_mode=t.label_mode.value,
                ground_truth=t.answer,
                raw_response=raw,
                normalized_prediction=norm_pred,
                correct=is_ok,
                latency_ms=round(dt, 2),
                invariance_partner_id=t.invariance_partner_id,
                error=err,
            )
        )
        if progress_cb is not None:
            progress_cb(idx + 1, len(tasks), sum(r.correct for r in records))

    def _agg(field: str) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[bool]] = defaultdict(list)
        for r in records:
            buckets[getattr(r, field)].append(r.correct)
        return {
            k: {
                "total": len(v),
                "correct": sum(v),
                "accuracy": round(sum(v) / len(v), 4) if v else 0.0,
            }
            for k, v in sorted(buckets.items())
        }

    rec_by_id = {r.task_id: r for r in records}
    inv_pairs = 0
    inv_both_correct = 0
    inv_pred_agree = 0
    for r in records:
        pid = r.invariance_partner_id
        if pid and pid in rec_by_id and r.task_id < pid:
            other = rec_by_id[pid]
            inv_pairs += 1
            if r.correct and other.correct:
                inv_both_correct += 1
            if r.normalized_prediction == other.normalized_prediction:
                inv_pred_agree += 1

    valid_records = [r for r in records if not r.error]
    error_count = len(records) - len(valid_records)
    overall_acc = round(sum(r.correct for r in records) / max(1, len(records)), 4)
    valid_acc = round(sum(r.correct for r in valid_records) / len(valid_records), 4) if valid_records else 0.0
    report: dict[str, Any] = {
        "model_label": run_label,
        "provider": provider,
        "total_tasks": len(records),
        "valid_calls": len(valid_records),
        "error_count": error_count,
        "overall_accuracy": overall_acc,
        "valid_only_accuracy": valid_acc,
        "mean_latency_ms": round(sum(r.latency_ms for r in records) / max(1, len(records)), 2),
        "by_family": _agg("family"),
        "by_difficulty": _agg("difficulty"),
        "by_degradation": _agg("degradation"),
        "by_label_mode": _agg("label_mode"),
        "invariance_pairs_evaluated": inv_pairs,
        "invariance_both_correct": inv_both_correct,
        "invariance_prediction_agreement": round(inv_pred_agree / inv_pairs, 4) if inv_pairs else None,
        "sample_failures": [r.model_dump() for r in records if not r.correct][:10],
        "records": [r.model_dump() for r in records],
    }

    if out_report_path is not None:
        out_p = Path(out_report_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, indent=2))

    return report
