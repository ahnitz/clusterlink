"""Transport shim for native HTCondor BLAHP and file-transfer GAHP.

No scheduler protocol is reimplemented. Only SSH startup differs from remote_gahp.
"""
import json
import os
from pathlib import Path
import random
import re
import shlex
import sys

from .transport import relay


def main():
    state = Path(os.environ["CLUSTERLINK_STATE"])
    site_name, command = sys.argv[1:3]
    site = json.loads((state / "sites.json").read_text())[site_name]
    root = site["root"]
    glite = root + "/glite"
    options = []
    if command == "blahpd":
        argv = ["env", "LD_LIBRARY_PATH=" + glite + '/lib', "BLAHPD_LOCATION=" + glite, "GLITE_LOCATION=" + glite,
                "BLAHPD_CONFIG_LOCATION=" + glite + "/etc/blah.config",
                "GAHP_TEMP=" + root + "/tmp", "TMPDIR=" + root + "/tmp", glite + "/bin/blahpd"]
    elif command == "condor_ft-gahp":
        # Follow remote_gahp's reverse SSH forwarding convention. The helper
        # can reach the local GridManager through this tunnel, not a public port.
        address = re.search(r"<([^?>]+)", os.environ.get("CONDOR_INHERIT", ""))
        if not address or not re.fullmatch(r"[0-9.]+:[0-9]+", address.group(1)):
            raise RuntimeError("Missing/unsupported GridManager callback address")
        port = random.SystemRandom().randrange(32768, 61000)
        options = ["-o", "ExitOnForwardFailure=yes", "-R", f"{port}:{address.group(1)}"]
        argv = ["env", "LD_LIBRARY_PATH=" + glite + '/lib', "CONDOR_CONFIG=" + glite + "/etc/condor_config.ft-gahp",
                "GAHP_TEMP=" + root + "/tmp", "TMPDIR=" + root + "/tmp", glite + "/bin/condor_ft-gahp", "-f"]
        print(f"Allocated port {port} for remote forward to", file=sys.stderr, flush=True)
    else:
        raise ValueError("Unsupported native helper")
    return relay(site["ssh"], shlex.join(argv), site["transport"], options)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"clusterlink remote helper: {e}", file=sys.stderr)
        sys.exit(1)
