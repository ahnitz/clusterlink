# Clusterlink acceptance status

## Current acceptance work

The first fresh SIF attempt in `local/pycbc-clean-run` was submitted once as
root job 1. It reached 29 completed main nodes before the injection-SNR merge
failed during Apptainer extraction on OSG worker `nal-005-docker`: a nested
container could not mount a separate devpts instance. User namespaces were
advertised, but that alone did not establish support for this extra mount.
The failed run was canceled and its logs retained; it is not an acceptance pass.

The launcher now disables devpts in its extracted private runtime configuration,
covering both the internal extractor and payload. This changes no host settings.
General OSG and affected-worker regression probes passed. The targeted job
(local 73, remote 16043293) returned valid PyCBC numerical results with exit zero
on `nal-005-docker`. A second fresh project, `local/pycbc-clean-run2`, was submitted once as root job 1 at 00:20 local time on 2026-10-16,
with two native DAGMan retries configured before submission. That development run was then stopped after H1 and L1 full-data inspiral jobs
passed, because a wrapper review found that `--cleanenv` discarded native
scheduler CPU-thread limits. The launcher now preserves those limits and GPU
visibility masks through Apptainer, retaining explicit Apptainer overrides.
Allocation/override probes passed on both su and osg: two requested CPUs
produced OpenMP/OpenBLAS limits of two inside the SIF, while an explicit MKL
override remained one. `local/pycbc-final-run` was submitted once as root job 1 at 00:52 local time
on 2026-10-16. Its native policy allows two DAGMan retries and caps each remote
job at one hour including startup. The predeclared worker requirement excludes
the one stalled Syracuse worker. At 01:25 a remote coincidence job was held, exposing the inherited Pegasus
12-hour held-job timeout. The private manager then received a native
120-second held-job removal policy. Job Router requeued the source onto su;
this is native rerouting, distinct from the earlier DAGMan payload retry. This run is now a
development run with one recorded intervention, not unattended acceptance.
The preparation helper now installs that policy before planning future runs.
A fresh project, `local/pycbc-unattended` (ID
`2f6b6ab1e0e94ec9ab06ed1ff00503c1`), was submitted once at 01:34:58 local time
on 2026-10-16 with the two-minute held-job timeout installed before image
build and planning. It has no manual job interventions.
No successful unattended full run is claimed yet.

The test launcher also needed a Bash invocation fix before the first submission;
the unused preflight plan is retained separately and submitted no jobs.

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
