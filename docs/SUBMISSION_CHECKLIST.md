# Submission checklist

✅ done · ⏳ waiting on Greg (photos, AWS, video, Devpost) · ❌ missing

| # | Competition requirement | Where it is satisfied | Status |
|---|-------------------------|-----------------------|--------|
| 1 | OpenCV 5 used for substantive image analysis | `app/counter.py` (Otsu, morphology, distance transform, connected components, watershed, contours). Import-time guard requires `cv2.__version__` 5.x; version shown in `/health` and every response. `tests/test_counter.py::test_opencv_is_version_5` | ✅ |
| 2 | A meaningful component runs on AWS | The whole inference service runs on EC2 t4g.small (Graviton), with S3, CloudWatch Logs and IAM. `deploy/`, `docs/AWS_SETUP.md` | ✅ code · ⏳ provisioning |
| 3a | Technical report: problem, users, architecture, OpenCV 5, AWS, evaluation, limitations, responsible use | `docs/REPORT.md` (sections 1–11). Real numbers are filled by `scripts/fill_report.py` | ✅ text · ⏳ real-photo numbers |
| 3b | Judge-accessible code repository | github.com/emediong-etuk/tabcount (work branch `claude/tabcount-opencv-competition-fvplnw`) | ⏳ merge to `main` and check access |
| 3c | Pinned dependencies, build/deploy/test instructions | `requirements.txt`, `requirements-dev.txt`, `requirements.lock.txt`, README Quickstart / Commands / Docker / AWS sections | ✅ |
| 3d | Architecture diagram with OpenCV 5 and AWS components | `docs/architecture.svg` + `.png` (hand-authored), `docs/architecture.mmd`, Mermaid embedded in README | ✅ |
| 3e | Working web endpoint | `http://ELASTIC_IP/` after `deploy/provision.py` + `deploy/deploy.py` | ⏳ |
| 3f | Video ≤ 5 min: team, app working, architecture, principal results | `docs/VIDEO_SCRIPT.md` (timed shot list, about 4:30) | ⏳ record + upload |
| 3g | Evaluation evidence incl. failure cases and limitations | `scripts/run_eval.py` → `eval/results/<dataset>/` (metrics, charts, failure gallery); synthetic run committed | ✅ synthetic · ⏳ real photos |
| 4 | No featured-path claims (not COOL, not agentic vision) | No such claims anywhere; Graviton is described only as the instance type | ✅ |
| – | Benchmark of live endpoint | `scripts/benchmark.py` → `eval/results/benchmark.json` | ⏳ needs live URL |
| – | Deployed consistency check | `scripts/run_eval.py --url` → `deployed_check` in `summary.json` | ⏳ needs live URL |
| – | Devpost text | `docs/DEVPOST.md` (rendered from `docs/templates/DEVPOST.template.md`) | ✅ text · ⏳ numbers, video link |
| – | Tests pass | `python -m pytest` (23 tests: counter + API, no AWS) | ✅ |
| – | No secrets in repo | `.gitignore` covers `.env`, `*.pem`, `.venv/`, `deploy/state*.json`; history grep for `AKIA`/`aws_secret`/`.pem` | ✅ |
