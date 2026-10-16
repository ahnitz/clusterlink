"""Project identity, discovery, and isolated interactive activation."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid


def discover(explicit=None):
    if explicit:
        return Path(explicit).expanduser().resolve()
    here = Path.cwd().resolve()
    for directory in (here, *here.parents):
        state = directory / '.clusterlink'
        if (state / 'project.json').is_file():
            recorded = json.loads((state / 'project.json').read_text())['root']
            if Path(recorded) != directory:
                raise ValueError('Project state was copied or moved; initialize a new project instead of reusing its identity')
            return state
    raise ValueError('No Clusterlink project found; run clusterlink init --env PREFIX')


def conda_executable():
    executable = os.environ.get('CONDA_EXE') or shutil.which('conda')
    if not executable or not Path(executable).is_file():
        raise ValueError('Conda is not available; launch Clusterlink from a shell with Conda installed')
    return executable


def resolve_environment(value):
    value = str(value)
    path = Path(value).expanduser()
    if (path / 'conda-meta').is_dir():
        return path.resolve()
    if path.is_absolute() or '/' in str(value) or str(value).startswith('.'):
        raise ValueError('The selected path is not a Conda environment: ' + str(value))
    info = json.loads(subprocess.check_output([conda_executable(), 'info', '--json'], text=True))
    if value == 'base':
        candidates = [Path(info['root_prefix'])] if info.get('root_prefix') else []
    else:
        directories = {Path(p).resolve() for p in info.get('envs_dirs', [])}
        candidates = [Path(p) for p in info.get('envs', [])
                      if Path(p).name == value and (not directories or Path(p).resolve().parent in directories)]
    candidates = sorted({p.resolve() for p in candidates if (p / 'conda-meta').is_dir()})
    if len(candidates) != 1:
        reason = 'not found' if not candidates else 'ambiguous'
        raise ValueError(f'Conda environment name {value!r} is {reason}; use an explicit path')
    return candidates[0]


def initialize(prefix, base=None):
    from .cli import save
    prefix = resolve_environment(prefix)
    if not (prefix / 'conda-meta').is_dir():
        raise ValueError('The selected path is not a Conda environment')
    state = Path.cwd().resolve() / '.clusterlink'
    # Private daemon paths currently require shell/config-safe names.
    import re
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(state)):
        raise ValueError('Project path must contain no whitespace or shell metacharacters')
    if state.exists():
        raise ValueError('Project state already exists; refusing to replace it')
    state.mkdir(mode=0o700)
    save(state / 'project.json', {'id': uuid.uuid4().hex, 'root': str(state.parent)})
    save(state / 'environment.json', {'prefix': str(prefix), 'backend': 'sif', **({'container_base': base} if base else {})})
    save(state / 'sites.json', {})
    (state / '.gitignore').write_text('*\n')
    return state


def remote_root(state, home, name):
    project = state / 'project.json'
    if project.exists():
        ident = json.loads(project.read_text())['id']
        return f'{home}/.clusterlink/projects/{ident}/{name}'
    return f'{home}/.clusterlink/{name}'


def environment_selection(state):
    """Require the single supported project environment model."""
    selection = json.loads((state / 'environment.json').read_text())
    if selection.get('backend') != 'sif' or selection.get('artifact'):
        raise ValueError('Legacy archive configuration is unsupported; initialize a fresh project with clusterlink init --env NAME_OR_PATH')
    return selection


def activate(state):
    from . import pool
    if not (state / 'project.json').is_file():
        raise ValueError('Initialize a project with clusterlink init --env NAME_OR_PATH')
    selection = environment_selection(state)
    prefix = Path(selection['prefix'])
    if not (prefix / 'conda-meta').is_dir():
        raise ValueError('Recorded Conda environment is missing: ' + str(prefix))
    conda = conda_executable()
    from .environments import bundle, publish_prepared
    import fcntl
    print('Preparing project SIF (reused when the environment is unchanged)...', flush=True)
    with (state / '.pack.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        artifact = bundle(prefix, state, base=selection.get('container_base'))
        publish_prepared(state, selection, artifact)
    # Validate shell integration before starting the project manager.
    hook = subprocess.check_output([conda, 'shell.bash', 'hook'], text=True)
    script = hook + '\nconda activate ' + shlex.quote(str(prefix)) + ' || exit 1\n'
    script += 'export CONDOR_CONFIG=' + shlex.quote(str(state / 'condor.config')) + '\n'
    script += 'export CLUSTERLINK_STATE=' + shlex.quote(str(state)) + '\n'
    script += 'clusterlink() {\n'
    script += '  if [ "$1" = deactivate ]; then exit; fi\n'
    script += '  ' + shlex.quote(sys.executable) + ' -m clusterlink.cli "$@"\n}\n'
    script += 'export PS1=' + shlex.quote(f'(clusterlink:{state.parent.name}) \\w \\$ ') + '\n'
    rc = state / 'shell.bash'
    rc.write_text(script)
    rc.chmod(0o600)
    pool.configure(state)
    if pool.running(state):
        subprocess.run(['condor_reconfig'], env=pool.environment(state), check=True)
    else:
        pool.start(state)
    print('Project shell: ' + str(state.parent) + '\nUse clusterlink deactivate to leave.', flush=True)
    return subprocess.call(['bash', '--noprofile', '--rcfile', str(rc), '-i'])
