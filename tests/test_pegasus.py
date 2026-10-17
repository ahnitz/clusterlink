import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from clusterlink import pegasus


class PegasusTests(unittest.TestCase):
    def test_complete_environment_needs_no_host_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'bin').mkdir()
            for name in pegasus.TOOLS:
                path=root/'bin'/name;path.write_text('#!/bin/sh\n');path.chmod(0o700)
            with patch('shutil.which',side_effect=AssertionError('host discovery')):
                self.assertEqual(pegasus.discover(root),{'kind':'environment'})

    def test_archive_install_separate_and_integrity_checked(self):
        from clusterlink.containers import checksum
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'worker.tar.gz';image=root/'image';image.mkdir()
            with tarfile.open(archive,'w:gz') as tar:
                for name in pegasus.TOOLS:
                    item=tarfile.TarInfo('pegasus-5.1.3/bin/'+name);item.size=10;item.mode=0o755
                    tar.addfile(item,io.BytesIO(b'#!/bin/sh\n'))
            selection={'kind':'archive','path':str(archive),'sha256':checksum(archive)}
            pegasus.install(selection,image)
            self.assertTrue(os.access(image/'opt/clusterlink/pegasus/bin/pegasus-config',os.X_OK))
            self.assertFalse((image/'opt/clusterlink/env').exists())
            archive.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):
                pegasus.install(selection,image)

    def test_unsafe_archive_rejected(self):
        from clusterlink.containers import checksum
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'worker.tar';image=root/'image';image.mkdir()
            with tarfile.open(archive,'w') as tar:
                tar.addfile(tarfile.TarInfo('../escape'))
            with self.assertRaises(tarfile.FilterError):
                pegasus.install({'kind':'archive','path':str(archive),'sha256':checksum(archive)},image)

    def test_host_worker_digest_participates_in_selection(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);workers=root/'share/pegasus/worker-packages'
            workers.mkdir(parents=True)
            archive=workers/'pegasus-worker-5.1.3-x86_64_rhel_9.tar.gz'
            archive.write_bytes(b'first')
            def query(command, **kwargs):
                return subprocess.CompletedProcess(command,0,stdout='5.1.3' if command[-1]=='--version' else str(root/'bin'))
            with patch('shutil.which',return_value=str(root/'bin/pegasus-config')), patch('subprocess.run',side_effect=query), patch('platform.machine',return_value='x86_64'):
                first=pegasus.discover(root/'conda')
                archive.write_bytes(b'second')
                second=pegasus.discover(root/'conda')
                self.assertEqual(first['path'],second['path'])
                self.assertNotEqual(first['sha256'],second['sha256'])
