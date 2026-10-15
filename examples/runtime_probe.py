"""Run inside a compute allocation to record its actual execution environment."""
import json
import os
import platform
import shutil
import sys

print(json.dumps({
    "hostname": platform.node(),
    "architecture": platform.machine(),
    "libc": platform.libc_ver(),
    "python": sys.version,
    "executable": sys.executable,
    "prefix": sys.prefix,
    "cwd": os.getcwd(),
    "apptainer": shutil.which("apptainer"),
    "singularity": shutil.which("singularity"),
}, indent=2))
