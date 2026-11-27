# SchemForge: Technical Architecture, Validation Proof & System Findings

**Version:** 0.2.0 (`Whole-Circuit Multi-Domain Release`)  
**Repository:** [tejuas98/challng](https://github.com/tejuas98/challng)

---

## 1. Domain Selection & Practical Impact

**Application Problem:** Automated Visual Understanding of IEEE/IEC Electrical & Digital Logic Schematics.  
In PCB fabrication QA, industrial PLC automation, power-grid control rooms, and hardware field service, technicians and automated optical inspection tools routinely interpret multi-stage schematics captured under imperfect real-world conditions (scanned PDFs, faded blueprints, overhead phone photos).

**Why Visual Errors Matter:** Unlike consumer bar charts where misreading a bar color is benign, a single visual failure in an engineering schematic causes critical operational faults:
- Confusing a **curved wire bridge jump** with a **solid solder junction dot** creates short circuits across independent voltage buses.
- Missing a small **IEEE output inversion bubble** on a `NAND`, `NOR`, or `NOT` gate inverts safety-interlock logic.
- Failing to spot a single **OPEN mechanical switch blade** includes dead resistor limbs in Ohm's-law load calculations.

---

## 2. Independent Ground-Truth Architecture (Zero VLM Circularity)

SchemForge strictly isolates answer synthesis from vision or language models:

```text
Seed + 6 Axes --> Formal SchematicSpec (Netlist + Coordinates) --> Deterministic Exact Solver --> Ground Truth + Step-by-Step Proof
                          |                                                                                   |
                          v                                                                                   v
               IEEE Vector CAD Renderer --> Optical Degradation --> 5-Gate Independent Quality Audit --> Audited TaskPackage
```

1. **Formal Netlist & Multi-Domain Solvers ([`src/schemforge/solver.py`](../src/schemforge/solver.py)):**
   - **Boolean DAG Evaluator (`solve_logic_network`):** Traverses explicit port-level connections across `5V`/`12V`/`24V` sources, switches, fuses, and IEEE logic gates (`AND`, `OR`, `NAND`, `NOR`, `XOR`, `NOT`) with memoized recursion, cycle guards, fault injection, and hypothetical single-switch toggle perturbations (`switch_toggle_override`).
   - **Conductivity BFS (`solve_conductivity_graph`):** Computes energized rails and multi-lamp power subsets (`L1, L2`, `L2, L3`, `NONE`) over active edges; unjoined orthogonal crossing arcs remain isolated unless connected topology links them.
   - **Exact Rational Impedance & Ohm's Law Solver (`eval_resistance_tree` / `solve_equivalent_resistance`):** Uses Python `fractions.Fraction` over recursive Series/Parallel switch-gated resistor subtrees to output exact Ohms (`35 Ohm`, `109.29 Ohm`) and powered DC load current in milliamps (`120 mA`, `55.81 mA`, `0 mA`).
   - **Whole-System Electromechanical Solver (`solve_whole_system`):** Couples upstream power rail, main protection fuse `F1`, interlock switches, and multi-gate digital logic directly into downstream parallel/series resistor load banks (`200 mA` vs. `0 mA` when disabled), combined dual-LED state vectors (`L1=ON, L2=OFF`), and single-switch perturbation queries on one complete industrial board.
   - **Unique Single-Fault Isolator (`solve_fault_diagnosis`):** Exhaustively simulates every candidate single-component fault against visible on-canvas bench probes (`TP1`, `TP2`, `TP3`) and enforces mathematical uniqueness (`len(matching) == 1`).
   - **Counterfactual Delta Verifier:** Solves Baseline Panel A and Mutated Panel B independently from identical layout ASTs with 1 surgical mutation (switch blade flip, gate inversion bubble swap, or inline fuse blow).

2. **Cross-Net Wire Crossing Verification (`compute_wire_topology`):**
   Whenever orthogonal segments from distinct electrical `net_id`s cross in pixel interior space inside [`src/schemforge/generator.py`](../src/schemforge/generator.py) or [`src/schemforge/ingest.py`](../src/schemforge/ingest.py), `compute_wire_topology` automatically inserts a semicircular `BridgeJump` (`r = 10px`) deterministically.

---

## 3. Seven Task Families & Meaningful Six-Axis Variation Strategy

Rather than tweaking chart colors or repeating one template, SchemForge generates genuine visual variety across **7 distinct schematic families**, **3 difficulty tiers**, **4 CAD themes**, **4 camera/scan degradations**, **2 label modes**, and **semantic-preserving invariance pairs**:

1. `state_propagation`: Multi-hop boolean circuits (`SW1..SW4`, inline fuse `F1`, `U_NOT`, `U1..U3`) plus genuinely unscripted multi-layer arbitrary procedural DAGs (`_generate_arbitrary_dag_core`), single-LED states, 4-way combined dual-LED vectors (`L1=..., L2=...`), and hypothetical switch-flip what-if questions.
2. `bridge_vs_junction`: 2-bus and 3-bus distribution grids with explicit solder dots, bridge jumps, and fuses querying multi-lamp energized subsets (`L2, L3`, `L1, L2`, `NONE`) and single-lamp reachability.
3. `equivalent_resistance`: Both passive terminal impedance (`Ohm`) and powered `12V`/`24V` Ohm's Law series-parallel switched load networks (`mA`).
4. `fault_diagnosis`: On-sheet probe badges (`5V HIGH` / `0V LOW`) paired with mathematically unique single-fault candidate banners.
5. `counterfactual_pair`: Dual-panel (`Panel A` vs `Panel B`) surgical single-edit comparisons across switch blades, IEEE gate inversion bubbles, and inline fuses.
6. `component_audit`: Dense multi-row mixed schematics verifying visual compliance (`R >= N Ohm`, IEEE inverting gate count, closed switch blades, open switch blades).
7. `whole_system`: End-to-end electromechanical + digital logic + switched resistor load boards asking cross-domain load currents (`mA`), hypothetical switch perturbations, and combined LED state vectors on a complete circuit sheet.

---

## 4. Validation Evidence & Mutation Testing Proof

Verified on both the **70-task full reference suite** (`artifacts/sample_dataset`) and the **35-task multi-tier public showcase** (`showcase/sample_dataset`) generated at `seed=42` ([`artifacts/validation_report.json`](../artifacts/validation_report.json), [`showcase/validation_report.json`](../showcase/validation_report.json), [`showcase/mutation_report.json`](../showcase/mutation_report.json), [`showcase/validation_test_log.txt`](../showcase/validation_test_log.txt)):

| Verification Gate | Result | Evidence |
| :--- | :---: | :--- |
| Automated Unit, Scale & API Suite (`pytest -v`) | **11 / 11 Passed** | [`tests/test_schemforge.py`](../tests/test_schemforge.py) & [`showcase/validation_test_log.txt`](../showcase/validation_test_log.txt) |
| High-Throughput Factory Scalability (`--lazy-render`) | **10,007 tasks / 3.22s** | 3,110 tasks/s multi-family; 10,000 custom DSL variations in **11.85s** (844/s) |
| Full Benchmark Validation (`70` Tasks / `7` Families) | **100.0% (70 / 70 Passed)** | `failed_ids: []`, `0` BBox collisions, `8.32x` mean contrast, `14/14` invariance twins |
| GitHub Showcase Validation (`35` Tasks / `easy+med+hard`) | **100.0% (35 / 35 Passed)** | `failed_ids: []`, `0` BBox collisions, `7.14x` mean contrast, `14/14` invariance twins |
| Independent Tesseract OCR Token Audit | **0.633 Recall** | Automatic dark-mode polarity normalization + `2x` Lanczos upscale |
| Planted Bug Mutation Kill Suite | **12 / 12 (100.0%)** | Kills injected gate, switch, fuse, bridge, resistor, fault, bbox, whole-board & perturbation bugs |

### Planted Software & Validator Mutants Killed (12 / 12)
- `M01_DROP_NAND_BUBBLE`: Dropping IEEE inversion bubble on `(1, 1)` NAND gate caught (`OFF` vs `ON`).
- `M02_IGNORE_OPEN_SWITCH`: Conducting through open switch caught via netlist state delta.
- `M03_IGNORE_BLOWN_FUSE`: Conducting across blown fuse caught (`TP1/L1` delta).
- `M04_SHORT_BRIDGE_JUMP`: Shorting bridge wire crossings altered lamp reachability.
- `M05_PARALLEL_AS_SERIES`: Summing `60 || 60` as `120 Ohm` instead of `30 Ohm` caught.
- `M06_LEAK_OPEN_BRANCH_RES`: Including open branch (`30 Ohm` vs `60 Ohm`) caught.
- `M07_AMBIGUOUS_FAULT_DIAG`: Injecting duplicate fault signature raised deterministic ambiguity guard error.
- `M08_OVERLAPPING_LABELS`: Overlapping `SW1` and `U1` label bounding boxes caught.
- `M09_OUT_OF_BOUNDS_LABEL`: Clipped canvas margin label (`x2 > 1262`) caught.
- `M10_COUNTERFACTUAL_COLLAPSE`: Distinguishes active counterfactual edits from invariant zero-diff controls.
- `M11_WHOLE_SYSTEM_LOGIC_OHM_COUPLING`: Caught decoupled Ohm's-law mutant when blown fuse `F1` disables whole-system load bank (`0 mA`).
- `M12_SWITCH_TOGGLE_WHATIF`: Caught mutant ignoring single-switch perturbation (`base=ON -> toggled=OFF`).

### 4.1 Documented Pipeline Failure Cases & Engineering Fixes

1. **Sparse-Ink Contrast Underestimation (`compute_contrast_ratio` in `validator.py`):** Schematic lines cover only ~1–3% of pixels; measuring `99.5`th vs `0.5`th grayscale luminance percentiles accurately separates ink strokes from paper (`8.32x` mean ratio).
2. **Dark-Mode Blueprint OCR Failures (`run_tesseract_ocr` in `validator.py`):** Inverted dark substrates (`np.median(arr) < 128.0`) and applied `2x` `Image.Resampling.LANCZOS` upscaling before `--psm 11`, lifting OCR legibility recall to `0.633`.
3. **Title-Block vs. Rule-Banner Gutter Overlap (`render_schematic` in `renderer.py`):** Enforced a `16px` horizontal gutter (`banner_w = max(200, tb_x - 48 - 16)`), responsive `textwrap` wrapping, and `lbl:rule_banner` BBox collision checking (`0` collisions across all `70` + `35` sheets).
4. **Cross-Net Orthogonal Crossing Drift (`compute_wire_topology` in `generator.py`):** Automatically intersects orthogonal wire segments from distinct `net_id`s in geometry space to place semicircular `BridgeJump` arcs cleanly, eliminating hardcoded jump drift.
5. **Decimal & Unit Normalization Bugs (`normalize_answer` & `answers_match` in `evaluator.py`):** Fixed early decimal-period stripping (`109.29 Ohm` previously parsed as `10929 Ohm`), added LaTeX `\boxed{...}` unwrapping (nested braces like `\boxed{200 \text{ mA}}`), added `0.5%` floating-decimal rounding tolerance strictly within matching units (`55.8 mA` matching `55.81 mA` while blocking `Ohm` vs `mA` swaps), and normalized multi-lamp sets (`"L3, L1"` -> `"L1, L3"`) and LED vectors (`L1=ON, L2=OFF`).
6. **API Transient & Quota Error Isolation (`_call_gemini`, `evaluate_dataset` in `evaluator.py`):** Added 3-attempt transient backoff (`3s`/`6s`), `--delay` pacing flag in CLI, and separate `valid_calls`, `error_count`, and `valid_only_accuracy` tracking so quota/network errors are never conflated with visual reasoning scores.

---

## 5. Empirical Evaluation Findings (Deterministic Baselines + Live VLMs)

### 5A. Full 70-Task Reference Benchmark & 35-Task Multi-Tier Showcase (0 Errors)

| Dataset Scope | `oracle_solver` | `blind_random` | `ocr_tesseract_heuristic` | Local `ollama:qwen2.5vl:3b` |
| :--- | :---: | :---: | :---: | :---: |
| **Full 70-Task Suite (`artifacts/`, 10/family)** | **100.00%** (70/70) | **27.14%** (19/70) | **20.00%** (14/70) | *(evaluated on 35-task showcase)* |
| **Multi-Tier Showcase (`showcase/`, 35 tasks)** | **100.00%** (35/35) | **31.43%** (11/35) | **20.00%** (7/35) | **17.14%** (6/35, `mean 11.85s`) |

Across the **35-task multi-tier showcase**, `ollama:qwen2.5vl:3b` achieved only **17.14%** (`0/5` on `whole_system`, `0/5` on `fault_diagnosis`, `0/10` on `low_contrast_fax`, and **28.57%** invariance pair agreement across the 7 transformed twins).

### 5B. Matched 14-Task `medium` + `hard` Whole-Circuit VLM Comparison (All 7 Families, 0 Errors)

Evaluated across the exact same **14 non-trivial `medium` + `hard` tasks** ([`showcase/sample_dataset/dataset_medium_hard_14.jsonl`](../showcase/sample_dataset/dataset_medium_hard_14.jsonl), 2 tasks per family across `clean`, `office_scan`, `mobile_photo`, `low_contrast_fax`, and `symbol_only` vs `annotated`; **`valid_calls: 14`, `error_count: 0`** on every model):

| Model / System | Overall | `medium` / `hard` | `annotated` / `symbol_only` | Weakest Family Breakdown | Latency / Task |
| :--- | :---: | :---: | :---: | :--- | :---: |
| **Oracle Formal Solver** | **100.00%** (14/14) | 100% / 100% | 100% / 100% | None (Exact AST Solver Ceiling) | 0.00 ms |
| **Gemini 3.1 Flash-Lite** (`gemini`) | **92.86%** (13/14) | 85.7% / 100% | 100% / 90.0% | `bridge_vs_junction` (**50.0%**, 1/2) | 5,270.44 ms |
| **Gemini 3.5 Flash-Lite** (`gemini`) | **85.71%** (12/14) | 100% / 71.4% | 100% / 80.0% | `equivalent_resistance` (**50.0%**, 1/2), `counterfactual_pair` (**50.0%**, 1/2) | 4,008.05 ms |
| **Tesseract OCR Heuristic** | **50.00%** (7/14) | 57.1% / 42.9% | 50.0% / 50.0% | `equivalent_resistance` (**0%**), `fault_diagnosis` (**0%**) | ~300 ms |
| **Blind Random Baseline** | **42.86%** (6/14) | 57.1% / 28.6% | 50.0% / 40.0% | `equivalent_resistance` (**0%**), `state_propagation` (**0%**) | 0.01 ms |
| **Ollama Qwen2.5-VL-3B** (local) | **21.43%** (3/14) | 28.6% / 14.3% | 0.0% / 30.0% | `whole_system` (**0%**), `fault_diagnosis` (**0%**), `bridge_vs_junction` (**0%**), `equivalent_resistance` (**0%**) | ~12,000 ms |

*(Note: Full evaluation reports saved cleanly in [`showcase/eval_gemini_31_flash_lite.json`](../showcase/eval_gemini_31_flash_lite.json), [`showcase/eval_gemini_35_flash_lite.json`](../showcase/eval_gemini_35_flash_lite.json), [`showcase/eval_ollama_qwen25vl.json`](../showcase/eval_ollama_qwen25vl.json), [`showcase/eval_ocr_heuristic.json`](../showcase/eval_ocr_heuristic.json), [`showcase/eval_blind_random.json`](../showcase/eval_blind_random.json), and [`artifacts/`](../artifacts/); matched 5-model 7-family charts in [`showcase/charts/`](../showcase/charts/).)*

### Observed Visual Failure Modes Across Evaluated Models

1. **Gemini 3.1 Flash-Lite — Crossbar Bridge vs. Solder Dot Hallucination (`task_0015_bridge_med`, `low_contrast_fax`):**
   On a 3-bus `low_contrast_fax` distribution schematic where **BUS1** (`0V`) and **BUS2** (`0V`) cross **BUS3** (`5V`), `gemini-3.1-flash-lite` scored **100%** on hard multi-stage schematics yet failed `task_0015_bridge_med`, claiming *"The line from BUS3 goes to a junction dot at coordinate B3. From there, it goes to SW1... All three lamps (L1, L2, and L3) are connected to the same 5V BUS3 rail... ANSWER: L1, L2, L3"* instead of the true energized set **`L2, L3`** (since `L1` actually tapped `0V BUS1`!).
2. **Gemini 3.5 Flash-Lite — Open Switch Blade & Gate Inversion Bubble Misses (`task_0023_equiva_har` & `task_0025_counte_har`):**
   On the hard 3-stage `12V` Ohm's Law ladder (`task_0023_equiva_har`), switch `SW2` was drawn tilted **OPEN** (`R4 = 100 Ohm` alone in Stage 2, total `215 Ohm -> 55.81 mA`), yet `gemini-3.5-flash-lite` misread `SW2` as **CLOSED** (`100 || 100 = 50 Ohm -> 165 Ohm -> 72.73 mA`). On the hard `office_scan` twin-panel counterfactual sheet (`task_0025_counte_har`), Panel B removed the output inversion bubble on gate `U2` (`NOR` -> `OR`, changing `L2` from `OFF` to `ON`), yet `gemini-3.5-flash-lite` hallucinated *"Panel B: U2 has a bubble at its output (NOR gate)... ANSWER: OFF -> OFF"* (`OFF -> ON` missed).
3. **Local Edge VLM `Qwen2.5-VL-3B` — Complete Multi-Domain Breakdown (`17.14%` on 35 tasks):**
   Achieved **0.0%** on `whole_system` (`0/5`), **0.0%** on `fault_diagnosis` (`0/5`), and **0.0%** on `low_contrast_fax` (`0/10`), misreading `"5V"` labels as `"SV"` on `task_0003_bridge_inv` (`kicad_blueprint` `mobile_photo`) and dropping to **28.57%** invariance agreement across visual style transforms.

---

## 6. Declared Tools, Models & Reproduction Commands

- **Evaluated Vision-Language Models:**
  - **Google Gemini 3.1 Flash-Lite (`gemini:gemini-3.1-flash-lite`)** & **Gemini 3.5 Flash-Lite (`gemini:gemini-3.5-flash-lite`)** via `google-genai` SDK (`GEMINI_API_KEY` supplied exclusively via runtime environment variables; never saved in repo files).
  - **Qwen2.5-VL-3B (`ollama:qwen2.5vl:3b`)** via local Ollama inference (`http://127.0.0.1:11434/api/chat`).
- **Verification & Engineering Stack:** Python 3.14, Pydantic v2, `fractions.Fraction`, Matplotlib + Pillow CAD/optical degradation, Tesseract OCR (`--psm 11`), `pytest`, 12-mutant kill suite (`schemforge.mutation`), FastAPI + `uvicorn` Drafting Bench (`http://127.0.0.1:8766`).
- **AI Assistance Disclosure:** An AI coding assistant collaborated on software refactoring, UI styling, and report drafting; every circuit solver proof, 5-gate audit, mutation run, and model evaluation metric was deterministically executed and logged directly in repository outputs.

```bash
# 1. Run tests, 12/12 mutation suite, and 70-task dataset generation
PYTHONPATH=src .venv/bin/pytest -v
PYTHONPATH=src .venv/bin/python -m schemforge.cli generate --count 63 --seed 42 --workers 2 --emit-svg --out artifacts/sample_dataset
PYTHONPATH=src .venv/bin/python -m schemforge.cli validate --dataset artifacts/sample_dataset/dataset.jsonl --out artifacts/validation_report.json
PYTHONPATH=src .venv/bin/python -m schemforge.cli mutate-test --out showcase/mutation_report.json

# 2. Evaluate local & cloud VLMs on multi-tier showcase split
PYTHONPATH=src .venv/bin/python -m schemforge.cli evaluate --dataset showcase/sample_dataset/dataset.jsonl --provider ollama --model qwen2.5vl:3b --out showcase/eval_ollama_qwen25vl.json
GEMINI_API_KEY="your_key" PYTHONPATH=src .venv/bin/python -m schemforge.cli evaluate --dataset showcase/sample_dataset/dataset_medium_hard_14.jsonl --provider gemini --model gemini-3.1-flash-lite --delay 4.2 --out showcase/eval_gemini_31_flash_lite.json
```
