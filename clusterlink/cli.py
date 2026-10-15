import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import shutil
import uuid

from . import remote
from .transport import destination, python_command, run
from .submission import submit as submit_native


def state_dir(args):
    root = Path(args.state).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def save(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def remote_call(site, action, *args, payload=b""):
    source = Path(remote.__file__).read_text()
    argv = [action] if action == "probe" else [action, site["root"], *args]
    output = run(site["ssh"], python_command(source, argv), site["transport"], payload, timeout=300)
    return json.loads(output)


def enroll(args, state):
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", args.name):
        raise ValueError("Site names must be lowercase letters, digits, underscores, or hyphens")
    sites = json.loads((state / "sites.json").read_text()) if (state / "sites.json").exists() else {}
    if args.name in sites and not args.update:
        raise ValueError("Site already enrolled; refusing to overwrite its settings")
    site = {"ssh": destination(args.ssh)}
    failures = []
    for mode in (["login", "exec"] if args.transport == "auto" else [args.transport]):
        site["transport"] = mode
        try:
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
    site["root"] = args.remote_dir or p["home"] + "/.clusterlink/" + args.name
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", site["root"]):
        raise ValueError("Remote project path must be absolute and contain no whitespace/metacharacters")
    limits = {"cache_bytes": int(args.cache_gb * 10**9), "storage_bytes": int(args.storage_gb * 10**9), "reserve_bytes": int(args.reserve_gb * 10**9)}
    if not 0 < limits["cache_bytes"] <= limits["storage_bytes"] or limits["reserve_bytes"] < 0:
        raise ValueError("Require 0 < cache budget <= storage budget and nonnegative reserve")
    site.update(scheduler=scheduler, limits=limits, probe=p, max_idle=args.max_idle, max_jobs=args.max_jobs)
    portable = args.helpers == 'portable' or not all(p['commands'][n] for n in ['blahpd', 'condor_ft-gahp'])
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


def pack(args, state):
    import conda_pack
    prefix = Path(args.env or os.environ.get("CONDA_PREFIX", "")).resolve()
    if not (prefix / "conda-meta").is_dir():
        raise ValueError("Activate a Conda environment or pass --env PREFIX")
    artifacts = state / "artifacts"
    artifacts.mkdir(exist_ok=True)
    temp = artifacts / "packing.tar.gz"
    if temp.exists():
        raise ValueError("Packing already in progress or interrupted; inspect packing.tar.gz")
    conda_pack.pack(prefix=str(prefix), output=str(temp))
    digest = hashlib.file_digest(temp.open("rb"), "sha256").hexdigest()
    target = artifacts / (digest + ".tar.gz")
    temp.replace(target)
    save(artifacts / (digest + ".json"), {"source": str(prefix), "sha256": digest, "bytes": target.stat().st_size})
    print(digest)


def cache(args, state):
    sites = json.loads((state / "sites.json").read_text())
    names = [args.site] if args.site else list(sites)
    artifact = Path(args.artifact).resolve()
    with artifact.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    for name in names:
        site = sites[name]
        result = remote_call(site, "check", digest)
        if not result["cached"]:
            result = remote_call(site, "upload", digest, artifact.stat().st_size, payload=artifact.read_bytes())
        print(json.dumps({"site": name, "sha256": digest, **result}))


def submit(args, state):
    if not args.artifact:
        return submit_native(args, state)
    from .pool import environment
    from .environments import bundle, executable_command, launcher as make_launcher
    prefix = args.env or os.environ.get('CONDA_PREFIX')
    if not args.artifact and not prefix:
        raise ValueError('Activate a Conda environment or pass --env PREFIX')
    artifact = Path(args.artifact).resolve() if args.artifact else bundle(prefix, state)
    command, script = executable_command(args.script, prefix)
    if not artifact.is_file():
        raise ValueError('Environment artifact must exist')
    sites = json.loads((state / 'sites.json').read_text())
    if args.site != 'auto' and args.site not in sites:
        raise ValueError('Unknown site')
    candidates = list(sites) if args.site == 'auto' else [args.site]
    if not candidates:
        raise ValueError('Enroll at least one cluster first')
    cached_digest = None
    if not args.no_cache and all(sites[n]['scheduler'] == 'condor' for n in candidates):
        with artifact.open('rb') as stream:
            cached_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        for name in candidates:
            result = remote_call(sites[name], 'check', cached_digest)
            if not result['cached']:
                result = remote_call(sites[name], 'upload', cached_digest,
                                     artifact.stat().st_size, payload=artifact.read_bytes())
            print(json.dumps({'site': name, 'environment_cache': result}), file=sys.stderr)
    run_dir = state / 'jobs' / uuid.uuid4().hex
    run_dir.mkdir(parents=True)
    files = ([script] if script else []) + [Path(p).resolve() for p in args.input]
    names = [p.name for p in files]
    if set(names) & {'launch.sh', 'environment.tar.gz', '.clusterlink-env', 'job.sub', 'submission.json'}:
        raise ValueError('Input filename conflicts with reserved runtime filenames')
    if len(names) != len(set(names)) or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', n) for n in names):
        raise ValueError('Input basenames must be distinct and contain no whitespace/metacharacters')
    for name in args.output:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in {'.', '..'}:
            raise ValueError('Output names must be simple filenames')
    for p in files:
        shutil.copy2(p, run_dir / p.name)
    if not cached_digest:
        shutil.copy2(artifact, run_dir / 'environment.tar.gz')
        names.append('environment.tar.gz')
    launcher = run_dir / 'launch.sh'
    launcher.write_text(make_launcher(command, cached_digest + '.tar.gz' if cached_digest else 'environment.tar.gz', prefix, script.name if script else None))
    launcher.chmod(0o700)
    sites = json.loads((state / 'sites.json').read_text())
    if args.site != 'auto' and args.site not in sites:
        raise ValueError('Unknown site')
    # Native Condor V2 argument quoting; do not use shell escaping here.
    arguments = '"' + ' '.join("'" + a.replace("'", "''").replace('"', '""') + "'" for a in args.arguments) + '"'
    description = f'''universe = vanilla
executable = {launcher}
arguments = {arguments}
initialdir = {run_dir}
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
transfer_input_files = {','.join(names)}
transfer_output_files = {','.join(args.output)}
output = stdout.txt
error = stderr.txt
log = events.log
request_cpus = 1
request_memory = 1024
request_disk = 2097152
+BatchRuntime = 300
+NodeNumber = 1
+ClusterlinkEligible = True
+ClusterlinkSite = "{args.site}"
+ClusterlinkRun = "{run_dir.name}"
+ClusterlinkPrepared = True
{('+ClusterlinkCachedEnv = ' + json.dumps(cached_digest)) if cached_digest else ''}
queue
'''
    path = run_dir / 'job.sub'
    path.write_text(description)
    out = subprocess.check_output(['condor_submit', '-terse', str(path)], env=environment(state), text=True)
    save(run_dir / 'submission.json', {'condor_id': out.strip(), 'run_dir': str(run_dir)})
    print(json.dumps({'condor_id': out.strip(), 'run_dir': str(run_dir)}))


def main():
    parser = argparse.ArgumentParser(description="Personal HTCondor cluster enrollment prototype")
    parser.add_argument("--state", default=os.environ.get("CLUSTERLINK_STATE", "./local/clusterlink"))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser('activate', help='Select a Conda environment for ordinary Condor submissions')
    p.add_argument('--env', default=os.environ.get('CONDA_PREFIX'))
    p = sub.add_parser("enroll")
    p.add_argument("name")
    p.add_argument("--ssh", required=True)
    p.add_argument('--update', action='store_true', help='Update an existing enrollment (stop its jobs first)')
    p.add_argument('--helpers', choices=['auto', 'portable'], default='auto')
    p.add_argument("--scheduler", choices=["condor", "slurm"])
    p.add_argument("--transport", choices=["auto", "exec", "login"], default="auto")
    p.add_argument("--remote-dir")
    p.add_argument("--cache-gb", type=float, required=True)
    p.add_argument("--storage-gb", type=float, required=True)
    p.add_argument("--reserve-gb", type=float, default=1)
    p.add_argument("--max-idle", type=int, default=2)
    p.add_argument("--max-jobs", type=int, default=10)
    p = sub.add_parser("pack")
    p.add_argument("--env")
    p = sub.add_parser("cache")
    p.add_argument("artifact")
    p.add_argument("--site")
    sub.add_parser("status")
    p = sub.add_parser('submit')
    p.add_argument('--artifact', help='Use an existing bundle instead of automatically packing the environment')
    p.add_argument('--env', help='Conda environment prefix (default: active environment)')
    p.add_argument('--no-cache', action='store_true', help='Stage the environment with every job')
    p.add_argument('--site', default='auto')
    p.add_argument('--input', action='append', default=[])
    p.add_argument('--output', action='append', default=[])
    p.add_argument('script')
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    p = sub.add_parser("pool")
    p.add_argument("action", choices=["configure", "start", "stop", "queue"])
    p.add_argument("--local-slots", type=int, default=0)
    args = parser.parse_args()
    try:
        state = state_dir(args)
        if args.command == 'activate':
            if not args.env or not (Path(args.env) / 'conda-meta').is_dir():
                raise ValueError('Activate a Conda environment or pass --env PREFIX')
            save(state / 'environment.json', {'prefix': str(Path(args.env).resolve())})
            from . import pool
            pool.configure(state)
            if (state / 'master.pid').exists():
                subprocess.run(['condor_reconfig'], env=pool.environment(state), check=True, stdout=sys.stderr)
            print('export CONDOR_CONFIG=' + shlex.quote(str(state / 'condor.config')))
            print('export CLUSTERLINK_STATE=' + shlex.quote(str(state)))
        elif args.command == "enroll":
            enroll(args, state)
        elif args.command == "pack":
            pack(args, state)
        elif args.command == "cache":
            cache(args, state)
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
            sites = json.loads((state / "sites.json").read_text())
            for name, site in sites.items():
                try:
                    print(json.dumps({"site": name, **remote_call(site, "status")}))
                except Exception as e:
                    print(json.dumps({"site": name, "error": str(e)}))
    except (ValueError, RuntimeError, OSError, KeyError) as e:
        parser.exit(1, f"clusterlink: {e}\n")


def ssh_main():
    from .interactive import main as interactive_main
    interactive_main()


if __name__ == "__main__":
    main()
