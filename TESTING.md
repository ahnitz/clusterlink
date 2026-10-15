# First cluster experiment

## Information to obtain

- SSH alias or exact SSH command, including username and any jump host.
- Existing key or SSH-agent arrangement: refer to a local path or alias, never
  copy private key contents into notes or chat.
- Scheduler type, if known; an example working submission script is useful.
- Account/allocation, partition/queue, QOS, and required job constraints, if any.
- Writable work/scratch path accessible to jobs, or permission to discover one.
- Small-test budget and any login-node polling/submission restrictions.

Unknown scheduler and path details can be investigated through read-only SSH
commands once the user identifies the destination for testing.

Proposed initial budget: one CPU, at most 1 GiB memory, five-minute walltime,
tiny text files, one job at a time. Confirm fit with site minimums and allocation.

## Acceptance sequence

User-experience acceptance target: start with a user-created Conda environment,
enroll a remote submission host, then run jobs without manual environment bundling,
remote submit-file editing, cache management, or per-job site selection. Verify
CondorIO input/output handling, automatic compatible placement, environment-change
handling, and bounded cache reuse. Maintain the no-remote-admin requirement.
The steps below first validate the existing backend before implementing this UX.

1. Check SSH-key access, scheduler commands, OS/architecture, writable directories,
   and local availability of matching HTCondor batch helpers.
2. Inspect what the installed remote-cluster setup will change before invoking it;
   use a dedicated remote directory and preserve existing SSH configuration.
3. Submit a tiny job through local HTCondor, identify its remote scheduler ID,
   retrieve stdout/stderr, and verify a staged input produces the expected output.
4. Verify cancellation and failed-job reporting with bounded test jobs.
5. Exercise a dropped connection and reconcile remote IDs without duplicate work.
   Distinguish scheduler acceptance from receipt of the acknowledgement.
6. Run a two-step Pegasus workflow with an intermediate file and final retrieval.
7. Record remote process footprint, query frequency, setup time, and manual steps.
8. Add a second cluster and verify routing with correct input/output placement.
9. Turn the proven procedure into repeatable package setup, diagnostics, and cleanup.

Do not run expensive payloads or scan entire cluster queues. Use bounded status
queries, connection reuse, backoff, and site-appropriate submission limits.

## Interactive access acceptance checks

For a remote HTCondor destination, verify that the remote command works directly
first, then test `ssh_to_job LOCAL_CLUSTER.PROC` with direct and routed submissions.
Check remote ID resolution, the job working directory and identity, terminal input,
Ctrl-C, clean exit, and SSH disconnect without job cancellation. Verify useful
errors for pending/completed jobs, Slurm destinations, and disabled remote access.
Inspect dry-run output before the first connection. This feature is not implemented yet; both enrolled test destinations use Condor.

## Current status

Both enrolled HTCondor destinations have completed synthetic scientific jobs.
See STATUS.md for current evidence and outstanding acceptance checks.
# Final acceptance: isolated PyCBC workflow

Only attempt after synthetic jobs, automatic executable/environment handling,
transfers, caching, and simultaneous enrollment of both test sites work.
Create a separate project-local Conda environment and install PyCBC and the
workflow's dependencies there. Do not borrow existing PyCBC, Pegasus, or Python
packages from this workstation. Run PyCBC's maintained mini search workflow
through the normal user-facing enrollment/submission path, allowing jobs to
route to either cluster. Record versions, commands, execution sites, transfer
results, and the workflow's scientific validation results. Submission alone is
not a passing test. Discover the maintained upstream test before selecting it.

User-authorized adaptations for this hard test: add a Pegasus site definition
to PyCBC, modify the test configuration, and replace hardcoded frame-data lookup
with cache files in `/home/gwdata`. Keep all other changes minimal, retain an
exact patch, and do not modify the shared frame data. This data exception does
not permit reuse of workstation software outside the isolated test environment.
