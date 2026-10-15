import json
from pathlib import Path
import tempfile
import unittest
from clusterlink.pool import configure, route_key


class PoolTests(unittest.TestCase):
    def test_hyphenated_sites_have_valid_distinct_config_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            (state/'pool.json').write_text(json.dumps({'port': 12345}))
            site={'scheduler':'condor','max_jobs':1,'max_idle':1,'root':'/home/test/.clusterlink/site'}
            names=['python-bootstrap','python_bootstrap']
            (state/'sites.json').write_text(json.dumps(dict.fromkeys(names,site)))
            text=configure(state).read_text()
            self.assertNotEqual(route_key(names[0]),route_key(names[1]))
            for name in names:
                key=route_key(name)
                self.assertRegex(key,r'^[A-Za-z_][A-Za-z0-9_]*$')
                self.assertIn('JOB_ROUTER_ROUTE_'+key+' @=route',text)
                self.assertIn('GridResource = "batch condor '+name+'"',text)
