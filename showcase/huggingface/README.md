---
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

Auto-exported benchmark containing **35** formally solved and quality-audited IEEE/IEC electrical schematic visual reasoning tasks across 7 task families (`state_propagation`, `bridge_vs_junction`, `equivalent_resistance`, `fault_diagnosis`, `counterfactual_pair`, `component_audit`, `whole_system`).

Load locally via Hugging Face `datasets`:
```python
from datasets import load_dataset
ds = load_dataset("imagefolder", data_dir="huggingface")
```
