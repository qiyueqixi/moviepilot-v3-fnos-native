"""Guard major selection, frontend pairing and complete release detection."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('upstream', Path(__file__).with_name('upstream.py'))
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


class UpstreamTests(unittest.TestCase):
    def test_only_stable_v3_is_selected(self):
        releases = [{'tag_name': v, 'prerelease': pre} for v, pre in
                    [('v2.99.9', False), ('v4.0.0', False), ('v3.9.0-rc1', True),
                     ('v3.2.3', False), ('v3.2.10', False), ('v3.3.0', True)]]
        self.assertEqual(upstream.select(releases)['tag_name'], 'v3.2.10')
        for value in ('v2.15.6', 'v4.0.0', 'v3.3.0-rc1'):
            with self.assertRaises(ValueError):
                upstream.stable(value)

    def test_frontend_comes_from_backend_declaration(self):
        self.assertEqual(upstream.declared_versions("APP_VERSION='v3.2.3'\nFRONTEND_VERSION='v3.2.2'"),
                         ('3.2.3', '3.2.2'))

    def test_complete_release_needs_both_architectures_and_reports(self):
        required = upstream.required_assets({'version': '3.2.3', 'native_revision': 1})
        self.assertEqual(len(required), 9)
        self.assertIn('moviepilot-v3_3.2.3-1_arm_installer.fpk', required)
        self.assertIn('VALIDATION.json', required)


if __name__ == '__main__':
    unittest.main()
