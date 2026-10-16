# Smoke payloads

`analyze.py input.json result.json` imports NumPy, computes a deterministic result,
and records the interpreter, NumPy location, and execution host. `verify.py
result.json` independently checks the expected numeric values using Python's
standard library. `runtime_probe.py` records execution-environment information
and should also be run inside the first remote compute allocation.

Use these payloads from an initialized project with `clusterlink activate` and
ordinary Condor submissions. Clusterlink builds the selected Conda environment
into a SIF automatically and runs it with its bundled private runtime. The
historical archive-relocation experiment has been retired as an execution mode.

Do not perform environment builds on remote login nodes. The remote test budget
is at most 100 GB of project storage in the user's home directory. Remote cache
and per-job staging must both fit within this total.
