import hashlib
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import classad2
from clusterlink.hooks import prepare


class HookTests(unittest.TestCase):
    def test_native_arguments_and_cached_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / 'env'
            (env / 'bin').mkdir(parents=True)
            exe = env / 'bin/search'
            exe.write_text('#!/bin/sh\n')
            exe.chmod(0o700)
            artifact = root / 'bundle.tar.gz'
            artifact.write_bytes(b'test archive')
            ad = classad2.ClassAd({'Cmd': str(exe), 'Iwd': str(root),
                 'GlobalJobId': 'test#1.0', 'ClusterlinkEnvironment': str(env),
                 'Arguments': "'a b' 'quoted'", 'RequestCpus': 4,
                 'TransferInput': 'data.txt', 'TransferOutput': 'result.txt'})
            with patch('clusterlink.hooks.bundle', return_value=artifact), patch(
                    'clusterlink.hooks.remote_call', return_value={'cached': True}) as remote:
                out = prepare(ad, {'scheduler': 'condor'}, root)
            self.assertEqual(out['Arguments'], "'a b' 'quoted'")
            self.assertEqual(out['NodeNumber'], 4)
            self.assertEqual(out['TransferInput'], 'data.txt')
            self.assertEqual(out['TransferOutput'], 'result.txt')
            self.assertEqual(out['ClusterlinkCachedEnv'], hashlib.sha256(b'test archive').hexdigest())
            self.assertEqual(remote.call_count, 1)
            self.assertIn('bin/search', Path(out['Cmd']).read_text())

    def test_prepared_convenience_submission_is_unchanged(self):
        ad = classad2.ClassAd({'ClusterlinkRun': 'already-prepared', 'Cmd': 'launch.sh'})
        self.assertIs(prepare(ad, {}, Path('/unused')), ad)


if __name__ == '__main__':
    unittest.main()
