import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from clusterlink.hooks import prepare_cache


class CacheBatchTests(unittest.TestCase):
    def test_waiting_jobs_share_check_but_keep_individual_leases(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);site={'ssh':'test','root':'/test'};digest='a'*64
            key=hashlib.sha256(json.dumps(site,sort_keys=True).encode()).hexdigest()
            identities=[hashlib.sha256(str(i).encode()).hexdigest() for i in range(20)]
            with patch('clusterlink.hooks.remote_call',return_value={'cached':True}) as remote, ThreadPoolExecutor(max_workers=20) as executor:
                with (state/('.upload-'+key+'.lock')).open('a') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX)
                    futures=[executor.submit(prepare_cache,site,state,state/'unused',digest,ident) for ident in identities]
                    until=time.monotonic()+5
                    requests=state/'cache-requests'/key/digest
                    while len(list(requests.glob('*.request')))<20 and time.monotonic()<until:
                        time.sleep(.005)
                    fcntl.flock(lock,fcntl.LOCK_UN)
                for future in futures: future.result(timeout=5)
            self.assertEqual(remote.call_count,1)
            args=remote.call_args.args
            self.assertEqual({args[3],*json.loads(args[5])},set(identities))
            self.assertEqual(list(requests.iterdir()),[])

    def test_failed_check_does_not_publish_acknowledgment(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            with patch('clusterlink.hooks.remote_call',side_effect=RuntimeError('offline')):
                with self.assertRaisesRegex(RuntimeError,'offline'):
                    prepare_cache({'ssh':'test'},state,state/'unused','a'*64,'b'*64)
            self.assertEqual(list(state.rglob('*.ready')),[])

    def test_cold_cache_upload_pins_followers_before_acknowledgment(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);site={'ssh':'test','root':'/test'};digest='a'*64
            key=hashlib.sha256(json.dumps(site,sort_keys=True).encode()).hexdigest()
            requests=state/'cache-requests'/key/digest;requests.mkdir(parents=True)
            (requests/('c'*64+'.request')).touch()
            (state/'sites.json').write_text(json.dumps({'test':site}))
            artifact=state/'image';artifact.write_bytes(b'image')
            with patch('clusterlink.hooks.remote_call',side_effect=[{'cached':False},{'cached':True},{'cached':True}]) as remote:
                prepare_cache(site,state,artifact,digest,'b'*64)
                prepare_cache(site,state,artifact,digest,'c'*64)
            self.assertEqual([call.args[1] for call in remote.call_args_list],['check','upload','check'])
            self.assertEqual(json.loads(remote.call_args_list[-1].args[5]),['c'*64])
            self.assertEqual(list(requests.iterdir()),[])
