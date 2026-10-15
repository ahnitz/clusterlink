# Clusterlink

Personal cluster federation over SSH, with automatic Conda environment packaging,
HTCondor job routing, and file staging.

**Development prototype:** small scientific jobs have completed through two
remote HTCondor submission hosts, including input/output transfer and execution
from cached environment bundles. A two-stage Pegasus CondorIO workflow also completed across both sites.
The isolated PyCBC acceptance test is in progress. See [STATUS.md](STATUS.md) for evidence and gaps.

## What it does

Clusterlink uses your existing SSH aliases to enroll remote submission hosts.
It runs a private, user-owned HTCondor pool with configuration and state in a
local directory. It does not edit `/etc/condor` or the remote scheduler settings.
HTCondor's Job Router selects a destination; its native BLAHP and file-transfer
helpers submit and monitor the remote job. The remote scheduler allocates CPUs.

The `submit` command packs a selected Conda environment, generates a launcher,
and declares input/output transfers. For remote HTCondor sites, immutable bundles
are cached on the submission host; that host's Condor transfers the bundle to the
compute node. No shared filesystem or container runtime is assumed for this path.

## Current prerequisites

- Linux workstation, Python 3.11+, Conda, OpenSSH, and a local HTCondor installation
  with Job Router and GridManager.
- Working SSH access to a remote submission host and permission to submit jobs.
  Existing aliases, keys, agents, and jump hosts are reused.
- Remote Python 3.8+ is currently required. Enrollment installs official HTCondor
  batch helpers in the user's project directory when missing; `--helpers portable`
  requests this explicitly. It writes only user-owned configuration. A remote
  Python bootstrap is still needed for hosts without Python.
- A compatible Linux Conda environment. Arbitrary system dependencies, GPU
  drivers, and architecture compatibility are not automatically resolved yet.

## Install

From your own activated Conda environment:

```bash
git clone git@github.com:ahnitz/clusterlink.git
cd clusterlink
python -m pip install .
export CLUSTERLINK_STATE="$PWD/local/clusterlink"
```

Alternatively, create a project-local development environment:

```bash
mkdir -p local/pkgs local/tmp
CONDA_PKGS_DIRS="$PWD/local/pkgs" TMPDIR="$PWD/local/tmp" \
  conda env create --prefix "$PWD/local/env" --file environment.yml
conda activate "$PWD/local/env"
python -m pip install .
export CLUSTERLINK_STATE="$PWD/local/clusterlink"
```

Use an absolute state path, including in later shells. Without this variable or
`--state`, the current default is `./local/clusterlink` relative to your directory.
Do not put state inside the Conda environment being bundled.

## Enroll and start

Replace `my-cluster` with an SSH alias that already works for you:

```bash
clusterlink enroll first --ssh my-cluster --cache-gb 5 --storage-gb 10
clusterlink pool configure
clusterlink pool start
clusterlink status
```

Budgets are decimal GB. Enrollment discovers the scheduler and uses a dedicated
`~/.clusterlink/first` directory on the remote host. `--remote-dir` can select
another dedicated directory beneath your remote home. `--max-idle` (default 2)
and `--max-jobs` (default 10) bound each route's queued jobs.

Add another site with another `enroll` command. Then regenerate and reload the
private configuration:

```bash
clusterlink enroll second --ssh another-cluster --cache-gb 5 --storage-gb 10
clusterlink pool configure
CONDOR_CONFIG="$CLUSTERLINK_STATE/condor.config" condor_reconfig
```

Enrollment automatically tries login-shell and command-shell transport. SSH
allows nonprompting keyboard-interactive authentication after public-key
acceptance, as required by some sites. Actual password/MFA prompts currently fail;
interactive authentication and connection reuse are future work. Use `enroll --update` to update a site after its jobs have stopped.

## Ordinary Condor and Pegasus jobs

Select the environment once in your submission shell:

```bash
eval "$(clusterlink activate --env "$CONDA_PREFIX")"
condor_submit job.sub
```

The generated private configuration marks vanilla jobs for routing. A native
Job Router hook bundles the environment, checks the selected site's cache, and
wraps the executable. Keep using normal `transfer_input_files` and
`transfer_output_files`. Pegasus should use a vanilla Condor site with
`data.configuration = condorio`; see `examples/pegasus_smoke.py`.

