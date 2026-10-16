"""Apply only site/config adaptations to a separately installed PyCBC checkout."""
import argparse
import difflib
from pathlib import Path
import shutil
from urllib.parse import urlparse, unquote

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--env', type=Path, required=True)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--cache-root', type=Path, required=True)
parser.add_argument('--evidence-dir', type=Path, help='Save generated patches outside the repository for a fresh run')
parser.add_argument('--requirements', help='Native Condor requirements for the remote execution site')
args = parser.parse_args()
source, env, work, caches = [x.resolve() for x in (args.source,args.env,args.work,args.cache_root)]
work.mkdir(parents=True, exist_ok=True)
evidence = (args.evidence_dir or Path(__file__).resolve().parent).resolve()
evidence.mkdir(parents=True, exist_ok=True)
site_rel = Path('pycbc/workflow/pegasus_sites.py')
old = (source/site_rel).read_text()
new = old.replace("KNOWN_SITES = ['local',", "KNOWN_SITES = ['local', 'clusterlink',")
function = '''def add_clusterlink_site(sitecat, cp):
    """User-owned SSH federation; Clusterlink supplies the environment."""
    site = Site("clusterlink", arch=Arch.X86_64, os_type=OS.LINUX)
    add_site_pegasus_profile(site, cp)
    site.add_profiles(Namespace.PEGASUS, key="style", value="condor")
    site.add_profiles(Namespace.PEGASUS, key="data.configuration", value="condorio")
    site.add_profiles(Namespace.CONDOR, key="universe", value="vanilla")
    sitecat.add_sites(site)


'''
new = new.replace('def add_site(sitecat,',function+'def add_site(sitecat,').replace("    elif sitename == 'osg':", "    elif sitename == 'clusterlink':\n        add_clusterlink_site(sitecat, cp)\n    elif sitename == 'osg':")
if args.requirements:
    new = new.replace('    sitecat.add_sites(site)\n\n\ndef add_site(sitecat,',
        '    site.add_profiles(Namespace.CONDOR, key="requirements", value='+repr(args.requirements)+')\n'
        '    sitecat.add_sites(site)\n\n\ndef add_site(sitecat,')
installed = next((env/'lib').glob('python*/site-packages'))
(installed/site_rel).write_text(new)
def patch(name, old, new, rel):
    (evidence/name).write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+str(rel),tofile='b/'+str(rel))))
patch('clusterlink-site.patch',old,new,site_rel)
for path in (source/'examples/search').glob('*.ini'):
    shutil.copy2(path,work/path.name)
p=work/'executables.ini';old=p.read_text()
new=old.replace('condor|request_disk = 1000','condor|request_disk = 1024M').replace('condor|accounting_group = ligo.dev.o4.cbc.bbh.pycbcoffline','condor|+BatchRuntime = 3600').replace('pycbc|primary_site = condorpool_symlink','pycbc|primary_site = clusterlink').replace('pycbc|site = condorpool_copy','pycbc|site = clusterlink').replace('pycbc|site = condorpool_shared','pycbc|site = clusterlink')
new=new.replace('[pegasus_profile-results_page]\npycbc|site = clusterlink',
    '[pegasus_profile-results_page]\npycbc|site = local\ncondor|universe = local\n'
    'env|PYTHONNOUSERSITE = 1\nenv|MPLCONFIGDIR = '+str(work/'mpl')+'\n'
    'env|XDG_CACHE_HOME = '+str(work/'cache'))
for generator in ['foreground_minifollowup', 'injection_minifollowup', 'singles_minifollowup']:
    new += ('\n[pegasus_profile-'+generator+']\npycbc|site = local\n'
            'condor|universe = local\nenv|PYTHONNOUSERSITE = 1\n')
p.write_text(new);patch('executables.patch',old,new,'examples/search/executables.ini')
p=work/'analysis.ini';old=p.read_text()
# The workflow imports every supplied cache entry into its replica catalog.
# Bound the input catalog to this test interval, retaining ordinary LCF records.
import re
start=int(re.search(r'^start-time\s*=\s*(\d+)',old,re.M).group(1))
end=int(re.search(r'^end-time\s*=\s*(\d+)',old,re.M).group(1))
selected=work/'frame-cache'
selected.mkdir(exist_ok=True)
followup_frames = {}
for ifo in ['H1','L1','V1']:
    lines=[]
    for line in (caches/(ifo+'.cache')).read_text().splitlines():
        parts=line.split()
        if len(parts)==5 and float(parts[2]) < end+64 and float(parts[2])+float(parts[3]) > start-64:
            lines.append(line)
    if not lines:
        raise ValueError('Cache has no entries for '+ifo+' in the test interval')
    (selected/(ifo+'.cache')).write_text('\n'.join(lines)+'\n')
    followup_frames[ifo] = [unquote(urlparse(line.split()[4]).path) for line in lines]

new='\n'.join(line for line in old.splitlines() if '-frame-file =' not in line and not line.startswith('frame-files ='))+'\n'
new=new.replace('datafind-method = AT_RUNTIME_FAKE_DATA','datafind-method = FROM_PREGENERATED_LCF_FILES\n'+'\n'.join(f'datafind-pregenerated-cache-file-{ifo.lower()} = {selected}/{ifo}.cache' for ifo in ['H1','L1','V1']))
# These generators do not call workflow.datafind. Declare their inputs using
# the same selected cache, so Pegasus stages them normally through CondorIO.
for ifo, files in followup_frames.items():
    sections = '&'.join(f'{name}-{ifo.lower()}' for name in
                        ['single_template', 'plot_singles_timefreq', 'plot_qscan'])
    new += '\n['+sections+']\nframe-files = '+' '.join(files)+'\n'
p.write_text(new);patch('analysis.patch',old,new,'examples/search/analysis.ini')
props=installed/'pycbc/workflow/pegasus_files/pegasus-properties.conf'
old=(source/'pycbc/workflow/pegasus_files/pegasus-properties.conf').read_text()
# Keep workflow metadata local and disable optional upstream telemetry.
old='\n'.join(line for line in old.splitlines() if not line.startswith(('pegasus.monitord.encoding','pegasus.catalog.workflow.amqp.url')))+'\n'
extra='\n# Clusterlink isolated acceptance test\npegasus.transfer.worker.package=true\npegasus.transfer.worker.package.strict=false\npegasus.catalog.master.url=sqlite:///'+str(work/'master.db')+'\n'
props.write_text(old+extra)
(evidence/'properties.txt').write_text(extra)
