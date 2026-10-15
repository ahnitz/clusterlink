"""Self-contained remote enrollment agent; standard library only, no daemon."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


def probe():
    import platform
    commands = {n: shutil.which(n) for n in ["condor_submit", "condor_ft-gahp", "blahpd", "sbatch", "apptainer", "rsync"]}
    for n in ["condor_ft-gahp", "blahpd"]:
        if not commands[n]:
            for d in ["/usr/sbin", "/usr/bin", "/usr/lib/condor", "/usr/libexec/condor"]:
                if os.access(d + "/" + n, os.X_OK):
                    commands[n] = d + "/" + n
                    break
    return dict(home=str(Path.home()), machine=platform.machine(), libc=platform.libc_ver(), commands=commands)


def size(root):
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def root_path(value):
    root = Path(value).expanduser().resolve()
    home = Path.home().resolve()
    if root == home or home not in root.parents:
        raise ValueError("Project root must be a dedicated directory beneath remote home")
    return root


def checksum(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def pin(root, digest, lease):
    if lease:
        if not re.fullmatch(r'[0-9a-f]{64}', lease):
            raise ValueError('Invalid cache lease')
        directory = root / 'leases' / digest
        directory.mkdir(parents=True, exist_ok=True)
        (directory / lease).touch()
    else:
        (root / 'pins' / (digest + '.tar')).touch()


def pinned(root, artifact):
    leases = root / 'leases' / artifact.name[:-7]
    return (root / 'pins' / artifact.stem).exists() or (leases.exists() and any(leases.iterdir()))


def install(root, settings, scripts):
    p = probe()
    if not p["commands"]["blahpd"] or not p["commands"]["condor_ft-gahp"]:
        raise RuntimeError("Native BLAHP/file-transfer helpers unavailable; portable helper deployment not yet implemented")
    if root.exists() and not (root / "owner.json").exists():
        raise RuntimeError("Refusing to adopt an unmarked existing remote directory")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for d in ["cache", "pins", "sandbox", "tmp", "glite/bin", "glite/etc", "glite/libexec", "glite/log"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "owner.json").write_text(json.dumps(settings, indent=2))
    for name in ["blahpd", "condor_ft-gahp"]:
        target = root / "glite/bin" / name
        if target.is_symlink():
            target.unlink()
        target.symlink_to(p["commands"][name])
    candidates = [Path("/usr/libexec/blahp"), Path("/usr/lib/blahp"), Path("/usr/lib/condor"), Path("/usr/libexec/condor")]
    source = next((d for d in candidates if (d / "blah_common_submit_functions.sh").exists()), Path('/usr/sbin'))
    # Deploy the submitting installation's maintained shell adapters; preserve
    # their upstream copyright notices. No system-wide remote installation.
    for name, content in scripts.items():
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+\.sh', name):
            raise ValueError('Invalid helper filename')
        target = root / 'glite/libexec' / name
        target.write_text(content)
        target.chmod(0o700)
    # Some releases find scripts under libexec, others under bin/scripts.
    for name in ["scripts"]:
        link = root / "glite/bin" / name
        if not link.exists():
            link.symlink_to("../libexec", target_is_directory=True)
    config = Path("/etc/blah.config").read_text()
    config += f'\nblah_libexec_directory="{root}/glite/libexec"\nblah_sbin_directory="{source}"\nblah_temp_dir="{root}/tmp"\nblah_shared_directories=/\nblah_run_in_workdir=yes\nblah_max_threaded_cmds=4\n'
    (root / "glite/etc/blah.config").write_text(config)
    (root / "glite/etc/condor_config.ft-gahp").write_text(
        f"BOSCO_SANDBOX_DIR = {root}/sandbox\nLOG = {root}/glite/log\nFT_GAHP_LOG = $(LOG)/FTGahpLog\n"
        "SEC_CLIENT_AUTHENTICATION_METHODS = FS\nUSE_SHARED_PORT = False\nENABLE_URL_TRANSFERS = False\n"
        "MAX_DEFAULT_LOG = 10000000\n")
    return p


def main():
    action = sys.argv[1]
    if action == "probe":
        print(json.dumps(probe()))
        return
    root = root_path(sys.argv[2])
    if action == "install":
        print(json.dumps(install(root, json.loads(sys.argv[3]), json.load(sys.stdin))))
        return
    settings = json.loads((root / "owner.json").read_text())
    with (root / ".cache.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "status":
            print(json.dumps({"cache_bytes": size(root / "cache"), "total_bytes": size(root), **settings}))
            return
        digest = sys.argv[3]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid content digest")
        target = root / "cache" / (digest + ".tar.gz")
        if action == 'release':
            lease = sys.argv[4]
            if not re.fullmatch(r'[0-9a-f]{64}', lease):
                raise ValueError('Invalid cache lease')
            (root / 'leases' / digest / lease).unlink(missing_ok=True)
            print(json.dumps({'released': True}))
            return
        if action == "check":
            exists = target.exists()
            if exists:
                if checksum(target) != digest:
                    raise RuntimeError('Cached artifact checksum mismatch')
                pin(root, digest, sys.argv[4] if len(sys.argv) > 4 else None)
                os.utime(target, None)
            print(json.dumps({"cached": exists, "path": str(target)}))
            return
        if action != "upload":
            raise ValueError("Unknown operation")
        expected = int(sys.argv[4])
        lease = sys.argv[5] if len(sys.argv) > 5 else None
        if expected <= 0 or expected > settings["cache_bytes"]:
            raise ValueError("Artifact exceeds cache budget")
        if target.exists():
            # A concurrent uploader may have completed after our cache check.
            # Consume/verify this stream, but do not reserve space or replace it.
            h = hashlib.sha256()
            remaining = expected
            while remaining:
                chunk = sys.stdin.buffer.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError('Incomplete upload')
                remaining -= len(chunk)
                h.update(chunk)
            if h.hexdigest() != digest or checksum(target) != digest:
                raise RuntimeError('Checksum mismatch')
            pin(root, digest, lease)
            print(json.dumps({'cached': True, 'uploaded_bytes': 0, 'path': str(target)}))
            return
        # LRU eviction considers only entries without outstanding job leases.
        for f in sorted((root / "cache").glob("*.tar.gz"), key=lambda f: f.stat().st_mtime):
            if size(root / "cache") + expected <= settings["cache_bytes"]:
                break
            if not pinned(root, f):
                f.unlink()
        if size(root / "cache") + expected > settings["cache_bytes"]:
            raise RuntimeError("Cache full; active/pinned artifacts cannot be evicted")
        if size(root) + expected > settings["storage_bytes"]:
            raise RuntimeError("Project storage budget would be exceeded")
        if shutil.disk_usage(root).free < expected + settings["reserve_bytes"]:
            raise RuntimeError("Insufficient free space for upload and reserve")
        temp = target.with_suffix(".partial")
        h = hashlib.sha256()
        received = 0
        try:
            with temp.open("xb") as out:
                while received < expected:
                    chunk = sys.stdin.buffer.read(min(1024 * 1024, expected - received))
                    if not chunk:
                        raise RuntimeError("Incomplete upload")
                    out.write(chunk)
                    h.update(chunk)
                    received += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            if h.hexdigest() != digest:
                raise RuntimeError("Checksum mismatch")
            temp.replace(target)
            pin(root, digest, lease)
        finally:
            temp.unlink(missing_ok=True)
        print(json.dumps({"cached": False, "uploaded_bytes": received, "path": str(target)}))


if __name__ == "__main__":
    main()
