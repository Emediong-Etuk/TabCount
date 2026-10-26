# Every target is also a plain command (see README). On Windows use the python commands directly.
PY ?= python

.PHONY: install run test synthetic eval-synthetic eval-real figure benchmark docker fill-report
install:
	$(PY) -m pip install -r requirements-dev.txt
run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --no-access-log
test:
	$(PY) -m pytest
synthetic:
	$(PY) scripts/make_synthetic.py --n 200 --seed 42 --out eval/data/synthetic
eval-synthetic: synthetic
	$(PY) scripts/run_eval.py --data eval/data/synthetic
eval-real:
	$(PY) scripts/run_eval.py --data eval/data/real
figure:
	$(PY) scripts/pipeline_figure.py eval/data/synthetic/syn_002.png
benchmark:
	$(PY) scripts/benchmark.py --url $(URL) --images eval/data/real --n 100 --concurrency 4
docker:
	docker build -t tabcount:latest . && docker run --rm -p 8000:8000 tabcount:latest
fill-report:
	$(PY) scripts/fill_report.py
