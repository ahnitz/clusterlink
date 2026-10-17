# Handoff: native per-site job settings (Clusterlink 0.1.7)

Upgrade Clusterlink in the environment that owns your project installation:

```bash
python -m pip install --upgrade git+https://github.com/ahnitz/clusterlink.git
```

Leave any old project shell and run `clusterlink activate` from the project
folder. Activation regenerates/reconfigures the private routes and prepares the
selected environment image when needed. No re-enrollment or manual Condor
configuration edits are needed. Do not restart another project's manager.
Already-routed jobs retain their existing settings; test with fresh submissions.
For reproducible campaigns, upgrade between runs rather than changing an active
installation. Regenerate Pegasus submit files after changing the workflow config.

## Configure PyCBC normally

Add entries to the appropriate existing PyCBC profile section. For example,
apply this only to inspiral jobs:

```ini
[pegasus_profile-inspiral]
condor|+REMOTE_Requirements_su = TARGET.RecentDaemonCoreDutyCycle < 0.05
condor|+REMOTE_Rank_su = TARGET.KFlops
condor|+REMOTE_Environment_su = "OMP_NUM_THREADS=1 MKL_NUM_THREADS=1"
```

Use the actual enrolled site name (`su` here), not its SSH hostname. Other routes
ignore these SU-specific settings. These are examples of policy, not recommended
universal thresholds: a missing duty-cycle advertisement makes that requirement
undefined and prevents matching. Check the remote pool's advertised attributes.
These expressions select workers within the chosen remote Condor pool; they do
not change which cluster Job Router selects or cancel slow jobs.

The normal Condor submit-file equivalent is:

```condor
+REMOTE_Requirements_su = TARGET.RecentDaemonCoreDutyCycle < 0.05
+REMOTE_Rank_su = TARGET.KFlops
+REMOTE_Environment_su = "OMP_NUM_THREADS=1 MKL_NUM_THREADS=1"
```

Keep ClassAd expressions unquoted. Quote string attributes, such as Environment.
Do not use `ClusterlinkRequirements_su`: that proposed name was not implemented.
These custom attributes do not replace the local job's normal Requirements.
Local-universe workflow helpers are not routed and do not interpret this suffix.

## Rules and precedence

- Use native **ClassAd attribute names**, not submit keywords: `RequestMemory`,
  `RequestCpus`, `Environment`, `Requirements`, `Rank`, `BatchExtraSubmitArgs`.
- `REMOTE_<attribute>_<site>` overrides `REMOTE_<attribute>` for that enrolled
  site. Without the site suffix, the native remote setting applies to all routes.
  Names follow ClassAd's case-insensitive convention. When site names overlap,
  the longest enrolled suffix wins. Suffixes matching enrolled sites are reserved
  for this convention; unknown suffixes are not inferred as destinations.
- Requirements replace the job's base remote requirement, then AND with any
  enrolled-site requirement. A site-specific remote requirement **replaces** the
  unsuffixed remote requirement; repeat any common clauses you still need.
  Remote Condor adds its normal resource/transfer matching clauses.
- Remote Rank overrides enrolled-site/default job Rank. Ranking does not measure
  historical job runtime or automatically move already-queued jobs between sites.
- Environment follows native replacement semantics, **not variable-by-variable
  merging**. A site-specific environment replaces the global remote environment,
  which replaces the ordinary job environment. Include all values required for
  that job. Legacy `Env`/`EnvDelim` remain supported; prefer `Environment`.
  The same selected environment reaches the SIF payload. Project Python/prefix
  setup and missing thread defaults remain managed by Clusterlink.
- Remote numeric resource overrides are supported. `REMOTE_RequestCpus_su = 2`
  changes the remote CPU request and missing thread defaults; `RequestMemory` is
  in MB and `RequestDisk` in KB. Image/input/fallback disk overhead is added to
  the requested working-space disk. Do not quote these numeric values.
- Selected custom remote attributes are forwarded as attributes to the remote
  Condor job; arbitrary names do not automatically acquire scheduler behavior.
  For Slurm, suffix selection still applies but interpretation is limited to
  what the native batch backend supports. Slurm execution remains untested.
- Clusterlink-managed executable/staging attributes (`Cmd`, `Iwd`, `GridResource`,
  `JobUniverse`, and transfer-control fields) cannot be overridden through
  `REMOTE_*`; use ordinary payload executable and CondorIO settings instead.

For an advanced native submit directive:

```ini
condor|+REMOTE_BatchExtraSubmitArgs_su = "periodic_remove = (JobStatus == 2) && (time() - JobCurrentStartDate > 3600)"
```

This replaces the global remote extra-submit string (or ordinary
`BatchExtraSubmitArgs`), rather than appending to it. Include all intended lines
in the selected value. In this submission-text field, Clusterlink accepts literal
`\n` as a line separator, since `condor_submit` preserves that spelling in custom
string attributes. Do not use literal backslash-n as data inside a raw directive.
Clusterlink retains its generated cache-transfer lines. Raw directives can
otherwise override generated settings: prefer the dedicated native attributes
for environment, requirements, rank, and resources. In particular, changing
`environment` only in raw submit text does not update the packaged launcher.

## Verify before launching the campaign

Submit a small CondorIO job using one intended route and then another route.
Check the source job's unchanged Requirements, the remote job's Requirements,
Rank and resource requests, and payload environment/output. Verify successful
completion, not merely that Job Router claimed the job. Keep ordinary
HTCondor/Pegasus retry policy; no speculative execution or straggler requeueing
was added. See the repository STATUS.md for this release's actual test evidence.
