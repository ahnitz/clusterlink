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

    def test_progressing_upload_can_exceed_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / 'payload'
            payload.write_bytes(b'x' * (6 * 1024 * 1024))
            code = """import sys,time
sys.stdout.buffer.write(b'READY\\n'); sys.stdout.buffer.flush()
size=0
while chunk:=sys.stdin.buffer.read(1024*1024):
 size+=len(chunk);time.sleep(0.08)
print(size)
"""
            proc = subprocess.Popen([sys.executable, '-c', code],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            with patch('clusterlink.transport.start', return_value=(proc, b'READY\n')):
                result = run('test', 'command', payload=payload, timeout=0.3)
            self.assertEqual(int(result), payload.stat().st_size)

    def test_stalled_upload_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / 'payload'
            payload.write_bytes(b'x' * (2 * 1024 * 1024))
            proc = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(10)'],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            with patch('clusterlink.transport.start', return_value=(proc, b'READY\n')):
                with self.assertRaisesRegex(RuntimeError, 'without upload progress'):
                    run('test', 'command', payload=payload, timeout=0.2)
            self.assertIsNotNone(proc.poll())
