"""CLI-driven SSH/SIF acceptance against ci/ssh-setup.sh's disposable accounts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from clusterlink import pool
from native import command, wait_until, ads


def cli(root, *args):
    result = subprocess.run(['clusterlink', *args], cwd=root,
                            text=True, capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError(f'clusterlink {args}: {result.stdout}\n{result.stderr}')
    return result


def finish(state, job, expected=0):
    for ad in ads(state, True):
        if f"{ad['ClusterId']}.{ad['ProcId']}" == job:
            assert ad['JobStatus'] == 4 and ad.get('ExitCode') == expected, ad
            return ad
    held = [ad for ad in ads(state) if ad.get('JobStatus') == 5]
    assert not held, held
    return False


def inside(root):
    state = root / '.clusterlink'
    expected = hashlib.sha256(b'only staged input\n').hexdigest()
    jobs = []
    for name, site, code in [('first', 'cia', 0), ('second', 'cib', 0), ('failure', 'cia', 7), ('automatic', None, 0)]:
        work = root / name
        work.mkdir()
        (work / 'input.txt').write_text('only staged input\n')
        script = work / 'payload.py'
        script.write_text('''import hashlib,json,os,sys
from pathlib import Path
assert sys.prefix == '/opt/clusterlink/env', sys.prefix
assert not Path(sys.argv[1]).exists(), 'Submit-only file visible on worker'
data={'digest':hashlib.sha256(Path('input.txt').read_bytes()).hexdigest(),
      'site':os.environ['CI_SITE'], 'prefix':sys.prefix}
Path('result.json').write_text(json.dumps(data))
sys.exit(int(sys.argv[2]))
''')
        extra = f'+ClusterlinkSite = "{site}"\n' if site else ''
        sub = work / 'job.sub'
        sub.write_text(f'''universe = vanilla
executable = {os.environ['CONDA_PREFIX']}/bin/python
arguments = "payload.py {root}/submit-only {code}"
initialdir = {work}
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
transfer_input_files = payload.py,input.txt
transfer_output_files = result.json
+pegasus_site = "clusterlink"
+REMOTE_Requirements = False
+REMOTE_Requirements_cia = True
+REMOTE_Requirements_cib = True
+REMOTE_Environment_cia = "CI_SITE=cia"
+REMOTE_Environment_cib = "CI_SITE=cib"
request_cpus = 1
request_memory = 256MB
request_disk = 100MB
output = job.out
error = job.err
log = job.log
{extra}queue
''')
        job = command(state, 'condor_submit', '-terse', str(sub)).stdout.split()[0]
        jobs.append((job, work, site, code))
    evidence = []
    for job, work, site, code in jobs:
        ad = wait_until(lambda: finish(state, job, code), seconds=600)
        data = json.loads((work / 'result.json').read_text())
        assert data['digest'] == expected, data
        assert data['site'] in ('cia', 'cib') and (site is None or data['site'] == site), data
        evidence.append({'job': job, 'result': data, 'exit_code': ad['ExitCode']})
    # Cancel a running remote job and verify both destination queues drain.
    sleeper = root / 'sleeper.py'
    sleeper.write_text('import time; time.sleep(1800)\n')
    submitted = json.loads(cli(root, 'submit', '--site', 'cia', '--runtime', '1800', str(sleeper)).stdout)
    cancel_id = submitted['condor_id'].split()[0]
    wait_until(lambda: any(f"{ad['ClusterId']}.{ad['ProcId']}" == cancel_id and
                          ad['JobStatus'] == 2 for ad in ads(state)), seconds=300)
    command(state, 'condor_rm', cancel_id)
    remote_ads = {}
    def empty_destinations():
        for site in ('cia', 'cib'):
            raw = subprocess.check_output(['ssh', site, 'condor_q', '-json'], text=True, timeout=30)
            remote_ads[site] = json.loads(raw or '[]')
        # Native batch submission may retain terminal ads for status queries.
        # Cancellation must end execution, not erase those accounting records.
        return not any(ad['JobStatus'] not in (3, 4)
                       for rows in remote_ads.values() for ad in rows)
    try:
        wait_until(empty_destinations, seconds=600)
    finally:
        (root / 'remote-after-cancel.json').write_text(json.dumps(remote_ads, indent=2))
        compact = {site: [{key: ad.get(key) for key in ('ClusterId', 'ProcId', 'JobStatus',
                   'HoldReason', 'ExitCode')} for ad in rows] for site, rows in remote_ads.items()}
        print('Remote cancellation state:', json.dumps(compact), flush=True)
    # Cache uploads must converge to one artifact per destination, and all leases drain.
    def drained():
        status = json.loads(cli(root, 'status', '--remote', '--json').stdout)
        for site in status['sites']:
            assert 'remote_error' not in site, site
            if site['remote']['active_leases']:
                return False
        return status
    status = wait_until(drained, seconds=120)
    for site in status['sites']:
        remote = site['remote']
        assert remote['cache_used_bytes'] <= site['limits']['cache_bytes'], remote
        count = subprocess.check_output(['ssh', site['name'], 'find', site['root'] + '/cache',
                                         '-maxdepth', '1', '-name', "'*.tar.gz'", '-type', 'f'], text=True)
        assert len(count.splitlines()) == 1, count
    (root / 'results.json').write_text(json.dumps({'jobs': evidence, 'status': status}, indent=2))


def main(root, prefix):
    root.mkdir(parents=True, mode=0o700)
    (root / 'submit-only').write_text('must not be accessible to destination users')
    cli(root, 'init', '--env', str(prefix))
    for site in ('cia', 'cib'):
        cli(root, 'enroll', site, '--ssh', site, '--cache-gb', '2', '--storage-gb', '5',
            '--reserve-gb', '0.1', '--max-jobs', '2', '--max-idle', '1', '--helpers', 'portable')
        # Explicitly demonstrate host filesystem isolation before execution.
        subprocess.run(['ssh', site, 'test', '!', '-r', str(root / 'submit-only')], check=True)
    try:
        # Exercise actual activate shell and environment selection, not a manual image fixture.
        import shlex
        script = shlex.join([sys.executable, str(Path(__file__).resolve()), '--inside', str(root)])
        result = subprocess.run(['clusterlink', 'activate'], cwd=root,
                                input=script + '\nexit $?\n', text=True, timeout=1800)
        assert result.returncode == 0, result.returncode
        assert (root / 'results.json').is_file()
    finally:
        state = root / '.clusterlink'
        if (state / 'condor.config').exists():
            command(state, 'condor_off', '-master', check=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', action='store_true')
    parser.add_argument('output', type=Path)
    parser.add_argument('--env', type=Path)
    args = parser.parse_args()
    if args.inside:
        inside(args.output.resolve())
    else:
        main(args.output.resolve(), args.env.resolve())
