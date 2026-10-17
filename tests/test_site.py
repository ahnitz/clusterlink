import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from clusterlink.cli import main


class SiteTests(unittest.TestCase):
    def test_queue_limits_preserve_disabled_site_and_remote_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'pool.json').write_text(json.dumps({'port':43779}))
            site={'scheduler':'condor','root':'/home/user/cache','max_jobs':10,'max_idle':2,'enabled':False}
            path=root/'sites.json';path.write_text(json.dumps({'test':site}))
            argv=['clusterlink','--state',tmp,'site','limits','test','--max-jobs','20','--max-idle','10']
            with patch('sys.argv',argv),patch('clusterlink.pool.running',return_value=False):
                main()
            updated=json.loads(path.read_text())['test']
            self.assertEqual(updated,{**site,'max_jobs':20,'max_idle':10})
            text=(root/'condor.config').read_text()
            self.assertIn('REQUIREMENTS False',text)
            before=path.read_text()
            with patch('sys.argv',argv[:-1]+['21']),self.assertRaises(SystemExit):
                main()
            self.assertEqual(path.read_text(),before)

    def test_unlimited_route_limits_and_large_finite_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'pool.json').write_text(json.dumps({'port':43779}))
            path = root/'sites.json'
            path.write_text(json.dumps({'test': {'scheduler':'slurm', 'root':'/home/user/cache', 'max_jobs':10, 'max_idle':2}}))
            for maximum, idle, expected_max, expected_idle in [('unlimited', 'unlimited', 2147483647, -1), ('5000', '500', 5000, 500)]:
                argv = ['clusterlink','--state',tmp,'site','limits','test','--max-jobs',maximum,'--max-idle',idle]
                with patch('sys.argv',argv), patch('clusterlink.pool.running',return_value=False):
                    main()
                config = (root/'condor.config').read_text()
                self.assertIn(f'MaxJobs = {expected_max}', config)
                self.assertIn(f'MaxIdleJobs = {expected_idle}', config)

    def test_enrollment_parser_accepts_explicit_limits_and_preservation_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extra, expected in [([], (None, None)), (['--max-jobs','5000','--max-idle','500'], (5000, 500)), (['--max-jobs','unlimited','--max-idle','unlimited'], (-1, -1))]:
                argv = ['clusterlink','--state',tmp,'enroll','test','--ssh','test','--cache-gb','2','--storage-gb','5'] + extra
                with patch('sys.argv',argv), patch('clusterlink.cli.enroll') as enroll, patch('clusterlink.pool.configure'):
                    main()
                args = enroll.call_args.args[0]
                self.assertEqual((args.max_jobs, args.max_idle), expected)

    def test_native_policy_validation_and_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'pool.json').write_text(json.dumps({'port':43779}))
            path=root/'sites.json'
            site={'scheduler':'condor','root':'/home/user/cache','max_jobs':10,'max_idle':2}
            path.write_text(json.dumps({'test':site}))
            argv=['clusterlink','--state',tmp,'site','policy','test','--requirements','TARGET.Memory >= 1024','--rank','TARGET.KFlops']
            with patch('sys.argv',argv), patch('clusterlink.pool.running',return_value=False):
                main()
            updated=json.loads(path.read_text())['test']
            self.assertIn('TARGET.Memory',updated['requirements'])
            self.assertEqual(updated['rank'],'TARGET.KFlops')
            self.assertEqual(updated['max_idle'],2)
            before=path.read_text()
            with patch('sys.argv',argv[:-1]+['(invalid']), self.assertRaises(SystemExit):
                main()
            self.assertEqual(path.read_text(),before)
