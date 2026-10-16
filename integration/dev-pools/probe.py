#!/usr/bin/env python
"""Small SIF environment and CondorIO round-trip probe."""
import json
import os
from pathlib import Path
import platform
import socket
import sys
import numpy as np
import pycbc

payload = json.loads(Path('input.json').read_text())
values = np.asarray(payload['values'], dtype=float)
assert np.allclose(np.fft.ifft(np.fft.fft(values)).real, values)
result = {
    'token': payload['token'],
    'sum': float(values.sum()),
    'sum_squares': float(np.dot(values, values)),
    'hostname': socket.gethostname(),
    'python': sys.executable,
    'prefix': sys.prefix,
    'glibc': platform.libc_ver(),
    'pycbc': pycbc.__version__,
    'threads': {k: os.environ.get(k) for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS')},
}
assert sys.prefix == '/opt/clusterlink/env', result
Path('result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
