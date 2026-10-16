import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from . import remote
from .transport import destination, python_command, run
from .submission import submit as submit_native


def state_dir(args):
    from .project import discover
    root = discover(args.state)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def remote_call(site, action, *args, payload=b""):
    source = Path(remote.__file__).read_text()
    argv = [action] if action == "probe" else [action, site["root"], *args]
    output = run(site["ssh"], python_command(source, argv, site.get("python", "python3")), site["transport"], payload, timeout=300)
    return json.loads(output)


def enroll(args, state):
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", args.name):
        raise ValueError("Site names must be lowercase letters, digits, underscores, or hyphens")
    sites = json.loads((state / "sites.json").read_text()) if (state / "sites.json").exists() else {}
    if args.name in sites and not args.update:
        raise ValueError("Site already enrolled; refusing to overwrite its settings")
    limits = {"cache_bytes": int(args.cache_gb * 10**9), "storage_bytes": int(args.storage_gb * 10**9), "reserve_bytes": int(args.reserve_gb * 10**9)}
    if not 0 < limits["cache_bytes"] <= limits["storage_bytes"] or limits["reserve_bytes"] < 0:
        raise ValueError("Require 0 < cache budget <= storage budget and nonnegative reserve")
    site = {"ssh": destination(args.ssh)}
    previous = sites.get(args.name, {})
    if previous.get('python') and previous.get('ssh') == site['ssh']:
        site['python'] = previous['python']
        site['python_bootstrap'] = previous.get('python_bootstrap')
    failures = []
    for mode in (["login", "exec"] if args.transport == "auto" else [args.transport]):
        site["transport"] = mode
        try:
            try:
                if args.python == 'portable' and 'python' not in site:
                    raise RuntimeError('Portable Python requested')
                p = remote_call(site, "probe")
                if p.get('python_version', [0]) < [3, 8]:
                    raise RuntimeError('Remote Python is too old')
            except RuntimeError:
                from .bootstrap import shell_probe, install as install_python
                home, arch = shell_probe(site)
                from .project import remote_root
                site['root'] = args.remote_dir or remote_root(state, home, args.name)
                install_python(site, state, limits, home, arch)
                p = remote_call(site, "probe")
            break
        except RuntimeError as error:
            failures.append(str(error))
    else:
        raise RuntimeError('SSH discovery failed: ' + '; '.join(failures))
    scheduler = args.scheduler or ("condor" if p["commands"]["condor_submit"] else "slurm" if p["commands"]["sbatch"] else None)
    if scheduler is None:
        raise ValueError("No supported scheduler found")
    # Restrict generated shell/config values until all backends support quoting.
    from .project import remote_root
    site["root"] = args.remote_dir or remote_root(state, p["home"], args.name)
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", site["root"]):
        raise ValueError("Remote project path must be absolute and contain no whitespace/metacharacters")
    site.update(scheduler=scheduler, limits=limits, probe=p, max_idle=args.max_idle, max_jobs=args.max_jobs,
                enabled=previous.get("enabled", True))
    portable = args.helpers == 'portable' or bool(sites.get(args.name, {}).get('helpers')) or not all(p['commands'][n] for n in ['blahpd', 'condor_ft-gahp'])
    if portable:
        from .helpers import helper_bundle
        data, digest, metadata = helper_bundle(p, state)
        remote_call(site, 'bootstrap', json.dumps(limits), digest, json.dumps(metadata), payload=data)
        site['helpers'] = metadata
    adapters = next((p for p in [Path('/usr/libexec/blahp'), Path('/usr/lib/condor'), Path('/usr/libexec/condor')]
                     if (p / 'blah_common_submit_functions.sh').exists()), None)
    if adapters is None and not portable:
        raise ValueError('Local HTCondor BLAHP shell adapters are not installed')
    scripts = {} if portable else {p.name: p.read_text() for p in adapters.glob('*.sh')
               if p.name.startswith(('blah', 'condor', 'slurm', 'pbs', 'lsf', 'sge'))}
    remote_call(site, "install", json.dumps(limits), payload=json.dumps(scripts).encode())
    sites[args.name] = site
    save(state / "sites.json", sites)
    print(json.dumps({"enrolled": args.name, **site}, indent=2))


def flush_releases(state, site):
    from . import leases
    while True:
        paths, records = leases.pending(state, site)
        if not paths:
            return
        remote_call(site, 'release-many', json.dumps(records))
        leases.acknowledge(paths)


def submit(args, state):
    if min(args.cpus, args.memory_mb, args.disk_mb, args.runtime) <= 0:
        raise ValueError('CPU, memory, disk and runtime requests must be positive')
    return submit_native(args, state)


