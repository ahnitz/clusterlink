import hashlib
import io
import json
import os
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
            marker=json.dumps({'backend':'sif','rootfs_bytes':100000}).encode()
            with tarfile.open(artifact,'w:gz') as tar:
                info=tarfile.TarInfo('clusterlink-container.json');info.size=len(marker)
                tar.addfile(info,io.BytesIO(marker))
                tar.addfile(tarfile.TarInfo("environment.sif"))
            self.assertEqual(required_bundle_disk(artifact),artifact.stat().st_size+len(marker)+100000)

    def test_sif_launcher_preserves_arguments_and_failure_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);artifact=root/'bundle.tar.gz'
            fake=b'''#!/bin/bash
set -eu
while [ "$1" != /bin/bash ]; do shift; done
shift
script=${1#/work/}; shift
unset OMP_NUM_THREADS MKL_NUM_THREADS CUDA_VISIBLE_DEVICES
for name in ${!APPTAINERENV_@}; do export "${name#APPTAINERENV_}=${!name}"; done
exec /bin/bash "$script" "$@"
'''
            with tarfile.open(artifact,'w:gz') as tar:
                for name,data,mode in [('environment.sif',b'fake',0o600),('apptainer-runtime/bin/apptainer',fake,0o700),
                    ('apptainer-runtime/x86_64/etc/apptainer/apptainer.conf',b'mount devpts = yes\nmount proc = yes\n',0o600)]:
                    info=tarfile.TarInfo(name);info.size=len(data);info.mode=mode;tar.addfile(info,io.BytesIO(data))
            probe=root/'probe.sh';probe.write_text('#!/bin/bash\nprintf "%s\\n" "$CONDA_PREFIX" "$PEGASUS_PYTHON" "$1" "$2" "OMP=$OMP_NUM_THREADS" "MKL=$MKL_NUM_THREADS" "GPU=${CUDA_VISIBLE_DEVICES-unset}" > observed\nexit 7\n');probe.chmod(0o700)
            launch=root/'launch.sh';launch.write_text(launcher('./probe.sh','bundle.tar.gz',outputs=['missing.dat']))
            env={k:v for k,v in os.environ.items() if not k.startswith('APPTAINERENV_')}
            env.update(OMP_NUM_THREADS='3',MKL_NUM_THREADS='7',APPTAINERENV_MKL_NUM_THREADS='2',CUDA_VISIBLE_DEVICES='')
            result=subprocess.run(['bash',str(launch),'with spaces','literal $value'],cwd=root,capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,7,result.stderr)
            self.assertEqual((root/'observed').read_text().splitlines(),['/opt/clusterlink/env','/opt/clusterlink/env/bin/python','with spaces','literal $value','OMP=3','MKL=2','GPU='])
            self.assertTrue((root/'missing.dat').exists())
            self.assertEqual((root/'.clusterlink-env/apptainer-runtime/x86_64/etc/apptainer/apptainer.conf').read_text(),
                             'mount devpts = no\nmount proc = yes\n')

    def test_archive_without_sif_cannot_fall_back_to_conda_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / 'legacy.tar.gz'
            with tarfile.open(artifact, 'w:gz') as tar:
                tar.addfile(tarfile.TarInfo('bin/conda-unpack'))
            with self.assertRaisesRegex(ValueError, 'SIF bundle'):
                required_bundle_disk(artifact)
            result = subprocess.run(['bash'], input=launcher('touch payload-ran', archive=str(artifact)),
                                    cwd=root, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('SIF missing', result.stderr)
            self.assertFalse((root / 'payload-ran').exists())


class PreparedImageTests(unittest.TestCase):
    def test_hook_lookup_never_provisions_and_checks_cached_integrity(self):
        from clusterlink.containers import build, VERSION
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            prefix = state / 'env'
            prefix.mkdir()
            base = 'docker://fedora:43'
            with patch('clusterlink.environments.fingerprint', return_value='signature'), patch('clusterlink.containers.runtime') as runtime:
                with self.assertRaisesRegex(ValueError, 'clusterlink activate'):
                    build(prefix, state, base, allow_build=False)
                key = hashlib.sha256(json.dumps([str(prefix), 'signature', base, VERSION, 'sif-v1']).encode()).hexdigest()
                digest = hashlib.sha256(b'prepared image').hexdigest()
                artifact = state / 'artifacts' / (digest + '.tar.gz')
                artifact.write_bytes(b'prepared image')
                (state / 'artifacts' / (key + '.manifest.json')).write_text(json.dumps({'sha256': digest}))
                self.assertEqual(build(prefix, state, base, allow_build=False), artifact)
                artifact.write_bytes(b'damaged')
                with self.assertRaisesRegex(ValueError, 'clusterlink activate'):
                    build(prefix, state, base, allow_build=False)
                runtime.assert_not_called()

    def test_install_failure_keeps_output_in_log(self):
        from clusterlink.containers import runtime
        data = b'test installer'
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            def failing(command, **kwargs):
                kwargs['stdout'].write('Extracting ... details\n')
                self.assertEqual(kwargs['stderr'], subprocess.STDOUT)
                raise subprocess.CalledProcessError(1, command)
            with patch('clusterlink.containers.shutil.which', return_value='/tool'), patch('clusterlink.containers.urllib.request.urlopen', return_value=io.BytesIO(data)), patch('clusterlink.containers.INSTALLER_SHA256', hashlib.sha256(data).hexdigest()), patch('clusterlink.containers.subprocess.run', side_effect=failing):
                with self.assertRaisesRegex(RuntimeError, 'install-apptainer.log'):
                    runtime(state)
            self.assertIn('Extracting', (state / 'install-apptainer.log').read_text())
            self.assertFalse((state / 'container-runtime').exists())


class StartupOptimizationTests(unittest.TestCase):
    def test_mount_fallback_does_not_repeat_payload(self):
        for mode, payload_exit, expected_calls in [('mount', 0, 1), ('mount', 7, 1), ('fallback', 0, 2), ('fallback', 7, 2), ('fail', 0, 2)]:
            with self.subTest(mode=mode, payload_exit=payload_exit), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fake = ('#!/bin/bash\nset -eu\necho attempt >> attempts\n'
                        + ('exit 42\n' if mode == 'fail' else '')
                        + ('[[ " $* " == *" --unsquash "* ]] || exit 42\n' if mode == 'fallback' else '')
                        + 'while [ "$1" != /bin/bash ]; do shift; done\nshift\nscript=${1#/work/}; shift\nexec /bin/bash "$script" "$@"\n').encode()
                archive = root / 'bundle.tar'
                with tarfile.open(archive, 'w') as tar:
                    for name, data, permissions in [('environment.sif', b'image', 0o600), ('apptainer-runtime/bin/apptainer', fake, 0o700), ('apptainer-runtime/x86_64/etc/apptainer/apptainer.conf', b'mount devpts = yes\n', 0o600)]:
                        member = tarfile.TarInfo(name); member.size = len(data); member.mode = permissions
                        tar.addfile(member, io.BytesIO(data))
                command = f'echo payload >> executions; exit {payload_exit}'
                result = subprocess.run(['bash'], input=launcher(command, archive=str(archive)), cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 42 if mode == 'fail' else payload_exit, result.stderr)
                self.assertEqual(len((root/'attempts').read_text().splitlines()), expected_calls)
                self.assertEqual((root/'executions').exists(), mode != 'fail')
                if mode != 'fail':
                    self.assertEqual((root/'executions').read_text(), 'payload\n')
                    self.assertIn('phase=payload_start', result.stderr)
                    self.assertIn('phase=payload_end', result.stderr)
                self.assertIn('phase=bundle_ready', result.stderr)
                self.assertEqual('phase=extraction_fallback' in result.stderr, mode != 'mount')

    def test_upgrade_removes_only_outer_compression(self):
        from clusterlink.containers import uncompress_bundle
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); archive = root/'old.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for name, data in [('environment.sif', b'immutable SIF content'), ('clusterlink-container.json', b'{"backend":"sif","rootfs_bytes":100000}')]:
                    member=tarfile.TarInfo(name); member.size=len(data); tar.addfile(member,io.BytesIO(data))
            old_disk=required_bundle_disk(archive)
            plain=uncompress_bundle(archive)
            self.assertEqual(plain.suffix, '.tar')
            self.assertNotEqual(plain.read_bytes()[:2], b'\x1f\x8b')
            with tarfile.open(plain) as tar:
                self.assertEqual(tar.extractfile('environment.sif').read(), b'immutable SIF content')
            self.assertEqual(required_bundle_disk(plain), old_disk-archive.stat().st_size+plain.stat().st_size)
            self.assertTrue(archive.exists())
