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
