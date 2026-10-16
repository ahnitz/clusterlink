"""Build a Conda environment into a SIF and ship a private Apptainer runtime."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

VERSION = '1.5.4'
INSTALLER = f'https://raw.githubusercontent.com/apptainer/apptainer/v{VERSION}/tools/install-unprivileged.sh'
INSTALLER_SHA256 = 'a097956eafa6ab3dd843ee429d0b774ed029753bfadf013b8046556228fac6f2'
PREFIX = '/opt/clusterlink/env'


def default_base():
    release = platform.freedesktop_os_release()
    distro, version = release.get('ID'), release.get('VERSION_ID')
    if distro not in {'fedora', 'ubuntu', 'debian', 'rockylinux', 'almalinux'} or not version:
        raise ValueError('Cannot choose a compatible container base; specify --container-base at init')
    return f'docker://{distro}:{version}'


def runtime(state):
    target = state / 'container-runtime'
    executable = target / 'bin/apptainer'
    if executable.is_file():
        return target
    missing = [name for name in ('curl', 'rpm2cpio', 'cpio') if not shutil.which(name)]
    if missing:
        raise ValueError('Private Apptainer installation needs local tools: ' + ', '.join(missing))
    installer = state / 'install-apptainer.sh'
    with urllib.request.urlopen(INSTALLER, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != INSTALLER_SHA256:
        raise ValueError('Apptainer installer checksum mismatch')
    installer.write_bytes(data)
    # Keep partial installs separate; failed provisioning must not look complete.
    partial = state / 'container-runtime.partial'
    if partial.exists():
        shutil.rmtree(partial)
    log = state / 'install-apptainer.log'
    try:
        with log.open('w') as output:
            subprocess.run(['bash', str(installer), '-v', VERSION, '-d', 'el8', str(partial)],
                           check=True, stdout=output, stderr=subprocess.STDOUT)
            subprocess.run([str(partial/'bin/apptainer'), '--version'],
                           check=True, stdout=output, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f'Private Apptainer installation failed; see {log}') from error
    partial.rename(target)
    return target


def build(prefix, state, base=None, *, allow_build=True):
    import conda_pack
    from .environments import fingerprint
    prefix, state = Path(prefix).resolve(), Path(state).resolve()
    if state == prefix or prefix in state.parents:
        raise ValueError('Project state must be outside the environment')
    base = base or default_base()
    signature = fingerprint(prefix)
    key = hashlib.sha256(json.dumps([str(prefix), signature, base, VERSION, 'sif-v1']).encode()).hexdigest()
    artifacts = state/'artifacts'; artifacts.mkdir(exist_ok=True)
    manifest = artifacts/(key+'.manifest.json')
    if manifest.exists():
        info = json.loads(manifest.read_text()); cached = artifacts/(info['sha256']+'.tar.gz')
        if cached.is_file() and checksum(cached) == info['sha256']:
            return cached
    if not allow_build:
        raise ValueError('Project SIF is missing, stale, or damaged; leave the project shell and run clusterlink activate before submitting jobs')
    private_runtime = runtime(state)
    env = {**os.environ}
    for keyname, directory in [('APPTAINER_CACHEDIR','container-cache'),('APPTAINER_TMPDIR','container-tmp'),('APPTAINER_CONFIGDIR','container-config')]:
        path = state/directory;path.mkdir(exist_ok=True);env[keyname] = str(path)
    apptainer = str(private_runtime/'bin/apptainer')
    with tempfile.TemporaryDirectory(prefix='container-build-',dir=state) as temporary:
        work=Path(temporary); archive=work/'environment.tar.gz'
        # Fixed-prefix packing rewrites entry points without a writable runtime env.
        try:
            conda_pack.pack(prefix=str(prefix), output=str(archive), dest_prefix=PREFIX)
        except conda_pack.CondaPackException as error:
            raise ValueError('Cannot build SIF from this Conda environment: ' + str(error)) from error
        if fingerprint(prefix) != signature:
            raise ValueError('Environment changed during container packing; retry after installs finish')
        rootfs=work/'rootfs'
        subprocess.run([apptainer,'build','--fix-perms','--sandbox',str(rootfs),base],env=env,check=True, stdout=sys.stderr)
        target=rootfs/PREFIX.lstrip('/');target.mkdir(parents=True)
        subprocess.run(['tar','-xzf',str(archive),'-C',str(target)],check=True, stdout=sys.stderr)
        # Smoke-check the actual image userspace before producing an artifact.
        subprocess.run([apptainer,'exec','--userns','--cleanenv',str(rootfs),PREFIX+'/bin/python','-c','import sys; print(sys.version)'],env=env,check=True, stdout=sys.stderr)
        image=work/'environment.sif'
        subprocess.run([apptainer,'build','--mksquashfs-args','-processors 2',str(image),str(rootfs)],env=env,check=True, stdout=sys.stderr)
        unpacked=sum(p.stat().st_size for p in rootfs.rglob('*') if p.is_file() and not p.is_symlink())
        metadata={'backend':'sif','base':base,'runtime_version':VERSION,'environment_prefix':PREFIX,'rootfs_bytes':unpacked,'source':str(prefix),'fingerprint':signature,'sif_sha256':checksum(image)}
        marker=work/'clusterlink-container.json';marker.write_text(json.dumps(metadata))
        output=work/'container.tar.gz'
        with tarfile.open(output,'w:gz') as tar:
            tar.add(image,arcname='environment.sif')
            tar.add(marker,arcname='clusterlink-container.json')
            tar.add(private_runtime,arcname='apptainer-runtime')
        digest=checksum(output);destination=artifacts/(digest+'.tar.gz');output.rename(destination)
        with tarfile.open(destination) as tar:
            extraction=sum(m.size for m in tar if m.isfile())
        # --unsquash needs space for the full rootfs as well as the delivery bundle.
        from .cli import save
        save(destination.with_suffix('.disk.json'), {'bytes':destination.stat().st_size+extraction+unpacked})
        save(manifest, {**metadata,'sha256':digest})
        return destination


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
