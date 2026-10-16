# Clusterlink acceptance status

## Current acceptance work

A fresh project-local SIF PyCBC acceptance run was submitted once as root job 1
on 2026-10-15 at 23:56 local time and is running under
`local/pycbc-clean-run`. It has an independently cloned Conda environment,
new project identity, fresh remote enrollment/cache roots, and no previous
workflow outputs or pinned environment archive. Its 247-node main DAG has
returned initial jobs from both sites. Completion is not yet claimed.

The test launcher needed a Bash invocation fix before submission; the unused
preflight plan is retained separately. No jobs were submitted from that plan.

The acceptance criterion is one submission reaching root-DAG success, all
follow-up workflows completing, and scientific-output validation passing,
without operator releases, resubmissions, or configuration edits during the run.
Native Pegasus/DAGMan retries are allowed and will be reported.

## Verified SIF and project behavior

- `init --env NAME_OR_PATH` records one environment per project; activation
  enters that environment and starts its private manager without manual exports.
- Separate projects have independent scheduler identities, ports, queues and
  remote directories. One isolation job completed; another was canceled after
  stalling on a worker. Both empty test managers were stopped.
- Automatic Conda-to-SIF builds bundle a private Apptainer runtime and a base
  matching the local distribution. The image includes glibc.
- Real remote PyCBC FFT/matched-filter probes passed on both su and osg with
  glibc 2.42 and a glibc 2.38+ symbol, using the image's Python environment.
- An installed `pycbc_inspiral --version` entry point completed on su.
- The 13-node Pegasus SIF smoke workflow completed after fixing worker Python
  discovery. Its output has sum 15, sum of squares 55, and mean 3.
- A standalone OSG inspiral attempt failed before execution because its worker
  disallowed user namespaces. Its empty output is **not** a successful result.
  Both pools advertise `HasUserNamespaces`; the fresh test site uses the native
  requirement `TARGET.HasUserNamespaces =?= True`.
- All 49 unit tests passed before the fresh run; regression coverage includes
  native submission-option preservation and Pegasus Python inside the SIF.

The earlier full PyCBC Conda-archive run completed, but required manual
interventions. Its detailed evidence is preserved in
[the pre-SIF acceptance report](integration/acceptance-before-sif.md) and
[chronological history](integration/acceptance-history.md).

## Remaining limits

Remote HTCondor is tested. Slurm enrollment and routing exist, but no Slurm
account has been supplied; cached delivery is Condor-only. Native Slurm extra
submission arguments are preserved for HTCondor's backend to interpret.
Clusterlink does not implement retry or automatic memory-escalation policy.

SIF execution requires compatible CPUs/kernels and unprivileged user namespaces.
A container-support advertisement alone does not guarantee unprivileged runtime
support. No remote administrator configuration is changed. Worker requirements
are ordinary Condor/Pegasus configuration, not a custom Clusterlink scheduler.

Only environment bundles are cached. Cache limits are enforced; native scheduler
staging is not a hard disk quota. Outputs require distinct basenames; directory
output transfers are unsupported. Native Job Router handles round robin and
queue limits; automatic capability discovery and cross-site failover are absent.
Interactive job access remains dependent on remote worker connectivity.

The old source environment suffered external `CaseConflict` renames. The fresh
run uses a dedicated intact clone; no global sync configuration was changed.
Local environments and raw logs are ignored by Git. No credentials are committed.
