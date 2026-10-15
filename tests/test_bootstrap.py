import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from clusterlink.bootstrap import archive_for, VERSION, RELEASE


class BootstrapTests(unittest.TestCase):
    def check_archive(self, member_name, link=None):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp); (state/'helpers').mkdir()
            filename=f'cpython-{VERSION}+{RELEASE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'
            archive=state/'helpers'/filename
            with tarfile.open(archive,'w:gz') as out:
                member=tarfile.TarInfo(member_name)
                if link:
                    member.type=tarfile.SYMTYPE;member.linkname=link
                    out.addfile(member)
                else:
                    member.size=2;out.addfile(member,io.BytesIO(b'ok'))
            digest=hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.dict('clusterlink.bootstrap.DIGESTS',x86_64=digest):
                return archive_for('x86_64',state)[1]

    def test_normal_archive(self):
        self.assertEqual(self.check_archive('python/bin/python3'),2)

    def test_traversal_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unsafe'):
            self.check_archive('python/../../outside')

    def test_escaping_symlink_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Escaping'):
            self.check_archive('python/bin/python3','../../outside')
