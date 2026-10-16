import json
import hashlib
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import classad2
from clusterlink.hooks import prepare, serialize, remote_output_settings


class HookTests(unittest.TestCase):
    def test_nested_outputs_survive_remote_condor_transfer(self):
        self.assertEqual(remote_output_settings('118674/result.hdf,plain.txt'),
                         'transfer_output_files = 118674/result.hdf,plain.txt\n')
        self.assertEqual(remote_output_settings('plain.txt'), '')
        for invalid in ('a/result.hdf,b/result.hdf', '../result.hdf', '/tmp/result.hdf'):
            with self.assertRaises(ValueError):
                remote_output_settings(invalid)

    def test_native_arguments_and_cached_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / 'env'
            (env / 'bin').mkdir(parents=True)
            exe = env / 'bin/search'
            exe.write_text('#!/bin/sh\n')
            exe.chmod(0o700)
            (root / 'environment.json').write_text(json.dumps({'prefix':str(env),'backend':'sif'}))
            artifact = root / 'bundle.tar.gz'
            artifact.write_bytes(b'test archive')
            ad = classad2.ClassAd({'Cmd': str(exe), 'Iwd': str(root),
                 'GlobalJobId': 'test#1.0', 'ClusterlinkEnvironment': str(env),
                 'ClusterlinkArtifact': classad2.Value.Undefined,
                 'BatchExtraSubmitArgs': '+UserChosenAttribute = "preserved"',
                 'Arguments': "'a b' 'quoted'", 'RequestCpus': 4,
                 'TransferInput': 'data.txt', 'TransferOutput': 'nested/result.txt',
                 'TransferOutputRemaps': 'result.txt=nested/result.txt'})
            with patch('clusterlink.hooks.required_bundle_disk', return_value=2048), patch('clusterlink.hooks.bundle', return_value=artifact) as bundle, patch(
                    'clusterlink.hooks.remote_call', return_value={'cached': True}) as remote:
                out = prepare(ad, {'scheduler': 'condor'}, root)
            bundle.assert_called_once_with(str(env), root, base=None, allow_build=False)
            self.assertEqual(out['Arguments'], "'a b' 'quoted'")
            self.assertEqual(out['NodeNumber'], 4)
            self.assertIn('+UserChosenAttribute = "preserved"\n', out['ClusterlinkRemoteSubmitArgs'])
            self.assertGreaterEqual(out['RequestDisk'], 65538)
            self.assertEqual(out['TransferInput'], 'data.txt')
            self.assertEqual(out['TransferOutput'], 'result.txt')
            self.assertEqual(out['ClusterlinkOutputRemaps'], 'result.txt=nested/result.txt')
            self.assertEqual(out['ClusterlinkCachedEnv'], hashlib.sha256(b'test archive').hexdigest())
            self.assertEqual(remote.call_count, 1)
            self.assertIn('bin/search', Path(out['Cmd']).read_text())

    def test_multiline_values_survive_line_oriented_hook_reader(self):
        original = classad2.ClassAd({'ClusterlinkRemoteSubmitArgs':
            'request_disk = 1024 KB\nrequirements = (OpSys == "LINUX")\n'})
        wire = serialize(original)
        self.assertEqual(len(wire.splitlines()), 1)
        decoded = classad2.parseOne("[" + wire + "]", parser=classad2.Parser.New)
        self.assertEqual(decoded['ClusterlinkRemoteSubmitArgs'],
                         original['ClusterlinkRemoteSubmitArgs'])

    def test_archive_backend_and_environment_overrides_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'environment.json').write_text(json.dumps({'prefix':tmp,'backend':'sif'}))
            for override in ({'ClusterlinkArtifact': '/old/archive.tar.gz'},
                             {'ClusterlinkBackend': 'conda'},
                             {'ClusterlinkEnvironment': '/different/env'}):
                with self.subTest(override=override), self.assertRaises(ValueError), patch('clusterlink.hooks.bundle') as build:
                    prepare(classad2.ClassAd(override), {}, root)
                build.assert_not_called()

    def test_hold_counters_and_nested_lists_survive_hook_serialization(self):
        ad = classad2.ClassAd({'NumHoldsByReason': classad2.ClassAd({'UserRequest': 1}),
             'Items': [classad2.ClassAd({'message': 'line one\nline two'}), 2]})
        wire = serialize(ad)
        self.assertEqual(len(wire.splitlines()), 2)
        decoded = classad2.parseOne('[' + ';'.join(wire.splitlines()) + ']',
                                    parser=classad2.Parser.New)
        self.assertEqual(decoded['NumHoldsByReason']['UserRequest'], 1)
        self.assertEqual(decoded['Items'][0]['message'], 'line one\nline two')



if __name__ == '__main__':
    unittest.main()