def main():
    parser = argparse.ArgumentParser(description="Personal HTCondor cluster enrollment prototype")
    parser.add_argument("--state", help="Explicit state directory (normally discovered from the project)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser('init', help='Initialize this project with an explicit Conda environment')
    p.add_argument('--env', required=True)
    p.add_argument('--container-base', help='Apptainer base URI (default: workstation distribution/version)')
    sub.add_parser('deactivate', help='Leave an activated project shell')
    p = sub.add_parser('activate', help='Select a Conda environment for ordinary Condor submissions')
    p = sub.add_parser("enroll")
    p.add_argument("name")
    p.add_argument("--ssh", required=True)
    p.add_argument('--update', action='store_true', help='Update an existing enrollment (stop its jobs first)')
    p.add_argument('--helpers', choices=['auto', 'portable'], default='auto')
    p.add_argument('--python', choices=['auto', 'portable'], default='auto')
    p.add_argument("--scheduler", choices=["condor", "slurm"])
    p.add_argument("--transport", choices=["auto", "exec", "login"], default="auto")
    p.add_argument("--remote-dir", help="Absolute dedicated remote project directory for cache, staging, helpers, logs, and temporary files (default: unique directory under your home)")
    p.add_argument("--cache-gb", type=float, required=True)
    p.add_argument("--storage-gb", type=float, required=True)
    p.add_argument("--reserve-gb", type=float, default=1)
    p.add_argument("--max-idle", type=int, default=2)
    p.add_argument("--max-jobs", type=int, default=10)
    p = sub.add_parser("site", help="Control routing without reinstalling remote helpers")
    p.add_argument("action", choices=["enable", "disable", "limits"])
    p.add_argument("name")
    p.add_argument('--max-jobs', type=int)
    p.add_argument('--max-idle', type=int)
    p = sub.add_parser("status", help="Show selected environment, pool state, and linked clusters")
    p.add_argument('--remote', action='store_true', help='Contact clusters for live cache usage and flush deferred lease releases')
    p.add_argument('--json', action='store_true', help='Print the overview as JSON')
    p = sub.add_parser('submit')
    p.add_argument('--no-cache', action='store_true', help='Stage the environment with every job')
    p.add_argument('--site', default='auto')
    p.add_argument('--cpus', type=int, default=1)
    p.add_argument('--memory-mb', type=int, default=1024)
    p.add_argument('--disk-mb', type=int, default=2048)
    p.add_argument('--runtime', type=int, default=300, help='Requested runtime in seconds')
    p.add_argument('--input', action='append', default=[])
    p.add_argument('--output', action='append', default=[])
    p.add_argument('script')
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    p = sub.add_parser("pool")
    p.add_argument("action", choices=["configure", "start", "stop", "queue"])
    p.add_argument("--local-slots", type=int, default=None)
    args = parser.parse_args()
    try:
        from . import project
        if getattr(args, 'env', None):
            args.env = str(project.resolve_environment(args.env))
        if args.command == 'init':
            if args.state:
                raise ValueError('init creates .clusterlink in the current project; do not pass --state')
            print('Initialized ' + str(project.initialize(args.env, args.container_base)))
            return
        if args.command == 'deactivate':
            raise ValueError('Use clusterlink deactivate inside the shell opened by clusterlink activate')
        state = project.discover(args.state) if args.command == 'status' else state_dir(args)
        if args.command == 'activate':
            raise SystemExit(project.activate(state))
        elif args.command == "site":
            sites = json.loads((state / "sites.json").read_text())
            if args.name not in sites:
                raise ValueError("Unknown enrolled site: " + args.name)
            if args.action == 'limits':
                site = sites[args.name]
                maximum = args.max_jobs if args.max_jobs is not None else site['max_jobs']
                idle = args.max_idle if args.max_idle is not None else site['max_idle']
                if not 0 < idle <= maximum:
                    raise ValueError('Require 0 < max-idle <= max-jobs')
                site.update(max_jobs=maximum, max_idle=idle)
            else:
                if args.max_jobs is not None or args.max_idle is not None:
                    raise ValueError('Use site limits to change queue limits')
                sites[args.name]["enabled"] = args.action == "enable"
            save(state / "sites.json", sites)
            from . import pool
            pool.configure(state)
            if pool.running(state):
                subprocess.run(["condor_reconfig"], env=pool.environment(state), check=True)
            if args.action == 'limits':
                print(f'{args.name}: max-jobs={maximum}, max-idle={idle}; existing jobs remain tracked')
            else:
                print(args.name + (" enabled for new jobs" if args.action == "enable" else " disabled for new jobs; existing jobs remain tracked"))
        elif args.command == "enroll":
            enroll(args, state)
            if (state / 'project.json').exists():
                from . import pool
                pool.configure(state)
                if pool.running(state):
                    subprocess.run(['condor_reconfig'], env=pool.environment(state), check=True)
        elif args.command == 'submit':
            submit(args, state)
        elif args.command == "pool":
            from . import pool
            if args.action == "configure":
                print(pool.configure(state, args.local_slots))
            elif args.action == "start":
                pool.start(state)
            elif args.action == "stop":
                subprocess.run(["condor_off", "-master"], env=pool.environment(state), check=True)
            else:
                subprocess.run(["condor_q"], env=pool.environment(state), check=True)
        else:
            from .status import collect, render
            result = collect(state, remote=args.remote)
            print(json.dumps(result, indent=2) if args.json else render(result))
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.CalledProcessError) as e:
        parser.exit(1, f"clusterlink: {e}\n")


def ssh_main():
    from .interactive import main as interactive_main
    interactive_main()


if __name__ == "__main__":
    main()
