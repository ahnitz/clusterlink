"""An isolated user-owned Condor test access point using installed binaries."""
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time


def environment(state):
    return {**os.environ, "CONDOR_CONFIG": str(state / "condor.config"), "CLUSTERLINK_STATE": str(state)}


def route_key(name):
    # Enrollment names allow hyphens; Condor configuration identifiers do not.
    return 'site_' + name.encode().hex()


def running(state):
    """Recognize this pool's live master, including after stale PID reuse."""
    try:
        pid = int((state / 'master.pid').read_text())
        proc = Path('/proc') / str(pid)
        command = (proc / 'cmdline').read_bytes().split(b'\0')[0]
        config = b'CONDOR_CONFIG=' + str(state / 'condor.config').encode()
        return (Path(os.fsdecode(command)).name == 'condor_master'
                and config in (proc / 'environ').read_bytes().split(b'\0'))
    except (OSError, ValueError):
        return False


def configure(state, local_slots=0):
    sites = json.loads((state / "sites.json").read_text())
    for name in ["log", "spool", "execute", "lock", "run"]:
        (state / name).mkdir(exist_ok=True)
    settings_path = state / "pool.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            settings = {"port": s.getsockname()[1]}
        settings_path.write_text(json.dumps(settings))
    package_root = str(Path(__file__).resolve().parent.parent)
    shim = state / "remote-gahp"
    shim.write_text("#!/bin/sh\nexport CLUSTERLINK_STATE=" + shlex.quote(str(state)) +
                    "\nexport PYTHONPATH=" + shlex.quote(package_root) +
                    "\nexec " + shlex.quote(sys.executable) + " -m clusterlink.gahp \"$@\"\n")
    shim.chmod(0o700)
    hook = state / 'prepare-job'
    hook.write_text(shim.read_text().replace('clusterlink.gahp', 'clusterlink.hooks'))
    hook.chmod(0o700)
    cleanup = state / 'cleanup-job'
    cleanup.write_text(hook.read_text().replace('clusterlink.hooks', 'clusterlink.hooks cleanup'))
    cleanup.chmod(0o700)
    username = __import__("getpass").getuser()
    text = f"""include : /etc/condor/condor_config
LOCAL_CONFIG_FILE =
LOCAL_CONFIG_DIR =
LOCAL_DIR = {state}
LOG = {state}/log
SPOOL = {state}/spool
EXECUTE = {state}/execute
LOCK = {state}/lock
RUN = {state}/run
DAEMON_LIST = MASTER COLLECTOR NEGOTIATOR SCHEDD JOB_ROUTER {"STARTD" if local_slots else ""}
COLLECTOR_HOST = 127.0.0.1:{settings['port']}
COLLECTOR_ARGS = -p {settings['port']}
CONDOR_HOST = 127.0.0.1
NETWORK_INTERFACE = 127.0.0.1
BIND_ALL_INTERFACES = False
USE_SHARED_PORT = False
SCHEDD_NAME = clusterlink-{username}@$(FULL_HOSTNAME)
UID_DOMAIN = clusterlink.local
FILESYSTEM_DOMAIN = clusterlink.local
SEC_DEFAULT_AUTHENTICATION = REQUIRED
SEC_DEFAULT_AUTHENTICATION_METHODS = FS
ALLOW_READ = {username}@*
ALLOW_WRITE = {username}@*
ALLOW_ADMINISTRATOR = {username}@*
QUEUE_SUPER_USERS = {username}
SEC_DEFAULT_ENCRYPTION = OPTIONAL
SEC_DEFAULT_INTEGRITY = OPTIONAL
CREATE_CORE_FILES = False
USE_PROCD = False
PROCD_ADDRESS =
REMOTE_GAHP = {shim}
GRIDMANAGER_GAHP_RESPONSE_TIMEOUT = 180
GRIDMANAGER_LOG = {state}/log/GridmanagerLog.$(USERNAME)
GRIDMANAGER_SELECTION_EXPR = Owner
JOB_ROUTER_LOG = {state}/log/JobRouterLog
JOB_ROUTER_LOCK = {state}/lock/JobRouterLock
JOB_ROUTER_ROUND_ROBIN_SELECTION = True
JOB_ROUTER_SOURCE_JOB_CONSTRAINT = ClusterlinkEligible =?= True && JobUniverse == 5
JOB_ROUTER_ROUTE_NAMES = {', '.join(route_key(name) for name in sites)}
JOB_ROUTER_POLLING_PERIOD = 10
NUM_CPUS = {max(1, local_slots)}
MEMORY = 1024
START = ClusterlinkEligible =!= True
SUSPEND = False
PREEMPT = False
KILL = False
WANT_SUSPEND = False
WANT_VACATE = False
MAX_DEFAULT_LOG = 10000000
JOB_ROUTER_HOOK_KEYWORD = CLUSTERLINK
CLUSTERLINK_HOOK_TRANSLATE_JOB = {hook}
CLUSTERLINK_HOOK_JOB_CLEANUP = {cleanup}
"""
    selected = state / 'environment.json'
    if selected.exists():
        selection = json.loads(selected.read_text())
        prefix = selection['prefix']
        text += '\nSUBMIT_ATTRS = ClusterlinkEnvironment, ClusterlinkEligible\n'
        text += 'ClusterlinkEnvironment = ' + json.dumps(prefix) + '\n'
        text += 'ClusterlinkEligible = True\nJOB_ROUTER_HOOK_KEYWORD = CLUSTERLINK\n'
        if selection.get('artifact'):
            text += 'SUBMIT_ATTRS = $(SUBMIT_ATTRS), ClusterlinkArtifact\n'
            text += 'ClusterlinkArtifact = ' + json.dumps(selection['artifact']) + '\n'
        text += 'CLUSTERLINK_HOOK_TRANSLATE_JOB = ' + str(hook) + '\n'
        text += 'CLUSTERLINK_HOOK_JOB_CLEANUP = ' + str(cleanup) + '\n'
    for name, site in sites.items():
        text += f"""
JOB_ROUTER_ROUTE_{route_key(name)} @=route
  REQUIREMENTS (ClusterlinkSite =?= undefined || ClusterlinkSite == "auto" || ClusterlinkSite == "{name}")
  GridResource = "batch {site['scheduler']} {name}"
  MaxJobs = {site['max_jobs']}
  MaxIdleJobs = {site['max_idle']}
  SET ClusterlinkDestination = "{name}"
  SET Requirements = True
  EVALSET TransferOutputRemaps = ClusterlinkOutputRemaps
  SET BatchExtraSubmitArgs = strcat(ifThenElse(isUndefined(ClusterlinkRemoteSubmitArgs), "", ClusterlinkRemoteSubmitArgs), ifThenElse(isUndefined(ClusterlinkCachedEnv), "", strcat("transfer_input_files = ", "$", "(transfer_input_files), {site['root']}/cache/", ClusterlinkCachedEnv, ".tar.gz")))
  DELETE ClusterlinkEligible
@route
"""
    (state / "condor.config").write_text(text)
    return state / "condor.config"


def start(state):
    config_check = subprocess.run(['condor_config_val', '-config'], env=environment(state),
                                  capture_output=True, text=True)
    if config_check.returncode:
        raise RuntimeError('Invalid private Condor configuration: ' + config_check.stderr.strip())
    pidfile = state / "master.pid"
    if running(state):
        raise RuntimeError("Managed pool already running")
    with (state / "log/master-console.log").open("ab") as log:
        proc = subprocess.Popen(["condor_master", "-f"], env=environment(state),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True)
    pidfile.write_text(str(proc.pid))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError('Private Condor master exited; inspect ' + str(state / 'log/master-console.log'))
        try:
            ready = subprocess.run(['condor_q', '-totals'], env=environment(state),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            if ready.returncode == 0:
                break
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.2)
    else:
        raise RuntimeError('Private pool started but scheduler is not ready; inspect ' + str(state / 'log'))
    print(f"Started user-owned Condor master {proc.pid}; config {state / 'condor.config'}")
