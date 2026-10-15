"""SSH transport, preserving OpenSSH aliases, identities, and jump hosts."""
import base64
import os
from pathlib import Path
import shutil
import re
import shlex
import subprocess
import threading
import uuid


def destination(value):
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", value):
        raise ValueError("Use an SSH config alias or user@hostname (configure ports in SSH config)")
    return value


def start(host, command, mode="exec", options=()):
    # Some sites require a zero-prompt keyboard-interactive exchange after
    # accepting a public key. BatchMode disables that exchange entirely.
    # Allow it, but fail real prompts rather than asking inside a daemon.
    args = ["ssh", "-T", "-o", "BatchMode=no", "-o", "ConnectTimeout=15", *options, destination(host)]
    marker = "CLUSTERLINK_" + uuid.uuid4().hex
    if mode == "exec":
        args += ["printf '%s\\n' " + shlex.quote(marker) + "; exec " + command]
    env = {**os.environ, "SSH_ASKPASS": "/bin/false", "SSH_ASKPASS_REQUIRE": "force"}
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, env=env)
    if mode == "login":
        p.stdin.write(("printf '%s\\n' " + shlex.quote(marker) + "; exec " + command + "\n").encode())
        p.stdin.flush()
    return p, marker.encode() + b"\n"


def run(host, command, mode="exec", payload=b"", timeout=120):
    # communicate handles both stdout draining and large uploads. Login banners
    # are discarded only up to our unpredictable framing marker.
    p, marker = start(host, command, mode)
    writer = None
    errors = []
    if isinstance(payload, Path):
        sink = p.stdin
        p.stdin = None
        def upload():
            try:
                with payload.open('rb') as source, sink:
                    shutil.copyfileobj(source, sink, 1024 * 1024)
            except (OSError, ValueError) as error:
                errors.append(error)
        writer = threading.Thread(target=upload, daemon=True)
        writer.start()
        payload = None
    try:
        out, _ = p.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise RuntimeError(f"SSH to {host} exceeded {timeout}s; inspect shell startup")
    if writer is not None:
        writer.join(timeout=5)
        if writer.is_alive() or errors:
            raise RuntimeError(f"Upload to {host} did not complete: {errors}")
    if marker not in out:
        raise RuntimeError(f"SSH to {host} did not reach the command (exit {p.returncode})")
    out = out.split(marker, 1)[1]
    if p.returncode:
        raise RuntimeError(f"Remote command failed ({p.returncode}): {out.decode(errors='replace')[-2000:]}")
    return out


def python_command(source, args=(), interpreter="python3"):
    code = "import base64;exec(compile(base64.b64decode(" + repr(base64.b64encode(source.encode()).decode()) + "),'<clusterlink>','exec'))"
    return shlex.join([interpreter, "-c", code, *map(str, args)])


def relay(host, command, mode, options=()):
    """Relay a native GAHP protocol without login banners corrupting it."""
    p, marker = start(host, command, mode, options)
    def feed():
        try:
            while chunk := os.read(0, 65536):
                p.stdin.write(chunk)
                p.stdin.flush()
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    threading.Thread(target=feed, daemon=True).start()
    while True:
        line = p.stdout.readline()
        if not line:
            return p.wait() or 1
        if line == marker:
            break
    while chunk := p.stdout.read1(65536):
        os.write(1, chunk)
    return p.wait()
