"""Disposable destination pool, invoked as its dedicated unprivileged account."""
import json
import sys
from pathlib import Path
from clusterlink import pool

state = Path.home() / 'pool'
state.mkdir(exist_ok=True)
(state / 'sites.json').write_text('{}')
pool.configure(state, local_slots=1)
with (state / 'condor.config').open('a') as config:
    config.write('''
DAEMON_LIST = MASTER COLLECTOR NEGOTIATOR SCHEDD STARTD
START = True
SUBMIT_REQUIREMENT_NAMES =
NEGOTIATOR_INTERVAL = 2
UPDATE_INTERVAL = 2
MEMORY = 2048
''')
pool.start(state)
