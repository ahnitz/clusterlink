"""Immutable Conda bundles and launchers for scripts or installed entry points."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import tarfile
import uuid


def fingerprint(prefix):
    """Detect installs/edits without repeatedly reading all package file contents."""
    h = hashlib.sha256()
    for base, dirs, files in os.walk(prefix, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for name in sorted(dirs + [f for f in files if not f.endswith(('.pyc', '.pyo'))]):
            path = Path(base) / name
            s = path.lstat()
            directory = stat.S_ISDIR(s.st_mode)
            value = [str(path.relative_to(prefix)), s.st_mode, 0 if directory else s.st_size,
                     0 if directory else s.st_mtime_ns, 0 if directory else s.st_ctime_ns,
                     os.readlink(path) if path.is_symlink() else None]
            h.update(json.dumps(value).encode())
    return h.hexdigest()


def bundle(prefix, state, backend='conda', base=None):
    if backend == 'sif':
        from .containers import build
        return build(prefix, state, base)
    if backend != 'conda':
        raise ValueError('Unknown environment backend: ' + str(backend))
    import conda_pack
    prefix = Path(prefix).resolve()
    if not (prefix / 'conda-meta').is_dir():
        raise ValueError('Activate a Conda environment or pass --env PREFIX')
    artifacts = state / 'artifacts'
    artifacts.mkdir(parents=True, exist_ok=True)
    if artifacts == prefix or prefix in artifacts.parents:
        raise ValueError('Bundle storage must be outside the environment')
    signature = fingerprint(prefix)
    key = hashlib.sha256((str(prefix) + signature).encode()).hexdigest()
    manifest = artifacts / (key + '.manifest.json')
    if manifest.exists():
        info = json.loads(manifest.read_text())
        target = artifacts / (info['sha256'] + '.tar.gz')
        if target.is_file():
            with target.open('rb') as f:
                if hashlib.file_digest(f, 'sha256').hexdigest() == info['sha256']:
                    return target
    temp = artifacts / (uuid.uuid4().hex + '.packing.tar.gz')
    try:
        try:
            conda_pack.pack(prefix=str(prefix), output=str(temp))
        except conda_pack.CondaPackException as error:
            raise ValueError(f'Cannot bundle this Conda environment: {error}') from error
        if fingerprint(prefix) != signature:
            raise ValueError('Environment changed during packing; retry after installs finish')
        with temp.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        target = artifacts / (digest + '.tar.gz')
        temp.replace(target)
        staging = manifest.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        staging.write_text(json.dumps(dict(source=str(prefix), sha256=digest,
                                          fingerprint=signature, bytes=target.stat().st_size)))
        staging.replace(manifest)
        return target
    finally:
        temp.unlink(missing_ok=True)


def required_bundle_disk(artifact):
    """Bytes needed for the immutable archive plus its unpacked environment."""
    record = artifact.with_suffix('.disk.json')
    if record.exists():
        return json.loads(record.read_text())['bytes']
    with tarfile.open(artifact) as archive:
        unpacked = sum(member.size for member in archive if member.isfile())
        if 'clusterlink-container.json' in archive.getnames():
            metadata = json.load(archive.extractfile('clusterlink-container.json'))
            rootfs = metadata['rootfs_bytes']
            if not isinstance(rootfs, int) or rootfs <= 0:
                raise ValueError('Invalid container root filesystem size')
            unpacked += rootfs
    total = artifact.stat().st_size + unpacked
    temp = record.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps({'bytes': total}))
    temp.replace(record)
    return total


def executable_command(value, prefix=None):
    """Return launch command and optional external file to transfer."""
    path = Path(value).expanduser()
    if prefix and not path.is_file():
        path = Path(prefix) / 'bin' / value
    if not path.is_file():
        raise ValueError(f'Executable does not exist: {value}')
    # Keep the lexical path: conda entry-point symlinks can target another
    # environment-relative executable, and conda-pack preserves them.
    path = path.absolute()
    if prefix:
        try:
            relative = path.relative_to(Path(prefix).resolve())
        except ValueError:
            pass
        else:
            return '"$CLUSTERLINK_ENV"/' + shlex.quote(str(relative)), None
    if path.suffix == '.py':
        return '"$CLUSTERLINK_ENV/bin/python" ' + shlex.quote(path.name), path
    if not path.stat().st_mode & stat.S_IXUSR:
        raise ValueError('Non-Python executables must have executable permission')
    return './' + shlex.quote(path.name), path


def launcher(command, archive='environment.tar.gz', source_prefix=None, staged_script=None, outputs=()):
    # A failed application may never create its declared outputs. Return its
    # stderr and nonzero exit instead of losing diagnostics to a transfer hold.
    safe_outputs = [str(p) for value in outputs if value
                    for p in [Path(value)] if not p.is_absolute()
                    and '..' not in p.parts and str(p) not in {'.', ''}]
    failure = ''
    if safe_outputs:
        failure = 'finish() {\n  result=$?\n  if [ "$result" -ne 0 ]; then\n'
        for value in safe_outputs:
            quoted=shlex.quote(value); parent=shlex.quote(str(Path(value).parent))
            failure += f'    [ -e {quoted} ] || (mkdir -p -- {parent} && touch -- {quoted}) || true\n'
        failure += '  fi\n  exit "$result"\n}\ntrap finish EXIT\n'
    remap = ''
    if source_prefix:
        remap = ('source_prefix=' + shlex.quote(str(source_prefix).rstrip('/') + '/') + '\n'
                 'mapped=()\nfor arg in "$@"; do\n'
                 '  mapped+=("${arg//"$source_prefix"/"$CLUSTERLINK_ENV/"}")\ndone\n'
                 'set -- "${mapped[@]}"\n')
        if staged_script:
            # Pegasus and other workflow engines generate text launchers that
            # can contain absolute paths into the selected local environment.
            code = ('from pathlib import Path;import sys;'
                    'p=Path(sys.argv[1]);data=p.read_bytes();'
                    'old=sys.argv[2].encode();new=sys.argv[3].encode();'
                    'p.write_bytes(data.replace(old,new)) if b"\\x00" not in data and old in data else None')
            remap += ('"$CLUSTERLINK_ENV/bin/python" -c ' + shlex.quote(code) + ' '
                      + shlex.quote(staged_script) + ' "$source_prefix" "$CLUSTERLINK_ENV/"\n')
    container = ('if [ -f .clusterlink-env/environment.sif ]; then\n'
        '  mkdir -p .clusterlink-env/tmp .clusterlink-env/cache .clusterlink-env/config\n'
        '  export APPTAINER_TMPDIR="$PWD/.clusterlink-env/tmp"\n'
        '  export APPTAINER_CACHEDIR="$PWD/.clusterlink-env/cache"\n'
        '  export APPTAINER_CONFIGDIR="$PWD/.clusterlink-env/config"\n'
        "  cat > .clusterlink-env/run.sh <<'CLUSTERLINK_INNER'\n"
        '#!/bin/bash\nset -euo pipefail\n'
        'export CLUSTERLINK_ENV=/opt/clusterlink/env\n'
        'export CONDA_PREFIX="$CLUSTERLINK_ENV"\n'
        'export PATH="$CLUSTERLINK_ENV/bin:$PATH"\n'
        'unset PYTHONHOME PYTHONPATH\nexport PYTHONNOUSERSITE=1\n'
        + remap + command + ' "$@"\nCLUSTERLINK_INNER\n'
        '  ./.clusterlink-env/apptainer-runtime/bin/apptainer exec --unsquash --userns --cleanenv --containall '
        '--bind "$PWD:/work" --pwd /work .clusterlink-env/environment.sif /bin/bash /work/.clusterlink-env/run.sh "$@"\n'
        '  exit $?\nfi\n')
    return '''#!/bin/bash
set -euo pipefail
mkdir .clusterlink-env
tar -xzf ARCHIVE_PLACEHOLDER -C .clusterlink-env
export CLUSTERLINK_ENV="$PWD/.clusterlink-env"
unset PYTHONHOME PYTHONPATH
export PYTHONNOUSERSITE=1
"$CLUSTERLINK_ENV/bin/python" "$CLUSTERLINK_ENV/bin/conda-unpack"
export PATH="$CLUSTERLINK_ENV/bin:$PATH"
export CONDA_PREFIX="$CLUSTERLINK_ENV"
'''.replace('ARCHIVE_PLACEHOLDER', shlex.quote(archive)).replace('export CLUSTERLINK_ENV=', container + 'export CLUSTERLINK_ENV=', 1).replace('set -euo pipefail\n', 'set -euo pipefail\n' + failure, 1) + remap + command + ' "$@"\n'
