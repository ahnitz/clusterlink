"""Convenience submission through the same native hook used by workflow engines."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from .pool import environment


def submit(args, state):
    prefix=Path(args.env or os.environ.get('CONDA_PREFIX','')).resolve()
    if not (prefix/'conda-meta').is_dir():
        raise ValueError('Activate a Conda environment or pass --env PREFIX')
    sites=json.loads((state/'sites.json').read_text())
    if args.site != 'auto' and args.site not in sites:
        raise ValueError('Unknown destination')
    script=Path(args.script).expanduser()
    if not script.is_file():
        script=prefix/'bin'/args.script
    if not script.is_file():
        raise ValueError('Executable not found: '+args.script)
    script=script.resolve()
    files=[Path(p).resolve() for p in args.input]
    argv=list(args.arguments)
    external=prefix not in script.parents
    if external:
        files.insert(0,script)
    names=[p.name for p in files]
    reserved={'job.sub','events.log','stdout.txt','stderr.txt','submission.json','.clusterlink-env','launch.sh'}
    if len(names)!=len(set(names)) or any(not re.fullmatch(r'[A-Za-z0-9_.-]+',n) or n in reserved for n in names):
        raise ValueError('Inputs need distinct, simple filenames, without runtime filename collisions')
    for name in args.output:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or name in reserved|{'.','..'}:
            raise ValueError('Outputs need simple filenames without runtime filename collisions')
    folder=state/'jobs'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    for path in files:
        shutil.copy2(path,folder/path.name)
    command=script
    if external:
        command=folder/script.name
        if script.suffix=='.py':
            command=prefix/'bin/python'
            argv.insert(0,script.name)
    arguments='"'+' '.join("'"+a.replace("'","''").replace('"','""')+"'" for a in argv)+'"'
    description=f'''universe = vanilla
executable = {command}
arguments = {arguments}
initialdir = {folder}
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
transfer_input_files = {','.join(names)}
transfer_output_files = {','.join(args.output)}
output = stdout.txt
error = stderr.txt
log = events.log
request_cpus = {args.cpus}
request_memory = {args.memory_mb}
request_disk = {args.disk_mb * 1024}
+BatchRuntime = {args.runtime}
+ClusterlinkEnvironment = {json.dumps(str(prefix))}
+ClusterlinkEligible = True
+ClusterlinkSite = {json.dumps(args.site)}
+ClusterlinkNoCache = {str(args.no_cache)}
queue
'''
    path=folder/'job.sub';path.write_text(description)
    job=subprocess.check_output(['condor_submit','-terse',str(path)],env=environment(state),text=True).strip()
    result={'condor_id':job,'run_dir':str(folder)}
    (folder/'submission.json').write_text(json.dumps(result)+'\n')
    print(json.dumps(result))
