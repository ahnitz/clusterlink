import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from clusterlink.containers import default_base
from clusterlink.environments import launcher, required_bundle_disk


class ContainerTests(unittest.TestCase):
    def test_base_tracks_host_distribution_not_remote_glibc(self):
        with patch('platform.freedesktop_os_release',return_value={'ID':'fedora','VERSION_ID':'43'}):
            self.assertEqual(default_base(),'docker://fedora:43')
        with patch('platform.freedesktop_os_release',return_value={'ID':'unknown'}),self.assertRaises(ValueError):
            default_base()

    def test_container_disk_includes_unsquashed_rootfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact=Path(tmp)/'image.tar.gz'
            marker=json.dumps({'rootfs_bytes':100000}).encode()
            with tarfile.open(artifact,'w:gz') as tar:
                info=tarfile.TarInfo('clusterlink-container.json');info.size=len(marker)
                tar.addfile(info,io.BytesIO(marker))
            self.assertEqual(required_bundle_disk(artifact),artifact.stat().st_size+len(marker)+100000)

    def test_sif_launcher_preserves_arguments_and_failure_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);artifact=root/'bundle.tar.gz'
            fake=b'''#!/bin/bash
set -eu
while [ "$1" != /bin/bash ]; do shift; done
shift
script=${1#/work/}; shift
exec /bin/bash "$script" "$@"
'''
            with tarfile.open(artifact,'w:gz') as tar:
                for name,data,mode in [('environment.sif',b'fake',0o600),('apptainer-runtime/bin/apptainer',fake,0o700),
                    ('apptainer-runtime/x86_64/etc/apptainer/apptainer.conf',b'mount devpts = yes\nmount proc = yes\n',0o600)]:
                    info=tarfile.TarInfo(name);info.size=len(data);info.mode=mode;tar.addfile(info,io.BytesIO(data))
            probe=root/'probe.sh';probe.write_text('#!/bin/bash\nprintf "%s\\n" "$CONDA_PREFIX" "$PEGASUS_PYTHON" "$1" "$2" > observed\nexit 7\n');probe.chmod(0o700)
            launch=root/'launch.sh';launch.write_text(launcher('./probe.sh','bundle.tar.gz',outputs=['missing.dat']))
            result=subprocess.run(['bash',str(launch),'with spaces','literal $value'],cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,7,result.stderr)
            self.assertEqual((root/'observed').read_text().splitlines(),['/opt/clusterlink/env','/opt/clusterlink/env/bin/python','with spaces','literal $value'])
            self.assertTrue((root/'missing.dat').exists())
            self.assertEqual((root/'.clusterlink-env/apptainer-runtime/x86_64/etc/apptainer/apptainer.conf').read_text(),
                             'mount devpts = no\nmount proc = yes\n')
