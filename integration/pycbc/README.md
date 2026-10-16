# PyCBC mini-search acceptance

This uses `ahnitz/pycbc` branch `firinspiral3-multidet-asym`, commit
`6c67f3fd2ee6e347f44be081ba150f420219ebfa`. The upstream bank, ranking-statistic,
search, follow-up, and report generators are retained. Scientific software runs
from our dedicated Conda installation; Clusterlink builds its SIF automatically.

## Fresh project procedure

Install PyCBC and its dependencies in a dedicated Conda environment first. Keep
an isolated checkout of that source and installations of Pegasus and Java for the
test. The example below assumes those installations already exist. Run
preparation **before activation**, because it adapts the installed PyCBC site
catalog and properties that go into the image.

From a fresh project folder:

```bash
python /path/to/clusterlink/integration/pycbc/prepare.py \
  --source /path/to/pycbc-source --env /path/to/project-conda-env \
  --work . --cache-root /home/ahnitz/gwdata --evidence-dir evidence \
  --requirements 'TARGET.HasUserNamespaces =?= True'
clusterlink init --env /path/to/project-conda-env
clusterlink enroll su --ssh su --cache-gb 3 --storage-gb 12 --max-jobs 20 --max-idle 10
clusterlink enroll osg --ssh osg --cache-gb 3 --storage-gb 8 --max-jobs 8 --max-idle 4
clusterlink activate
python /path/to/clusterlink/integration/pycbc/run.py \
  --source /path/to/pycbc-source --pegasus /path/to/pegasus --java /path/to/java
condor_q
```

The helper sets the test's Pegasus/Java paths internally, generates fresh bank
and statistic files, plans the workflow, and submits it once. It refuses an
existing `output` directory. Each stage has its own log and the commands are
recorded in `run-commands.json`. There are no manual environment-variable exports.

The user-namespace requirement is ordinary native Condor matching for our two
test pools, which advertise that capability. It excludes workers where that
attribute is false or absent. A different cluster may need a different native
requirement or a capability check; this is not automatic capability discovery.

After the root DAG finishes, run in the same activated project:

```bash
python /path/to/clusterlink/integration/pycbc/validate.py output --report validation.json
```

The validator requires root-DAG success and checks positive finite template
masses, nonempty finite trigger SNRs for H1/L1/V1 in both search branches, and
finite injection optimal SNRs. It checks scientific integrity, not equivalence
to a reference scientific analysis.

## Configuration adaptations

- One vanilla Condor site named `clusterlink`, with CondorIO and the optional
  native worker requirement. No Clusterlink executable paths in the workflow.
- Execution profiles select this site, remove the site's original accounting
  group, and request 1 GiB of working disk. Clusterlink adds environment and
  input-file storage to the disk request.
- Workflow generators and final HTML assembly use local-universe jobs in the
  project's environment; their scientific child jobs still use the remote site.
- Main workflow data discovery uses `FROM_PREGENERATED_LCF_FILES` and selected
  entries from `/home/ahnitz/gwdata/{H1,L1,V1}.cache`. Data is read-only.
- Follow-up generators do not call the main datafind machinery, so their frame
  inputs are declared from the same cache records and staged through CondorIO.
- Pegasus worker-package transfer and a local SQLite metadata database are
  configured, with optional upstream telemetry disabled.

Generated patches are saved in the run's evidence directory. Preparation does
not modify the source checkout. The checked-in patches record the earlier run;
paths in fresh patches naturally refer to the new project.

## Evidence

The earlier Conda-archive run completed with manual recovery. That history is
preserved in [the earlier report](../acceptance-before-sif.md). It is not the
fresh unattended SIF acceptance result. [STATUS.md](../../STATUS.md) tracks the
current run and remaining limitations.
