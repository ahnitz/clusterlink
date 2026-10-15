#!/bin/bash
set -euo pipefail
tar -xzf apptainer-runtime.tar.gz
mkdir -p apptainer-cache apptainer-config apptainer-tmp
export APPTAINER_CACHEDIR="$PWD/apptainer-cache"
export APPTAINER_CONFIGDIR="$PWD/apptainer-config"
export APPTAINER_TMPDIR="$PWD/apptainer-tmp"
{
 hostname
 ./apptainer-runtime/bin/apptainer --version
 printf 'host: '; getconf GNU_LIBC_VERSION
 printf 'container: '
 ./apptainer-runtime/bin/apptainer exec --unsquash --userns --cleanenv --containall ubuntu22.sif getconf GNU_LIBC_VERSION
} > result.txt 2>&1
