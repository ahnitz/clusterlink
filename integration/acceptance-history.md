# Prototype status — 2026-10-15

## Verified

- A private local HTCondor pool configured entirely in project-owned files.
  Existing system Condor configuration and the original local pool are unchanged.
- Two remote HTCondor sites enrolled through the package CLI (`su` and `osg`).
  No remote shell startup or scheduler configuration was changed.
- Both sites completed NumPy jobs with native HTCondor input/output transfers.
  Returned results independently passed: count 5, sum 15, sum of squares 55,
  mean 3. Runtime paths confirmed Python and NumPy came from the shipped bundle.
- Jobs with automatic site selection completed on both sites while both were
  enrolled. Routing uses HTCondor's round-robin Job Router.
- Automatic Conda packaging completed a remote job without a supplied archive.
- Cached environment delivery completed jobs on both sites: archives are kept on
  the remote submission host and included by its native Condor transfer machinery.
- Five unit tests cover SSH command construction and nonprompting authentication,
  executable selection, environment-change detection, and generated route config.

## Local evidence (not committed)

| Source job | Remote site | Check | Result directory under `local/clusterlink/jobs/` |
| --- | --- | --- | --- |
| 2.0 | su | Initial transfer and relocated environment | `2f937d58ec6b40808456639e8cfce79a` |
| 4.0 | osg | Second-site transfer and execution | `043ca48310f2474fb7f113ad6efa1aea` |
| 6.0 | su | Automatic bundling and routing | `705073f712ad4b90898460fdc058c1df` |
| 8.0 | osg | Automatic routing with cached archive | `2a80a846c8544dcdae189c0b69edde25` |
| 10.0 | su | Automatic bundling, routing, cached archive | `9f02e5273c4d4773b7dccd15a9e954f8` |

The first bundles used Python 3.11.17; the latest used Python 3.11.11 after
replacing ncurses 6.6 with 6.5 in the project environment. The newer ncurses
installation repeatedly lacked three package-managed symlinks and failed strict
conda-pack checks. No ignore-missing-files override is used by automatic bundling.

The initial osg authentication failure was a client issue: `BatchMode=yes`
disabled the additional nonprompting authentication exchange required after the
server accepted the key. Normal SSH worked. The transport was corrected and
user-side changes were unnecessary.

## Remaining acceptance work

- Automatic packaging for ordinary Condor submissions and Pegasus workflows,
  including installed entry points and arbitrary executable arguments.
- Missing remote helper provisioning to meet the intended SSH-only requirement.
- Cache lifetime management, actual cache-hit transfer accounting, error recovery,
  native staging limits, and storage-pressure tests.
- Resource compatibility/eligibility, local execution, and Slurm validation.
- Cancellation, reconnection, duplicate-submission prevention, interactive access,
  and documented cleanup.
- Pegasus CondorIO dependent workflow, then the isolated PyCBC mini search test
  with only the explicitly permitted adaptations listed in TESTING.md.

This is a working two-site prototype, not the completed federation package.

## Incremental development after the initial checkpoint

- Added native Job Router preparation/cleanup hooks and `clusterlink activate`.
  Ordinary `condor_submit` job 13.0 completed on su and passed the scientific
  verifier; evidence is in `local/native-submit/`. Its cached input payload was
  approximately 1.5 KB instead of retransferring the 111 MB environment.
- Provisioned checksum-verified official HTCondor 25.0.14 helper bundles beneath
  both remote home directories. The su native-submission test used these helpers.
  No system helper installation is needed on this tested path.
- Added per-job cache leases, release, LRU eviction of unpinned entries, concurrent
  upload handling, and corruption/incomplete-upload tests. Legacy explicitly
  cached bundles remain pinned. Thirteen unit tests pass.
- Added interactive job-ID resolution and SSH forwarding; resolution is verified,
  but a complete interactive command/session still needs acceptance testing.
- Installed independent project-local Pegasus 5.1.3 and Java/Python tooling.
  The two-stage CondorIO workflow is submitted; final success is still pending.
- New setup uses pip for conda-pack rather than mixing a version-constrained pip
  install with Conda's package metadata. A copy-only payload environment with its
  own package cache is being used to isolate unexpected case-distinct terminfo
  file disappearance in the earlier environments. No integrity check is bypassed.

## Verified 2026-10-15: cross-cluster Pegasus

Private DAG 24 completed all 13 nodes with exit status 0. Analyze ran on
`CRUSH-OG-10-5-235-27` through su; summarize ran on `river-c016.ssl-hep.org`
through osg. The returned result passes `examples/verify.py`, and both Python
paths point into extracted `.clusterlink-env` directories. No remote shared
filesystem or container runtime was used. Evidence: ignored local directory
`local/pegasus-smoke-clean`. Fifteen focused unit tests pass.

Native routing now preserves disk/Requirements expressions, CPU and GPU counts;
multiline hook output has a regression test. Bundle uploads stream from disk.
The isolated PyCBC environment/install is in progress, not yet a passing test.

## Recovery and PyCBC progress

Removing source job 42 removed remote su job 59267643. Two private su helper
SSH sessions were deliberately terminated during source 46 / grid 47 / remote
59267730; GridManager restarted, recovered the same remote ID, and returned the
job's hostname output successfully. This verifies recovery after an established
submission; it does not prove exactly-once submission at every acknowledgement
failure boundary.

