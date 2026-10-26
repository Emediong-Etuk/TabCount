#!/bin/bash
# EC2 bootstrap for TabCount (Amazon Linux 2023). Runs once at first boot as root.
set -euxo pipefail
dnf install -y docker tar rsync
systemctl enable --now docker
usermod -aG docker ec2-user
echo "tabcount bootstrap done" > /var/log/tabcount-bootstrap.log
