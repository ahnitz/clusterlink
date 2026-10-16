import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from clusterlink import pool


class PoolHelperTests(unittest.TestCase):
    def test_cleanup_protocol_survives_broken_exported_shell_functions(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'sites.json').write_text('{}')
            (state / 'pool.json').write_text('{"port":18235}')
            pool.configure(state)
            environment = {**os.environ, 'BASH_FUNC_ml%%': '() { echo broken',
                           'BASH_FUNC_module%%': '() { if true; then'}
            result = subprocess.run([str(state / 'cleanup-job')], input='[]',
                                    env=environment, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr, '')
            with patch.dict(os.environ, environment):
                clean = pool.environment(state)
            self.assertFalse(any(k.startswith('BASH_FUNC_') for k in clean))
            self.assertEqual(clean.get('SSH_AUTH_SOCK'), environment.get('SSH_AUTH_SOCK'))

    def test_resource_detection_and_explicit_slots_survive_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'sites.json').write_text('{}')
            (state / 'pool.json').write_text('{"port":18235}')
            pool.configure(state)
            def value(key):
                return subprocess.run(['condor_config_val', key], env=pool.environment(state),
                                      text=True, capture_output=True)
            config = (state / 'condor.config').read_text()
            self.assertFalse(any(line.startswith(('MEMORY =', 'NUM_CPUS ='))
                                 for line in config.splitlines()))
            pool.configure(state, local_slots=3)
            pool.configure(state)
            self.assertEqual(value('NUM_CPUS').stdout.strip(), '3')
            self.assertEqual(json.loads((state / 'pool.json').read_text())['local_slots'], 3)

    def test_native_submit_rule_rejects_remote_scratch_only_for_routed_jobs(self):
        import classad2
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'sites.json').write_text('{}')
            (state / 'pool.json').write_text('{"port":18235}')
            pool.configure(state)
            expression = subprocess.check_output(
                ['condor_config_val', 'SUBMIT_REQUIREMENT_ClusterlinkCondorIO'],
                env=pool.environment(state), text=True)
            rule = classad2.ExprTree(expression)
            for universe, eligible, attribute, expected in [
                (5, True, 'RemoteIwd', False),
                (5, True, 'REMOTE_Iwd', False),
                (5, True, 'Iwd', True),
                (12, True, 'RemoteIwd', True),
                (5, False, 'RemoteIwd', True),
            ]:
                job = classad2.ClassAd({'JobUniverse': universe, 'ClusterlinkEligible': eligible,
                                       attribute: '/submit-host/scratch'})
                with self.subTest(universe=universe, eligible=eligible, attribute=attribute):
                    self.assertEqual(rule.eval(scope=classad2.ClassAd(), target=job), expected)
