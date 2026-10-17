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
from .environments import prepared_image, executable_command, launcher
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


def prepare_cache(site, state, artifact, digest, ident):
    """Coalesce waiting hooks' cache pins; keep individual durable job leases."""
    cache_key = hashlib.sha256(json.dumps(site, sort_keys=True).encode()).hexdigest()
    requests = state / 'cache-requests' / cache_key / digest
    requests.mkdir(parents=True, exist_ok=True)
    request = requests / (ident + '.request')
    ready = requests / (ident + '.ready')
    request.touch()
    with (state / ('.upload-' + cache_key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not ready.exists():
            # The first holder handles hooks already waiting behind it. No
            # deliberate batching delay; isolated jobs still start immediately.
            others = [p.stem for p in sorted(requests.glob('*.request'))
                      if p.stem != ident][:255]
            pending, releases = leases.pending(state, site)
            result = remote_call(site, 'check', digest, ident, json.dumps(releases), json.dumps(others))
            leases.acknowledge(pending)
            if not result['cached']:
                enrolled = json.loads((state / 'sites.json').read_text())
                candidates = list(dict.fromkeys(s['root'] for s in enrolled.values()
                                               if s['root'] != site['root']))
                if candidates:
                    result = remote_call(site, 'reuse', digest, json.dumps(candidates), ident)
                if not result['cached']:
                    remote_call(site, 'upload', digest, artifact.stat().st_size, ident, payload=artifact)
                if others:
                    result = remote_call(site, 'check', digest, ident, '[]', json.dumps(others))
                    if not result['cached']:
                        raise RuntimeError('Uploaded cache artifact disappeared before pinning')
            # Publish acknowledgments only after the remote pins succeeded.
            for lease in [ident, *others]:
                (requests / (lease + '.ready')).touch()
                (requests / (lease + '.request')).unlink(missing_ok=True)
        request.unlink(missing_ok=True)
        ready.unlink()


def prepare(ad, site, state):
    # VanillaToGrid removes these for unsandboxed Job Router copies. Our grid
    # copy transfers directly into the source Iwd, so restore them in the route.
    if isinstance(ad.get('TransferOutputRemaps'), str):
        ad['ClusterlinkOutputRemaps'] = ad['TransferOutputRemaps']
    from .project import environment_selection
    selection = environment_selection(state)
    prefix = str(Path(selection['prefix']).resolve())
    requested = ad.get('ClusterlinkEnvironment')
    if isinstance(requested, str) and Path(requested).resolve() != Path(prefix):
        raise ValueError('Job environment must match the project environment')
    backend = ad.get('ClusterlinkBackend')
    if backend not in (None, classad2.Value.Undefined, 'sif'):
        raise ValueError('Only SIF execution is supported')
    selected = ad.get('ClusterlinkArtifact')
    if selected is not None and selected != classad2.Value.Undefined:
        raise ValueError('Archive overrides are unsupported; use the project environment')
    ident = hashlib.sha256(str(ad.get('GlobalJobId', '')).encode()).hexdigest()
    work = state / 'prepared' / ident
    work.mkdir(parents=True, exist_ok=True)
    artifact, digest, environment_disk = prepared_image(state, selection)
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
    # Cache filenames retain the legacy suffix for remote protocol compatibility;
    # tar auto-detects compressed old bundles and uncompressed new bundles.
    archive = digest + '.tar.gz'
    if site['scheduler'] == 'condor' and ad.get('ClusterlinkNoCache') is not True:
        prepare_cache(site, state, artifact, digest, ident)
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
        native_extra = ad.get('BatchExtraSubmitArgs')
        if isinstance(native_extra, str) and native_extra.strip():
            extra += native_extra.rstrip() + '\n'
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
