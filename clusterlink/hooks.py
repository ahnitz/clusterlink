"""Native Job Router hook: prepare software, leaving scheduling to HTCondor."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import classad2

from .cli import remote_call
from .environments import bundle, executable_command, launcher


def prepare(ad, site, state):
    # The convenience submit command has already prepared its launcher.
    if ad.get('ClusterlinkPrepared') is True:
        return ad
    prefix = ad.get('ClusterlinkEnvironment')
    if not isinstance(prefix, str):
        raise ValueError('No Conda environment selected; run clusterlink activate first')
    prefix = str(Path(prefix).resolve())
    ident = hashlib.sha256(str(ad.get('GlobalJobId', '')).encode()).hexdigest()
    work = state / 'prepared' / ident
    work.mkdir(parents=True, exist_ok=True)
    with (state / '.pack.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        artifact = bundle(prefix, state)
    with artifact.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    inputs = ad.get('TransferInput', '')
    if not isinstance(inputs, str):
        inputs = ''
    executable = Path(ad['Cmd'])
    if not executable.is_absolute():
        executable = Path(ad['Iwd']) / executable
    command, external = executable_command(str(executable), prefix)
    files = [p for p in inputs.split(',') if p]
    if external and str(external) not in files and external.name not in files:
        files.append(str(external))
    archive = digest + '.tar.gz'
    if site['scheduler'] == 'condor' and ad.get('ClusterlinkNoCache') is not True:
        result = remote_call(site, 'check', digest, ident)
        if not result['cached']:
            remote_call(site, 'upload', digest, artifact.stat().st_size, ident,
                        payload=artifact)
        ad['ClusterlinkCachedEnv'] = digest
        ad['ClusterlinkLease'] = ident
    else:
        archive = artifact.name
        files.append(str(artifact))
    wrapper = work / 'launch.sh'
    wrapper.write_text(launcher(command, archive, prefix, external.name if external else None))
    wrapper.chmod(0o700)
    ad['Cmd'] = str(wrapper)
    ad['TransferExecutable'] = True
    ad['TransferInput'] = ','.join(files)
    ad['ShouldTransferFiles'] = 'YES'
    ad['ClusterlinkPrepared'] = True
    ad['NodeNumber'] = int(ad.get('RequestCpus', 1))
    if isinstance(ad.get('RequestGPUs'), (int, float)):
        ad['GPUNumber'] = int(ad['RequestGPUs'])
    if site['scheduler'] == 'condor':
        extra = 'request_disk = ' + str(int(ad.get('RequestDisk', 2097152))) + ' KB\n'
        if 'Requirements' in ad:
            extra += 'requirements = ' + str(ad.lookup('Requirements')) + '\n'
        ad['ClusterlinkRemoteSubmitArgs'] = extra
    return ad


def serialize(ad):
    """Serialize hook updates as one assignment per physical line."""
    return "\n".join(f"{key} = {ad.lookup(key)}" for key in ad) + "\n"


def main():
    try:
        state = Path(os.environ['CLUSTERLINK_STATE'])
        if len(sys.argv) > 1 and sys.argv[1] == 'cleanup':
            ad = classad2.parseOne(sys.stdin.read())
            lease = ad.get('ClusterlinkLease')
            if isinstance(lease, str):
                sites = json.loads((state / 'sites.json').read_text())
                site = sites[ad['ClusterlinkDestination']]
                remote_call(site, 'release', ad['ClusterlinkCachedEnv'], lease)
            return
        header, source = re.split(r'\n-{6,}\n', sys.stdin.read(), maxsplit=1)
        route = classad2.parseOne(header)
        ad = classad2.parseOne(source)
        sites = json.loads((state / 'sites.json').read_text())
        # GridResource is supplied by the native router, not selected here.
        site_name = route['GridResource'].split()[2]
        ad = prepare(ad, sites[site_name], state)
        # The native hook reader inserts one ClassAd assignment per line.
        # printOld() emits literal newlines inside string values; ExprTree's
        # string representation escapes them for this line-oriented protocol.
        sys.stdout.write(serialize(ad))
    except Exception as error:
        print('clusterlink preparation failed: ' + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
