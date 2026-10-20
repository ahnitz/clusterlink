import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from clusterlink import gahp

class GahpStorageTests(unittest.TestCase):
    def test_native_status_cache_uses_enrolled_storage(self):
        script = next((root / 'condor_status.sh' for root in map(Path,
                      ['/usr/libexec/blahp', '/usr/lib/condor', '/usr/libexec/condor'])
                      if (root / 'condor_status.sh').exists()), None)
        if script is None:
            self.skipTest('Native HTCondor shell helpers unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'tmp').mkdir()
            (root/'glite/etc').mkdir(parents=True)
            (root/'bin').mkdir()
            query = root/'bin/condor_q'
            query.write_text('#!/bin/sh\nprintf "123,2,0,0,0,0,0,0,0\\n"\n')
            query.chmod(0o700)
            (root/'glite/etc/blah.config').write_text(f'condor_binpath={root}/bin/\nsupported_lrms=condor\n')
            (root/'sites.json').write_text(json.dumps({'test':{'root':str(root),'ssh':'alias','transport':'login'}}))
            with patch.dict(os.environ,{'CLUSTERLINK_STATE':str(root)}),patch('sys.argv',['gahp','test','blahpd']),patch('clusterlink.gahp.relay',return_value=0) as relay:
                gahp.main()
            argv=shlex.split(relay.call_args.args[1])
            overrides=dict(value.split('=',1) for value in argv[1:-1])
            self.assertEqual(overrides['GAHP_TEMP'],str(root/'tmp'))
            self.assertEqual(overrides['TMPDIR'],str(root/'tmp'))
            self.assertEqual(overrides['BLAHPD_CONFIG_LOCATION'],str(root/'glite/etc/blah.config'))
            result=subprocess.run(['bash',str(script),'condor/123//'],env={**os.environ,**overrides},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('JobStatus=2',result.stdout.replace(' ',''))
            self.assertTrue((root/'tmp/cache..').is_file())
            self.assertNotIn('No such file',result.stderr)
