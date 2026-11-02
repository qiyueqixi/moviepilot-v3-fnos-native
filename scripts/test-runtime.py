"""Exercise native runtime replacement on Linux without starting MoviePilot."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'fnos/cmd/runtime'


@unittest.skipIf(os.name == 'nt', 'Runtime installation runs on Linux; exercised by CI')
class RuntimeTests(unittest.TestCase):
    def setup_runtime(self, base, corrupt=False):
        root = Path(base)
        app, var = root / 'app', root / 'var'
        (app / 'runtime').mkdir(parents=True)
        (var / 'venv/bin').mkdir(parents=True)
        (var / 'venv/native-runtime.json').write_text('old')
        (var / 'venv/bin/python3').write_text('#!/bin/sh\nexit 0\n')
        (var / 'venv/bin/python3').chmod(0o755)
        archive = app / 'runtime/venv.tgz'
        if corrupt:
            archive.write_bytes(b'corrupt archive')
        else:
            with tarfile.open(archive, 'w:gz') as target:
                for name, data, mode in [('venv/native-runtime.json', b'new', 0o644), ('venv/bin/python3', b'#!/bin/sh\nexit 0\n', 0o755)]:
                    member = tarfile.TarInfo(name)
                    member.size, member.mode = len(data), mode
                    target.addfile(member, io.BytesIO(data))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (app / 'runtime/expected.json').write_text(json.dumps({'sha256': digest}))
        env = dict(os.environ, TRIM_APPDEST=str(app), TRIM_PKGVAR=str(var))
        return app, var, archive, digest, env

    def run_helper(self, command, env):
        return subprocess.run(['bash', '-c', 'source "$1"; ' + command, '--', str(HELPER)], env=env, capture_output=True, text=True)

    def test_upgrade_replaces_stale_dependencies_and_second_start_keeps_current_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            app, var, archive, digest, env = self.setup_runtime(temp)
            self.assertNotEqual(self.run_helper('runtime_is_current', env).returncode, 0)
            result = self.run_helper('runtime_install_archive "$TRIM_APPDEST/runtime/venv.tgz"', env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((var / 'venv/native-runtime.json').read_text(), 'new')
            self.assertEqual((var / '.runtime.sha256').read_text().strip(), digest)
            (var / 'venv/plugin-installed').write_text('keep')
            self.assertEqual(self.run_helper('runtime_is_current', env).returncode, 0)
            self.assertEqual(self.run_helper('runtime_install_archive "$TRIM_APPDEST/runtime/venv.tgz"', env).returncode, 0)
            self.assertTrue((var / 'venv/plugin-installed').exists())

    def test_wrong_archive_preserves_installed_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            app, var, archive, digest, env = self.setup_runtime(temp)
            archive.write_bytes(b'wrong release')
            result = self.run_helper('runtime_install_archive "$TRIM_APPDEST/runtime/venv.tgz"', env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((var / 'venv/native-runtime.json').read_text(), 'old')
            self.assertFalse((var / '.runtime.sha256').exists())

    def test_extraction_failure_preserves_installed_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            app, var, archive, digest, env = self.setup_runtime(temp, corrupt=True)
            self.assertNotEqual(self.run_helper('runtime_install_archive "$TRIM_APPDEST/runtime/venv.tgz"', env).returncode, 0)
            self.assertEqual((var / 'venv/native-runtime.json').read_text(), 'old')

    def test_lifecycle_preserves_moviepilot_proxy_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            app, var, archive, digest, env = self.setup_runtime(temp)
            archive.unlink()  # No bundled runtime required for this configuration test.
            config = Path(temp) / 'config'
            config.mkdir()
            original = b"PROXY_HOST='http://mp-setting:8080'\nOTHER=value\n"
            (config / 'app.env').write_bytes(original)
            (var / '.proxy').write_text('http://legacy-setting:8080')
            env.update(TRIM_DATA_SHARE_PATHS=str(config), TRIM_UID='0', TRIM_GID='0',
                       wizard_proxy='', wizard_clear_app_proxy='false',
                       HTTPS_PROXY='http://inherited-setting:8080')
            command = ('source "$1"; prepare_system_log() { :; }; chown() { :; }; '
                       'for hook in service_postinst service_postconfig service_postupgrade; do "$hook"; done; '
                       'printf "%s" "$HTTPS_PROXY"')
            result = subprocess.run(['bash', '-c', command, '--', str(HELPER.with_name('service-setup'))],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((config / 'app.env').read_bytes(), original)
            self.assertEqual((var / '.proxy').read_text(), 'http://legacy-setting:8080')
            self.assertEqual(result.stdout, env['HTTPS_PROXY'])

    def test_wizard_prefills_native_proxy_and_explicit_clear(self):
        with tempfile.TemporaryDirectory() as temp:
            app, var, archive, digest, env = self.setup_runtime(temp)
            archive.unlink()
            config = Path(temp) / 'config'
            config.mkdir()
            (config / 'app.env').write_text("PROXY_HOST='http://old:8080'\nOTHER=value\n")
            env.update(TRIM_DATA_SHARE_PATHS=str(config), TRIM_UID='0', TRIM_GID='0',
                       wizard_proxy='http://wizard-setting:8080', wizard_clear_app_proxy='false',
                       HTTPS_PROXY='http://inherited-setting:8080')
            script = ('source "$1"; prepare_system_log() { :; }; chown() { :; }; '
                      '"$2"; printf "%s" "$HTTPS_PROXY"')
            for hook in ['service_postinst', 'service_postconfig', 'service_postupgrade']:
                (config / 'app.env').write_text("PROXY_HOST='http://old:8080'\nOTHER=value\n")
                result = subprocess.run(['bash', '-c', script, '--',
                                         str(HELPER.with_name('service-setup')), hook],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, env['HTTPS_PROXY'])
                self.assertEqual((config / 'app.env').read_text(),
                                 "PROXY_HOST='http://wizard-setting:8080'\nOTHER=value\n")
            env.update(wizard_proxy='', wizard_clear_app_proxy='true')
            result = subprocess.run(['bash', '-c', script, '--',
                                     str(HELPER.with_name('service-setup')), 'service_postconfig'],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((config / 'app.env').read_text(), "PROXY_HOST=''\nOTHER=value\n")


if __name__ == '__main__':
    unittest.main()
