#!/usr/bin/env python
"""Validate probes after the activated project's queue has drained."""
from pathlib import Path
import json
import subprocess

root = Path.cwd()
project = next(p for p in [root, *root.parents] if (p / ".clusterlink/project.json").is_file())
attributes = 'ClusterId,JobUniverse,JobStatus,ExitCode,ClusterlinkDestination,GridJobId,Iwd'
queue = json.loads(subprocess.check_output(['condor_q', '-json'], text=True) or '[]')
assert not queue, 'Wait for the test queue to drain before validating'
history = json.loads(subprocess.check_output([
    'condor_history', '-json', '-attributes', attributes], text=True))
remote = [job for job in history if job['JobUniverse'] == 9
          and Path(job.get('Iwd', '/')).parent == root]
assert len(remote) == 6, remote
assert all(job['JobStatus'] == 4 and job.get('ExitCode') == 0 for job in remote), remote
results = []
for path in sorted(root.glob('*-dev*/result.json')):
    result = json.loads(path.read_text())
    assert result['token'] == path.parent.name
    assert result['sum'] == 15 and result['sum_squares'] == 55, result
    assert result['prefix'] == '/opt/clusterlink/env', result
    jobs = [job for job in remote if Path(job['Iwd']) == path.parent]
    assert len(jobs) == 1, jobs
    job = jobs[0]
    mode, label = path.parent.name.split('-', 1)
    if mode == 'targeted':
        assert job['ClusterlinkDestination'] == label, job
    results.append({'case': path.parent.name, 'result': result, 'remote_job': job})
assert len(results) == 6
assert {r['remote_job']['ClusterlinkDestination'] for r in results
        if r['case'].startswith('automatic-')} == {'dev1', 'dev3', 'dev4'}
report = {'project': json.loads((project / '.clusterlink/project.json').read_text()),
          'results': results, 'all_passed': True}
(root / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
print('Six successful SIF/CondorIO jobs; all three pools covered in both rounds.')
