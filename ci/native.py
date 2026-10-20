"""Real private-pool integration; no SSH, image downloads, or existing pools.

Run with the installed wheel's Python and an empty output directory argument.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from clusterlink import pool


def command(state, *args, check=True):
    result = subprocess.run(args, env=pool.environment(state), text=True,
                            capture_output=True, timeout=45)
    if check and result.returncode:
        raise RuntimeError(f'{args}: {result.stdout}\n{result.stderr}')
    return result


def create(root, name, slots=1):
    state = root / name
    state.mkdir()
    (state / 'sites.json').write_text('{}')
    (state / 'project.json').write_text(json.dumps({'id': name, 'root': str(state.parent)}))
    pool.configure(state, local_slots=slots, local_helpers=1)
    with (state / 'condor.config').open('a') as config:
        config.write('\nNEGOTIATOR_INTERVAL = 2\nUPDATE_INTERVAL = 2\n')
    return state


def submit(state, name, site='condorpool_shared', universe='vanilla', seconds=0, exit_code=0):
    script = state / (name + '.sh')
    script.write_text(f'#!/bin/sh\nsleep {seconds}\ncat input.txt > result.txt\nexit {exit_code}\n')
    script.chmod(0o700)
    work = state / name
    work.mkdir()
    (work / 'input.txt').write_text(name)
    sub = work / 'job.sub'
    sub.write_text(f'''universe = {universe}
executable = {script}
initialdir = {work}
+ClusterlinkEligible = True
+pegasus_site = "{site}"
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
transfer_input_files = input.txt
transfer_output_files = result.txt
request_cpus = 1
request_memory = 64MB
request_disk = 10MB
output = job.out
error = job.err
log = job.log
queue
''')
    result = command(state, 'condor_submit', '-terse', str(sub))
    return result.stdout.split()[0], work


def wait_until(predicate, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(1)
    raise AssertionError('Timed out waiting for native HTCondor state')


def ads(state, history=False):
    return json.loads(command(state, 'condor_history' if history else 'condor_q', '-json').stdout or '[]')


def completed(state, job, expected=0):
    rows = [ad for ad in ads(state, True) if f"{ad['ClusterId']}.{ad['ProcId']}" == job]
    if not rows:
        held = [ad for ad in ads(state) if ad.get('JobStatus') == 5]
        assert not held, held
        return False
    assert rows[0]['JobStatus'] == 4 and rows[0]['ExitCode'] == expected, rows
    assert 'RoutedToJobId' not in rows[0], rows
    return rows[0]


def main(root):
    root.mkdir(parents=True, exist_ok=False)
    states = [create(root, 'first'), create(root, 'second'), create(root, 'no-workers', 0)]
    evidence = {}
    try:
        for state in states:
            pool.start(state)
        first, second, empty = states
        # Fail at submission instead of leaving unrouted work idle.
        try:
            submit(empty, 'reject')
        except RuntimeError as error:
            assert 'local execution slots' in str(error), error
        else:
            raise AssertionError('An unrouted job was accepted without local capacity')
        jobs = []
        for state, site, universe, code in [
            (first, 'condorpool_shared', 'vanilla', 0),
            (first, 'condorpool_symlink', 'vanilla', 0),
            (first, 'local', 'local', 0),
            (second, 'condorpool_shared', 'vanilla', 7),
        ]:
            job, work = submit(state, site, site, universe, exit_code=code)
            jobs.append((state, job, work, code))
        remote_job, _ = submit(first, 'remote-only', 'clusterlink')
        for state, job, work, code in jobs:
            ad = wait_until(lambda: completed(state, job, code))
            assert (work / 'result.txt').read_text() == work.name
            evidence[state.name + '/' + work.name] = {'job': job, 'exit_code': ad['ExitCode']}
        remote = [ad for ad in ads(first) if f"{ad['ClusterId']}.{ad['ProcId']}" == remote_job]
        assert len(remote) == 1 and remote[0]['JobStatus'] == 1, remote
        assert not ads(second), 'Project queues leaked into each other'
        # Native removal and queue persistence across a controlled manager restart.
        command(first, 'condor_off', '-master')
        wait_until(lambda: not pool.running(first))
        pool.start(first)
        assert any(ad['ClusterId'] == int(remote_job.split('.')[0]) for ad in ads(first))
        command(first, 'condor_rm', remote_job)
        wait_until(lambda: not ads(first))
        # Two local helpers must not execute simultaneously at a configured cap of one.
        one, _ = submit(first, 'helper-one', 'local', 'local', seconds=3)
        two, _ = submit(first, 'helper-two', 'local', 'local', seconds=3)
        a = wait_until(lambda: completed(first, one))
        b = wait_until(lambda: completed(first, two))
        assert a['CompletionDate'] <= b['JobStartDate'] or b['CompletionDate'] <= a['JobStartDate'], (a, b)
        # A real DAGMan chain stages the first node's output into a new sandbox.
        dagwork = root / 'dag'
        dagwork.mkdir()
        (dagwork / 'seed.txt').write_text('intermediate transfer verified')
        for name, source, output in [('one', 'seed.txt', 'intermediate.txt'),
                                     ('two', 'intermediate.txt', 'final.txt')]:
            (dagwork / (name + '.sub')).write_text(f"""universe = vanilla
executable = /bin/cp
arguments = {source} {output}
initialdir = {dagwork}
+ClusterlinkEligible = False
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
transfer_input_files = {source}
transfer_output_files = {output}
request_cpus = 1
request_memory = 64MB
output = {name}.out
error = {name}.err
log = {name}.log
queue
""")
        dag = dagwork / 'chain.dag'
        dag.write_text(f'JOB one {dagwork}/one.sub\nJOB two {dagwork}/two.sub\nPARENT one CHILD two\n')
        command(first, 'condor_submit_dag', '-force', str(dag))
        wait_until(lambda: (dagwork / 'final.txt').exists())
        assert (dagwork / 'final.txt').read_text() == 'intermediate transfer verified'
        wait_until(lambda: not ads(first))
        managers = [ad for ad in ads(first, True) if ad.get('JobUniverse') == 7]
        assert managers and all(ad.get('ExitCode') == 0 for ad in managers), managers
        evidence['isolation_restart_removal_helper_cap_dag_transfers'] = 'passed' 
        (root / 'results.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(json.dumps(evidence, indent=2), flush=True)
    finally:
        for state in states:
            for name, args in [('queue.json', ('condor_q', '-json')),
                               ('history.json', ('condor_history', '-json'))]:
                try:
                    (state / name).write_text(command(state, *args, check=False).stdout)
                except subprocess.TimeoutExpired:
                    pass
            command(state, 'condor_off', '-master', check=False)
        for state in states:
            wait_until(lambda: not pool.running(state), seconds=45)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    main(parser.parse_args().output.resolve())
