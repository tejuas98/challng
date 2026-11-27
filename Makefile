.PHONY: test mutate benchmark export-hf serve docker-build docker-up

PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest

test:
	PYTHONPATH=src $(PYTEST) -v

mutate:
	PYTHONPATH=src $(PYTHON) -m schemforge.cli mutate-test --out artifacts/mutation_report.json

benchmark:
	PYTHONPATH=src $(PYTHON) -m schemforge.cli generate --count 60 --seed 42 --emit-svg --out artifacts/sample_dataset
	PYTHONPATH=src $(PYTHON) -m schemforge.cli validate --dataset artifacts/sample_dataset/dataset.jsonl --out artifacts/validation_report.json
	PYTHONPATH=src $(PYTHON) -m schemforge.cli evaluate --dataset artifacts/sample_dataset/dataset.jsonl --provider blind_random --out artifacts/eval_blind_random.json
	PYTHONPATH=src $(PYTHON) -m schemforge.cli evaluate --dataset artifacts/sample_dataset/dataset.jsonl --provider ocr_heuristic --out artifacts/eval_ocr_heuristic.json
	PYTHONPATH=src $(PYTHON) -m schemforge.cli evaluate --dataset artifacts/sample_dataset/dataset.jsonl --provider oracle_solver --out artifacts/eval_oracle_solver.json
	PYTHONPATH=src $(PYTHON) -m schemforge.cli charts --reports artifacts/eval_blind_random.json artifacts/eval_ocr_heuristic.json artifacts/eval_oracle_solver.json --out artifacts/charts

export-hf:
	PYTHONPATH=src $(PYTHON) -m schemforge.cli export --dataset artifacts/sample_dataset/dataset.jsonl --format huggingface --out artifacts/exports/huggingface

serve:
	PYTHONPATH=src $(PYTHON) -m schemforge.cli serve --host 0.0.0.0 --port 8765

docker-build:
	docker build -t schemforge:latest .

docker-up:
	docker compose up --build
