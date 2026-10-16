import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from clusterlink.cli import main
from clusterlink.status import collect, render


class StatusTests(unittest.TestCase):
    def test_uninitialized_status_does_not_create_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'absent'
            output = io.StringIO()
            with patch('sys.argv', ['clusterlink', '--state', str(state), 'status', '--json']), contextlib.redirect_stdout(output):
                main()
            report = json.loads(output.getvalue())
            self.assertEqual(report['sites'], [])
            self.assertFalse(report['pool']['configured'])
            self.assertFalse(state.exists())

    def test_offline_overview_reports_selection_not_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            selected = state / 'science'; (selected / 'conda-meta').mkdir(parents=True)
            (state / 'environment.json').write_text(json.dumps({'prefix': str(selected), 'backend': 'sif'}))
            (state / 'sites.json').write_text(json.dumps({'test': {'ssh':'my-alias','scheduler':'condor','enabled':False,'root':'/home/user/cache','max_jobs':10,'max_idle':2,'limits':{'cache_bytes':5e9,'storage_bytes':10e9}}}))
            with patch.dict('os.environ', {'CONDA_PREFIX': str(state/'other')}), patch('clusterlink.cli.remote_call') as remote:
                result = collect(state)
            remote.assert_not_called()
            self.assertFalse(result['environment']['shell_matches_selection'])
            self.assertEqual(result['environment']['packaging'], 'automatic SIF')
            self.assertEqual(result['environment']['prefix'], str(selected))
            text = render(result)
            self.assertIn('disabled for new jobs', text)
            self.assertIn('cache 5 GB', text)
            self.assertIn('Shell Conda environment differs:', text)

    def test_remote_failure_keeps_other_sites_and_local_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            site = {'ssh':'alias','scheduler':'condor','root':'/home/user/cache','max_jobs':10,'max_idle':2}
            (state/'sites.json').write_text(json.dumps({'a':site,'b':site}))
            usage = {'cache_used_bytes':10,'total_bytes':20,'active_leases':0}
            with patch('clusterlink.cli.flush_releases') as flush, patch('clusterlink.cli.remote_call', side_effect=[RuntimeError('unreachable'),usage]):
                result = collect(state, remote=True)
            self.assertEqual(flush.call_count, 2)
            self.assertEqual(result['sites'][0]['remote_error'], 'unreachable')
            self.assertEqual(result['sites'][1]['remote'], usage)
            self.assertIn('Live usage:', render(result))
