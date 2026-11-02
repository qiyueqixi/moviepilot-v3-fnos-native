"""Apply real config callbacks while an existing backend reads authorization."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fnos_native', ROOT / 'fnos/resources/fnos_native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
BASH = shutil.which('bash') or r'C:\Program Files\Git\bin\bash.exe'


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fnos grants ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.var = self.base / 'var'
        self.var.mkdir()
        self.snapshot = self.var / '.accessible_paths'
        self.first = self.base / 'existing media'
        self.second = self.base / 'new downloads'
        self.first.mkdir()
        self.second.mkdir()
        self.env = dict(os.environ, TRIM_PKGVAR=self.var.as_posix(),
                        TRIM_DATA_ACCESSIBLE_PATHS='', wizard_proxy='', wizard_clear_app_proxy='false')
        if os.name != 'nt':
            self.env.update(TRIM_UID=str(os.getuid()), TRIM_GID=str(os.getgid()))
        self.patch = patch.dict(os.environ, MOVIEPILOT_ALLOWED_PATHS_FILE=str(self.snapshot),
                                TRIM_PKGVAR=str(self.var), CONFIG_DIR=str(self.base / 'config'))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def configure(self, paths):
        self.env['TRIM_DATA_ACCESSIBLE_PATHS'] = ':'.join(p.as_posix() for p in paths)
        # Test fixtures on Windows use MSYS paths for fnOS's colon separator.
        windows = os.name == 'nt'
        if windows:
            self.env['TRIM_DATA_ACCESSIBLE_PATHS'] = ':'.join('/' + p.drive[0].lower() + p.as_posix()[2:] for p in paths)
        command = 'source "$1"; service_postconfig'
        result = subprocess.run([BASH, '-c', command, '--', (ROOT / 'fnos/cmd/service-setup').as_posix()],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(os.name == 'nt', 'fnOS absolute paths use Linux colon-separated grants')
    def test_grants_and_revocations_apply_to_same_running_backend(self):
        self.configure([self.first])
        self.assertTrue(native.path_allowed(self.first / 'movie.mkv'))
        self.assertFalse(native.path_allowed(self.second / 'movie.mkv'))
        self.configure([self.first, self.second])
        self.assertTrue(native.path_allowed(self.second / 'movie.mkv'))
        self.configure([self.second])
        self.assertFalse(native.path_allowed(self.first / 'movie.mkv'))
        self.assertTrue(native.path_allowed(self.second / 'movie.mkv'))
        self.configure([])
        self.assertEqual(native.authorized_roots(), ())
        self.assertFalse(native.path_allowed(self.second / 'movie.mkv'))

    def test_callback_replaces_snapshot_and_preserves_proxy_config(self):
        self.snapshot.write_text('old authorization')
        config = self.base / 'config'
        config.mkdir()
        app_env = config / 'app.env'
        app_env.write_text("PROXY_HOST='http://existing:8080'\n")
        self.env['TRIM_DATA_SHARE_PATHS'] = config.as_posix()
        self.configure([self.first, self.second])
        self.assertIn('new downloads', self.snapshot.read_text())
        self.assertEqual(list(self.var.glob('.accessible_paths.*')), [])
        self.assertEqual(app_env.read_text(), "PROXY_HOST='http://existing:8080'\n")
        if os.name != 'nt':
            self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.snapshot.stat().st_uid, os.getuid())
        self.configure([])
        self.assertEqual(self.snapshot.read_text(), '')


if __name__ == '__main__':
    unittest.main()
