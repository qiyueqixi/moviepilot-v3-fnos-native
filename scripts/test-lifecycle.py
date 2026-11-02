"""Run the real fnOS lifecycle entrypoints inside disposable Linux directories."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == 'nt', 'Lifecycle entrypoints are exercised on Linux CI')
class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='V3 lifecycle ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.volume = self.base / 'volume1'
        self.app = self.volume / '@appcenter/moviepilot-v3/target'
        self.var = self.volume / '@appdata/moviepilot-v3'
        self.etc = self.volume / '@appconf/moviepilot-v3'
        self.home = self.volume / '@apphome/moviepilot-v3'
        self.tmp = self.volume / '@apptemp/moviepilot-v3'
        self.shares = [self.volume / 'shares/moviepilot-v3' / name
                       for name in ('config', 'logs', 'exports', 'runtime')]
        self.cmd = self.base / 'package scripts/cmd'
        shutil.copytree(ROOT / 'fnos/cmd', self.cmd)
        for directory in [self.app, self.var, self.etc, self.home, self.tmp, *self.shares]:
            directory.mkdir(parents=True)
        self.env = dict(os.environ, TRIM_APPNAME='moviepilot-v3', TRIM_APPDEST=str(self.app),
                        TRIM_PKGVAR=str(self.var), TRIM_PKGETC=str(self.etc), TRIM_PKGHOME=str(self.home),
                        TRIM_PKGTMP=str(self.tmp),
                        TRIM_DATA_SHARE_PATHS=':'.join(map(str, self.shares)),
                        TRIM_DATA_ACCESSIBLE_PATHS=str(self.volume / 'media'),
                        TRIM_TEMP_LOGFILE=str(self.base / 'install result.log'),
                        TRIM_UID=str(os.getuid()), TRIM_GID=str(os.getgid()),
                        wizard_proxy='', wizard_delete_data='false', wizard_clear_app_proxy='false')
        self.make_runtime()

    def make_runtime(self, content=b'new-runtime'):
        directory = self.app / 'runtime'
        directory.mkdir(exist_ok=True)
        archive = directory / 'venv.tgz'
        with tarfile.open(archive, 'w:gz') as target:
            for name, data, mode in [('venv/native-runtime.json', content, 0o644),
                                     ('venv/bin/python3', b'#!/bin/sh\nexit 0\n', 0o755)]:
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode = len(data), mode
                target.addfile(entry, io.BytesIO(data))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (directory / 'expected.json').write_text(json.dumps({'sha256': digest}))

    def hook(self, name, success=True):
        result = subprocess.run(['bash', str(self.cmd / name)], env=self.env,
                                capture_output=True, text=True, timeout=30)
        if success:
            log = Path(self.env['TRIM_TEMP_LOGFILE']).read_text() if Path(self.env['TRIM_TEMP_LOGFILE']).exists() else ''
            self.assertEqual(result.returncode, 0, result.stderr + log)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def seed_data(self):
        for directory in [self.var, self.etc, self.home, *self.shares]:
            (directory / 'keep.db').write_text('existing application data')
        self.media = self.volume / 'media'
        self.media.mkdir(exist_ok=True)
        (self.media / 'movie.mkv').write_text('media')
        self.v2 = self.volume / '@appdata/moviepilot'
        self.v2.mkdir(parents=True, exist_ok=True)
        (self.v2 / 'keep.db').write_text('v2')

    def assert_other_data_unchanged(self):
        self.assertEqual((self.media / 'movie.mkv').read_text(), 'media')
        self.assertEqual((self.v2 / 'keep.db').read_text(), 'v2')

    def test_fresh_full_install_and_retry(self):
        for share in self.shares:
            share.rmdir()
        self.hook('install_init')
        self.hook('install_callback')
        self.assertTrue(all(p.is_dir() for p in self.shares))
        self.assertEqual((self.var / 'venv/native-runtime.json').read_bytes(), b'new-runtime')
        (self.var / 'venv/plugin-installed').touch()
        (self.shares[0] / 'user.db').write_text('db')
        self.hook('install_callback')
        self.assertTrue((self.var / 'venv/plugin-installed').exists())
        self.assertEqual((self.shares[0] / 'user.db').read_text(), 'db')

    def test_split_install_leaves_data_ready_without_runtime(self):
        (self.app / 'runtime/venv.tgz').unlink()
        self.hook('install_init')
        self.hook('install_callback')
        self.assertTrue((self.var / 'core').exists())
        self.assertFalse((self.var / 'venv').exists())

    def test_corrupt_full_install_propagates_error_and_preserves_database(self):
        self.seed_data()
        (self.app / 'runtime/venv.tgz').write_bytes(b'wrong runtime')
        self.hook('install_callback', success=False)
        log = Path(self.env['TRIM_TEMP_LOGFILE']).read_text()
        self.assertIn('SHA-256 mismatch', log)
        self.assertIn('failed', log)
        self.assertEqual((self.shares[0] / 'keep.db').read_text(), 'existing application data')

    def test_upgrade_keeps_data_and_installs_matching_runtime(self):
        self.seed_data()
        self.hook('install_callback')
        self.make_runtime(b'upgraded-runtime')
        self.hook('upgrade_init')
        self.hook('upgrade_callback')
        self.assertEqual((self.var / 'venv/native-runtime.json').read_bytes(), b'upgraded-runtime')
        self.assertEqual((self.shares[0] / 'keep.db').read_text(), 'existing application data')
        self.assert_other_data_unchanged()

    def test_keep_data_uninstall_and_reinstall(self):
        self.seed_data()
        self.hook('uninstall_init')
        self.hook('uninstall_callback')
        for directory in [self.var, self.etc, self.home, *self.shares]:
            self.assertTrue((directory / 'keep.db').exists())
        self.hook('install_callback')
        self.assertEqual((self.shares[0] / 'keep.db').read_text(), 'existing application data')
        self.assert_other_data_unchanged()

    def test_delete_uninstall_only_removes_v3_and_is_repeatable(self):
        self.seed_data()
        self.env['wizard_delete_data'] = 'true'
        self.hook('uninstall_init')
        self.hook('uninstall_callback')
        self.hook('uninstall_callback')
        for directory in [self.var, self.etc, self.home, *self.shares]:
            self.assertFalse(directory.exists(), str(directory))
        self.assert_other_data_unchanged()

    def test_symlink_to_media_aborts_before_deleting_any_data(self):
        self.seed_data()
        shutil.rmtree(self.shares[-1])
        self.shares[-1].symlink_to(self.media, target_is_directory=True)
        self.env['wizard_delete_data'] = 'true'
        self.hook('uninstall_init', success=False)
        self.assertTrue((self.var / 'keep.db').exists())
        self.assertTrue((self.shares[0] / 'keep.db').exists())
        self.assert_other_data_unchanged()

    def test_uninstall_stops_backend_frontend_and_log_mirror(self):
        self.seed_data()
        processes = []
        threads = []
        for name in ('moviepilot-v3.pid', 'moviepilot-v3-frontend.pid', 'moviepilot-v3-log-mirror.pid'):
            process = subprocess.Popen(['sleep', '120'])
            processes.append(process)
            (self.var / name).write_text(str(process.pid))
            thread = threading.Thread(target=process.wait, daemon=True)
            thread.start()
            threads.append(thread)
        try:
            self.hook('uninstall_init')
            for process, thread in zip(processes, threads):
                thread.join(timeout=5)
                self.assertIsNotNone(process.poll())
            self.assertFalse(list(self.var.glob('*.pid')))
            self.assertTrue((self.shares[0] / 'keep.db').exists())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_v2_identity_is_rejected(self):
        self.env['TRIM_APPNAME'] = 'moviepilot'
        self.hook('install_callback', success=False)

    def test_main_start_replaces_invalid_account_home_for_all_children(self):
        self.hook('install_callback')
        public = self.app / 'public'
        (public / 'node/bin').mkdir(parents=True)
        supervisor = public / 'backend-supervisor.sh'
        supervisor.write_text('#!/bin/bash\nenv > "$TRIM_PKGVAR/backend-env.txt"\nexec sleep 120\n')
        node = public / 'node/bin/node'
        node.write_text('#!/bin/bash\nenv > "$TRIM_PKGVAR/frontend-env.txt"\nexec sleep 120\n')
        node.chmod(0o755)
        self.env.update(HOME='/home/moviepilot-v3', XDG_CACHE_HOME='/not-writable',
                        CLOAKBROWSER_CACHE_DIR='/not-writable/browser')
        try:
            result = subprocess.run(['bash', str(self.cmd / 'main'), 'start'], env=self.env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            import time
            for _ in range(50):
                if all((self.var / f'{name}-env.txt').exists() for name in ('backend', 'frontend')):
                    break
                time.sleep(0.1)
            for name in ('backend', 'frontend'):
                values = dict(line.split('=', 1) for line in (self.var / f'{name}-env.txt').read_text().splitlines())
                self.assertEqual(values['HOME'], str(self.home))
                self.assertEqual(values['TMPDIR'], str(self.tmp))
                self.assertEqual(values['CLOAKBROWSER_CACHE_DIR'], str(self.home / '.cache/cloakbrowser'))
                self.assertEqual(values['PLAYWRIGHT_BROWSERS_PATH'], str(self.home / '.cache/ms-playwright'))
                self.assertTrue(Path(values['HOME']).is_dir())
                self.assertTrue(Path(values['CLOAKBROWSER_CACHE_DIR']).is_dir())
        finally:
            # Reap processes concurrently so main's kill -0 sees their exit.
            for name in ('moviepilot-v3.pid', 'moviepilot-v3-frontend.pid', 'moviepilot-v3-log-mirror.pid'):
                pidfile = self.var / name
                if pidfile.exists():
                    pid = int(pidfile.read_text())
                    try:
                        os.kill(pid, 15)
                    except ProcessLookupError:
                        pass

    def test_legacy_home_and_cache_migrate_once_without_overwriting_newer_files(self):
        (self.var / 'home/.config').mkdir(parents=True)
        (self.var / 'home/.config/settings').write_text('legacy')
        (self.var / 'cache/cloakbrowser').mkdir(parents=True)
        (self.var / 'cache/cloakbrowser/chrome').write_text('cached browser')
        (self.home / '.config').mkdir()
        (self.home / '.config/settings').write_text('newer')
        self.hook('upgrade_callback')
        self.assertEqual((self.home / '.config/settings').read_text(), 'newer')
        browser = self.home / '.cache/cloakbrowser/chrome'
        self.assertEqual(browser.read_text(), 'cached browser')
        self.assertTrue((self.var / 'cache/cloakbrowser/chrome').exists())
        browser.unlink()
        self.hook('upgrade_callback')
        self.assertFalse(browser.exists(), 'Migration must not undo a later intentional cache clear')


if __name__ == '__main__':
    unittest.main()
