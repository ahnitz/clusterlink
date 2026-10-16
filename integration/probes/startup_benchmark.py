"""Compare startup modes using an existing test image; run on a worker host.

Usage: python startup_benchmark.py ENROLLED_ROOT CACHED_ARTIFACT
Run only in an authorized test enrollment with enough temporary storage for
one delivery archive plus the extracted runtime and image filesystem.
"""
import json, os, pathlib, resource, shutil, subprocess, sys, tempfile, time
root=pathlib.Path(sys.argv[1]).resolve()
archive=pathlib.Path(sys.argv[2]).resolve()
if root not in archive.parents or not archive.is_file():
    raise ValueError('Artifact must be an existing file in the test enrollment')
results=[]
def timed(label, cmd, **kwargs):
    start=time.monotonic(); before=resource.getrusage(resource.RUSAGE_CHILDREN)
    r=subprocess.run(cmd, text=True, capture_output=True, timeout=300, **kwargs)
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    row=dict(phase=label, seconds=time.monotonic()-start, cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime, returncode=r.returncode, stdout=r.stdout[-1000:], stderr=r.stderr[-2000:])
    results.append(row); print(json.dumps(row),flush=True)
    return r
with tempfile.TemporaryDirectory(prefix='startup-bench-',dir=root) as tmp:
    work=pathlib.Path(tmp); unpack=work/'unpack';unpack.mkdir()
    timed('gzip_unpack',['tar','-xf',str(archive),'-C',str(unpack)])
    exe=unpack/'apptainer-runtime/bin/apptainer'
    for config in (unpack/'apptainer-runtime').glob('*/etc/apptainer/apptainer.conf'):
        config.write_text(config.read_text().replace('mount devpts = yes','mount devpts = no'))
    env=dict(os.environ)
    for key in ['APPTAINER_TMPDIR','APPTAINER_CACHEDIR','APPTAINER_CONFIGDIR']:
        directory=work/key;directory.mkdir();env[key]=str(directory)
    for index in range(2):
        for mode in ['mount','unsquash']:
            timed(mode, [str(exe),'exec']+(['--unsquash'] if mode=='unsquash' else [])+['--userns','--cleanenv','--containall',str(unpack/'environment.sif'),'/opt/clusterlink/env/bin/python','-c','import numpy,pycbc; print(numpy.arange(5).sum())'],env=env)
    plain=work/'bundle.tar'
    timed('plain_pack',['tar','-cf',str(plain),'-C',str(unpack),'.'])
    print(json.dumps({'gzip_bytes':archive.stat().st_size,'plain_bytes':plain.stat().st_size}),flush=True)
    shutil.rmtree(unpack);unpack.mkdir()
    timed('plain_unpack',['tar','-xf',str(plain),'-C',str(unpack)])
