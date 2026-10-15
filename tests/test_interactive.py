import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from clusterlink.interactive import resolve


class InteractiveTests(unittest.TestCase):
    def test_resolves_routed_condor_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            (state/'sites.json').write_text(json.dumps({'one': {'scheduler':'condor','ssh':'alias'}}))
            with patch('clusterlink.interactive.query', side_effect=[
                    {'RoutedToJobId':'2.0'}, {'ClusterlinkDestination':'one',
                     'GridJobId':'batch condor sandbox condor/12345//'}]):
                site, cmd = resolve(state,'1.0')
            self.assertEqual(site['ssh'],'alias')
            self.assertEqual(cmd,['condor_ssh_to_job','-shells','/bin/sh','-ssh','ssh -tt','12345.0'])

    def test_pending_job_has_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            (state/'sites.json').write_text('{}')
            with patch('clusterlink.interactive.query',return_value={}):
                with self.assertRaisesRegex(ValueError,'not yet been routed'):
                    resolve(state,'1.0')


if __name__ == '__main__':
    unittest.main()
