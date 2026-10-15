"""Install an official standalone Python under the user's owned cluster root."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import tarfile
import urllib.request
import uuid

from .transport import run

VERSION = '3.11.17'
RELEASE = '20261013'
DIGESTS = {
    'x86_64': '3b8e5a248bcc351265ffe68f5e457668a2e09c99a47f81f658988c7d3d107522',
    'aarch64': '3d09fa150bebc6c4f888f8d601328b46fd17f1be5c62cd390a353b7ccff6ed51',
}


def shell_probe(site):
    text = run(site['ssh'], "sh -c 'printf \"%s\\n\" \"$HOME\"; uname -s; uname -m'",
               site['transport'], timeout=45).decode().splitlines()
    if len(text) != 3 or text[1] != 'Linux' or text[2] not in DIGESTS:
        raise ValueError('Python bootstrap supports x86_64/aarch64 Linux')
    return text[0], text[2]


def archive_for(arch, state):
    name=f'cpython-{VERSION}+{RELEASE}-{arch}-unknown-linux-gnu-install_only_stripped.tar.gz'
    directory=state/'helpers'; directory.mkdir(parents=True,exist_ok=True)
    archive=directory/name
    url=f'https://github.com/astral-sh/python-build-standalone/releases/download/{RELEASE}/'+name.replace('+','%2B')
    if not archive.exists():
        temp=directory/(uuid.uuid4().hex+'.partial')
        try:
            with urllib.request.urlopen(url,timeout=120) as source, temp.open('wb') as out:
                while chunk := source.read(1024*1024): out.write(chunk)
            temp.replace(archive)
        finally: temp.unlink(missing_ok=True)
    with archive.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=DIGESTS[arch]:
            raise ValueError('Standalone Python checksum mismatch')
    size=0
    with tarfile.open(archive) as tar:
        for member in tar:
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or path.parts[0]!='python':
                raise ValueError('Unsafe standalone Python archive path')
            if member.isfile(): size+=member.size
            elif member.issym() or member.islnk():
                if member.linkname.startswith('/'):
                    raise ValueError('Absolute link in Python archive')
                # Published archive contains relative internal library links.
                depth=len(path.parts)-1
                for part in PurePosixPath(member.linkname).parts:
                    depth += -1 if part=='..' else 0 if part=='.' else 1
                    if depth<1: raise ValueError('Escaping Python archive link')
            elif not member.isdir(): raise ValueError('Special file in Python archive')
    return archive,size,{'version':VERSION,'release':RELEASE,'url':url,'sha256':DIGESTS[arch]}


def install(site, state, limits, home, arch):
    archive,expanded,metadata=archive_for(arch,state)
    root=site['root']; q=shlex.quote
    probe = ('test -f ' + q(root+'/python.json') + ' && ' +
             q(root+'/python/bin/python3') + ' -c ' + q(
                 'import json;from pathlib import Path;'
                 'assert json.loads(Path(' + repr(root+'/python.json') + ').read_text())["sha256"] == ' + repr(metadata['sha256'])))
    try:
        run(site['ssh'], 'sh -c ' + q(probe), site['transport'], timeout=60)
    except RuntimeError:
        pass
    else:
        site['python']=root+'/python/bin/python3'
        site['python_bootstrap']=metadata
        return
    stage='.python-bootstrap-'+uuid.uuid4().hex
    # Shell-only bootstrap: no remote Python, download client, or daemon needed.
    # Validate canonical location before creating anything; refuse foreign roots.
    script=f'''set -eu
root=$(realpath -m -- {q(root)})
home=$(realpath -- {q(home)})
case "$root" in "$home"/*) ;; *) echo 'Project root must be beneath home'; exit 1;; esac
if test -e "$root"; then
 test -f "$root/owner.json" || {{ echo 'Unmarked existing root'; exit 1; }}
else
 mkdir -p -m 700 "$root"
 printf '%s\\n' {q(json.dumps(limits))} > "$root/owner.json"
fi
used=$(du -sb "$root" | cut -f1)
free=$(df -Pk "$root" | awk 'END {{print $4 * 1024}}')
test "$((used + {expanded+archive.stat().st_size}))" -le {limits['storage_bytes']}
awk 'BEGIN {{exit !('{expanded+archive.stat().st_size+limits['reserve_bytes']}' <= '"$free"')}}'
mkdir "$root/{stage}"
trap 'rm -rf "$root/{stage}"' EXIT
trap 'exit 1' HUP INT TERM
cat > "$root/{stage}/runtime.tar.gz"
printf '%s  %s\\n' {q(metadata['sha256'])} "$root/{stage}/runtime.tar.gz" | sha256sum -c -
tar -xzf "$root/{stage}/runtime.tar.gz" -C "$root/{stage}" \
 --exclude=python/share/terminfo --exclude=python/share/man \
 --exclude=python/include --exclude=python/lib/python3.11/site-packages \
 --exclude=python/lib/python3.11/tkinter --exclude=python/lib/python3.11/ensurepip
"$root/{stage}/python/bin/python3" -c 'import ssl, json, fcntl; print("Python bootstrap verified")'
if test -e "$root/python"; then echo 'Python runtime already exists; refusing overwrite'; exit 1; fi
mv "$root/{stage}/python" "$root/python"
printf '%s\\n' {q(json.dumps(metadata))} > "$root/python.json"
'''
    run(site['ssh'],'sh -c '+q(script),site['transport'],payload=archive,timeout=900)
    site['python']=root+'/python/bin/python3'
    site['python_bootstrap']=metadata
