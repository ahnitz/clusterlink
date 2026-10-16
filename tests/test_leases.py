import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from clusterlink import leases
from clusterlink.cli import flush_releases


class LeaseTests(unittest.TestCase):
    def test_release_survives_failed_contact_and_is_site_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            site = {'ssh': 'one', 'root': '/home/user/cache'}
            other = {**site, 'ssh': 'two'}
            leases.defer(state, site, 'a'*64, 'b'*64)
            leases.defer(state, site, 'a'*64, 'b'*64)
            self.assertEqual(len(leases.pending(state, site)[0]), 1)
            self.assertEqual(leases.pending(state, other), ([], []))
            with patch('clusterlink.cli.remote_call', side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):
                    flush_releases(state, site)
            self.assertEqual(leases.pending(state, site)[1], [['a'*64, 'b'*64]])
            with patch('clusterlink.cli.remote_call', return_value={'released': True}):
                flush_releases(state, site)
            self.assertEqual(leases.pending(state, site), ([], []))
