#!/usr/bin/env python3
"""Validate an intermediate scientific result and retain both execution hosts."""
import json
from pathlib import Path
import socket
import sys

result=json.loads(Path(sys.argv[1]).read_text())
assert {key: result[key] for key in ['count','sum','sum_squares','mean']} == {
    'count':5,'sum':15.0,'sum_squares':55.0,'mean':3.0}
result['second_hostname']=socket.gethostname()
result['second_executable']=sys.executable
Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
