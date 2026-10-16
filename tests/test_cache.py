import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from clusterlink import remote


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / 'owned'
        for name in ['cache', 'pins']:
            (self.root / name).mkdir(parents=True)
        (self.root / 'owner.json').write_text(json.dumps({
            'cache_bytes': 8, 'storage_bytes': 10000, 'reserve_bytes': 0}))
        self.lease = 'a' * 64

    def call(self, action, *args, payload=b'', success=True):
        result = subprocess.run([sys.executable, remote.__file__, action,
                                 str(self.root), *map(str, args)], input=payload,
                                capture_output=True, env={**os.environ, 'HOME': str(self.home)})
        if success:
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def upload(self, data, **kwargs):
        digest = hashlib.sha256(data).hexdigest()
        return digest, self.call('upload', digest, len(data), self.lease, payload=data, **kwargs)

    def test_pin_release_and_eviction(self):
        digest, _ = self.upload(b'12345678')
        self.upload(b'abcdefgh', success=False)
        self.assertTrue(self.call('check', digest, self.lease)['cached'])
        self.call('release', digest, self.lease)
        replacement, _ = self.upload(b'abcdefgh')
        self.assertFalse(self.call('check', digest, self.lease)['cached'])
        self.assertTrue(self.call('check', replacement, self.lease)['cached'])

    def test_duplicate_upload_does_not_require_double_capacity(self):
        digest, _ = self.upload(b'12345678')
        result = self.call('upload', digest, 8, self.lease, payload=b'12345678')
        self.assertTrue(result['cached'])
        self.assertEqual(result['uploaded_bytes'], 0)

    def test_corruption_is_detected(self):
        digest, _ = self.upload(b'12345678')
        (self.root / 'cache' / (digest + '.tar.gz')).write_bytes(b'corrupt!')
        result = self.call('check', digest, self.lease, success=False)
        self.assertIn(b'checksum mismatch', result.stderr)

    def test_failed_upload_does_not_publish_partial_artifact(self):
        digest = hashlib.sha256(b'12345678').hexdigest()
        self.call('upload', digest, 8, self.lease, payload=b'bad', success=False)
        self.assertEqual(list((self.root / 'cache').iterdir()), [])

    def visible_source(self, data=b'12345678'):
        other = self.home / 'other'
        (other / 'cache').mkdir(parents=True)
        (other / 'owner.json').write_text('{}')
        digest = hashlib.sha256(data).hexdigest()
        (other / 'cache' / (digest + '.tar.gz')).write_bytes(data)
        return other, digest

    def test_visible_enrolled_cache_reused_with_lease(self):
        other, digest = self.visible_source()
        result = self.call('reuse', digest, json.dumps([str(other)]), self.lease)
        self.assertTrue(result['cached'])
        self.assertEqual(result['uploaded_bytes'], 0)
        self.assertEqual(result['reused_bytes'], 8)
        self.assertEqual((self.root/'cache'/(digest+'.tar.gz')).read_bytes(), b'12345678')
        self.assertTrue((self.root/'leases'/digest/self.lease).exists())

    def test_reuse_obeys_budget_and_checksums(self):
        other, digest = self.visible_source(b'123456789')
        self.call('reuse', digest, json.dumps([str(other)]), self.lease, success=False)
        candidate = other/'cache'/(digest+'.tar.gz')
        candidate.write_bytes(b'bad')
        self.call('reuse', digest, json.dumps([str(other)]), self.lease, success=False)
        self.assertEqual(list((self.root/'cache').iterdir()), [])

    def test_reuse_missing_or_outside_home_falls_back(self):
        digest = hashlib.sha256(b'12345678').hexdigest()
        result = self.call('reuse', digest, json.dumps(['/tmp', str(self.home/'absent')]), self.lease)
        self.assertFalse(result['cached'])

    def test_reuse_rejects_cache_directory_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            digest = hashlib.sha256(b'12345678').hexdigest()
            (Path(outside)/(digest+'.tar.gz')).write_bytes(b'12345678')
            other = self.home/'linked'
            other.mkdir()
            (other/'owner.json').write_text('{}')
            (other/'cache').symlink_to(outside, target_is_directory=True)
            result = self.call('reuse', digest, json.dumps([str(other)]), self.lease)
            self.assertFalse(result['cached'])


if __name__ == '__main__':
    unittest.main()
