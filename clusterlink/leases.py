"""Durable local acknowledgments for remote cache leases.

Job completion must not depend on opening a new SSH connection. Defer unpins
until the next contact with that site; the remote cache stays conservative.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile


def directory(state, site):
    identity = json.dumps([site.get('ssh'), site.get('root')])
    key = hashlib.sha256(identity.encode()).hexdigest()
    return Path(state) / 'pending-releases' / key


def defer(state, site, digest, lease):
    root = directory(state, site)
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((digest + lease).encode()).hexdigest()
    fd, temporary = tempfile.mkstemp(dir=root)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump([digest, lease], stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / (key + '.json'))
    finally:
        Path(temporary).unlink(missing_ok=True)


def pending(state, site):
    paths = sorted(directory(state, site).glob('*.json'))[:256]
    return paths, [json.loads(p.read_text()) for p in paths]


def acknowledge(paths):
    for path in paths:
        path.unlink(missing_ok=True)
