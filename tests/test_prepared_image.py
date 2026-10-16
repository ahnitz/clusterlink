import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import classad2
from clusterlink.environments import publish_prepared, prepared_image
from clusterlink.hooks import prepare


class PreparedSnapshotTests(unittest.TestCase):
    def snapshot(self, root):
        env = root / 'env'
        (env / 'bin').mkdir(parents=True)
        exe = env / 'bin' / 'search'
        exe.write_text('#!/bin/sh\nexit 0\n')
        exe.chmod(0o700)
        selection = {'prefix': str(env), 'backend': 'sif'}
        (root / 'environment.json').write_text(json.dumps(selection))
        (root / 'artifacts').mkdir()
        data = b'fixture image'
        digest = hashlib.sha256(data).hexdigest()
        artifact = root / 'artifacts' / (digest + '.tar.gz')
        artifact.write_bytes(data)
        artifact.with_suffix('.disk.json').write_text('{"bytes":4096}')
        publish_prepared(root, selection, artifact)
        return selection, artifact, digest, exe

    def test_parallel_hooks_ignore_build_lock_and_never_walk_or_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, artifact, digest, exe = self.snapshot(root)
            def run(number):
                ad = classad2.ClassAd({'Cmd': str(exe), 'Iwd': str(root),
                                      'GlobalJobId': f'test#{number}.0'})
                return prepare(ad, {'scheduler': 'condor', 'root': f'/remote/site{number % 4}'}, root)
            with (root / '.pack.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch('clusterlink.environments.fingerprint', side_effect=AssertionError('walk')), patch('hashlib.file_digest', side_effect=AssertionError('hash')), patch('clusterlink.hooks.remote_call', return_value={'cached': True}), ThreadPoolExecutor(max_workers=4) as executor:
                    results = list(executor.map(run, range(64)))
            self.assertEqual(len(results), 64)
            self.assertTrue(all(ad['ClusterlinkCachedEnv'] == digest for ad in results))

    def test_missing_changed_or_different_selection_requires_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, artifact, digest, exe = self.snapshot(root)
            self.assertEqual(prepared_image(root, selection), (artifact, digest, 4096))
            with self.assertRaisesRegex(ValueError, 'clusterlink activate'):
                prepared_image(root, {**selection, 'container_base': 'different'})
            artifact.write_bytes(b'changed image')
            with self.assertRaisesRegex(ValueError, 'clusterlink activate'):
                prepared_image(root, selection)
            (root / 'prepared-image.json').unlink()
            with self.assertRaisesRegex(ValueError, 'clusterlink activate'):
                prepared_image(root, selection)

    def test_source_edits_do_not_change_published_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, artifact, digest, exe = self.snapshot(root)
            exe.write_text('source changed after activation')
            self.assertEqual(prepared_image(root, selection), (artifact, digest, 4096))
