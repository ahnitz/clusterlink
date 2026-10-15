#!/usr/bin/env python3
"""Small deterministic payload; requires NumPy from the packaged environment."""
import argparse
import json
import platform
import sys
from pathlib import Path

import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("input", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
values = np.asarray(json.loads(args.input.read_text())["values"], dtype=np.float64)
result = {
    "count": int(values.size),
    "sum": float(values.sum()),
    "sum_squares": float(np.dot(values, values)),
    "mean": float(values.mean()),
    "python": sys.version,
    "executable": sys.executable,
    "prefix": sys.prefix,
    "numpy": np.__version__,
    "numpy_file": np.__file__,
    "hostname": platform.node(),
}
args.output.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, sort_keys=True))
