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
