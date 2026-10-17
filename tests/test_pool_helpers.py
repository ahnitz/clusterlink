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

    def test_mixed_sites_use_consistent_native_admission_rules(self):
        import classad2
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'sites.json').write_text('{}')
            (state / 'pool.json').write_text('{"port":18235}')
            for slots in (0, 2):
                pool.configure(state, local_slots=slots, local_helpers=3)
                def rule(name):
                    return classad2.ExprTree(subprocess.check_output(
                        ['condor_config_val', name], env=pool.environment(state), text=True))
                routing = rule('JOB_ROUTER_SOURCE_JOB_CONSTRAINT')
                start = rule('START')
                transfer = rule('SUBMIT_REQUIREMENT_ClusterlinkCondorIO')
                capacity = rule('SUBMIT_REQUIREMENT_ClusterlinkLocalExecution')
                helpers = rule('START_LOCAL_UNIVERSE')
                for site in (None, 'clusterlink', 'condorpool_shared', 'condorpool_symlink', 'local'):
                    for eligible in (None, True, False):
                        for universe in (5, 7, 12):
                            job = classad2.ClassAd({'JobUniverse': universe, 'RemoteIwd': '/local/scratch'})
                            if site is not None:
                                job['pegasus_site'] = site
                            if eligible is not None:
                                job['ClusterlinkEligible'] = eligible
                            routed = eligible is True and universe == 5 and site in (None, 'clusterlink')
                            with self.subTest(slots=slots, site=site, eligible=eligible, universe=universe):
                                self.assertEqual(routing.eval(scope=job), routed)
                                self.assertEqual(start.eval(scope=classad2.ClassAd(), target=job), not routed)
                                self.assertEqual(transfer.eval(scope=classad2.ClassAd(), target=job), not routed)
                                self.assertEqual(capacity.eval(scope=classad2.ClassAd(), target=job),
                                                 universe != 5 or routed or bool(slots))
                self.assertTrue(helpers.eval(scope=classad2.ClassAd({'TotalLocalJobsRunning': 2})))
                self.assertFalse(helpers.eval(scope=classad2.ClassAd({'TotalLocalJobsRunning': 3})))

    def test_helper_limit_is_independent_persistent_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'sites.json').write_text('{}')
            (state / 'pool.json').write_text('{"port":18235}')
            with patch('clusterlink.pool.os.cpu_count', return_value=32):
                config = pool.configure(state).read_text()
            self.assertIn('START_LOCAL_UNIVERSE = TotalLocalJobsRunning < 8', config)
            self.assertNotIn('JOB_ROUTER STARTD', config)
            pool.configure(state, local_helpers=2, local_slots=4)
            config = pool.configure(state).read_text()
            self.assertIn('START_LOCAL_UNIVERSE = TotalLocalJobsRunning < 2', config)
            self.assertIn('NUM_CPUS = 4', config)
            before = (state / 'pool.json').read_text()
            for kwargs in ({'local_helpers': 0}, {'local_helpers': -1}, {'local_slots': -1}):
                with self.assertRaises(ValueError):
                    pool.configure(state, **kwargs)
            self.assertEqual((state / 'pool.json').read_text(), before)
