"""Discover and validate optional Pegasus worker tools at image-build time."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile

TOOLS = ('pegasus-config', 'pegasus-kickstart', 'pegasus-transfer', 'pegasus-integrity')
IMAGE_PREFIX = '/opt/clusterlink/pegasus'


def discover(prefix):
    if all(os.access(Path(prefix) / 'bin' / name, os.X_OK) for name in TOOLS):
        return {'kind': 'environment'}
    config = shutil.which('pegasus-config')
    if not config:
        return None
    def query(option):
        return subprocess.run([config, option], check=True, capture_output=True,
                              text=True, timeout=30).stdout.strip()
    version = query('--version')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.-]*', version):
        raise ValueError('Unrecognized Pegasus version from ' + config)
    home = Path(query('--bin')).parent
    candidates = sorted((home / 'share/pegasus/worker-packages').glob(
        f'pegasus-worker-{version}-{platform.machine()}_*.tar.gz'), reverse=True)
    candidates = [p for p in candidates if not any(x in p.name.lower() for x in ('macos', 'darwin', 'windows'))]
    if not candidates:
        raise ValueError(f'Pegasus {version} lacks a Linux {platform.machine()} worker archive under {home}; install its full worker package before activation')
    from .containers import checksum
    return {'kind': 'archive', 'path': str(candidates[0].resolve()),
            'sha256': checksum(candidates[0]), 'version': version}


def install(selection, rootfs):
    """Keep the worker prefix separate; never modify the user's Conda environment."""
    if not selection:
        return
    # Minimal base images can omit `which`, used by PegasusLite and its CLI
    # wrappers. Supply PATH lookup without adding host binaries/dependencies.
    helper = rootfs / 'opt/clusterlink/bin/which'
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text('#!/bin/sh\n[ "$#" -gt 0 ] || exit 1\nstatus=0\nfor name do\n  command -v "$name" || status=1\ndone\nexit "$status"\n')
    helper.chmod(0o755)
    if selection['kind'] != 'archive':
        return
    from .containers import checksum
    archive = Path(selection['path'])
    if checksum(archive) != selection['sha256']:
        raise ValueError('Pegasus worker archive changed during activation')
    target = rootfs / IMAGE_PREFIX.lstrip('/')
    target.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        roots = {Path(m.name).parts[0] for m in members if Path(m.name).parts}
        if len(roots) != 1:
            raise ValueError('Pegasus worker archive must contain one top-level directory')
        # The stdlib data filter rejects traversal, devices and escaping links.
        scratch = target.parent / 'pegasus-unpack'
        scratch.mkdir()
        tar.extractall(scratch, filter='data')
        source = scratch / roots.pop()
        for name in TOOLS:
            if not os.access(source / 'bin' / name, os.X_OK):
                raise ValueError('Pegasus worker archive lacks ' + name)
        target.rmdir()
        source.rename(target)
        scratch.rmdir()


def validate(selection, apptainer, rootfs, env):
    if not selection:
        return
    prefix = IMAGE_PREFIX if selection['kind'] == 'archive' else '/opt/clusterlink/env'
    # Exercise both native and Python workers inside the actual image userspace.
    common = [apptainer, 'exec', '--userns', '--cleanenv', str(rootfs),
              '/usr/bin/env', 'PEGASUS_PYTHON=/opt/clusterlink/env/bin/python',
              'PATH=' + prefix + '/bin:/opt/clusterlink/env/bin:/usr/bin:/bin:/opt/clusterlink/bin']
    subprocess.run(common + ['/bin/sh', '-c', 'which pegasus-config'], env=env, check=True, capture_output=True, timeout=30)
    for tool, args in [('pegasus-config', ['--version']), ('pegasus-kickstart', ['/bin/true']),
                       ('pegasus-transfer', ['--help']), ('pegasus-integrity', ['--help'])]:
        result = subprocess.run(common + [prefix + '/bin/' + tool, *args], env=env,
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise ValueError(f'Pegasus worker {tool} is incompatible with the image: {result.stderr[-2000:]}')
        if tool == 'pegasus-config' and selection.get('version') and result.stdout.strip() != selection['version']:
            raise ValueError('Bundled Pegasus version does not match submit-host Pegasus')
