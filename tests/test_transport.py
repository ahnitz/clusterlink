import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from clusterlink.transport import run


class StreamingTests(unittest.TestCase):
    def test_large_file_stream_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / 'payload'
            payload.write_bytes(bytes(range(256)) * 8192)
            proc = subprocess.Popen([sys.executable, '-c',
                'import sys;sys.stdout.buffer.write(b"READY\\n");'
                'sys.stdout.buffer.write(sys.stdin.buffer.read())'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            with patch('clusterlink.transport.start', return_value=(proc, b'READY\n')):
                result = run('test', 'command', payload=payload, timeout=10)
            self.assertEqual(result, payload.read_bytes())
