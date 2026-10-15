#!/bin/bash
set -eu
mkdir -p nested
printf 'nested-transfer-ok\n' > nested/result.txt
hostname
command -v apptainer || command -v singularity || true
apptainer --version || true
unshare -Ur true && echo USERNS_OK || echo USERNS_UNAVAILABLE
