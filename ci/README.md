# Automated validation

GitHub Actions runs `.github/workflows/tests.yml` on pushes, pull requests,
manual dispatch, and weekly. No cluster credentials or repository secrets are
needed. Workflow token permissions are read-only. All jobs have deadlines and
preserve diagnostic logs on failure; private SSH keys and container images are
excluded from uploaded artifacts.

## Required native checks

Two Ubuntu jobs cover Python 3.11/3.12 and HTCondor 25.0/25.x. Each builds the
wheel, installs it in a fresh venv, and runs tests outside the checkout so imports
come from the installed package. Missing native tests are failures, not silent
skips. Coverage reports expose untested paths without a misleading arbitrary
coverage percentage gate.

`native.py` starts independent two-slot and one-slot private pools and a no-worker access
point. It verifies native submit rejection, mixed Pegasus-site admission,
CondorIO contents, a nonzero exit status, private queue isolation, manager restart
with queued work, removal, serialized local helpers, and a real DAGMan chain
transferring an intermediate output. It does not claim that DAGMan alone tests
the Pegasus planner. The DAG pool leaves capacity for DAGMan's own resource
reservation on feature-channel releases as well as its child job.

Run locally using the installed package's Python:

```bash
python ci/native.py /absolute/path/to/new-test-directory
```

It creates only its own pools, runs tiny jobs, and stops those managers in
`finally`. Do not reuse an existing output directory. Logs remain for inspection.

## Required SSH/SIF checks

The SSH job provisions two disposable Unix accounts on the runner, each with its
own one-slot Condor pool and home directory (mode 0700). The source project also
has mode 0700. A temporary SSH key authorizes only these ephemeral accounts.
`ssh.py` uses normal `init`, `enroll`, and `activate` commands with a small real
Conda environment. Activation builds the real SIF and bundles private Apptainer.
Jobs execute through SSH/BLAHP/GridManager and native Condor transfer.

Checks include both explicit destinations and automatic routing, site-specific
remote requirements/environment, inaccessible submit-only files, returned input
checksums, fixed image Python prefix, nonzero payload exit, cancellation, remote
active-job draining (terminal accounting ads may remain), bounded cache usage, one cached image per destination, and lease
cleanup. No mocks or existing cluster installations stand in for this path.

`install-condor.sh` and `ssh-setup.sh` are **disposable-machine provisioning only**:
they install packages, stop the runner's default Condor service, create accounts,
and allow unprivileged user namespaces on Ubuntu. They refuse to run unless
`GITHUB_ACTIONS=true` or `CLUSTERLINK_DISPOSABLE_CI=true`. These are test-infrastructure
operations, not requirements imposed on enrolled user clusters. Do not run these
scripts on a workstation/shared server.

## Scope and remaining work

These tests do not replace real-site acceptance. Full PyCBC/Pegasus planning,
Slurm execution, kernel/site policy differences, network partitions at scheduler
acceptance, and large-scale throughput still require additional tests. Existing
cache/transport regressions cover several interrupted-upload and lock-contention
cases; the weekly run currently repeats the same bounded checks, not an unbounded
stress campaign. Dependencies in the 25.0/25.x channels advance to detect upstream
compatibility changes; logs print the installed native version.
