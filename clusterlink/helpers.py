"""Provision upstream HTCondor helpers without a remote system installation."""
import hashlib
import io
from pathlib import Path
import re
import tarfile
import urllib.request

VERSION = '25.0.14'
BASE = f'https://htcss-downloads.chtc.wisc.edu/tarball/25.0/{VERSION}/release/'


def helper_bundle(probe, state):
    arch = probe['machine']
    if arch not in {'x86_64', 'aarch64'} or probe['libc'][0] != 'glibc':
        raise ValueError('Portable helpers currently support x86_64/aarch64 Linux with glibc')
    libc = tuple(map(int, probe['libc'][1].split('.')[:2]))
    if libc < (2, 28):
        raise ValueError('Portable helpers require glibc 2.28 or later')
    platform = arch + ('_AlmaLinux9' if libc >= (2, 34) else '_AlmaLinux8')
    filename = f'condor-{VERSION}-{platform}-stripped.tar.gz'
    directory = state / 'helpers'
    directory.mkdir(parents=True, exist_ok=True)
    checksums = urllib.request.urlopen(BASE + 'sha256sum.txt', timeout=60).read().decode()
    expected = next((line.split()[0] for line in checksums.splitlines()
                     if line.split()[-1].lstrip('*') == filename), None)
    if not expected or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('Upstream did not publish a checksum for ' + filename)
    archive = directory / filename
    if not archive.exists():
        temporary = archive.with_suffix('.partial')
        try:
            with urllib.request.urlopen(BASE + filename, timeout=120) as source, temporary.open('wb') as out:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    out.write(chunk)
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
            raise ValueError('Upstream archive checksum mismatch: ' + str(archive))
    result = io.BytesIO()
    with tarfile.open(archive) as source, tarfile.open(fileobj=result, mode='w:gz') as target:
        for member in source.getmembers():
            relative = member.name.split('/', 1)[-1]
            destination = None
            if relative in {'usr/bin/blahpd', 'usr/sbin/condor_ft-gahp'}:
                destination = 'bin/' + Path(relative).name
            elif relative.startswith('usr/sbin/bl') and '/' not in relative[len('usr/sbin/'):]:
                destination = 'sbin/' + Path(relative).name
            elif re.fullmatch(r'usr/lib64/[^/]+\.so[^/]*', relative):
                destination = 'lib/' + Path(relative).name
            elif relative.startswith('usr/libexec/blahp/') and not member.isdir():
                destination = 'libexec/' + Path(relative).name
            elif relative == 'etc/blah.config':
                destination = relative
            elif relative.startswith('usr/share/licenses/') or relative.endswith('/condor/LICENSE'):
                if member.isfile():
                    destination = 'licenses/' + relative.replace('/', '_')
            if destination and (member.isfile() or member.issym() or member.islnk()):
                stream = source.extractfile(member)
                content = stream.read()
                info = tarfile.TarInfo(destination)
                info.size = len(content)
                info.mode = 0o700 if destination.startswith(('bin/', 'sbin/', 'libexec/')) else 0o600
                target.addfile(info, io.BytesIO(content))
    data = result.getvalue()
    return data, hashlib.sha256(data).hexdigest(), {'version': VERSION, 'url': BASE + filename, 'sha256': expected}
