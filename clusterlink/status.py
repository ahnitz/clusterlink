"""Project-state overview; remote checks are explicitly requested."""
import json
import os
from pathlib import Path

from . import pool


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def master_running(state):
    # A restricted process view is not evidence that the pool is stopped.
    if pool.running(state):
        return True
    try:
        pid = int((state / 'master.pid').read_text())
        (Path('/proc') / str(pid) / 'environ').read_bytes()
    except PermissionError:
        return None
    except (OSError, ValueError):
        pass
    return False


def collect(state, remote=False):
    selection = read(state / 'environment.json')
    prefix = selection.get('prefix')
    artifact = selection.get('artifact')
    active = os.environ.get('CONDA_PREFIX')
    result = {
        'state_directory': str(state),
        'project': read(state / 'project.json'),
        'environment': {
            'prefix': prefix,
            'backend': selection.get('backend', 'conda') if prefix else None,
            'conda_metadata_present': bool(prefix and (Path(prefix) / 'conda-meta').is_dir()),
            'packaging': 'pinned archive' if artifact else 'automatic' if prefix else 'not selected',
            'artifact': artifact,
            'artifact_exists': Path(artifact).is_file() if artifact else None,
            'shell_prefix': active,
            'shell_matches_selection': (Path(active).resolve() == Path(prefix).resolve()) if active and prefix else None,
        },
        'pool': {
            'configured': (state / 'condor.config').is_file(),
            'master_running': master_running(state),
        },
        'sites': [],
    }
    for name, site in sorted(read(state / 'sites.json').items()):
        entry = {key: site.get(key) for key in ('ssh', 'scheduler', 'root', 'max_jobs', 'max_idle')}
        entry.update(name=name, enabled=site.get('enabled', True), limits=site.get('limits', {}))
        if remote:
            from .cli import flush_releases, remote_call
            try:
                flush_releases(state, site)
                entry['remote'] = remote_call(site, 'status')
            except (RuntimeError, OSError, ValueError, KeyError) as error:
                entry['remote_error'] = str(error)
        result['sites'].append(entry)
    return result


def render(data):
    env, pool_state = data['environment'], data['pool']
    lines = ([f"Project: {data['project']['root']}"] if data.get('project') else []) + [f"State: {data['state_directory']}",
             f"Conda environment: {env['prefix'] or 'not selected (run clusterlink activate --env PREFIX)'}",
             f"Packaging: {env['packaging']}",
             f"Backend: {env.get('backend') or 'not selected'}"]
    if env['prefix'] and not env['conda_metadata_present']:
        lines.append('  Selected environment is missing its conda-meta directory.')
    if env['artifact']:
        lines.append(f"Archive: {env['artifact']}" + ('' if env['artifact_exists'] else ' (missing)'))
    if env['shell_matches_selection'] is False:
        lines.append(f"Shell Conda environment differs: {env['shell_prefix']}")
    elif not env['shell_prefix']:
        lines.append('Shell Conda environment: none active')
    label = ('unknown (process inspection unavailable)' if pool_state['master_running'] is None
             else 'master running' if pool_state['master_running']
             else 'stopped' if pool_state['configured'] else 'not configured')
    lines += [f'Local pool: {label}', '', f"Linked clusters: {len(data['sites'])}"]
    for site in data['sites']:
        enabled = 'enabled' if site['enabled'] else 'disabled for new jobs'
        lines += [f"  {site['name']}: {site['ssh']} ({site['scheduler']}; {enabled})",
                  f"    Remote directory: {site['root']}",
                  f"    Queue limits: {site['max_jobs']} total, {site['max_idle']} idle"]
        limits = site['limits']
        def gb(key):
            return f"{limits[key] / 1e9:g} GB" if key in limits else 'not set'
        lines.append(f"    Budgets: cache {gb('cache_bytes')}, storage {gb('storage_bytes')}")
        if 'remote_error' in site:
            lines.append('    Remote check failed: ' + site['remote_error'])
        elif 'remote' in site:
            r = site['remote']
            lines.append(f"    Live usage: cache {r['cache_used_bytes']/1e9:.2f} GB, storage {r['total_bytes']/1e9:.2f} GB; leases {r['active_leases']}")
    lines += ['', 'Environment inventory and scheduler health are not validated by this overview.']
    if not any('remote' in s or 'remote_error' in s for s in data['sites']):
        lines.append('Remote connectivity not checked; use clusterlink status --remote for live cache usage.')
    return '\n'.join(lines)
