# Your checklist (Greg)

Deadline: **Tue Oct 27, 07:59 WAT** (Mon Oct 26, 11:59 PM Pacific). Commands are PowerShell.

**Step 0, once:** create the venv and install everything. Run every `python ...` command below with the venv's
Python: activate it first, or replace `python` with `.venv\Scripts\python.exe`.
```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass; .venv\Scripts\Activate.ps1   # optional
```

1. [ ] **Devpost:** confirm the team is registered on the competition page and start a draft submission now.
2. [ ] **Photos:** shoot ≥ 30 photos per `eval/PHOTO_PROTOCOL.md`, copy them to one folder, then:
   ```powershell
   python scripts/prepare_real.py --src C:\path\to\photos
   ```
   Fill in `eval/data/real/labels.csv` (true_count, background, condition, notes). Count each photo twice.
   Then push (or send me the folder) so I can run the real evaluation.
3. [ ] **AWS credentials:** `aws sts get-caller-identity` must work (or follow `docs/AWS_SETUP.md` in the console).
4. [ ] **Provision and deploy** (costs money while running):
   ```powershell
   python deploy/provision.py --region eu-west-1      # check the plan, type yes
   python deploy/deploy.py --host <ELASTIC_IP> --key tabcount-key.pem
   ```
   Open `http://<ELASTIC_IP>/` on your phone **over mobile data** and count a tray.
   Check an object appears in S3 (`requests/…`) and log lines appear in CloudWatch `/tabcount/app`.
5. [ ] **Benchmark and consistency** (after the real photos are in):
   ```powershell
   python scripts/run_eval.py --data eval/data/real --url http://<ELASTIC_IP>
   python scripts/benchmark.py --url http://<ELASTIC_IP> --images eval/data/real --n 100 --concurrency 4
   python scripts/pipeline_figure.py eval/data/real/img_00X.jpg   # pick a good touching example
   python scripts/fill_report.py
   ```
6. [ ] **Review** `eval/results/real/summary.md` and `eval/results/real/failures/`.
7. [ ] **Video:** record from `docs/VIDEO_SCRIPT.md`, ≤ 5:00, upload to YouTube as **Unlisted**.
   Put the link in `docs/templates/DEVPOST.template.md` (`{{VIDEO_URL}}`) or paste it straight into Devpost.
8. [ ] **GitHub:** merge the work branch into `main` (or set it as default) so judges land on the full README.
   If the repo is private, give judges access as the rules require. Check the README renders, including the Mermaid diagram.
9. [ ] **Devpost form:** paste from `docs/DEVPOST.md`; add the repo link, live URL, video link and report link
   (`docs/REPORT.md`, or upload `docs/REPORT.pdf`/`.html` if a file is required).
10. [ ] **Submit before 07:59 WAT** and screenshot the confirmation.
11. [ ] **Leave the EC2 instance running until Nov 9, 2026.** Do not run `deploy/teardown.py` before Nov 10.
