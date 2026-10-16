#!/usr/bin/env python
"""Create six tiny CondorIO probes in an initialized test project."""
from pathlib import Path
import json
import shutil

root = Path.cwd()
if not any((p / '.clusterlink/project.json').is_file() for p in [root, *root.parents]):
    raise SystemExit('Run this from an initialized Clusterlink test project')
probe = Path(__file__).with_name('probe.py')
for mode in ('targeted', 'automatic'):
    for site in ('dev1', 'dev3', 'dev4'):
        directory = root / f'{mode}-{site}'
        directory.mkdir()  # Refuse to overwrite a previous run.
        shutil.copyfile(probe, directory / 'probe.py')
        (directory / 'probe.py').chmod(0o755)
        (directory / 'input.json').write_text(json.dumps({
            'token': directory.name, 'values': [1, 2, 3, 4, 5]}))
        submit = '''universe = vanilla
executable = probe.py
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
transfer_input_files = input.json
transfer_output_files = result.json
output = job.out
error = job.err
log = job.log
request_cpus = 1
request_memory = 512MB
request_disk = 256MB
+BatchExtraSubmitArgs = "periodic_remove = (JobStatus == 2) && (time() - JobCurrentStartDate > 300)"
'''
        if mode == 'targeted':
            submit += f'+ClusterlinkSite = "{site}"\n'
        (directory / 'job.sub').write_text(submit + 'queue\n')
