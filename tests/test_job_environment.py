import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import classad2
from clusterlink.job_environment import values
from clusterlink.environments import launcher


class EnvironmentTests(unittest.TestCase):
    def test_native_submit_encoding(self):
        # Use Condor's own encoder to verify decoding of its ClassAd form.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'job.sub'
            source.write_text('executable = /bin/true\nenvironment = "one=1 two=""2"" three=\'spacey \'\'quoted\'\' value\' empty= literal=\'$(touch bad); `bad` \\ value\'"\nqueue\n')
            result = subprocess.run(['condor_submit', '-dry-run', str(root/'ad'), str(source)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            job = classad2.parseOne((root/'ad').read_text())
        self.assertEqual(values(job), {'one':'1','two':'"2"','three':"spacey 'quoted' value",'empty':'','literal':'$(touch bad); `bad` \\ value'})

    def test_old_and_remote_encodings(self):
        self.assertEqual(values({'Env':'A=one|B=two=three|EMPTY=', 'EnvDelim':'|'}),
                         {'A':'one','B':'two=three','EMPTY':''})
        self.assertEqual(values({'Environment':'A=source','REMOTE_Env':'A=remote'}), {'A':'remote'})
        with self.assertRaises(ValueError):
            values({'Environment':"A='unfinished"})

    def test_payload_defaults_and_explicit_overrides(self):
        for cpus, explicit in [(1, {}), (4, {}), (2, {'OMP_NUM_THREADS':'3', 'APPTAINERENV_MKL_NUM_THREADS':'7', 'SINGULARITYENV_MKL_NUM_THREADS':'9', 'EMPTY':'', 'TEXT':"spaces ' quotes $(touch bad)\nline2"})]:
            with self.subTest(cpus=cpus, explicit=explicit), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                fake=b'''#!/bin/bash
set -eu
while [ "$1" != /bin/bash ]; do shift; done
shift
script=${1#/work/}; shift
for name in ${!APPTAINERENV_@}; do export "${name#APPTAINERENV_}=${!name}"; done
exec /bin/bash "$script" "$@"
'''
                artifact=root/'bundle.tar'
                with tarfile.open(artifact,'w') as tar:
                    for name,data,mode in [('environment.sif',b'image',0o600),('apptainer-runtime/bin/apptainer',fake,0o700),('apptainer-runtime/x/etc/apptainer/apptainer.conf',b'mount devpts = yes\n',0o600)]:
                        member=tarfile.TarInfo(name);member.size=len(data);member.mode=mode
                        tar.addfile(member,io.BytesIO(data))
                command='printf "%s\\n" "$OMP_NUM_THREADS" "$MKL_NUM_THREADS" "$OPENBLAS_NUM_THREADS" "$NUMEXPR_NUM_THREADS" "$VECLIB_MAXIMUM_THREADS" > observed; printf "%s" "${TEXT-}" > text'
                script=launcher(command, str(artifact), cpus=cpus, environment=explicit)
                clean={k:v for k,v in os.environ.items() if not k.startswith(('APPTAINERENV_', 'SINGULARITYENV_')) and k not in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')}
                result=subprocess.run(['bash'],input=script,cwd=root,env=clean,text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual((root/'observed').read_text().splitlines(), [explicit.get('OMP_NUM_THREADS',str(cpus)),explicit.get('APPTAINERENV_MKL_NUM_THREADS',str(cpus)),str(cpus),str(cpus),str(cpus)])
                self.assertEqual((root/'text').read_text(),explicit.get('TEXT',''))
                self.assertFalse((root/'bad').exists())
