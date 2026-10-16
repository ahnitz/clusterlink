---
name: clusterlink-project
description: Set up or troubleshoot a user's scientific project with Clusterlink, enroll SSH-accessible clusters, and verify SIF execution and CondorIO before running their workload. Use for Clusterlink onboarding and project operation, including Pegasus or PyCBC workflows; not for unrelated cluster administration.
---

# Set up a Clusterlink project

Deliver a working project with a small verified remote job and a clear way for
the user to continue. Preserve their scientific workflow and use the public CLI.
Read the repository [README](../../../README.md) for current commands and
[STATUS](../../../STATUS.md) for tested capabilities. Resolve these references
relative to this skill, not the user's project directory. If using an installed
release, check its `clusterlink --help` before applying repository examples.

## Understand the project without an interrogation

Start from the conversation and inspect the named project read-only. Check for
existing `.clusterlink/project.json`, environment selection, workflow files, and
submission examples. Do not initialize over existing state or copy another
project's `.clusterlink` directory. Use `clusterlink status --json` in an existing
project to see its selection and enrollment.

Ask only for information still needed. A useful first question is:

> Which project folder and Conda environment should we use, and which SSH aliases
> can it submit through? For each cluster, what cache/storage budget and optional
> remote directory should we use? Share a small example command or workflow and
> its inputs/expected outputs; I can inspect anything else already in the project.

Adapt this question rather than repeating it verbatim. If the user already gave
an alias, environment, budgets, or testing authorization, carry those forward.
If no environment exists, ask for the project's dependencies or environment
recipe and create one inside the chosen project. Do not borrow the development
repository's scientific environment or another user's software installation.

Before submitting, establish the workload's CPU, memory, working disk, runtime,
input/output paths, expected result, and intended concurrency. Ask about known
allocation/account, partition, or worker requirements when relevant. Unknown
scheduler details and available commands can usually be discovered over the
provided SSH alias; do not make the user find them manually.

Clarify storage budgets or workload scope when missing rather than inventing a
large allowance. Continue local inspection while waiting. Approval for a small
probe is not approval for a large campaign. Existing explicit authorization is
sufficient; do not add repeated confirmation gates for routine setup within it.

## Keep one execution model

- One project folder records one Conda environment. `init --env` accepts a bare
  Conda name or a path. Activation enters that exact environment and selects the
  project's private HTCondor pool.
- **SIF only:** Clusterlink builds the image and supplies its private Apptainer
  runtime. Do not revive Conda-archive execution, archive pinning, per-job
  environment overrides, or manual pack/cache commands. Conda packing inside
  the image builder is an implementation detail, not an alternative runtime.
- No remote administrator changes. Enrollment installs user-owned helpers under
  the chosen remote directory. Do not edit system Condor, SSH, container, or shell
  startup configuration to make a test pass.
- Preserve the user's SSH aliases, agent, and jump-host setup. Never ask for
  private-key contents. A user who can `ssh ALIAS` without prompts may use
  zero-prompt keyboard-interactive authentication; failure with `BatchMode=yes`
  does not establish that their access requires a password. Diagnose with the
  package's transport before asking the user to change authentication.
- SSH submission access does not guarantee worker compatibility. SIF bundles
  userspace libraries, not the host kernel, CPU architecture, or GPU drivers.
  Validate actual worker execution; a user-namespace advertisement alone is
  insufficient evidence.

## Set up through the supported commands

Use the [README](../../../README.md) sequence: install into the user's selected
Conda environment if needed, enter the project, initialize with its environment,
enroll each provided alias with explicit budgets, then activate and inspect
status. Replace examples with the user's values; never assume `su`, `osg`, or
`dev1`–`dev4` are available or authorized on another machine.

Use `--remote-dir` only when needed for the user's storage policy; give each
project a dedicated directory. Otherwise enrollment chooses a unique directory
under the remote home. Budgets use decimal GB. Cache limits govern environment
bundles; the storage setting is not a hard quota on all scheduler staging.
Clusterlink's helper temporary files belong in enrolled storage, not an assumed
writable system `/tmp`. Worker scratch is a separate resource requirement.

`clusterlink activate` opens an interactive Bash shell. Keep subsequent
`condor_submit`, `condor_q`, and workflow commands inside that shell using a
persistent terminal session. Do not assume activation in one tool process
changes another process's environment. Do not tell the user to export environment
variables, edit global Condor configuration, or source a hand-written setup file.

For an existing SIF project, reuse its enrollment and activate normally. A legacy
archive configuration is unsupported: explain the error and initialize a fresh
project rather than silently changing an active queue's execution model.

## Verify before expanding the run

Use a tiny representative job within the agreed budget, with normal vanilla
Condor submission and CondorIO. Include an input file, invoke a dependency from
the user's environment, produce a deterministic regular output file, and record
the worker hostname and container Python/environment. Set `request_disk` for payload working data; Clusterlink adds the bundle/input
allowance, including image extraction space. Check that the resulting request
fits the worker.

For multiple sites, first establish that each can execute a job (an explicit
`+ClusterlinkSite = "SITE"` can target a diagnostic), then exercise ordinary
submissions without that attribute to check automatic routing. Test a second
job against the same image to verify cache reuse. Read local/native job records
to establish destination and exit status; submission acceptance or an empty queue
alone is not success. Validate the returned data, not just stdout.

Check `clusterlink status --remote` after the jobs drain: it also flushes pending
cache-lease releases. Record remaining leases and storage usage. If stopping a
test pool, first verify its queue is empty; `pool stop` does not cancel remote
jobs. `deactivate` only exits the project shell; jobs continue to be tracked.

If a job fails or is held, inspect its reason and logs before retrying. Distinguish
payload errors, container/worker incompatibility, staging/disk problems, and
scheduler/SSH failures. Use bounded native HTCondor/Pegasus policies agreed before
a run; do not repeatedly release holds, silently relax requirements, or build a
Clusterlink retry scheduler. Stop escalating a probe when the same failure
recurs without a relevant change. Report the blocker and required next step.
Record operator interventions separately from native retries; do not describe a
manually repaired workflow as unattended acceptance.

## Workflow-specific guidance and handoff

For Pegasus, use a vanilla Condor site with CondorIO; preserve its dependency
management. HTCondor owns routing, native scheduler submission, queue limits,
and job tracking. Clusterlink owns project configuration, executable wrapping,
SIF delivery, and environment-cache leases. Native requirements and site-specific
submission settings stay in Condor/Pegasus configuration.

For PyCBC, read the [integration guide](../../../integration/pycbc/README.md)
only when needed. Its source branch, frame-cache paths, site requirements, and
test budgets are recorded examples, not defaults for new users. Prepare any
installed workflow/site adaptations before image build; retain minimal patches
and validate scientific outputs as well as DAG/report completion.

For scaling requests, read [TESTING](../../../TESTING.md#scale-validation-still-required).
Do not claim 20–30k-job throughput is validated or launch a large load test based
on the small probes. Slurm routing remains unvalidated in the recorded evidence;
check current status and treat a new Slurm account as a bounded backend test.

Finish with the project/environment, enrolled sites and budgets, exact successful
commands or saved submit files, validated results, and any remaining limitations.
Give the user the short continuation: enter their project, `clusterlink activate`,
then submit their job/workflow normally. Keep raw logs and large artifacts out of
Git; do not publish data, credentials, or project changes without authorization.
