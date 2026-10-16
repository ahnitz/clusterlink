"""Resolve a local routed job and delegate interaction to remote Condor."""
import argparse
import json
import os
from pathlib import Path
import re
import select
import shlex
import subprocess
import sys
import termios
import tty

from .pool import environment


def query(state, job):
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', job):
        raise ValueError('Job ID must be CLUSTER or CLUSTER.PROC')
    ads = json.loads(subprocess.check_output(['condor_q', job, '-json'], env=environment(state)))
    if len(ads) != 1:
        raise ValueError('Expected one queued job; specify CLUSTER.PROC for multi-job clusters')
    return ads[0]


def resolve(state, job):
    ad = query(state, job)
    if ad.get('RoutedToJobId'):
        ad = query(state, ad['RoutedToJobId'])
    site_name = ad.get('ClusterlinkDestination')
    sites = json.loads((state / 'sites.json').read_text())
    if site_name not in sites:
        raise ValueError('Job has not yet been routed to an enrolled site')
    site = sites[site_name]
    if site['scheduler'] != 'condor':
        raise ValueError('Interactive forwarding currently supports remote HTCondor only')
    match = re.fullmatch(r'batch condor \S+ condor/([0-9]+)/([^/]*)/([^/]*)', ad.get('GridJobId', ''))
    if not match:
        raise ValueError('Remote job ID is not available yet')
    cluster, schedd, pool = match.groups()
    argv = ['condor_ssh_to_job', '-shells', '/bin/sh', '-ssh', 'ssh -tt']
    if schedd:
        argv += ['-name', schedd]
    if pool:
        argv += ['-pool', pool]
    argv.append(cluster + '.0')
    return site, argv


def connect(site, argv):
    command = shlex.join(argv)
    ssh = ['ssh', '-T', '-o', 'ConnectTimeout=15', site['ssh']]
    if site['transport'] == 'exec':
        return subprocess.call([*ssh, command])
    # Login-shell transport also supports sites with problematic exec startup.
    # The inner SSH allocates the job terminal; the head-node shell stays
    # noninteractive to avoid terminal-dependent startup scripts.
    proc = subprocess.Popen(ssh, stdin=subprocess.PIPE)
    original = None
    try:
        proc.stdin.write(('exec ' + command + '\n').encode())
        proc.stdin.flush()
        if sys.stdin.isatty():
            original = termios.tcgetattr(0)
            tty.setraw(0)
        while proc.poll() is None:
            ready, _, _ = select.select([sys.stdin], [], [], 0.2)
            if ready:
                data = os.read(0, 65536)
                if not data:
                    proc.stdin.close()
                    return proc.wait()
                proc.stdin.write(data)
                proc.stdin.flush()
        return proc.returncode
    finally:
        if original is not None:
            termios.tcsetattr(0, termios.TCSADRAIN, original)
        if proc.poll() is None:
            proc.terminate()
            proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', default=None)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('job')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        from .project import discover
        site, argv = resolve(discover(args.state), args.job)
        argv += args.command
        if args.dry_run:
            print(json.dumps({'ssh': site['ssh'], 'transport': site['transport'], 'command': argv}))
        else:
            raise SystemExit(connect(site, argv))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'ssh_to_job: {error}\n')
