# Clusterlink

Run Conda-based scientific jobs on your SSH-accessible clusters from one project
folder. Keep using ordinary HTCondor submissions or Pegasus workflows. Clusterlink
automatically builds a SIF container from your environment, prepares remote caches,
and manages private configuration.
SIF is the only execution model. The Conda environment recorded by `init` is
the source for that image; there is no archive-only mode or per-job environment
override. No administrator changes or manual environment variables are required.

**Development prototype.** A fresh full PyCBC SIF workflow completed across SU
and OSG without manual intervention: all 15 DAGs passed, with seven native retry
events. See
[STATUS.md](STATUS.md) for evidence and remaining limitations.

## Setup once per project

You need Linux, Bash, Conda, OpenSSH, and HTCondor with Job Router/GridManager on
your workstation. Local SIF building also needs `curl`, `rpm2cpio`, and `cpio`.
Remote workers must permit unprivileged user namespaces; Apptainer itself is
provided by Clusterlink, without administrator installation. Start with your project's Conda environment activated, then:

```bash
python -m pip install git+https://github.com/ahnitz/clusterlink.git
cd my-project
clusterlink init --env my-analysis-env
clusterlink enroll su --ssh su --cache-gb 20 --storage-gb 100
```

Replace the Conda environment name, SSH alias, and budgets with your own.
`--env` also accepts an explicit environment path. Names resolve through your
Conda installation and are recorded as absolute paths. Budgets are
in decimal GB. Use another `enroll` command for each additional cluster.
New enrollments have no Clusterlink total/idle job cap; remote scheduler policy
still applies. To bound a site, pass `--max-jobs 5000 --max-idle 500` to `enroll`.
Existing enrollments retain their limits. To remove both limits on one:

```bash
clusterlink site limits su --max-jobs unlimited --max-idle unlimited
```

These are queue limits, not CPU counts. Clusterlink does not infer cluster capacity
from the SSH login node.
Use `--remote-dir /path/to/dedicated-project-directory` during enrollment when
a cluster requires a different storage location. Choose a separate directory for
each project; cache, staging, helpers, logs, and submission temporary files belong
there. The default is a unique directory under your remote home.
Enrollment installs missing helpers in that directory and configures
the project automatically. SSH access must work without interactive prompts.

`init` records the environment and creates an ignored `.clusterlink/` directory.
Commands discover it from the project folder or any subdirectory. Each project
gets its own local queue, configuration, and unique remote directories—even when
two projects enroll the same SSH alias. They still share your account's cluster
quotas. Do not copy `.clusterlink/` into another project; initialize that project
separately. Project paths currently cannot contain spaces or shell metacharacters.

## Work in the project

```bash
clusterlink activate
clusterlink status
condor_submit job.sub
condor_q
```

`activate` opens a Bash project shell, activates the exact recorded Conda
environment, builds or reuses its SIF, selects its Condor configuration, and starts its project job manager
if needed. It does not modify your shell startup files. Use ordinary Condor
executable, resource-request, and input/output-transfer settings in `job.sub`.
Clusterlink wraps the executable and caches the image and private Apptainer runtime
automatically. The image includes userspace libraries such as glibc. Initial
activation downloads a base matching the workstation distribution and builds the
image; later activations reuse it until the environment changes. After installing
or changing software, leave the project shell and activate again before submitting.
Job hooks only reuse prepared images; they never download Apptainer or build SIFs.
Apptainer installer output is saved in `.clusterlink/install-apptainer.log`.

For Pegasus, select a vanilla Condor site with CondorIO. The PyCBC site adaptation
and completed example are documented in [the PyCBC guide](integration/pycbc/README.md).
Select that site for child workflows too, and generate a fresh workflow plan;
previously generated shared-filesystem submit files cannot be reused. Routed jobs
with `remote_initialdir` are rejected with an explanation.
Pegasus manages dependencies; HTCondor handles routing and remote job tracking.
Local-universe workflow helpers use HTCondor’s detected host resources; no manual
memory or slot edits are needed. The project manager does not replace or change
the existing system pool’s resource policies.

When finished with the shell:

```bash
clusterlink deactivate
```

This returns to the previous shell and environment. Submitted jobs keep running;
the project manager continues tracking them.

## Inspect and control

```bash
clusterlink status                 # Environment, manager, linked clusters, limits
clusterlink status --remote        # Also check live cache and storage usage
clusterlink site disable su        # Stop new routing there; preserve existing jobs
clusterlink site enable su
condor_rm JOB_ID                   # Cancel a job inside the activated project shell
```

Status works offline by default. `--remote` also delivers pending cache-lease
releases. `--json` provides structured output. A running master is not a complete
scheduler-health check, and environment presence is not a package-integrity check.
Logs live in `.clusterlink/log`. Use `clusterlink --help` for other controls.
`clusterlink pool stop` stops the project manager; it does not cancel remote jobs.

## Current limits

- Campaigns of 20–30k jobs and high submission rates have not been benchmarked.
  Per-job environment checks and staging still have measurable overhead.
- Remote HTCondor execution is tested. Slurm route generation is untested and
  cached delivery is currently Condor-only.
- Routing uses native Job Router round robin and queue limits. Automatic
  cross-site failover and capability discovery are not implemented.
- SIF isolates userspace libraries, not the kernel, CPU architecture, or GPU
  drivers. Workers must allow user namespaces. Source Conda environments must be
  intact; containers do not repair damaged package installations.
- Only environment bundles are cached. Other inputs use ordinary CondorIO.
  Cache budgets are enforced; total scheduler staging is not a hard disk quota.
- Outputs must have distinct basenames; directory transfers are unsupported.
- `ssh_to_job` resolves remote jobs, but interactive access depends on the remote
  pool allowing worker connections.

## Help for agents

Agents working from this checkout can use the
[Clusterlink project skill](.agents/skills/clusterlink-project/SKILL.md) to gather
project details, enroll clusters, and verify jobs. [AGENTS.md](AGENTS.md) points
agents to it; compatible skill loaders can select it automatically or invoke it
as `$clusterlink-project`.

[Validation evidence](STATUS.md) · [Test plan](TESTING.md) ·
[HTCondor Job Router](https://htcondor.readthedocs.io/en/main/grid-computing/job-router.html)
