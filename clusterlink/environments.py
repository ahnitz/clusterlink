"""Project environment fingerprints and SIF job launchers."""
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


def bundle(prefix, state, base=None, *, allow_build=True):
    """Build or reuse the project's SIF delivery bundle."""
    from .containers import build
    return build(prefix, state, base, allow_build=allow_build)


def required_bundle_disk(artifact):
    """Bytes needed for the immutable archive plus its unpacked environment."""
    record = artifact.with_suffix('.disk.json')
    if record.exists():
        return json.loads(record.read_text())['bytes']
    with tarfile.open(artifact) as archive:
        unpacked = sum(member.size for member in archive if member.isfile())
        if not {'clusterlink-container.json', 'environment.sif'}.issubset(archive.getnames()):
            raise ValueError('Expected a Clusterlink SIF bundle; Conda archives are no longer supported')
        metadata = json.load(archive.extractfile('clusterlink-container.json'))
        if metadata.get('backend') != 'sif':
            raise ValueError('Expected SIF bundle metadata')
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
    container = ('[ -f .clusterlink-env/environment.sif ] || { echo "Clusterlink SIF missing" >&2; exit 1; }\n'
        '  mkdir -p .clusterlink-env/tmp .clusterlink-env/cache .clusterlink-env/config\n'
        '  export APPTAINER_TMPDIR="$PWD/.clusterlink-env/tmp"\n'
        '  export APPTAINER_CACHEDIR="$PWD/.clusterlink-env/cache"\n'
        '  export APPTAINER_CONFIGDIR="$PWD/.clusterlink-env/config"\n'
        # Keep native allocation limits across --cleanenv. Explicit Apptainer
        # overrides retain their normal precedence; absent values stay absent.
        '  for name in CUBACORES GOMAXPROCS JULIA_NUM_THREADS MKL_NUM_THREADS NUMEXPR_NUM_THREADS '
        'OMP_NUM_THREADS OMP_THREAD_LIMIT OPENBLAS_NUM_THREADS PYTHON_CPU_COUNT ROOT_MAX_THREADS '
        'TF_LOOP_PARALLEL_ITERATIONS TF_NUM_THREADS CUDA_VISIBLE_DEVICES NVIDIA_VISIBLE_DEVICES; do\n'
        '    target="APPTAINERENV_$name"\n'
        '    if [[ -v "$name" && ! -v "$target" ]]; then export "$target=${!name}"; fi\n'
        '  done\n'
        # This is our freshly extracted, user-owned runtime, never the host's
        # configuration. The nested unsquashfs helper does not inherit CLI
        # --no-mount flags, so configure devpts here for both helper and payload.
        '  for config in .clusterlink-env/apptainer-runtime/*/etc/apptainer/apptainer.conf; do\n'
        '    [ -f "$config" ] || { echo "Private Apptainer configuration missing" >&2; exit 1; }\n'
        '    sed -i -E "s/^[[:space:]]*mount devpts[[:space:]]*=.*/mount devpts = no/" "$config"\n'
        '  done\n'
        "  cat > .clusterlink-env/run.sh <<'CLUSTERLINK_INNER'\n"
        '#!/bin/bash\nset -euo pipefail\n'
        'export CLUSTERLINK_ENV=/opt/clusterlink/env\n'
        'export CONDA_PREFIX="$CLUSTERLINK_ENV"\n'
        'export PEGASUS_PYTHON="$CLUSTERLINK_ENV/bin/python"\n'
        'export PATH="$CLUSTERLINK_ENV/bin:$PATH"\n'
        'unset PYTHONHOME PYTHONPATH\nexport PYTHONNOUSERSITE=1\n'
        + remap + command + ' "$@"\nCLUSTERLINK_INNER\n'
        '  ./.clusterlink-env/apptainer-runtime/bin/apptainer exec --unsquash --userns --cleanenv --containall '
        '--bind "$PWD:/work" --pwd /work .clusterlink-env/environment.sif /bin/bash /work/.clusterlink-env/run.sh "$@"\n'
        '  exit $?\n')
    return ('#!/bin/bash\nset -euo pipefail\n' + failure
            + 'mkdir .clusterlink-env\ntar -xzf ' + shlex.quote(archive)
            + ' -C .clusterlink-env\n' + container)
