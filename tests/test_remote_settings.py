import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import classad2
from clusterlink.remote_settings import select
from clusterlink.hooks import prepare, serialize
from clusterlink.job_environment import values


class RemoteSettingsTests(unittest.TestCase):
    def test_native_expressions_selection_case_and_no_source_mutation(self):
        original=classad2.ClassAd({'REMOTE_Requirements':classad2.ExprTree('TARGET.Memory > 100'),
          'remote_requirements_SU':classad2.ExprTree('TARGET.RecentDaemonCoreDutyCycle < 0.05'),
          'REMOTE_Rank_dev1':classad2.ExprTree('TARGET.KFlops'),
          'REMOTE_Custom_gpu_su':17})
        before=str(original)
        su=select(original,'su',['su','dev1','gpu_su'])
        dev=select(original,'dev1',['su','dev1','gpu_su'])
        self.assertIn('DutyCycle',str(su.lookup('REMOTE_Requirements')))
        self.assertNotIn('REMOTE_Rank',su)
        self.assertNotIn('REMOTE_Custom_gpu',su)
        self.assertIn('TARGET.Memory',str(dev.lookup('REMOTE_Requirements')))
        self.assertIn('TARGET.KFlops',str(dev.lookup('REMOTE_Rank')))
        self.assertEqual(select(original,'gpu_su',['su','gpu_su'])['REMOTE_Custom'],17)
        self.assertEqual(str(original),before)
        self.assertFalse(any(k.lower().endswith(('_su','_dev1')) for k in su))

    def test_environment_replacement_group_matches_native_precedence(self):
        ad=classad2.ClassAd({'Environment':'SOURCE=source', 'REMOTE_Environment':'GLOBAL=global',
                            'REMOTE_Env_su':'SITE=su;EMPTY=', 'REMOTE_Environment_dev1':'SITE=dev1'})
        self.assertEqual(values(select(ad,'su',['su','dev1'])),{'SITE':'su','EMPTY':''})
        self.assertEqual(values(select(ad,'dev1',['su','dev1'])),{'SITE':'dev1'})
        self.assertEqual(values(select(ad,'dev4',['su','dev1','dev4'])),{'GLOBAL':'global'})

    def test_prepare_remote_policy_resources_and_cache_extra_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prefix=root/'env';(prefix/'bin').mkdir(parents=True)
            exe=prefix/'bin/probe';exe.write_text('#!/bin/sh\n');exe.chmod(0o700)
            (root/'environment.json').write_text(json.dumps({'prefix':str(prefix),'backend':'sif'}))
            (root/'sites.json').write_text(json.dumps({'su':{},'dev1':{}}))
            artifact=root/'bundle.tar';artifact.write_bytes(b'image')
            ad=classad2.ClassAd({'Cmd':str(exe),'Iwd':tmp,'GlobalJobId':'probe#1.0',
                'Requirements':classad2.ExprTree('TARGET.Memory >= 100'), 'RequestCpus':1,
                'REMOTE_Requirements_su':classad2.ExprTree('TARGET.RecentDaemonCoreDutyCycle < 0.05'),
                'REMOTE_Rank_su':classad2.ExprTree('TARGET.KFlops'),
                'REMOTE_Environment_su':"SITE=su NOTE='space ''quote'' $literal'",
                'REMOTE_RequestCpus_su':2,'REMOTE_RequestDisk_su':1024,
                'REMOTE_Custom_su':'custom value',
                'BatchExtraSubmitArgs':'+GlobalExtra = 1',
                'REMOTE_BatchExtraSubmitArgs_su':'+SiteExtra = 2\\n+SecondExtra = 3'})
            before=str(ad)
            with patch('clusterlink.hooks.prepared_image',return_value=(artifact,hashlib.sha256(b'image').hexdigest(),4096)), patch('clusterlink.hooks.prepare_cache'):
                su=prepare(ad,{'scheduler':'condor','requirements':'TARGET.HasUserNamespaces'},root,'su')
                dev=prepare(ad,{'scheduler':'condor'},root,'dev1')
            self.assertEqual(str(ad),before)
            self.assertNotEqual(su['Cmd'],dev['Cmd'])
            self.assertEqual(su['NodeNumber'],2)
            self.assertGreater(su['RequestDisk'],1024)
            extra=su['ClusterlinkRemoteSubmitArgs']
            self.assertIn('DutyCycle',extra);self.assertIn('HasUserNamespaces',extra)
            self.assertIn('rank = TARGET.KFlops',extra)
            self.assertIn('+Custom = "custom value"',extra)
            self.assertIn('+SiteExtra = 2',extra);self.assertNotIn('+GlobalExtra',extra)
            self.assertNotIn('REMOTE_BatchExtraSubmitArgs',su)
            self.assertIn('APPTAINERENV_SITE=su',Path(su['Cmd']).read_text())
            self.assertIn('$target=2',Path(su['Cmd']).read_text())
            self.assertNotIn('APPTAINERENV_SITE=su',Path(dev['Cmd']).read_text())
            self.assertNotIn('DutyCycle',dev['ClusterlinkRemoteSubmitArgs'])
            self.assertIn('+GlobalExtra = 1',dev['ClusterlinkRemoteSubmitArgs'])
            # Parse generated lines with native condor_submit, not just string checks.
            source=root/'remote.sub'
            source.write_text('executable = /bin/true\n'+extra+'queue\n')
            proc=subprocess.run(['condor_submit','-dry-run',str(root/'remote.ad'),str(source)],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            remote=classad2.parseOne((root/'remote.ad').read_text())
            self.assertIn('DutyCycle',str(remote.lookup('Requirements')))
            self.assertEqual(remote['Custom'],'custom value')
            self.assertEqual(remote['RequestCpus'],2)
            self.assertEqual(remote['SiteExtra'],2)
            self.assertEqual(remote['SecondExtra'],3)
            # Hook protocol preserves expressions rather than evaluating TARGET locally.
            decoded=classad2.ClassAd('['+';'.join(serialize(su).splitlines())+']')
            self.assertIn('DutyCycle',str(decoded.lookup('REMOTE_Requirements')))

    def test_managed_execution_settings_are_rejected(self):
        for field in ('Cmd','Iwd','TransferInput','GridResource'):
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'managed'):
                select(classad2.ClassAd({'REMOTE_'+field+'_su':'override'}),'su',['su'])

    def test_native_submit_multiline_and_environment_expressions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/'job.sub'
            source.write_text('executable = /bin/true\n+REMOTE_BatchExtraSubmitArgs_su = strcat("+One = 1", "\\n", "+Two = 2")\n+REMOTE_Environment_su = strcat("SITE=", "su")\nqueue\n')
            result=subprocess.run(['condor_submit','-dry-run',str(root/'job.ad'),str(source)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            ad=select(classad2.parseOne((root/'job.ad').read_text()),'su',['su'])
            self.assertEqual(ad.eval('REMOTE_BatchExtraSubmitArgs').replace('\\n','\n'),'+One = 1\n+Two = 2')
            self.assertEqual(values(ad),{'SITE':'su'})