The requested `ahnitz/pycbc` branch `firinspiral3-multidet-asym` at
`6c67f3fd2ee6e347f44be081ba150f420219ebfa` is installed in a separate environment.
Its native reader passed short reads of H1/L1/V1 from the provided HDF5 caches.
The first 252-node main workflow was stopped because its full multi-year caches
caused unnecessary staging. Cache subsets now contain only the six files that
intersect the padded analysis interval. The corrected plan/run is in progress.

A native interactive `pwd` succeeded on one OSG worker with an inner terminal;
other workers have stalled after successful SSH authentication. Remote native
interactive support is therefore conditional, not yet a consistently passing
package acceptance test.

## Nested output transfer and bootstrap

The explicit portable-Python enrollment succeeded on su in a separate owned
bootstrap-test directory, including checksum verification and helper installation.
The main PyCBC DAG reached 34/252 nodes; several inspiral jobs exited zero but
were held during the second transfer hop because remote Condor flattened nested
output paths. The hook now supplies remote basename-to-relative-path remaps.
Completed outputs were recovered within their owned sandboxes without rerunning
those jobs. Independent two-site nested-output tests are submitted. Twenty unit
tests pass; full workflow acceptance is still pending.

Failure launchers preserve a nonzero application exit and stderr, creating empty
placeholders only for absent declared relative outputs. Existing partial files
are preserved. This lets workflow engines see the real failure instead of a
secondary missing-output transfer hold; placeholders are not successful results.

## Verified: nested outputs and container feasibility

Native prepared Conda jobs 209 (su) and 210 (osg) returned
`nested/result.txt` to the intended local directory. Older remote Condor cannot
create missing remap directories, so the final implementation lets remote Condor
flatten outputs, fetches their basenames through GridManager, and materializes
the original local remaps as literal ClassAd strings. This avoids depending on
remote directory-creation behavior. An intentional failure returned exit 7,
stderr, and its missing-output placeholder without a transfer hold.

An independently downloaded, project-local Apptainer 1.5.4 runtime and Ubuntu
22.04 SIF were transferred through CondorIO. On su host
`CRUSH-OG-10-5-137-186` (glibc 2.31), the unprivileged image ran glibc 2.35.
On osg host `epyc06` (glibc 2.34), FUSE was unavailable; `--unsquash --userns`
succeeded and ran glibc 2.35 without a privileged runtime or admin changes.
These are feasibility probes, not an automatic container-packaging backend.

The main PyCBC DAG reached 53/252 nodes and all six initial inspiral jobs exited
zero. Downstream analysis is running. A separate pool restart test is in progress.
Twenty-three unit tests pass. Configuration now supports hyphenated enrollment
names and pool startup waits until its scheduler accepts queries.

The independent bootstrap-test pool was stopped and restarted while source job 1
was running remotely. Grid job 2 recovered the same remote su ID 59269500 and
returned `CRUSH-OG-10-5-207-23` with exit zero. A second start verified immediate
scheduler readiness and an empty queue; the auxiliary pool is now stopped.

The normal and injection trigger merges contain nonempty, finite SNR datasets
for H1/L1/V1 (429370/392573/360240 and 79120/65946/68888 triggers respectively).
This is a sanity check, not a replacement for final workflow completion.
A stalled fitting allocation was canceled through source hold/release and the
same source job was selected for OSG. That exposed a nested-ClassAd formatting
bug in hook serialization (`NumHoldsByReason`); formatting newlines are now
collapsed while escaped string contents are preserved. Twenty-four tests pass.
Native interactive connection diagnostics on OSG stalled in its CCB connection
to the worker; that conditional remote limitation remains unresolved.

The main DAG has reached 87/252 nodes with no failed nodes. Follow-up workflow
generators and final HTML assembly are configured as local orchestration jobs,
while their scientific child jobs retain remote execution. A separate Pegasus
planning check confirms final report assembly uses the local universe.

Direct installed-entry-point submission passed on OSG: local source 272 / remote
16043017 ran `pycbc_inspiral --version` from the cached isolated environment,
returned its version on stdout, empty stderr, and exit zero. No external launch
script was supplied by the user.

During the plotting batch, the active remote helper processes used approximately
18 MiB RSS on su and 20 MiB on osg (a snapshot, not a peak guarantee). Owned
storage was 2.80 GB and 2.50 GB, including caches of 2.56 GB and 2.34 GB.

The main DAG reached 129/252 nodes. OSG allocation 16043019 reported running
without input-transfer bytes, CPU, or memory usage for roughly ten minutes; native
output access timed out. Source 277 was held, its routed job 287 was removed,
and then it was released with su selected. This is an explicit test recovery;
automatic cross-site failover is not implemented.

### Follow-up tail allocation retry

Source 775 / grid 779 / su2 remote 49376828 remained assigned for over
25 minutes with NumJobStarts=0 and zero reported CPU. Input bytes had reached
the worker. The source was held and targeted to osg. GridManager canceled the
old allocation; remote queue absence and history JobStatus=3 were confirmed
before source 775 was released. This is an explicit reconciled intervention,
not an automatic stalled-worker detector or a claim that no transfer occurred.
