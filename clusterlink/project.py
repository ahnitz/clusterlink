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
    # Preserve legacy state only when no project was discovered.
    if os.environ.get('CLUSTERLINK_STATE'):
        return Path(os.environ['CLUSTERLINK_STATE']).resolve()
    legacy = here / 'local/clusterlink'
    if legacy.is_dir():
        return legacy
    raise ValueError('No Clusterlink project found; run clusterlink init --env PREFIX')


def initialize(prefix):
    from .cli import save
    prefix = Path(prefix).expanduser().resolve()
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
    save(state / 'environment.json', {'prefix': str(prefix)})
    save(state / 'sites.json', {})
    (state / '.gitignore').write_text('*\n')
    return state


def remote_root(state, home, name):
    project = state / 'project.json'
    if project.exists():
        ident = json.loads(project.read_text())['id']
        return f'{home}/.clusterlink/projects/{ident}/{name}'
    return f'{home}/.clusterlink/{name}'


def activate(state):
    from . import pool
    selection = json.loads((state / 'environment.json').read_text())
    prefix = Path(selection['prefix'])
    if not (prefix / 'conda-meta').is_dir():
        raise ValueError('Recorded Conda environment is missing: ' + str(prefix))
    conda = os.environ.get('CONDA_EXE') or shutil.which('conda')
    if not conda or not Path(conda).is_file():
        raise ValueError('Conda is not available; launch Clusterlink from a shell with Conda installed')
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
