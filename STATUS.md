# Clusterlink acceptance status

## Completed fresh SIF acceptance

The fresh project `local/pycbc-acceptance` completed its full PyCBC mini search
across SU and OSG on 2026-10-16. It was initialized/enrolled through the normal
CLI, built its own environment image, and submitted once. All 15 DAGs succeeded
with **zero manual interventions**, no rescue restarts, and seven native DAGMan
retry events. The runtime and environment remained unchanged during execution.
The empty private manager was stopped after collecting evidence.

[Full acceptance evidence](integration/pycbc/sif-acceptance.json) records source,
image, environment, configuration and implementation identities, native attempt
outcomes, retry events, and validation results:

- 434 templates, 68 injections, six finite nonempty trigger datasets.
- 166 HTML files, 334 PNG assets, 4,483 local references checked. The upstream
  unconfigured Pegasus dashboard placeholder is reported separately.
- 565 grid attempts completed with exit zero (377 SU, 188 OSG). Other grid
  records include seven removals and one exit 255; grid removals/rerouting and
  DAGMan retry counts describe different events and should not be combined.
- One environment artifact throughout; no hook-output truncations.
- Both caches contain one 751,755,770-byte bundle and have zero active leases.

Retries recovered worker container incompatibility and scheduler/storage
failures. This establishes an unattended end-to-end result, not failure-free
infrastructure or equivalence to a reference scientific analysis.

## Single SIF model and workstation pools

SIF is now the only supported execution model. The project-selected Conda
environment builds its image automatically. Archive execution, archive pinning,
manual pack/cache commands, per-job environment overrides, and legacy activation
have been removed. Existing SIF projects reactivate and reuse their images;
legacy archive configurations require a fresh project initialization.

The small HTCondor pools at `dev1`, `dev3`, and `dev4` passed six probes before
simplification and six after: one targeted and one automatically routed job per
pool in each run. All returned correct NumPy/PyCBC results through CondorIO,
using the bundled SIF/runtime without host Apptainer installations. CPU limits
were preserved, one image was reused, and all cache leases were released.
No host configuration changes, holds, or manual recovery were required.
The empty test manager was stopped after validation. All 50 tests and the wheel
build pass. See [initial results](integration/dev-pools/initial-results.json) and
[SIF-only results](integration/dev-pools/sif-only-results.json).

## Remote storage correction

Enrollment accepts `--remote-dir /absolute/dedicated/project/path`; the default
is a unique directory under the remote home. The native helper now receives
`GAHP_TEMP`, `TMPDIR`, and an explicit `BLAHPD_CONFIG_LOCATION`, so its submission
and status files use that enrolled directory. Older SU BLAHP binaries ignored
the newer temporary-directory controls; a full login-node root filesystem
exposed the gap even though home storage had ample space.

This correction was integrated **after** the unchanged full workflow completed.
[Two isolated SU jobs](integration/pycbc/storage-location-regression.json) passed
with a custom enrolled path, and the native status cache was observed there.
A regression invokes the actual installed native status script. This redirects
Clusterlink's helpers; it does not relocate every internal file of a remote
scheduler or supply worker-local disk.

Earlier development failures and interventions remain documented in
[development completion evidence](integration/pycbc/sif-development-completion.json)
and Git history. One older pre-fix development run retained an orphaned cache
lease after a rejected hook translation; the fresh acceptance run did not.

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
- All 50 tests pass after integrating the storage fix, and the installable wheel
  builds successfully. Coverage includes native submission-option preservation,
  Pegasus Python inside the SIF, and native-helper temporary storage.

The earlier full PyCBC Conda-archive run completed, but required manual
interventions. Its detailed evidence is preserved in
[the pre-SIF acceptance report](integration/acceptance-before-sif.md) and
[chronological history](integration/acceptance-history.md).

## Remaining limits

Campaigns of 20–30k jobs have not been benchmarked. Per-job fingerprinting, bundle
hashing, SSH cache checks, and staging have measurable overhead; see the bounded
[scale validation plan](TESTING.md#scale-validation-still-required).

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
