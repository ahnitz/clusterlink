"""An isolated user-owned Condor test access point using installed binaries."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def environment(state):
    # Exported Bash functions can be truncated by daemon environment handling.
    # They are shell setup, not inputs to Condor or its protocol helpers.
    clean = {key: value for key, value in os.environ.items()
             if not key.startswith('BASH_FUNC_')}
    return {**clean, "CONDOR_CONFIG": str(state / "condor.config"), "CLUSTERLINK_STATE": str(state)}


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


def configure(state, local_slots=None):
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
    if local_slots is None:
        local_slots = settings.get("local_slots", 0)
    settings["local_slots"] = local_slots
    settings_path.write_text(json.dumps(settings))
    package_root = str(Path(__file__).resolve().parent.parent)
    shim = state / "remote-gahp"
    hook = state / 'prepare-job'
    cleanup = state / 'cleanup-job'
    for path, module, arguments in [(shim, 'clusterlink.gahp', []),
                                    (hook, 'clusterlink.hooks', []),
                                    (cleanup, 'clusterlink.hooks', ['cleanup'])]:
        # Start Python directly: a shell parses exported functions before any
        # shell-script cleanup can run. Keep the interpreter from installation.
        path.write_text(f"#!{sys.executable}\n"
                        "import os, runpy, sys\n"
                        "for key in tuple(os.environ):\n"
                        "    if key.startswith('BASH_FUNC_'): del os.environ[key]\n"
                        f"os.environ['CLUSTERLINK_STATE'] = {str(state)!r}\n"
                        f"os.environ['PYTHONPATH'] = {package_root!r}\n"
                        f"sys.path.insert(0, {package_root!r})\n"
                        f"sys.argv[1:1] = {arguments!r}\n"
                        f"runpy.run_module({module!r}, run_name='__main__')\n")
        path.chmod(0o700)
    username = __import__("getpass").getuser()
    schedd = f'clusterlink-{username}'
    if (state / 'project.json').exists():
        schedd += '-' + json.loads((state / 'project.json').read_text())['id']
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
SCHEDD_NAME = {schedd}@$(FULL_HOSTNAME)
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
# Translation returns the whole job ad. Pegasus ads exceed the 10 KiB default.
JOB_ROUTER.PIPE_BUFFER_MAX = 16777216
# Reject shared-filesystem plans before they become remote staging failures.
SUBMIT_REQUIREMENT_NAMES = $(SUBMIT_REQUIREMENT_NAMES) ClusterlinkCondorIO
SUBMIT_REQUIREMENT_ClusterlinkCondorIO = (TARGET.JobUniverse != 5) || (TARGET.ClusterlinkEligible =!= True) || (isUndefined(TARGET.RemoteIwd) && isUndefined(TARGET.REMOTE_Iwd))
SUBMIT_REQUIREMENT_ClusterlinkCondorIO_REASON = "Clusterlink uses CondorIO sandboxes: remove remote_initialdir/RemoteIwd and replan Pegasus with data.configuration=condorio in a fresh output directory. Shared-filesystem plans are unsupported."
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
    # Local-universe jobs match the schedd's machine ad. Let native Condor
    # detect host resources; an artificial MEMORY limit can strand helpers.
    if local_slots:
        text += f'NUM_CPUS = {local_slots}\n'
    selected = state / 'environment.json'
    if selected.exists():
        from .project import environment_selection
        selection = environment_selection(state)
        prefix = selection['prefix']
        text += '\nSUBMIT_ATTRS = ClusterlinkEnvironment, ClusterlinkEligible\n'
        text += 'ClusterlinkEnvironment = ' + json.dumps(prefix) + '\n'
        text += 'ClusterlinkEligible = True\nJOB_ROUTER_HOOK_KEYWORD = CLUSTERLINK\n'
        text += 'CLUSTERLINK_HOOK_TRANSLATE_JOB = ' + str(hook) + '\n'
        text += 'CLUSTERLINK_HOOK_JOB_CLEANUP = ' + str(cleanup) + '\n'
    # Native per-route MaxJobs has no negative unlimited sentinel (unlike
    # MaxIdleJobs). Use its signed-int ceiling for an uncapped enrollment.
    for name, site in sites.items():
        text += f"""
JOB_ROUTER_ROUTE_{route_key(name)} @=route
  REQUIREMENTS {"True" if site.get("enabled", True) else "False"} && (ClusterlinkSite =?= undefined || ClusterlinkSite == "auto" || ClusterlinkSite == "{name}")
  GridResource = "batch {site['scheduler']} {name}"
  MaxJobs = {2147483647 if site['max_jobs'] == -1 else site['max_jobs']}
  MaxIdleJobs = {site['max_idle']}
  SET ClusterlinkDestination = "{name}"
  SET Requirements = True
  EVALSET TransferOutputRemaps = ClusterlinkOutputRemaps
"""
        if site['scheduler'] == 'condor':
            text += f"""  SET BatchExtraSubmitArgs = strcat(ifThenElse(isUndefined(ClusterlinkRemoteSubmitArgs), "", ClusterlinkRemoteSubmitArgs), ifThenElse(isUndefined(ClusterlinkCachedEnv), "", strcat("transfer_input_files = ", "$", "(transfer_input_files), {site['root']}/cache/", ClusterlinkCachedEnv, ".tar.gz")))
"""
        text += """
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
