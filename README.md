# Clusterlink

Run Conda-based scientific jobs on your SSH-accessible clusters from one project
folder. Keep using ordinary HTCondor submissions or Pegasus workflows. Clusterlink
automatically builds a SIF container from your environment, prepares remote caches,
and manages private configuration.
No administrator changes or manual environment variables are required.

**Development prototype.** A full PyCBC SIF workflow has completed across SU and
OSG, with a documented configuration intervention. A fresh unattended run is
in progress. See
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
image; later activations reuse it until the environment changes.

For Pegasus, select a vanilla Condor site with CondorIO. The PyCBC site adaptation
and completed example are documented in [the PyCBC guide](integration/pycbc/README.md).
Pegasus manages dependencies; HTCondor handles routing and remote job tracking.

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

[Validation evidence](STATUS.md) · [Test plan](TESTING.md) ·
[HTCondor Job Router](https://htcondor.readthedocs.io/en/main/grid-computing/job-router.html)
