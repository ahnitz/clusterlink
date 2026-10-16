# Clusterlink acceptance status — 2026-10-15

The package works across both enrolled HTCondor sites. The complete PyCBC
acceptance workflow is **not finished**: 141/252 main nodes are complete, with
follow-up workflows and final HTML assembly still pending.

## Current recovery

The `su` scheduler became unreachable during the test. SSH still works, but
its advertised `10.5.0.107:9618` endpoint has no listening socket. Native
GridManager reports the resource down. Two old remote allocations remain tracked for cancellation when that scheduler returns:

| Local source | Routed job | Remote su job | Purpose |
| --- | --- | --- | --- |
| 277 | 380 | 59270318 | Exclude-zero-lag analysis dependency |
| 315 | 336 | 59270215 | IFAR report fragment |

The suggested `sugwg-login2` host has a healthy, separate scheduler and shared
home storage. It was enrolled as `su2` through the normal CLI with a 5 GB cache
and 10 GB owned-storage budget. The original `su` route is disabled for new jobs.
PyCBC resumed from rescue checkpoint 002 with 141 completed main nodes preserved;
new jobs route to su2 or OSG. The old routed jobs are marked for removal and retain
their remote IDs. No cluster service or administrator configuration was changed.

## Verified behavior

- Private user-owned local Condor configuration; no changes to `/etc/condor`.
- Enrollment and execution through both `su` and `osg` using existing SSH aliases.
- Automatic Conda packaging, executable relocation, cache reuse, and CondorIO.
- Ordinary `condor_submit`, convenience submission, installed `pycbc_inspiral`
  entry-point execution, and nested output file return.
- A 13-node two-stage Pegasus workflow completed across both sites, and its
  numerical output passed independent checks.
- Cancellation, helper SSH connection loss, and a full private-pool restart with
  a remote job in flight preserved remote identity and returned correct output.
- Missing remote Python and native helpers can be provisioned in user-owned
  directories; the portable-Python enrollment path completed a remote job.
- Failed applications returned nonzero status and stderr without a missing-output
  transfer hold. Cache budget/lease/eviction/corruption behavior has unit coverage.
- All 32 unit tests pass. The distributable wheel builds successfully.

The head-node helper RSS snapshot was about 18 MiB on su and 20 MiB on osg.
Owned storage was 2.80 GB and 2.50 GB, with cached environments accounting for
2.56 GB and 2.34 GB respectively. These are snapshots, not peak or quota guarantees.

## Scientific acceptance evidence

The isolated PyCBC install uses the requested `firinspiral3-multidet-asym`
branch at `6c67f3fd2ee6e347f44be081ba150f420219ebfa`, with real frame-cache
inputs from `/home/ahnitz/gwdata`. All six initial inspiral jobs passed.
The merged outputs contain 434 templates, 68 injections, and nonempty finite
trigger SNRs for H1/L1/V1 in both branches. Report plotting jobs have returned
nonempty assets. This does not replace full root-DAG completion.

See [PyCBC setup and validation](integration/pycbc/README.md) for patches and validation commands.
Workflow generators and final HTML assembly use the isolated local environment;
their scientific child jobs retain remote execution.

An external process renamed Conda-managed ncurses files to `*_CaseConflict`.
The remaining test explicitly selects a previously validated immutable snapshot;
automatic packaging does not bypass integrity checks or silently reuse old archives.
Two glibc-incompatible dependency builds were replaced with compatible builds
of the same versions before that snapshot was created.

## Limits and interventions

- Native Job Router provides round-robin selection and queue limits. Automatic
  capability discovery, cross-site failover, and unified local/remote slot matching
  are not implemented.
- Two allocations on the same OSG worker stalled before transferring inputs.
  They were explicitly canceled and retried; excluding that worker let the second
  retry succeed. A separate earlier fitting allocation was also explicitly retried.
- Remote HTCondor is tested. Slurm route generation exists, but no Slurm cluster
  was supplied, and cached delivery remains Condor-only.
- Interactive forwarding resolves job IDs. A command succeeded in one test, but
  other native worker connections stalled in CCB negotiation; access is conditional.
- An independently transferred private Apptainer runtime ran Ubuntu SIFs with
  bundled glibc on both clusters. OSG needed `--unsquash --userns`. Automatic
  Conda-to-SIF packaging is not implemented; the default uses conda-pack.
- Cache uploads enforce configured budgets. Native scheduler staging is not a
  hard filesystem quota. Directory output transfer and duplicate output basenames
  are unsupported by the current SSH grid path.

Detailed chronological evidence is in
[acceptance history](integration/acceptance-history.md). Local raw logs and outputs
are preserved under ignored `local/`; environments and credentials are not committed.

## Alternate-host recovery updates

The resumed workflow reached 161 completed main nodes. Two local follow-up
generators produced valid child DAX files but their adapted wrappers omitted
Pegasus's success footer; those wrappers now emit it only after successful
execution and the two nodes await retry. Fresh planning with the committed local
site profiles uses the normal Pegasus wrapper.

The first su2 upload exposed a fixed-duration timeout and slow home-directory
writeback. Uploads now use inactivity timeouts. Automatic cache preparation also
looks for identical immutable archives in visible enrolled roots under the same
remote home. It verifies checksums, enforces destination budgets, and uses hard
links when supported; separate filesystems fall back to upload. The su and su2
archive paths were verified to share inode 61148753, size 675206181 bytes.
