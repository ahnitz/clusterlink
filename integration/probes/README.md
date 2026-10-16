# Small acceptance payloads

`nested-output.sh` creates `nested/result.txt`; declare that path in
`transfer_output_files` and map `result.txt=nested/result.txt` locally. It also
reports worker container capabilities. Test through ordinary vanilla submission,
with the selected Conda environment, on each enrolled site.

`failure.sh` deliberately exits 7 without creating its declared `missing.txt`.
The expected result is exit 7, its diagnostic in stderr, and an empty placeholder
output rather than a missing-output transfer hold.

`sif.sh` expects `ubuntu22.sif` and a tarball containing an `apptainer-runtime/`
private unprivileged installation. It tests the shipped runtime with user
namespaces and explicit SIF extraction, using only job-local caches. The image
and runtime are test inputs, not included in this repository. This is the original runtime
feasibility test. Normal submissions now build and stage the SIF automatically.


The reproducible three-pool test lives in `../dev-pools/`. From an activated
project enrolled with `dev1`, `dev3`, and `dev4` (one routed job per site), run
`python /path/to/clusterlink/integration/dev-pools/prepare.py`. Submit each
`targeted-*/job.sub` from its own directory, wait for completion, then submit
each `automatic-*/job.sub`. Finally run
`python /path/to/clusterlink/integration/dev-pools/validate.py` after the queue
drains. Automatic case names identify inputs, not a requested destination.
The test checks SIF Python/PyCBC, numerical results, input/output transfer, and
coverage of all three sites with and without explicit placement.
