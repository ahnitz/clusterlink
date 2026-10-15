"""Plan a two-stage CondorIO workflow against the local Clusterlink pool."""
import argparse
from pathlib import Path
from Pegasus.api import (Arch, Directory, File, FileServer, Job, Namespace, Operation,
                         OS, Properties, ReplicaCatalog, Site, SiteCatalog,
                         Transformation, TransformationCatalog, Workflow)

parser = argparse.ArgumentParser()
parser.add_argument('--work-dir', required=True)
args = parser.parse_args()
work = Path(args.work_dir).resolve()
work.mkdir(parents=True, exist_ok=True)
examples = Path(__file__).resolve().parent
local = Site('local', arch=Arch.X86_64, os_type=OS.LINUX)
for kind, name in [(Directory.SHARED_SCRATCH, 'scratch'), (Directory.LOCAL_STORAGE, 'outputs')]:
    path=work/name
    path.mkdir(exist_ok=True)
    local.add_directories(Directory(kind,str(path)).add_file_servers(FileServer('file://'+str(path),Operation.ALL)))
remote = Site('clusterlink', arch=Arch.X86_64, os_type=OS.LINUX).add_pegasus_profile(
    style='condor', data_configuration='condorio').add_condor_profile(universe='vanilla')
sc=SiteCatalog().add_sites(local,remote)
sc.write(work/'sites.yml')
props=Properties()
props['pegasus.data.configuration']='condorio'
props['pegasus.transfer.worker.package']='true'
props['pegasus.transfer.worker.package.strict']='false'
props['pegasus.catalog.master.url']='sqlite:///' + str(work/'master.db')
props.write(work/'pegasus.properties')
rc=ReplicaCatalog().add_replica('local',File('input.json'),str(examples/'input.json'))
tc=TransformationCatalog()
for name in ['analyze','summarize']:
    tc.add_transformations(Transformation(name,site='local',pfn=str(examples/(name+'.py')),
                                          is_stageable=True,arch=Arch.X86_64,os_type=OS.LINUX))
wf=Workflow('clusterlink-smoke').add_site_catalog(sc).add_replica_catalog(rc).add_transformation_catalog(tc)
source=File('input.json'); middle=File('intermediate.json'); output=File('result.json')
first=Job('analyze').add_args(source,middle).add_inputs(source).add_outputs(middle,stage_out=False)
second=Job('summarize').add_args(middle,output).add_inputs(middle).add_outputs(output)
wf.add_jobs(first,second)
wf.write(work/'workflow.yml')
wf.plan(dir=work/'submit',sites=['clusterlink'],output_sites=['local'],
        conf=work/'pegasus.properties',submit=True)
print(wf.braindump.submit_dir)
