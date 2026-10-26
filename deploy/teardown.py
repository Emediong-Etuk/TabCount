"""Delete every TabCount AWS resource listed in deploy/state.json.

    python deploy/teardown.py [--profile myprofile]

!!! DO NOT RUN BEFORE NOV 10, 2026: judges need the live endpoint until
!!! judging ends on Nov 9, 2026. You must type the bucket name to confirm.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import ClientError
except ModuleNotFoundError:
    raise SystemExit(
        "boto3 is not installed for this Python. Use the project venv (PowerShell):\n"
        "  py -3.12 -m venv .venv\n"
        "  .venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt\n"
        "  .venv\\Scripts\\python.exe " + __file__.replace("\\", "/").split("/")[-2] + "/" + __file__.replace("\\", "/").split("/")[-1] + " ...")

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
SAFE_AFTER = dt.date(2026, 11, 10)


def step(msg, fn, *args, **kw):
    try:
        fn(*args, **kw)
        print(f"  deleted: {msg}")
    except ClientError as e:
        print(f"  skip ({e.response['Error']['Code']}): {msg}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--keep-bucket", action="store_true", help="keep the S3 bucket and its objects")
    ap.add_argument("--i-know-judging-is-not-over", action="store_true")
    a = ap.parse_args()

    banner = "!" * 72
    print(f"\n{banner}\n!!  TEARDOWN deletes the live TabCount endpoint and its data.\n"
          f"!!  DO NOT run this before {SAFE_AFTER:%b %d, %Y}: judging ends Nov 9, 2026.\n{banner}\n")
    if dt.date.today() < SAFE_AFTER and not a.i_know_judging_is_not_over:
        sys.exit(f"Refusing: today is {dt.date.today()}, before {SAFE_AFTER}. "
                 "(Override with --i-know-judging-is-not-over.)")
    if not STATE.exists():
        sys.exit("deploy/state.json not found; nothing to delete (or delete by hand in the console).")
    st = json.loads(STATE.read_text())
    print(json.dumps(st, indent=2))
    if input(f'\nType the bucket name ({st.get("bucket")}) to confirm deletion: ').strip() != st.get("bucket"):
        sys.exit("aborted, nothing deleted")

    sess = boto3.Session(profile_name=a.profile, region_name=st["region"])
    ec2, iam, s3, logs = (sess.client(x) for x in ("ec2", "iam", "s3", "logs"))

    if st.get("instance_id"):
        step(f"instance {st['instance_id']}", ec2.terminate_instances, InstanceIds=[st["instance_id"]])
        print("  waiting for termination ...")
        ec2.get_waiter("instance_terminated").wait(InstanceIds=[st["instance_id"]])
    if st.get("eip_allocation_id"):
        step(f"Elastic IP {st.get('elastic_ip')}", ec2.release_address, AllocationId=st["eip_allocation_id"])
    if st.get("security_group_id"):
        step(f"security group {st['security_group_id']}", ec2.delete_security_group, GroupId=st["security_group_id"])
    if st.get("key_name"):
        step(f"key pair {st['key_name']}", ec2.delete_key_pair, KeyName=st["key_name"])
    role, prof = st.get("role"), st.get("instance_profile")
    if prof and role:
        step("role from instance profile", iam.remove_role_from_instance_profile, InstanceProfileName=prof, RoleName=role)
        step(f"instance profile {prof}", iam.delete_instance_profile, InstanceProfileName=prof)
    if role:
        step("inline role policy", iam.delete_role_policy, RoleName=role, PolicyName="tabcount-least-privilege")
        step(f"IAM role {role}", iam.delete_role, RoleName=role)
    if st.get("log_group"):
        step(f"log group {st['log_group']}", logs.delete_log_group, logGroupName=st["log_group"])
    if st.get("bucket") and not a.keep_bucket:
        b = sess.resource("s3").Bucket(st["bucket"])
        try:
            b.objects.all().delete()
            b.object_versions.all().delete()
        except ClientError as e:
            print(f"  could not empty bucket: {e}")
        step(f"bucket {st['bucket']}", s3.delete_bucket, Bucket=st["bucket"])
    STATE.rename(STATE.with_suffix(".deleted.json"))
    print("\nTeardown complete. The local .pem file was left in place; delete it yourself.")


if __name__ == "__main__":
    main()
