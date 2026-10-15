# Isolated PyCBC acceptance test (in progress)

The upstream `examples/search` workflow is used, including its template-bank
and ranking-statistic generators. The environment was installed from an isolated
checkout into `local/pycbc-env`, with a copy-only Conda package cache and pip cache
under the project. Java/Pegasus are also project-local. No existing workstation
PyCBC environment is used.

`clusterlink-site.patch` adds one vanilla Condor/CondorIO site. The executable
configuration patch selects that site, removes a site-specific accounting group,
and requests room for the unpacked environment. `properties.txt` records the
local Pegasus property overrides. No search algorithm changes are intended.

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
See STATUS.md for verified stages.

Portability fix during acceptance: pip initially selected a glibc 2.34 build of
cryptography and locally compiled SQLAlchemy C extensions needing glibc 2.38.
The older su workers cannot use those binaries. Keep the same cryptography
version but select its `manylinux_2_28_x86_64` wheel; install SQLAlchemy 1.3.24
with `DISABLE_SQLALCHEMY_CEXT=1` to use its Python fallback. These change package
builds, not PyCBC algorithms. The initial failed run is retained for diagnosis;
completion is still pending.
