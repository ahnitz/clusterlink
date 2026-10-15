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
