# Clusterlink acceptance status — 2026-10-15

The package works across both enrolled HTCondor sites. The complete PyCBC
acceptance workflow is **not finished**: 244/252 main nodes are complete, with
follow-up workflows and final HTML assembly still pending.

## Current recovery

The suggested `sugwg-login2` host was enrolled as `su2` through the normal
CLI with a 5 GB cache and 10 GB owned-storage budget. Its independent scheduler
successfully ran the installed PyCBC entry point and plotting jobs. No cluster
service or administrator configuration was changed.

The original `su` scheduler recovered; its old allocations have been reconciled
and cancellation completed. All three routes are enabled. OSG temporarily stopped accepting new SSH
connections, then recovered; the package's existing nonprompting login path worked
again and deferred cache releases drained successfully. Existing native jobs
were tracked to completion/removal; no remote identity was discarded.

The workflow resumed as root DAG 1167 from rescue checkpoint 004. All 305
injection follow-up nodes have now completed successfully, as have all nine
singles child workflows. Both corrected foreground generators passed and their
100-node and 103-node child workflows are running without failures. The main DAG
has 244/252 nodes complete. The foreground workflows were generated normally from
the repaired configuration: frame inputs are declared and staged through CondorIO,
and submit files request the corrected 1024 MB of working disk. Syracuse queue
limits are 20 total / 10 idle jobs per site, changed through `site limits`.

The injection tail was checkpointed only after confirming the canceled OSG
allocation 16043206 absent from the queue and JobStatus=3 in history. Its next
attempt explicitly selects su. This allows independent foreground work to proceed
without duplicating the old allocation. Earlier completed nodes remain preserved.

Cache cleanup now writes durable local release records and delivers them with
the next preparation/status/cache contact. An unavailable SSH endpoint therefore
does not delay completed-job reporting; cached objects remain pinned until release
is acknowledged. Cache hits update separate LRU metadata, keeping hard-linked
archives immutable and avoiding repeated cross-cache checksum reads.

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
- All 39 unit tests pass. The distributable wheel builds successfully.

Persistent head-node helpers use roughly 17–20 MiB RSS per host. During the
concurrent follow-up workload, summed RSS including temporary native submission
and status processes was about 75 MiB on su, 20 MiB on osg, and 16 MiB on su2.
This sums process RSS (including shared pages), and is not a measured peak.
Recent owned-storage snapshots were 3.12 GB on su, 1.88 GB on su2, and
2.36 GB on osg; cached environments account for 2.56 GB, 0.68 GB, and 2.34 GB
respectively. These are snapshots, not peak or quota guarantees.

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

Conda-managed ncurses aliases were renamed to `*_CaseConflict`. A running
Synology Drive daemon was identified locally, and a fresh package-inventory check
still reports three missing aliases. Excluding project `local/` from sync has
been requested so ordinary automatic packing can be retested after repair.
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

The su2 installed-command acceptance job (local 389, remote 49374612) returned
`PyCBC version: 0.0a1`, exit zero, and empty stderr. Three PyCBC plotting jobs
there also passed. All nine singles child DAGs completed. The main DAG reached
197 completed nodes; the two corrected foreground generators still need a
checkpoint retry. Their corrected log format passes Pegasus's exit-code checker.

## Busy-scheduler submission recovery

A su2 submission (source 863 / grid 869) hit BLAHP's 30-second silent-command
timeout. Its unique sandbox identity was absent from both the remote queue and
recent history before both local entries were released. It then acquired remote
ID 49377298 and ran. This was an explicit reconciled retry, not automatic failover.
Enrollment now sets `blah_child_poll_timeout=120`, below the private GridManager's
180-second deadline. Existing private remote configurations were updated for their
next helper start; in-flight helpers were not restarted. The setting's seconds
conversion was checked in [upstream BLAHP](https://github.com/htcondor/BLAH/blob/devel/src/mapped_exec.c).
