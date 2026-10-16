"""Self-contained remote enrollment agent; standard library only, no daemon."""
import fcntl
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import io
import tarfile


def probe():
    import platform
    commands = {n: shutil.which(n) for n in ["condor_submit", "condor_ft-gahp", "blahpd", "sbatch", "apptainer", "rsync"]}
    for n in ["condor_ft-gahp", "blahpd"]:
        if not commands[n]:
            for d in ["/usr/sbin", "/usr/bin", "/usr/lib/condor", "/usr/libexec/condor"]:
                if os.access(d + "/" + n, os.X_OK):
                    commands[n] = d + "/" + n
                    break
    return dict(python_version=list(sys.version_info[:2]), home=str(Path.home()), machine=platform.machine(), libc=platform.libc_ver(), commands=commands)


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


def cache_signature(path):
    s = path.stat()
    return [s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def remember_verified(root, digest, target):
    directory = root / 'verified'
    directory.mkdir(exist_ok=True)
    (directory / digest).write_text(json.dumps(cache_signature(target)))


def verify_cached(root, digest, target):
    record = root / 'verified' / digest
    if record.exists() and json.loads(record.read_text()) == cache_signature(target):
        return
    if checksum(target) != digest:
        raise RuntimeError('Cached artifact checksum mismatch')


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
    portable = (root / 'helpers.json').exists()
    if not portable and (not p["commands"]["blahpd"] or not p["commands"]["condor_ft-gahp"]):
        raise RuntimeError("Native BLAHP/file-transfer helpers unavailable; portable helper deployment not yet implemented")
    if root.exists() and not (root / "owner.json").exists():
        raise RuntimeError("Refusing to adopt an unmarked existing remote directory")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for d in ["cache", "pins", "sandbox", "tmp", "glite/bin", "glite/etc", "glite/libexec", "glite/log"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "owner.json").write_text(json.dumps(settings, indent=2))
    for name in ["blahpd", "condor_ft-gahp"]:
        if portable:
            continue
        target = root / "glite/bin" / name
        if target.is_symlink():
            target.unlink()
        target.symlink_to(p["commands"][name])
    candidates = [Path("/usr/libexec/blahp"), Path("/usr/lib/blahp"), Path("/usr/lib/condor"), Path("/usr/libexec/condor")]
    source = root / 'glite/sbin' if portable else next((d for d in candidates if (d / "blah_common_submit_functions.sh").exists()), Path('/usr/sbin'))
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
    config = (root / 'glite/etc/blah.config' if portable else Path('/etc/blah.config')).read_text()
    config += f'\nblah_libexec_directory="{root}/glite/libexec"\nblah_sbin_directory="{source}"\nblah_temp_dir="{root}/tmp"\nblah_shared_directories=/\nblah_run_in_workdir=yes\nblah_max_threaded_cmds=4\n'
    (root / "glite/etc/blah.config").write_text(config)
    (root / "glite/etc/condor_config.ft-gahp").write_text(
        f"BOSCO_SANDBOX_DIR = {root}/sandbox\nLOG = {root}/glite/log\nFT_GAHP_LOG = $(LOG)/FTGahpLog\n"
        "SEC_CLIENT_AUTHENTICATION_METHODS = FS\nUSE_SHARED_PORT = False\nENABLE_URL_TRANSFERS = False\n"
        "MAX_DEFAULT_LOG = 10000000\n")
    return p


def bootstrap(root, settings, digest, metadata):
    if root.exists() and not (root / 'owner.json').exists():
        raise RuntimeError('Refusing to adopt an unmarked remote directory')
    data = sys.stdin.buffer.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError('Helper bundle checksum mismatch')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
        total = sum(m.size for m in members)
        if size(root) + total > settings['storage_bytes']:
            raise RuntimeError('Helpers would exceed project storage budget')
        if shutil.disk_usage(root).free < total + settings['reserve_bytes']:
            raise RuntimeError('Insufficient free space for helpers')
        for member in members:
            path = Path(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe helper archive member')
            target = root / 'glite' / path
            # Never follow a preexisting binary symlink into system directories.
            if target.is_symlink():
                target.unlink()
            if (root / 'glite').resolve() not in target.resolve().parents:
                raise ValueError('Helper path escapes managed directory')
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(member.mode & 0o700)
    (root / 'owner.json').write_text(json.dumps(settings))
    (root / 'helpers.json').write_text(json.dumps(metadata))
    return {'installed_bytes': total, **metadata}


def main():
    action = sys.argv[1]
    if action == "probe":
        print(json.dumps(probe()))
        return
    root = root_path(sys.argv[2])
    if action == 'bootstrap':
        print(json.dumps(bootstrap(root, json.loads(sys.argv[3]), sys.argv[4], json.loads(sys.argv[5]))))
        return
    if action == "install":
        print(json.dumps(install(root, json.loads(sys.argv[3]), json.load(sys.stdin))))
        return
    settings = json.loads((root / "owner.json").read_text())
    with ExitStack() as streams, (root / ".cache.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "status":
            print(json.dumps({"cache_used_bytes": size(root / "cache"), "total_bytes": size(root),
                              'active_leases': sum(1 for p in (root / 'leases').glob('*/*') if p.is_file()),
                              **settings}))
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
                verify_cached(root, digest, target)
                pin(root, digest, sys.argv[4] if len(sys.argv) > 4 else None)
                os.utime(target, None)
                remember_verified(root, digest, target)
            print(json.dumps({"cached": exists, "path": str(target)}))
            return
        if action not in {"upload", "reuse"}:
            raise ValueError("Unknown operation")
        lease = sys.argv[5] if len(sys.argv) > 5 else None
        input_stream = sys.stdin.buffer
        if action == "reuse":
            # Only probe explicitly enrolled, user-owned roots beneath this
            # host's home. A shared home is optional, never a prerequisite.
            source = None
            for value in json.loads(sys.argv[4]):
                try:
                    other = root_path(value)
                    candidate = other / "cache" / (digest + ".tar.gz")
                    if ((other / "owner.json").stat().st_uid != os.getuid()
                            or candidate.is_symlink()
                            or other not in candidate.resolve().parents
                            or candidate.stat().st_uid != os.getuid()):
                        continue
                    source = streams.enter_context(candidate.open("rb"))
                    break
                except (OSError, ValueError):
                    continue
            if source is None:
                print(json.dumps({"cached": False, "reused_bytes": 0}))
                return
            input_stream = source
            expected = os.fstat(source.fileno()).st_size
        else:
            expected = int(sys.argv[4])
        if expected <= 0 or expected > settings["cache_bytes"]:
            raise ValueError("Artifact exceeds cache budget")
        if target.exists():
            # A concurrent uploader may have completed after our cache check.
            # Consume/verify this stream, but do not reserve space or replace it.
            h = hashlib.sha256()
            remaining = expected
            while remaining:
                chunk = input_stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError('Incomplete upload')
                remaining -= len(chunk)
                h.update(chunk)
            if h.hexdigest() != digest or checksum(target) != digest:
                raise RuntimeError('Checksum mismatch')
            pin(root, digest, lease)
            remember_verified(root, digest, target)
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
                    chunk = input_stream.read(min(1024 * 1024, expected - received))
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
            remember_verified(root, digest, target)
        finally:
            temp.unlink(missing_ok=True)
        print(json.dumps({"cached": action == "reuse",
                          "uploaded_bytes": received if action == "upload" else 0,
                          "reused_bytes": received if action == "reuse" else 0,
                          "path": str(target)}))


if __name__ == "__main__":
    main()
