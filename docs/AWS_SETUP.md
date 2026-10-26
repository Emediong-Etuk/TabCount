# AWS setup

Two ways to create the same resources:

* **A. Script (recommended):** `python deploy/provision.py --region eu-west-1`
* **B. Console click-path:** below, if your AWS CLI/credentials are not set up locally.

Region used throughout: **eu-west-1 (Ireland)**. Replace `ACCOUNT_ID` with your 12-digit account ID
(top-right menu in the console).

---

## A. Script path (Windows PowerShell)

```powershell
# 0. Credentials: the default boto3 chain. Check this works first:
aws sts get-caller-identity          # or: aws configure   (needs an access key for YOUR IAM user)

# 1. Provision (prints the plan, waits for "yes")
python deploy/provision.py --region eu-west-1
#    add --profile NAME if you use a named profile

# 2. Wait ~2 minutes for Docker to install on first boot, then deploy
python deploy/deploy.py --host ELASTIC_IP --key tabcount-key.pem
```

macOS/Linux: identical commands with `python3`.

Never paste access keys into files in this repo. `.env`, `*.pem` and `deploy/state.json` are gitignored.

---

## B. Console click-path

### 1. S3 bucket
1. **S3 → Create bucket**. Name `tabcount-ACCOUNT_ID-eu-west-1`, region eu-west-1.
2. **Block all public access**: leave ON (all four boxes).
3. **Default encryption**: SSE-S3 (Amazon S3 managed keys). Create.
4. Open the bucket → **Management → Create lifecycle rule**:
   name `delete-requests-after-60-days`, scope *Limit with filters*, prefix `requests/`,
   action *Expire current versions of objects*, **60** days. Save.

### 2. CloudWatch log group
1. **CloudWatch → Logs → Log groups → Create log group**: `/tabcount/app`, retention **30 days**.

### 3. IAM role (least privilege)
1. **IAM → Roles → Create role** → Trusted entity *AWS service* → Use case **EC2** → Next.
2. Skip managed policies → Next → Role name `tabcount-ec2-role` → Create.
3. Open the role → **Add permissions → Create inline policy → JSON**, paste
   `deploy/iam-policy.json` after replacing `${BUCKET}`, `${REGION}` (`eu-west-1`) and `${ACCOUNT_ID}`.
   Name it `tabcount-least-privilege`. (The console creates the instance profile with the same name
   automatically.)

### 4. Security group
1. **EC2 → Security Groups → Create**: name `tabcount-sg`, VPC = the **default** VPC.
2. Inbound rules:
   * HTTP, TCP 80, source `0.0.0.0/0`
   * SSH, TCP 22, source **My IP**
3. Outbound: leave default (all). Create.

### 5. Key pair
1. **EC2 → Key Pairs → Create key pair**: name `tabcount-key`, type ED25519, format `.pem`.
2. Save `tabcount-key.pem` in the repo folder (it is gitignored). On Windows, restrict it:
   ```powershell
   icacls tabcount-key.pem /inheritance:r
   icacls tabcount-key.pem /grant:r "$($env:USERNAME):(R)"
   ```

### 6. EC2 instance
1. **EC2 → Launch instance**. Name `tabcount`.
2. AMI: **Amazon Linux 2023**, architecture **64-bit (Arm)**.
3. Instance type: **t4g.small**. Key pair: `tabcount-key`.
4. Network: default VPC, auto-assign public IP on, security group `tabcount-sg`.
5. Storage: 16 GiB gp3.
6. **Advanced details**:
   * IAM instance profile: `tabcount-ec2-role`
   * Metadata accessible: Enabled; **Metadata version: V2 only (token required)**
   * **Metadata response hop limit: 2** (required so the container can reach the instance-role credentials)
   * User data: paste the contents of `deploy/user-data.sh`
7. Launch.

### 7. Elastic IP
1. **EC2 → Elastic IPs → Allocate** → Allocate.
2. Select it → **Actions → Associate** → instance `tabcount` → Associate. This is the permanent URL.

### Setting the hop limit on an existing instance
Console: **EC2 → Instances → select → Actions → Instance settings → Modify instance metadata options**
→ IMDSv2 *Required*, hop limit **2** → Save.

CLI:
```powershell
aws ec2 modify-instance-metadata-options --instance-id i-XXXXXXXX --http-tokens required --http-put-response-hop-limit 2 --http-endpoint enabled --region eu-west-1
```

### 8. Deploy
```powershell
python deploy/deploy.py --host ELASTIC_IP --key tabcount-key.pem --bucket tabcount-ACCOUNT_ID-eu-west-1 --region eu-west-1
```

---

## Fallback (only if the arm64 build fails)
Use `t3.small` with the AL2023 **x86_64** AMI and change nothing else:
`python deploy/provision.py --region eu-west-1 --instance-type t3.small --arch x86_64`.
Log it in `docs/DECISIONS.md` and remove every "Graviton"/"arm64" claim from the docs.

## After judging (not before Nov 10, 2026)
`python deploy/teardown.py` deletes everything listed in `deploy/state.json`.
