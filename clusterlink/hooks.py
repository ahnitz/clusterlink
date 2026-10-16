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
from .environments import bundle, executable_command, launcher, required_bundle_disk
from . import leases


def remote_output_settings(outputs):
    """Let remote Condor flatten outputs; GridManager fetches those basenames."""
    paths = [p for p in outputs.split(',') if p]
    nested = [p for p in paths if '/' in p]
    if not nested:
        return ''
    names = [Path(p).name for p in paths]
    if len(names) != len(set(names)):
        raise ValueError('Remote Condor outputs must have distinct basenames')
    for path in nested:
        if (Path(path).is_absolute() or '..' in Path(path).parts
                or not re.fullmatch(r'[A-Za-z0-9_./-]+', path)):
            raise ValueError('Nested remote output paths must be safe relative paths')
    return 'transfer_output_files = ' + outputs + '\n'


def prepare(ad, site, state):
    # VanillaToGrid removes these for unsandboxed Job Router copies. Our grid
    # copy transfers directly into the source Iwd, so restore them in the route.
    if isinstance(ad.get('TransferOutputRemaps'), str):
        ad['ClusterlinkOutputRemaps'] = ad['TransferOutputRemaps']
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
        selected = ad.get('ClusterlinkArtifact')
        if selected is not None and selected != classad2.Value.Undefined:
            if not isinstance(selected, str) or not Path(selected).is_file():
                raise ValueError('ClusterlinkArtifact must name an existing environment bundle')
            artifact = Path(selected).resolve()
        else:
            artifact = bundle(prefix, state, backend=ad.get('ClusterlinkBackend', 'conda'), base=ad.get('ClusterlinkContainerBase'))
        environment_disk = required_bundle_disk(artifact)
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
    input_disk = 0
    for value in files:
        path = Path(value)
        if not path.is_absolute():
            path = Path(ad['Iwd']) / path
        if path.is_file():
            input_disk += path.stat().st_size
    # Packaging introduces disk usage the original submit file cannot know.
    # Preserve the user's working-space request and add inputs plus environment.
    ad['RequestDisk'] = int(ad.get('RequestDisk', 0)) + (environment_disk + input_disk + 1023)//1024 + 65536
    archive = digest + '.tar.gz'
    if site['scheduler'] == 'condor' and ad.get('ClusterlinkNoCache') is not True:
        cache_key = hashlib.sha256(json.dumps(site, sort_keys=True).encode()).hexdigest()
        # Serialize check+upload locally so simultaneous jobs do not send the
        # same large environment over SSH before the first upload completes.
        with (state / ('.upload-' + cache_key + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pending, releases = leases.pending(state, site)
            result = remote_call(site, 'check', digest, ident, json.dumps(releases))
            leases.acknowledge(pending)
            if not result['cached']:
                enrolled = json.loads((state / 'sites.json').read_text())
                candidates = list(dict.fromkeys(s['root'] for s in enrolled.values()
                                               if s['root'] != site['root']))
                if candidates:
                    result = remote_call(site, 'reuse', digest, json.dumps(candidates), ident)
            if not result['cached']:
                remote_call(site, 'upload', digest, artifact.stat().st_size, ident,
                            payload=artifact)
        ad['ClusterlinkCachedEnv'] = digest
        ad['ClusterlinkLease'] = ident
    else:
        archive = artifact.name
        files.append(str(artifact))
    wrapper = work / 'launch.sh'
    wrapper.write_text(launcher(command, archive, prefix, external.name if external else None,
                                ad.get('TransferOutput', '').split(',')))
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
        outputs = ad.get('TransferOutput', '')
        output_settings = remote_output_settings(outputs)
        if output_settings:
            extra += output_settings
            ad['TransferOutput'] = ','.join(Path(p).name for p in outputs.split(',') if p)
        if 'Requirements' in ad:
            extra += 'requirements = ' + str(ad.lookup('Requirements')) + '\n'
        ad['ClusterlinkRemoteSubmitArgs'] = extra
    return ad


def serialize(ad):
    """Serialize hook updates as one assignment per physical line."""
    # ExprTree escapes string contents, but pretty-prints nested ads/lists over
    # several lines. Collapse only those physical formatting newlines.
    lines = []
    for key in ad:
        expression = str(ad.lookup(key)).replace('\n', ' ').replace('\r', ' ')
        lines.append(f'{key} = {expression}')
    return '\n'.join(lines) + '\n'


def main():
    try:
        state = Path(os.environ['CLUSTERLINK_STATE'])
        if len(sys.argv) > 1 and sys.argv[1] == 'cleanup':
            ad = classad2.parseOne(sys.stdin.read())
            lease = ad.get('ClusterlinkLease')
            if isinstance(lease, str):
                sites = json.loads((state / 'sites.json').read_text())
                site = sites[ad['ClusterlinkDestination']]
                leases.defer(state, site, ad['ClusterlinkCachedEnv'], lease)
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
