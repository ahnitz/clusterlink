# Smoke payloads

`analyze.py input.json result.json` imports NumPy, computes a deterministic result,
and records the interpreter, NumPy location, and execution host. `verify.py
result.json` independently checks the expected numeric values using Python's
standard library. `runtime_probe.py` records execution-environment information
and should also be run inside the first remote compute allocation.

The test environment lives at `../local/env`; its recipe is `../environment.yml`.
The tested environment can be packed using its `conda-pack` command. Environment
creation and package download caches are kept under `../local/`. An explicit
package list and build logs are stored there too.

Initial local validation passed both in the original environment and after
packing, extraction to `../local/relocation-test`, and `conda-unpack`. This proves
local relocation only, not compatibility with a remote host's libc or architecture.

Do not perform environment builds on remote login nodes. The remote test budget
is at most 100 GB of project storage in the user's home directory. Remote cache
and per-job staging must both fit within this total.
