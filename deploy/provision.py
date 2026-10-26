"""Provision TabCount's AWS resources (idempotent; prints every action).

    python deploy/provision.py --region eu-west-1 [--profile myprofile]

Creates (or reuses):
  * S3 bucket tabcount-<account>-<region>: public access blocked, SSE-S3,
    lifecycle rule deleting requests/ after 60 days
  * CloudWatch log group /tabcount/app (30-day retention)
  * IAM role tabcount-ec2-role + instance profile (least privilege, deploy/iam-policy.json)
  * Security group tabcount-sg (80 from anywhere, 22 from your IP only)
  * Key pair tabcount-key (saved to ./tabcount-key.pem, gitignored)
  * EC2 t4g.small (Graviton, Amazon Linux 2023 arm64), IMDSv2 required, hop limit 2
  * Elastic IP associated with the instance

It prints the plan and waits for you to type "yes". Credentials come from the
default boto3 chain (your local AWS profile); nothing is written to the repo
except deploy/state.json (gitignored) and tabcount-key.pem (gitignored).
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATE = HERE / "state.json"
NAME = "tabcount"
ROLE = "tabcount-ec2-role"
PROFILE = "tabcount-ec2-profile"
POLICY_NAME = "tabcount-least-privilege"
SG_NAME = "tabcount-sg"
KEY_NAME = "tabcount-key"
LOG_GROUP = "/tabcount/app"
AMI_PARAM = {
    "arm64": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64",
    "x86_64": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
}
TAGS = [{"Key": "Name", "Value": NAME}, {"Key": "project", "Value": NAME}]


def say(msg: str) -> None:
    print(f"  -> {msg}", flush=True)


def code(e: ClientError) -> str:
    return e.response.get("Error", {}).get("Code", "")


def my_public_ip() -> str:
    return urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10).read().decode().strip()


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2))


# --------------------------------------------------------------------------- #
def ensure_bucket(s3, bucket: str, region: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
        say(f"S3 bucket {bucket} exists (reusing)")
    except ClientError as e:
        if code(e) not in ("404", "NoSuchBucket", "NotFound"):
            raise
        kw = {} if region == "us-east-1" else {"CreateBucketConfiguration": {"LocationConstraint": region}}
        s3.create_bucket(Bucket=bucket, **kw)
        say(f"created S3 bucket {bucket}")
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True})
    say("block all public access: on")
    s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
    say("default encryption: SSE-S3")
    s3.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration={"Rules": [{
        "ID": "delete-requests-after-60-days", "Status": "Enabled",
        "Filter": {"Prefix": "requests/"}, "Expiration": {"Days": 60}}]})
    say("lifecycle: delete requests/ after 60 days")


def ensure_log_group(logs) -> None:
    try:
        logs.create_log_group(logGroupName=LOG_GROUP)
        say(f"created log group {LOG_GROUP}")
    except ClientError as e:
        if code(e) != "ResourceAlreadyExistsException":
            raise
        say(f"log group {LOG_GROUP} exists (reusing)")
    logs.put_retention_policy(logGroupName=LOG_GROUP, retentionInDays=30)
    say("log retention: 30 days")


def ensure_role(iam, bucket: str, region: str, account: str) -> str:
    trust = (HERE / "trust-policy.json").read_text()
    policy = ((HERE / "iam-policy.json").read_text()
              .replace("${BUCKET}", bucket).replace("${REGION}", region).replace("${ACCOUNT_ID}", account))
    try:
        iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=trust,
                        Description="TabCount EC2 instance role (least privilege)", Tags=TAGS)
        say(f"created IAM role {ROLE}")
    except ClientError as e:
        if code(e) != "EntityAlreadyExists":
            raise
        say(f"IAM role {ROLE} exists (reusing)")
    iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY_NAME, PolicyDocument=policy)
    say(f"inline policy {POLICY_NAME} attached (S3 requests/* put/get, logs on {LOG_GROUP})")
    try:
        iam.create_instance_profile(InstanceProfileName=PROFILE, Tags=TAGS)
        say(f"created instance profile {PROFILE}")
    except ClientError as e:
        if code(e) != "EntityAlreadyExists":
            raise
        say(f"instance profile {PROFILE} exists (reusing)")
    prof = iam.get_instance_profile(InstanceProfileName=PROFILE)["InstanceProfile"]
    if not any(r["RoleName"] == ROLE for r in prof["Roles"]):
        iam.add_role_to_instance_profile(InstanceProfileName=PROFILE, RoleName=ROLE)
        say("role added to instance profile")
    return prof["Arn"]


def default_vpc(ec2) -> str:
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        sys.exit("No default VPC in this region. Create one: aws ec2 create-default-vpc --region REGION")
    return vpcs[0]["VpcId"]


def ensure_sg(ec2, vpc_id: str, ssh_cidr: str) -> str:
    sgs = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [SG_NAME]},
                                                {"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]
    if sgs:
        sg = sgs[0]["GroupId"]
        say(f"security group {SG_NAME} exists ({sg}, reusing)")
    else:
        sg = ec2.create_security_group(GroupName=SG_NAME, VpcId=vpc_id,
                                       Description="TabCount: HTTP from anywhere, SSH from admin IP",
                                       TagSpecifications=[{"ResourceType": "security-group", "Tags": TAGS}])["GroupId"]
        say(f"created security group {SG_NAME} ({sg})")
    for port, cidr, desc in [(80, "0.0.0.0/0", "HTTP"), (22, ssh_cidr, "SSH admin")]:
        try:
            ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[{
                "IpProtocol": "tcp", "FromPort": port, "ToPort": port,
                "IpRanges": [{"CidrIp": cidr, "Description": desc}]}])
            say(f"ingress tcp/{port} from {cidr}")
        except ClientError as e:
            if code(e) != "InvalidPermission.Duplicate":
                raise
            say(f"ingress tcp/{port} from {cidr} already present")
    return sg


def ensure_key(ec2, pem: Path) -> None:
    try:
        ec2.describe_key_pairs(KeyNames=[KEY_NAME])
        if not pem.exists():
            sys.exit(f"Key pair {KEY_NAME} exists in AWS but {pem} is missing locally. "
                     f"Find the .pem, or delete the key pair in the EC2 console and re-run.")
        say(f"key pair {KEY_NAME} exists, using {pem}")
        return
    except ClientError as e:
        if code(e) != "InvalidKeyPair.NotFound":
            raise
    key = ec2.create_key_pair(KeyName=KEY_NAME, KeyType="ed25519",
                              TagSpecifications=[{"ResourceType": "key-pair", "Tags": TAGS}])
    pem.write_bytes(key["KeyMaterial"].encode())  # LF line endings, also on Windows
    say(f"created key pair {KEY_NAME}, saved private key to {pem} (gitignored)")
    if os.name == "nt":
        user = os.environ.get("USERNAME", "")
        print("     Windows: OpenSSH refuses keys other users can read. Restricting with icacls:")
        print(f'     icacls "{pem}" /inheritance:r')
        print(f'     icacls "{pem}" /grant:r "$($env:USERNAME):(R)"')
        try:
            import subprocess
            subprocess.run(["icacls", str(pem), "/inheritance:r"], check=True, capture_output=True)
            subprocess.run(["icacls", str(pem), "/grant:r", f"{user}:(R)"], check=True, capture_output=True)
            say("icacls applied")
        except Exception as exc:  # print-only fallback
            say(f"could not run icacls automatically ({exc}); run the two commands above")
    else:
        os.chmod(pem, stat.S_IRUSR)
        say("chmod 400 applied")


def find_instance(ec2) -> dict | None:
    res = ec2.describe_instances(Filters=[
        {"Name": "tag:Name", "Values": [NAME]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])
    for r in res["Reservations"]:
        for i in r["Instances"]:
            return i
    return None


def ensure_instance(ec2, ssm, instance_type: str, arch: str, sg: str) -> str:
    inst = find_instance(ec2)
    if inst:
        iid = inst["InstanceId"]
        say(f"instance {iid} exists ({inst['State']['Name']}, reusing)")
        if inst["State"]["Name"] in ("stopped", "stopping"):
            ec2.get_waiter("instance_stopped").wait(InstanceIds=[iid])
            ec2.start_instances(InstanceIds=[iid])
            say("started instance")
        return iid
    ami = ssm.get_parameter(Name=AMI_PARAM[arch])["Parameter"]["Value"]
    say(f"AMI {ami} (Amazon Linux 2023 {arch}, from SSM {AMI_PARAM[arch]})")
    user_data = (HERE / "user-data.sh").read_text()
    for attempt in range(10):  # a brand-new instance profile takes a few seconds to propagate
        try:
            out = ec2.run_instances(
                ImageId=ami, InstanceType=instance_type, MinCount=1, MaxCount=1, KeyName=KEY_NAME,
                SecurityGroupIds=[sg], IamInstanceProfile={"Name": PROFILE}, UserData=user_data,
                MetadataOptions={"HttpTokens": "required", "HttpPutResponseHopLimit": 2,
                                 "HttpEndpoint": "enabled"},
                BlockDeviceMappings=[{"DeviceName": "/dev/xvda",
                                      "Ebs": {"VolumeSize": 16, "VolumeType": "gp3", "Encrypted": True,
                                              "DeleteOnTermination": True}}],
                TagSpecifications=[{"ResourceType": "instance", "Tags": TAGS},
                                   {"ResourceType": "volume", "Tags": TAGS}])
            iid = out["Instances"][0]["InstanceId"]
            say(f"launched {instance_type} instance {iid} (IMDSv2 required, hop limit 2)")
            return iid
        except ClientError as e:
            if code(e) == "InvalidParameterValue" and "iamInstanceProfile" in str(e) and attempt < 9:
                say("instance profile not visible yet, retrying in 5 s ...")
                time.sleep(5)
                continue
            raise
    raise RuntimeError("could not launch instance")


def ensure_eip(ec2, iid: str) -> tuple[str, str]:
    addrs = ec2.describe_addresses(Filters=[{"Name": "tag:Name", "Values": [NAME]}])["Addresses"]
    if addrs:
        a = addrs[0]
        say(f"Elastic IP {a['PublicIp']} exists (reusing)")
    else:
        a = ec2.allocate_address(Domain="vpc", TagSpecifications=[{"ResourceType": "elastic-ip", "Tags": TAGS}])
        say(f"allocated Elastic IP {a['PublicIp']}")
    if a.get("InstanceId") != iid:
        ec2.associate_address(AllocationId=a["AllocationId"], InstanceId=iid)
        say(f"associated {a['PublicIp']} with {iid}")
    return a["PublicIp"], a["AllocationId"]


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="eu-west-1")
    ap.add_argument("--profile", default=None, help="local AWS profile (default chain if omitted)")
    ap.add_argument("--instance-type", default="t4g.small")
    ap.add_argument("--arch", default="arm64", choices=["arm64", "x86_64"],
                    help="x86_64 only for the documented fallback (use with --instance-type t3.small)")
    ap.add_argument("--ssh-cidr", default=None, help="CIDR allowed to SSH (default: your current IP/32)")
    ap.add_argument("--key-path", default=str(ROOT / "tabcount-key.pem"))
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a = ap.parse_args()

    sess = boto3.Session(profile_name=a.profile, region_name=a.region)
    ident = sess.client("sts").get_caller_identity()
    account = ident["Account"]
    bucket = f"tabcount-{account}-{a.region}"
    ssh_cidr = a.ssh_cidr or f"{my_public_ip()}/32"
    pem = Path(a.key_path)

    print("\nTabCount provisioning plan")
    print("=" * 60)
    print(f"AWS account      {account}  ({ident['Arn']})")
    print(f"Region           {a.region}")
    print(f"S3 bucket        {bucket}  (private, SSE-S3, requests/ expire after 60 days)")
    print(f"Log group        {LOG_GROUP}  (30-day retention)")
    print(f"IAM role         {ROLE} + instance profile {PROFILE}")
    print("                 s3:PutObject/GetObject on requests/*; logs:* (4 actions) on the log group only")
    print(f"Security group   {SG_NAME}: tcp/80 from 0.0.0.0/0, tcp/22 from {ssh_cidr}")
    print(f"Key pair         {KEY_NAME} -> {pem}")
    print(f"EC2              {a.instance_type} ({a.arch}), Amazon Linux 2023, default VPC, 16 GB gp3")
    print("                 IMDSv2 required, HttpPutResponseHopLimit=2")
    print("Elastic IP       1, associated with the instance")
    print("=" * 60)
    print(f"Check that {ssh_cidr} is YOUR public IP (override with --ssh-cidr).")
    print("These resources cost money while they exist. Keep them until judging ends (Nov 9, 2026).")
    if not a.yes and input('Type "yes" to create/reuse these resources: ').strip().lower() != "yes":
        sys.exit("aborted, nothing created")

    state = load_state()
    state.update({"account": account, "region": a.region, "bucket": bucket, "log_group": LOG_GROUP,
                  "role": ROLE, "instance_profile": PROFILE, "key_name": KEY_NAME, "key_path": str(pem)})
    s3, ec2 = sess.client("s3"), sess.client("ec2")

    print("\n[1/7] S3"); ensure_bucket(s3, bucket, a.region); save_state(state)
    print("[2/7] CloudWatch Logs"); ensure_log_group(sess.client("logs"))
    print("[3/7] IAM"); state["instance_profile_arn"] = ensure_role(sess.client("iam"), bucket, a.region, account); save_state(state)
    print("[4/7] Security group"); vpc = default_vpc(ec2); state["vpc_id"] = vpc
    state["security_group_id"] = ensure_sg(ec2, vpc, ssh_cidr); save_state(state)
    print("[5/7] Key pair"); ensure_key(ec2, pem)
    print("[6/7] EC2 instance")
    iid = ensure_instance(ec2, sess.client("ssm"), a.instance_type, a.arch, state["security_group_id"])
    state.update({"instance_id": iid, "instance_type": a.instance_type, "arch": a.arch}); save_state(state)
    say("waiting for the instance to be running ...")
    ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
    print("[7/7] Elastic IP")
    ip, alloc = ensure_eip(ec2, iid)
    state.update({"elastic_ip": ip, "eip_allocation_id": alloc}); save_state(state)

    print("\nDone. Resource IDs saved to deploy/state.json (gitignored).")
    print(f"  Elastic IP : {ip}")
    print(f"  URL        : http://{ip}/")
    print(f"  Bucket     : {bucket}")
    print(f"  SSH        : ssh -i {pem} ec2-user@{ip}")
    print("\nWait ~2 minutes for the bootstrap (Docker install), then deploy:")
    print(f"  python deploy/deploy.py --host {ip} --key {pem}")


if __name__ == "__main__":
    main()