Clusterlink owns the cache and its leases. HTCondor owns job/data transport and
remote scheduler tracking; Pegasus owns workflow dependencies. Only environment
bundles are cached currently: arbitrary input data still follows ordinary Condor
transfer. On a cache hit the archive does not cross the workstation-to-cluster
link, but remote Condor still transfers it to each compute sandbox.

## Run the small example

From the repository, with the environment containing NumPy activated:

```bash
clusterlink submit --input examples/input.json --output result.json \
  examples/analyze.py input.json result.json
clusterlink pool queue
```

The command prints a local job ID and an absolute result directory. Once the job
finishes, verify its returned output:

```bash
python examples/verify.py /path/printed/by/submit/result.json
```

No manual archive creation or destination selection is required. `--env PREFIX`
selects an environment explicitly; otherwise the active `CONDA_PREFIX` is used.
An installed executable can replace the Python script, for example
`clusterlink submit --env /path/to/env my-installed-command arguments`.
Installed entry-point execution is implemented but not yet covered by a remote
acceptance test. Inputs and outputs must currently have simple, distinct filenames.
Declare every required data file; workstation paths are not automatically shared.

Useful options, placed before the executable:

- `--site first`: choose a particular enrolled site; the default is `auto`.
- `--no-cache`: transfer the environment with each job.
- `--artifact /path/environment.tar.gz`: use a prebuilt conda-pack archive.

Automatic placement currently uses HTCondor Job Router round robin and per-site
queue limits, not resource-capability discovery. Remote jobs remain visible as
source/routed jobs in the private local queue; remote CPUs do not become local slots.

## Help, logs, and stopping

```bash
clusterlink --help
clusterlink enroll --help
clusterlink submit --help
clusterlink pool queue
clusterlink status
clusterlink pool stop
```

Job directories contain the generated submit file, launcher, event log, stdout,
stderr, and returned files. Daemon logs are under `$CLUSTERLINK_STATE/log`.
For native Condor commands, select this pool explicitly:

```bash
CONDOR_CONFIG="$CLUSTERLINK_STATE/condor.config" condor_q
CONDOR_CONFIG="$CLUSTERLINK_STATE/condor.config" condor_rm JOB_ID
```

Stopping the pool does not remove remote jobs, caches, or enrollment. Cancellation
and restart behavior still need acceptance testing. Do not delete state while jobs
are outstanding. `ssh_to_job JOB_ID` resolves routed remote Condor IDs and forwards SSH; actual
interactive-session validation is still in progress.

## Limits and next milestones

- Real execution is tested with remote HTCondor only. Slurm enrollment/route
  generation exists but has not been validated; cached delivery is Condor-only.
- Cache uploads enforce configured budgets and checksums. Native submissions
  acquire per-job leases; cleanup releases them, allowing LRU eviction. Legacy
  explicit `cache`/`--artifact` operations retain permanent pins.
  `--storage-gb` is not a filesystem quota or a hard limit on scheduler staging.
- A native Job Router hook prepares the selected site's environment automatically,
  including ordinary `condor_submit` and Pegasus compute jobs. An unreachable
  selected site currently retries rather than automatically failing over.
- Resource requests in the smoke-test submission path are fixed at one CPU,
  1 GiB memory, 2 GiB disk, and a five-minute runtime request.
- Pegasus CondorIO completed all 13 nodes of the two-stage example, with compute
  jobs on different clusters. The isolated PyCBC search test remains in progress.

See [TESTING.md](TESTING.md) for the validation plan. Run local unit tests with:

```bash
python -m unittest discover -s tests -v
```

Development uses small, reviewable commits. Local environments, archives,
credentials, enrollment settings, and job outputs belong in ignored `local/`,
not in Git.

## Upstream components

- [HTCondor SSH batch submission](https://htcondor.readthedocs.io/en/latest/grid-computing/grid-universe.html#remote-batch-job-submission-via-ssh)
- [HTCondor Job Router](https://htcondor.readthedocs.io/en/main/grid-computing/job-router.html)
- [conda-pack](https://conda.github.io/conda-pack/)
- [Pegasus deployment documentation](https://pegasus.isi.edu/documentation/user-guide/deployment-scenarios.html)

Enrollment copies installed HTCondor BLAHP shell adapters into the user's remote
project directory, retaining their upstream copyright notices. These adapters
are not vendored in this repository.
