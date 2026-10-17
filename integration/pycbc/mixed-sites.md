# Handoff: mixed Pegasus sites (Clusterlink 0.1.8)

## Upgrade between workflow runs

In the environment owning the Clusterlink installation:

```bash
python -m pip install --upgrade git+https://github.com/ahnitz/clusterlink.git
```

Leave the old project shell with `clusterlink deactivate`, then run
`clusterlink activate` from the project directory. Activation regenerates and
reconfigures this project's manager. No re-enrollment, manual environment
variables, or generated Condor configuration edits are needed. Already-routed
jobs are not recalled; generate a fresh workflow plan for this test.

## PyCBC configuration

The proposed mixed configuration is supported by the routing and validation rules:

```ini
[pegasus_profile]
pycbc|primary_site = condorpool_shared

[pegasus_profile-inspiral]
pycbc|site = clusterlink
```

Keep the `clusterlink` Pegasus site vanilla with `data.configuration = condorio`.
It may explicitly set `My.ClusterlinkEligible = True`. Verify generated compute
submit ads have `pegasus_site = "clusterlink"`; this is the selector Clusterlink
uses. Other named Pegasus sites are never routed, even when they inherit
`ClusterlinkEligible = True`. Ordinary non-Pegasus submissions remain eligible
by default; explicit `ClusterlinkEligible = False` opts out.

The CondorIO/RemoteIwd rejection applies only to routed jobs. Shared/symlink
sites may retain their local scratch paths. They execute without Clusterlink's
remote SIF wrapper and must have their software and files available locally.
Apply the site profiles to child workflows as appropriate, and check their
actual generated ads rather than assuming profile inheritance.

## Local execution must have an explicit budget

The default project manager has no vanilla execution slots and does not
implicitly use the system pool. Version 0.1.8 rejects unrouted vanilla submissions
with an explanation when no local slots are configured, rather than leaving them
idle indefinitely. Local-universe helpers remain supported without these slots.

For a test with an agreed allocation of **two otherwise available local CPUs**:

```bash
clusterlink pool configure --local-slots 2 --local-helpers 2
```

Then leave and reactivate the project shell to apply the configuration. The
settings persist through subsequent activations and enrollments. `clusterlink
status` displays them. This is a private startd on the submission machine;
shared/symlink paths therefore stay on that machine. If the project already has
an explicit local-slot budget, it is preserved on upgrade.

Do not allocate the full host separately to every project. These slots are NOT
coordinated with other private startds or the system pool. Budget resources across
all uses. Automatic integration with the system execution pool is not implemented
in this release; native flocking also requires destination authorization and
correct filesystem visibility. Do not assume this upgrade enables it.

`--local-helpers` limits concurrent local-universe jobs in this project's schedd.
The default is min(8, host logical CPUs), independently of vanilla slots. This is
a job-count limit, not CPU/memory enforcement or a host-wide limit. Heavy compute
belongs in vanilla jobs with resource requests. Scheduler-universe DAGMan limits
are unchanged. Remove old manual configuration edits and use these persisted
options instead.

## Fresh validation for the PyCBC agent

1. Confirm `clusterlink status` shows the intended local slots and helper limit.
2. Generate a small mixed workflow in a fresh output directory. Inspect its ads:
   inspiral jobs should name `clusterlink`; shared jobs should name their shared
   site. Only the former should require CondorIO.
3. Submit it. Confirm only `clusterlink` compute jobs acquire a routed destination;
   shared jobs run on the local private startd and preserve scratch access.
4. Check local helpers remain within the configured count, and the DAG completes.
5. Before simultaneous-project testing, divide the available local allocation
   explicitly between projects. This release does not claim aggregate resource
   enforcement across projects.

Package tests evaluate the generated rules with native ClassAds across ordinary,
clusterlink, shared, symlink, and local sites, eligibility overrides, and vanilla,
local, and scheduler universes. A full fresh mixed PyCBC workflow is still the
agent's integration test; the previous remote-only acceptance run does not prove
mixed-site completion.
