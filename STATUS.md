# Clusterlink acceptance status

## Worker startup optimization (0.1.4)

Workers first let the bundled Apptainer runtime mount the SIF. A failed setup
retries with `--unsquash` only if the container-side wrapper has not started;
application failures are never replayed by this fallback. Disk reservations
still cover full extraction. New bundles use an uncompressed tar wrapper around
the already-compressed SIF and private runtime. Activation converts a verified
old gzip wrapper without rebuilding its unchanged SIF. Existing compressed
bundles remain readable. Remote cache object names retain their historical
`.tar.gz` suffix for protocol compatibility; extraction detects actual content.

`CLUSTERLINK_TIMING` records in job stderr mark bundle unpacking, container setup,
and payload execution. Native Condor event logs retain transfer timing. This
adds no user configuration or administrator requirements.

The isolated dev1 benchmark measured 0.99–1.01 s for direct mounting plus
NumPy/PyCBC imports versus 14.4–15.1 s with extraction. Outer archive unpacking
fell from 13.8 s to 5.2 s, with about 14% more delivery bytes. These small samples
ran under live host load with uncontrolled filesystem caching, not a cold-cache
or full-workflow benchmark. See [startup evidence](integration/probes/startup-014.json)
and the [reproducible probe](integration/probes/startup_benchmark.py).

Validation: all 62 tests pass and the 0.1.4 wheel builds. A native dev1 CondorIO
job completed with verified NumPy/PyCBC output, a 0.15 s container-start phase,
and no extraction fallback. A real-runtime test with an injected pre-payload
setup failure used extraction and ran its deliberately failing payload exactly
once, preserving exit 7. The dev3/dev4 probes were canceled while still queued
behind busy workers, so they are not successful execution evidence. All three
test caches drained to zero leases and remained within their budgets.

## Concurrent hook snapshot fix (0.1.3)

The exclusive nonblocking packaging lock introduced in 0.1.2 caused concurrent
read-only translation hooks to fail. Hooks also scanned the Conda environment
and repeatedly hashed the image. Activation now publishes `prepared-image.json`
atomically with the verified artifact path, digest, disk requirement, environment
selection, and file identity. Hooks read that snapshot without a packaging lock,
environment scan, or artifact hash. Changed/missing artifact metadata requires
reactivation; source environment changes take effect on the next activation.
The previous snapshot remains readable while activation prepares a replacement.
HTCondor's native failure throttling remains unchanged.

All 60 tests pass, including 64 concurrent preparations across four simulated
routes while an exclusive build lock is held, with hashing and fingerprinting
forbidden. Missing/modified artifacts and selection mismatches are rejected.
The 0.1.3 wheel builds. These are local regression tests, not a new full workflow
or thousands-job throughput benchmark. Existing projects must activate once
after upgrading to publish their snapshot; no fresh workflow plan is needed
solely for this fix.

## Queue limits (0.1.2)

New enrollments default to unlimited total and idle routed jobs, replacing 10/2.
Enrollment accepts explicit limits; `site limits` also accepts `unlimited`.
Existing limits are preserved, including enrollment updates. The native route
uses MaxIdleJobs=-1 and MaxJobs=2147483647 (its integer ceiling, because native
per-route MaxJobs does not support a negative unlimited sentinel). Remote
scheduler policies still apply. Large-scale throughput remains unbenchmarked.

All 57 regression tests pass and the 0.1.2 wheel builds. Tests cover prepared
artifact integrity without provisioning, installer failure logs, hook reuse-only
behavior, explicit enrollment limits, and unlimited/5000-job route generation.
Native idle-limit behavior is described in the [HTCondor Job Router manual](https://htcondor.readthedocs.io/en/main/grid-computing/job-router.html).

## Image preparation outside hooks (0.1.2)

Activation prepares the SIF and its private Apptainer runtime before starting
the manager. Job translation now requires that prepared image: missing, stale,
or damaged artifacts produce a short reactivation instruction instead of an
installer/build inside the hook. Busy image preparation is reported without
waiting on the packaging lock. Installer stdout/stderr go to a project log,
with its path reported on failure. The reported transform timeout has not been
independently reproduced; this removes the expensive build path that could
cause it. First remote cache upload still occurs during job preparation.

## Project setup fixes (0.1.1)

Removed the private manager’s artificial 1 GB memory and default one-CPU
advertisements. HTCondor detects host resources for local-universe helpers;
explicit local-worker slot choices survive configuration regeneration. A live
2 GB helper reproduced the old idle condition and completed after the fix.
Generated protocol helpers start Python directly and remove exported shell
functions, including malformed module initialization inherited from the shell.
A native submit requirement rejects routed shared-filesystem scratch paths
before remote staging; ordinary CondorIO and local-universe jobs remain allowed.

The reported integration project contained submit files referencing another
planning run’s scratch directory. Its retry must use a fresh CondorIO workflow
plan, including child workflows. No changes were made to that agent’s project.

[Setup regression evidence](integration/project-setup-regression.json) records
the local helper, early rejection, and successful dev1 SIF/CondorIO probe
(exit zero, validated output, zero cache leases). All 53 tests pass and the
0.1.1 wheel builds. The other agent’s full workflow retry remains outstanding.

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

Campaigns of 20–30k jobs have not been benchmarked. Per-job SSH cache checks and staging have measurable overhead; see the bounded
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
