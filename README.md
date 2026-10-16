# Clusterlink

Run Conda-based scientific jobs on your SSH-accessible clusters from one project
folder. Keep using ordinary HTCondor submissions or Pegasus workflows. Clusterlink
handles environment packaging, remote cache preparation, and private configuration.
No administrator changes or manual environment variables are required.

**Development prototype.** The PyCBC acceptance workflow completed across three
remote HTCondor submission hosts, with documented manual retries. See
[STATUS.md](STATUS.md) for evidence and remaining limitations.

## Setup once per project

You need Linux, Bash, Conda, OpenSSH, and HTCondor with Job Router/GridManager on
your workstation. Start with your project's Conda environment activated, then:

```bash
python -m pip install git+https://github.com/ahnitz/clusterlink.git
cd my-project
clusterlink init --env /absolute/path/to/your/conda-env
clusterlink enroll su --ssh su --cache-gb 20 --storage-gb 100
```

Replace the environment path, SSH alias, and budgets with your own. Budgets are
in decimal GB. Use another `enroll` command for each additional cluster.
Enrollment installs missing helpers in your remote home directory and configures
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
environment, selects its Condor configuration, and starts its project job manager
if needed. It does not modify your shell startup files. Use ordinary Condor
executable, resource-request, and input/output-transfer settings in `job.sub`.
Clusterlink wraps the executable and caches the environment automatically.

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
- Conda bundles still require compatible worker operating systems and libraries.
  Automatic container creation is not implemented.
- Only environment bundles are cached. Other inputs use ordinary CondorIO.
  Cache budgets are enforced; total scheduler staging is not a hard disk quota.
- Outputs must have distinct basenames; directory transfers are unsupported.
- `ssh_to_job` resolves remote jobs, but interactive access depends on the remote
  pool allowing worker connections.

[Validation evidence](STATUS.md) · [Test plan](TESTING.md) ·
[HTCondor Job Router](https://htcondor.readthedocs.io/en/main/grid-computing/job-router.html)
