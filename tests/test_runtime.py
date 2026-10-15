import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from clusterlink.environments import executable_command, fingerprint, launcher
from clusterlink.transport import destination, start, python_command
from clusterlink.pool import configure


class RuntimeTests(unittest.TestCase):
    def test_ssh_alias_is_not_shell_code(self):
        for name in ['-oProxyCommand=bad', 'host;touch /tmp/bad', 'host name']:
            with self.assertRaises(ValueError):
                destination(name)
        self.assertEqual(destination('user@cluster'), 'user@cluster')

    def test_nonprompting_keyboard_interactive_is_allowed(self):
        proc = Mock()
        with patch('clusterlink.transport.subprocess.Popen', return_value=proc) as popen:
            start('osg', 'true', 'login')
        argv = popen.call_args.args[0]
        env = popen.call_args.kwargs['env']
        self.assertIn('BatchMode=no', argv)
        self.assertEqual(env['SSH_ASKPASS_REQUIRE'], 'force')
        self.assertEqual(env['SSH_ASKPASS'], '/bin/false')
        self.assertEqual(argv[-1], 'osg')
        self.assertIn(b'exec true', proc.stdin.write.call_args.args[0])

    def test_entrypoint_and_external_python_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / 'env'
            (env / 'bin').mkdir(parents=True)
            entry = env / 'bin/search'
            entry.write_text('#!/bin/python\n')
            entry.chmod(0o700)
            cmd, file = executable_command('search', env)
            self.assertEqual(cmd, '"$CLUSTERLINK_ENV"/bin/search')
            self.assertIsNone(file)
            script = root / 'external.py'
            script.write_text('print(1)')
            cmd, file = executable_command(str(script), env)
            self.assertEqual(file, script)
            self.assertIn('"$CLUSTERLINK_ENV/bin/python"', cmd)
            self.assertIn('exec ', launcher(cmd))

    def test_environment_install_invalidates_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'module.py'
            path.write_text('original')
            original = fingerprint(root)
            path.write_text('modified')
            self.assertNotEqual(original, fingerprint(root))

    def test_routes_use_enrolled_settings_and_local_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sites.json').write_text(json.dumps({'example': {
                'scheduler': 'slurm', 'max_jobs': 3, 'max_idle': 1, 'root': '/home/example/.clusterlink'}}))
            # The test supplies its own collector port; no socket required.
            (root / 'pool.json').write_text('{"port": 18234}')
            config = configure(root).read_text()
            self.assertIn('batch slurm example', config)
            self.assertIn('MaxJobs = 3', config)
            self.assertIn('MaxIdleJobs = 1', config)
            self.assertIn('JOB_ROUTER_ROUND_ROBIN_SELECTION = True', config)
            self.assertIn('SPOOL = ' + str(root), config)
            self.assertNotIn('batch condor su', config)


if __name__ == '__main__':
    unittest.main()
