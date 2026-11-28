<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/hero-dark.svg" />
  <source media="(prefers-color-scheme: light)" srcset="assets/hero-light.svg" />
  <img src="assets/hero-dark.svg" alt="SchemForge — Seeded Visual Circuit Generator, Exact Solver & Verification Studio" width="100%" />
</picture>

<br /><br />

<a href="https://schemforge-visual-task-factory.onrender.com"><strong>Open Live Studio</strong></a>
&nbsp;&middot;&nbsp;
<a href="#live-interactive-walkthrough"><strong>Live Demo</strong></a>
&nbsp;&middot;&nbsp;
<a href="#visual-tour-across-all-studio-tabs"><strong>Studio Tour</strong></a>
&nbsp;&middot;&nbsp;
<a href="#architecture--pipeline"><strong>Architecture</strong></a>
&nbsp;&middot;&nbsp;
<a href="#how-to-run"><strong>Quick Start</strong></a>
&nbsp;&middot;&nbsp;
<a href="docs/TECHNICAL_REPORT.md"><strong>Technical Report</strong></a>

<br /><br />

[![Live Deploy](https://img.shields.io/badge/Live_Demo-Online-10b981?style=flat-square&labelColor=161b22&logo=render&logoColor=46e3b7)](https://schemforge-visual-task-factory.onrender.com)
[![CI](https://github.com/tejuas98/challng/actions/workflows/ci.yml/badge.svg)](https://github.com/tejuas98/challng/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat-square&labelColor=161b22&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ed?style=flat-square&labelColor=161b22&logo=docker&logoColor=white)](Dockerfile)

</div>

---

## Live Interactive Walkthrough

> Recorded directly from the live production deployment: opening the quick guide, browsing schematics & custom frosted controls, switching accent themes, generating zero-duplicate custom question banks, compiling arrow-DSL circuits live (`ON -> OFF`), comparing Vision AI vs. baselines, and inspecting broken-circuit guardrails.

<div align="center">
  <img src="assets/schemforge-demo.gif" alt="SchemForge Live Interactive Walkthrough" width="100%" />
</div>

---

## Visual Tour Across All Studio Tabs

<table>
  <tr>
    <td width="50%" align="center">
      <strong>1. Browse Questions &amp; Verified Steps</strong><br /><br />
      <img src="assets/tab1-browse-questions.png" alt="Browse Questions Studio" width="100%" />
    </td>
    <td width="50%" align="center">
      <strong>2. Question Bank Library &amp; <code>.ZIP</code> Builder</strong><br /><br />
      <img src="assets/tab2-create-question-bank.png" alt="Create Question Bank Studio" width="100%" />
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <strong>3. Build Your Own Circuit (Live Arrow DSL)</strong><br /><br />
      <img src="assets/tab3-custom-circuit-builder.png" alt="Build Your Own Circuit" width="100%" />
    </td>
    <td width="50%" align="center">
      <strong>4. AI Test Scores &amp; Model Comparison</strong><br /><br />
      <img src="assets/tab4-live-result-summary.png" alt="Live AI Test Summary" width="100%" />
    </td>
  </tr>
</table>

---

## Tech Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend &amp; API** | ![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&labelColor=161b22&logo=python&logoColor=ffd43b) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&labelColor=161b22&logo=fastapi&logoColor=2dd4bf) ![Pydantic](https://img.shields.io/badge/Pydantic_v2-E92063?style=flat-square&labelColor=161b22&logo=pydantic&logoColor=ff5c8a) ![Uvicorn](https://img.shields.io/badge/Uvicorn-4C566A?style=flat-square&labelColor=161b22&logo=gunicorn&logoColor=white) |
| **Solvers &amp; Vision QA** | ![NumPy](https://img.shields.io/badge/NumPy-013243?style=flat-square&labelColor=161b22&logo=numpy&logoColor=60a5fa) ![Pillow](https://img.shields.io/badge/Pillow_PIL-306998?style=flat-square&labelColor=161b22&logo=python&logoColor=ffd43b) ![Matplotlib](https://img.shields.io/badge/Matplotlib-11557C?style=flat-square&labelColor=161b22&logo=plotly&logoColor=38bdf8) ![Tesseract OCR](https://img.shields.io/badge/Tesseract_OCR-4285F4?style=flat-square&labelColor=161b22&logo=google&logoColor=60a5fa) |
| **Frontend Studio** | ![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=flat-square&labelColor=161b22&logo=html5&logoColor=fb923c) ![CSS3](https://img.shields.io/badge/CSS3_Glass-1572B6?style=flat-square&labelColor=161b22&logo=css3&logoColor=38bdf8) ![JavaScript](https://img.shields.io/badge/JavaScript_ES6-F7DF1E?style=flat-square&labelColor=161b22&logo=javascript&logoColor=facc15) ![Web Audio API](https://img.shields.io/badge/Web_Audio_API-8A2BE2?style=flat-square&labelColor=161b22&logo=audiomack&logoColor=c084fc) |
| **AI Providers &amp; Infra** | ![Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=flat-square&labelColor=161b22&logo=googlegemini&logoColor=c4b5fd) ![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat-square&labelColor=161b22&logo=openai&logoColor=a78bfa) ![Anthropic](https://img.shields.io/badge/Claude-191919?style=flat-square&labelColor=161b22&logo=anthropic&logoColor=f59e0b) ![OpenRouter](https://img.shields.io/badge/OpenRouter-6366F1?style=flat-square&labelColor=161b22&logo=openapiinitiative&logoColor=818cf8) ![Ollama](https://img.shields.io/badge/Local_Ollama-111111?style=flat-square&labelColor=161b22&logo=ollama&logoColor=ffffff) ![Hugging Face](https://img.shields.io/badge/Hugging_Face-FFD21E?style=flat-square&labelColor=161b22&logo=huggingface&logoColor=facc15) ![Pytest](https://img.shields.io/badge/Pytest-0A9EDC?style=flat-square&labelColor=161b22&logo=pytest&logoColor=38bdf8) ![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&labelColor=161b22&logo=docker&logoColor=60a5fa) ![Render](https://img.shields.io/badge/Render-46E3B7?style=flat-square&labelColor=161b22&logo=render&logoColor=46e3b7) ![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat-square&labelColor=161b22&logo=githubactions&logoColor=60a5fa) |

---

## Architecture & Pipeline

SchemForge computes ground-truth answers independently before drawing pixels so visual reasoning checks cannot shortcut via guessed labels:

```mermaid
flowchart LR
    A["Seed & Parameters"] --> B["Formal Netlist AST"]
    B --> C["Exact Circuit Solvers"]
    C --> D["Verified Answer & Proof"]
    B --> E["IEEE Schematic Renderer"]
    E --> F["Optical Scan Effects"]
    F --> G["5 Automated QA Gates"]
    D --> H["Audited Question Set"]
    G --> H
```

### Core Modules ([`src/schemforge/`](src/schemforge/))

| Module | Responsibility |
| :--- | :--- |
| [`solver.py`](src/schemforge/solver.py) | Boolean DAG evaluation (including hypothetical switch flips), BFS wire reachability, exact `fractions.Fraction` impedance & Ohm's-law (`mA`), unique single-fault isolation |
| [`generator.py`](src/schemforge/generator.py) | Seeded circuit generation across 7 topics (`state_propagation`, `bridge_vs_junction`, `equivalent_resistance`, `fault_diagnosis`, `counterfactual_pair`, `component_audit`, `whole_system`) |
| [`ingest.py`](src/schemforge/ingest.py) & [`netlist.py`](src/schemforge/netlist.py) | Compiles arbitrary circuit JSON schemas or arrow DSL (`VCC1(12V) -> SW1(CLOSED) -> U1(AND) -> L1`) into batch variations |
| [`renderer.py`](src/schemforge/renderer.py) & [`degradation.py`](src/schemforge/degradation.py) | Renders IEEE/IEC schematic symbols across 4 paper styles plus clean, scanned, phone-photo, and faded-print optical profiles |
| [`validator.py`](src/schemforge/validator.py) & [`mutation.py`](src/schemforge/mutation.py) | Bounding-box overlap checks, WCAG contrast audit, OCR readout check, and 12 planted-error guardrail tests |
| [`exporters.py`](src/schemforge/exporters.py) & [`evaluator.py`](src/schemforge/evaluator.py) | Exports `.zip` quiz packs, Hugging Face ImageFolder, OpenAI Evals JSONL, and runs live model vs. baseline tests |
| [`server.py`](src/schemforge/server.py) &amp; [`static/`](static/) | Async FastAPI service, `lazy_render` batch queue, host-protected API config, and Liquid Glass studio frontend |

---

## How to Run

### Option A — Use Live Deployed Studio
Open **[https://schemforge-visual-task-factory.onrender.com](https://schemforge-visual-task-factory.onrender.com)** (first visit after inactivity may take ~30–50s to wake the free-tier container).

### Option B — Local Python Setup

```bash
git clone https://github.com/tejuas98/challng.git
cd challng

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: configure API keys if running live cloud models locally (never committed)
cp .env.example .env

# Start the web studio
PYTHONPATH=src .venv/bin/python -m schemforge.cli serve --host 127.0.0.1 --port 8765
```

Or run `./start_studio.sh`, then open `http://127.0.0.1:8765`.

### Option C — Docker

```bash
docker compose up --build
```

Exposes port `8765` with `/healthz` and `/readyz` readiness probes.

### Run Automated Tests

```bash
PYTHONPATH=src .venv/bin/pytest -v
```

---

## CLI & API Quick Reference

### CLI Commands (`python -m schemforge.cli`)
- `serve` — Launch FastAPI Web Studio (`--host`, `--port`)
- `generate` — Create seeded schematic sets (`--count`, `--seed`, `--workers`, `--lazy-render`, `--out`)
- `from-netlist` — Compile custom JSON/DSL circuits into 1–25,000 unique variations (`--input`, `--count`, `--out`)
- `validate` / `mutate-test` — Run label-overlap, contrast, invariance, and 12 guardrail checks
- `export` — Export datasets as `huggingface`, `openai-evals`, or `zip`
- `evaluate` / `charts` — Run model/baseline checks and plot accuracy charts

### Core FastAPI Routes
- `GET /`, `/healthz`, `/readyz`, `/api/overview`
- `GET / POST / DELETE /api/batches`, `GET /api/batches/{batch_id}/download`
- `GET /api/tasks`, `/api/tasks/{task_id}/image`, `/api/tasks/{task_id}/spec`
- `POST /api/generate-live`, `/api/from-netlist`, `/api/from-netlist/dsl`, `/api/from-netlist/batch`
- `GET / POST / DELETE /api/providers/status`, `/api/providers/key`, `POST /api/evaluate-jobs`, `/api/mutate-test`

---

## Repository Structure

| Path | Purpose |
| :--- | :--- |
| [`src/schemforge/`](src/schemforge/) | Core solvers, circuit generators, renderer, QA validators, CLI, and FastAPI server |
| [`static/`](static/) | Web Studio frontend (`index.html`, `styles.css`, `app.js`) |
| [`tests/test_schemforge.py`](tests/test_schemforge.py) | End-to-end unit, rendering, scale, DSL, and FastAPI test suite (`11` test cases) |
| [`assets/`](assets/) | Recorded live interactive GIF walkthrough and studio screenshots |
| [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md) | Formal solver specifications, verification benchmarks, and failure taxonomy |
| [`examples/`](examples/) | Sample JSON circuit netlists for custom variation synthesis |
| [`showcase/`](showcase/) | Pre-built starter question packs, Hugging Face / OpenAI exports, and reports |
| [`Dockerfile`](Dockerfile) & [`docker-compose.yml`](docker-compose.yml) | Container image and Compose setup (`port 8765`, `/healthz`) |
| [`render.yaml`](render.yaml) | Render blueprint deployment configuration |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Automated Pytest CI, mutation check, and GitHub Deployment tracking |

---

## Author & Technical Docs

- **Developed by:** **Tejas Jaware** · [GitHub Repository](https://github.com/tejuas98/challng)
- **Live App:** [https://schemforge-visual-task-factory.onrender.com](https://schemforge-visual-task-factory.onrender.com)
- **Deep Dive:** [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md)
