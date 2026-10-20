"""Stream command output and expose bounded failure details in CI annotations."""
from collections import deque
import subprocess
import sys

lines = deque(maxlen=100)
with subprocess.Popen(sys.argv[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      text=True, bufsize=1) as process:
    for line in process.stdout:
        print(line, end='', flush=True)
        lines.append(line)
    code = process.wait()
if code:
    details = ''.join(lines)[-16000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print('::error title=Integration command failed::' + details, flush=True)
sys.exit(code)
