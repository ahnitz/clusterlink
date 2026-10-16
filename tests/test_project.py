import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from clusterlink import project, pool


class ProjectTests(unittest.TestCase):
    def test_two_projects_and_discovery_override_active_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root/'env'; (env/'conda-meta').mkdir(parents=True)
            states = []
            for name in ('one','two'):
                folder = root/name;folder.mkdir()
                with patch('pathlib.Path.cwd',return_value=folder):
                    state = project.initialize(env)
                pool.configure(state)
                states.append(state)
                with patch('pathlib.Path.cwd',return_value=folder/'subdir'), patch.dict(os.environ,{'CLUSTERLINK_STATE':'/wrong/project'}):
                    self.assertEqual(project.discover(),state)
                with patch('pathlib.Path.cwd',return_value=folder), self.assertRaises(ValueError):
                    project.initialize(env)
            self.assertNotEqual(project.remote_root(states[0],'/home/user','same'),project.remote_root(states[1],'/home/user','same'))
            configs=[(s/'condor.config').read_text() for s in states]
            names=[next(x for x in c.splitlines() if x.startswith('SCHEDD_NAME')) for c in configs]
            self.assertNotEqual(*names)
            self.assertEqual(json.loads((states[0]/'environment.json').read_text())['prefix'],str(env))

    def test_activation_records_exact_environment_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env=root/'env';(env/'conda-meta').mkdir(parents=True)
            conda=root/'conda';conda.touch()
            with patch('pathlib.Path.cwd',return_value=root):state=project.initialize(env)
            with patch('clusterlink.environments.publish_prepared') as publish,patch('clusterlink.environments.bundle') as build,patch.dict(os.environ,{'CONDA_EXE':str(conda)}),patch('clusterlink.project.subprocess.check_output',return_value='# conda hook'),patch('clusterlink.project.subprocess.call',return_value=0) as shell,patch('clusterlink.pool.configure'),patch('clusterlink.pool.running',return_value=False),patch('clusterlink.pool.start') as start:
                self.assertEqual(project.activate(state),0)
            build.assert_called_once_with(env, state, base=None)
            publish.assert_called_once_with(state, project.environment_selection(state), build.return_value)
            start.assert_called_once_with(state)
            script=(state/'shell.bash').read_text()
            self.assertIn('conda activate '+str(env),script)
            self.assertIn('export CONDOR_CONFIG='+str(state/'condor.config'),script)
            self.assertIn('deactivate ]; then exit',script)
            self.assertEqual(shell.call_args.args[0][-1],'-i')

    def test_missing_environment_creates_no_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('pathlib.Path.cwd',return_value=Path(tmp)),self.assertRaises(ValueError):project.initialize(Path(tmp)/'missing')
            self.assertFalse((Path(tmp)/'.clusterlink').exists())

    def test_registered_name_base_and_ambiguity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'conda';first=base/'envs/science';second=root/'other/science'
            for p in (base,first,second):(p/'conda-meta').mkdir(parents=True,exist_ok=True)
            info={'root_prefix':str(base),'envs_dirs':[str(first.parent)],'envs':[str(base),str(first),str(second)]}
            with patch('clusterlink.project.conda_executable',return_value='/conda'),patch('clusterlink.project.subprocess.check_output',return_value=json.dumps(info)):
                self.assertEqual(project.resolve_environment('science'),first)
                self.assertEqual(project.resolve_environment('base'),base)
                with self.assertRaises(ValueError):project.resolve_environment('missing')
            info['envs_dirs'].append(str(second.parent))
            with patch('clusterlink.project.conda_executable',return_value='/conda'),patch('clusterlink.project.subprocess.check_output',return_value=json.dumps(info)),self.assertRaisesRegex(ValueError,'ambiguous'):
                project.resolve_environment('science')

    def test_legacy_archive_project_is_rejected_before_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'environment.json').write_text(json.dumps({'prefix': tmp, 'backend': 'conda'}))
            with self.assertRaisesRegex(ValueError, 'fresh project'):
                project.environment_selection(root)
