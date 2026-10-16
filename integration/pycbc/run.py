#!/usr/bin/env python3
"""Generate and submit a fresh mini search inside a Clusterlink project shell."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--pegasus', type=Path, required=True)
    parser.add_argument('--java', type=Path, required=True)
    args = parser.parse_args()
    work = Path.cwd().resolve()
    selection = json.loads((work / '.clusterlink/environment.json').read_text())
    if Path(sys.prefix).resolve() != Path(selection['prefix']).resolve():
        parser.error('Run with python inside clusterlink activate for this project')
    if (work / 'output').exists():
        parser.error('output already exists; use a fresh project for acceptance')
    env = dict(os.environ)
    env.update(PATH=os.pathsep.join([str(Path(sys.prefix)/'bin'),
                                   str(args.pegasus.resolve()/'bin'),
                                   str(args.java.resolve()/'bin'), '/usr/bin', '/bin']),
               JAVA_HOME=str(args.java.resolve()), PEGASUS_JAVA_HOME=str(args.java.resolve()),
               PEGASUS_PYTHON=sys.executable, PYTHONNOUSERSITE='1', PEGASUS_METRICS='false',
               MPLCONFIGDIR=str(work/'mpl'), XDG_CACHE_HOME=str(work/'cache'),
               TMPDIR=str(work/'tmp'))
    for directory in ('mpl', 'cache', 'tmp'):
        (work/directory).mkdir(exist_ok=True)
    steps = [
        ('bank', ['bash', str(args.source.resolve()/'examples/search/bank.sh')], work),
        ('stats', ['bash', str(args.source.resolve()/'examples/search/stats.sh')], work),
        ('generate', ['pycbc_make_offline_search_workflow', '--workflow-name', 'gw',
                      '--output-dir', 'output', '--config-files', 'analysis.ini',
                      'plotting.ini', 'executables.ini', 'injections_minimal.ini',
                      '--config-overrides', 'results_page:output-path:'+str(work/'html'),
                      '--plan-now'], work),
        ('submit', ['bash', './start'], work/'output'),
    ]
    (work/'run-commands.json').write_text(json.dumps(
        [{'stage': name, 'command': command, 'cwd': str(cwd)} for name, command, cwd in steps], indent=2)+'\n')
    for name, command, cwd in steps:
        print(f'{name}: see {work/name}.log', flush=True)
        with (work/(name+'.log')).open('w') as log:
            subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    print('Submitted once. Observe with condor_q; validate output after completion.', flush=True)


if __name__ == '__main__':
    main()
