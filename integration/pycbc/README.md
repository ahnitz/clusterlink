# Isolated PyCBC acceptance test (in progress)

The upstream `examples/search` workflow is used, including its template-bank
and ranking-statistic generators. The environment was installed from an isolated
checkout into `local/pycbc-env`, with a copy-only Conda package cache and pip cache
under the project. Java/Pegasus are also project-local. No existing workstation
PyCBC environment is used.

`clusterlink-site.patch` adds one vanilla Condor/CondorIO site. The executable
configuration patch selects that site, removes a site-specific accounting group,
and requests 1 GiB of working disk explicitly (`1024M`). Clusterlink adds input
and packed/unpacked environment storage automatically. `properties.txt` records the
local Pegasus property overrides. Follow-up workflow generators and final HTML
assembly run in the isolated local environment using Condor local-universe jobs:
they create local absolute paths and child-workflow executable references. The
scientific jobs in those child workflows still select Clusterlink. No search
algorithm changes are intended.

The user-selected source is `ahnitz/pycbc`, branch
`firinspiral3-multidet-asym`, commit `6c67f3fd2ee6e347f44be081ba150f420219ebfa`.
Its native HDF5 frame reader successfully reads all three supplied caches.
`analysis.patch` removes the example's hardcoded GWF filenames and sets
`FROM_PREGENERATED_LCF_FILES` with `/home/ahnitz/gwdata/{H1,L1,V1}.cache`.
PyCBC selects the required frame files and Pegasus stages them through CondorIO.
Shared data is read only; nothing is converted or modified there.

Reapply the site and configuration adaptations with:

```bash
python integration/pycbc/prepare.py --source local/pycbc-source \
  --env local/pycbc-env --work local/pycbc-test \
  --cache-root /home/ahnitz/gwdata
```

The complete workflow has been planned and submitted. It has not yet passed.
See [STATUS.md](../../STATUS.md) for verified stages, alternate-host recovery, and remaining validation.

Portability fix during acceptance: pip initially selected a glibc 2.34 build of
cryptography and locally compiled SQLAlchemy C extensions needing glibc 2.38.
The older su workers cannot use those binaries. Keep the same cryptography
version but select its `manylinux_2_28_x86_64` wheel; install SQLAlchemy 1.3.24
with `DISABLE_SQLALCHEMY_CEXT=1` to use its Python fallback. These change package
builds, not PyCBC algorithms. The initial failed run is retained for diagnosis;
completion is still pending.

During the run, an external process repeatedly renamed ncurses aliases to
`*_CaseConflict`, breaking the live local environment's Conda inventory. The
remaining workflow explicitly selects the previously validated immutable archive
`4bf0900e4ab35c9b0a7e8e4aced2f7b3be5260ea367542fc42434c0efdb987ce`
using `clusterlink activate --env local/pycbc-env --artifact ARCHIVE`. This is an
explicit snapshot choice, not an integrity-check bypass or automatic fallback.
The ordinary automatic path was exercised before this external interference.

The running main DAGMan had cached its original submit defaults. Its 182 already
planned vanilla submit files were therefore given the same explicit
`+ClusterlinkArtifact` setting; pending workflow sources were updated consistently.
Newly started planners/DAGMan processes use the selected private configuration.

After the root DAG finishes, validate completion and basic scientific-output
integrity with the isolated environment:

```bash
local/pycbc-env/bin/python integration/pycbc/validate.py \
  local/pycbc-test/output-cache --report local/pycbc-test/validation.json
```

The validator checks the root DAG exit status, positive finite template masses,
nonempty finite trigger SNRs in both search branches for all three detectors,
and finite injection optimal SNRs. `--allow-incomplete` permits an explicitly
incomplete progress report; it never reports a running workflow as complete.
