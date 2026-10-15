"""Verify scientific output without requiring NumPy on the checking host."""
import json
import sys
from pathlib import Path

result = json.loads(Path(sys.argv[1]).read_text())
expected = {"count": 5, "sum": 15.0, "sum_squares": 55.0, "mean": 3.0}
for key, value in expected.items():
    if result.get(key) != value:
        raise SystemExit(f"FAIL {key}: expected {value}, got {result.get(key)!r}")
print("PASS: deterministic NumPy calculation and output retrieval")
