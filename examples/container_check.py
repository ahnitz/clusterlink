"""Exercise PyCBC and a glibc >=2.38 symbol inside the packaged environment."""
import ctypes
import json
import os
from pathlib import Path
import platform
import socket
import sys

import numpy as np
import pycbc
from pycbc.types import TimeSeries
from pycbc.filter import matched_filter

libc = ctypes.CDLL(None)
copy = libc.strlcpy
copy.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
copy.restype = ctypes.c_size_t
buffer = ctypes.create_string_buffer(32)
assert copy(buffer, b'container-glibc', len(buffer)) == 15
assert buffer.value == b'container-glibc'
rng = np.random.default_rng(17)
series = TimeSeries(rng.normal(size=4096), delta_t=1/1024)
spectrum = series.to_frequencyseries()
restored = spectrum.to_timeseries()
assert np.allclose(series.numpy(), restored.numpy(), atol=1e-12)
snr = matched_filter(series, series, low_frequency_cutoff=20)
assert np.isfinite(snr.numpy()).all() and abs(snr).max() > 0
result = {'site':sys.argv[1], 'glibc':platform.libc_ver(), 'prefix':os.environ['CONDA_PREFIX'],
          'hostname':socket.gethostname(),
          'thread_limits':{key:os.environ.get(key) for key in
                           ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','OMP_THREAD_LIMIT')},
          'pycbc':pycbc.__version__, 'strlcpy':buffer.value.decode(),
          'fft_max_error':float(np.max(np.abs(series.numpy()-restored.numpy()))),
          'matched_filter_peak':float(abs(snr).max())}
Path('result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
