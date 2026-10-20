#!/usr/bin/env bash
# Disposable CI machines only. Never run this on a user's workstation.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true || ${CLUSTERLINK_DISPOSABLE_CI:-} == true ]]
channel=${1:-25.0}
sudo apt-get update
sudo apt-get install -y curl ca-certificates openssh-server rpm2cpio cpio python3-venv
curl --fail --location --retry 3 --max-time 180 https://get.htcondor.org -o /tmp/clusterlink-install-condor.sh
sudo env GET_HTCONDOR_PASSWORD=disposable-ci-only bash /tmp/clusterlink-install-condor.sh --no-dry-run --channel "$channel" --minicondor
sudo systemctl stop condor
condor_version
# No system jobs run: tests create their own unprivileged pools.
