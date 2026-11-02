"""Exercise real V3 file operations at the fnOS authorization boundary."""
import ast
from enum import Enum
import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fnos_native', ROOT / 'fnos/resources/fnos_native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeStorageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.allowed = self.base / 'media'
        self.denied = self.base / 'private'
        self.allowed.mkdir()
        self.denied.mkdir()
        self.secret = self.denied / 'secret.txt'
        self.secret.write_text('private data')
        self.addCleanup(patch.stopall)
        patch.object(native, 'authorized_roots', return_value=(self.allowed.resolve(),)).start()
        tree = ast.parse((ROOT / '.build/source/app/modules/filemanager/storages/local.py').read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'LocalStorage')
        # Execute the actual patched class, replacing its external I/O collaborators.
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[])
        ast.fix_missing_locations(module)
        class Schema(Enum):
            Local = 'local'
        def stat(path):
            info = Path(path).stat()
            return {'mtime': info.st_mtime, 'size': info.st_size, 'is_file': Path(path).is_file(), 'dev': info.st_dev, 'ino': info.st_ino}
        namespace = {
            'local_storage': native.local_storage, 'StorageBase': object, 'StorageSchema': Schema,
            'Path': Path, '_SchemaFileItem': SimpleNamespace, 'transfer_process': lambda f: f,
            'fsproxy': SimpleNamespace(stat=stat),
            'SystemUtils': SimpleNamespace(is_windows=lambda: os.name == 'nt',
                list_sub_directory=lambda p: [x for x in p.iterdir() if x.is_dir()],
                list_sub_file=lambda p: [x for x in p.iterdir() if x.is_file()]),
            'logger': SimpleNamespace(debug=lambda *a: None, warn=lambda *a: None),
        }
        exec(compile(module, '<actual V3 LocalStorage>', 'exec'), namespace)
        self.storage = namespace['LocalStorage']()

    def test_root_listing_only_returns_authorized_roots(self):
        items = self.storage.list(SimpleNamespace(path='/'))
        self.assertEqual([Path(x.path) for x in items], [self.allowed])

    def test_read_and_mutation_cannot_escape_authorized_roots(self):
        item = SimpleNamespace(path=str(self.secret))
        for name, args in [('detail', (item,)), ('delete', (item,)), ('download', (item,)),
                           ('copy', (item, self.allowed, 'copy.txt')),
                           ('move', (item, self.allowed, 'moved.txt')),
                           ('link', (item, self.allowed / 'link.txt'))]:
            with self.subTest(operation=name), self.assertRaises(PermissionError):
                getattr(self.storage, name)(*args)
        self.assertEqual(self.secret.read_text(), 'private data')

    def test_target_name_cannot_traverse_outside_authorization(self):
        item = SimpleNamespace(path=str(self.allowed))
        with self.assertRaises(PermissionError):
            self.storage.create_folder(item, '../private/created')
        with self.assertRaises(PermissionError):
            self.storage.get_folder(self.denied / 'created')
        self.assertFalse((self.denied / 'created').exists())

    def test_authorization_is_rechecked_after_revocation(self):
        self.assertTrue(native.path_allowed(self.allowed / 'movie.mkv'))
        with patch.object(native, 'authorized_roots', return_value=()):
            with self.assertRaises(PermissionError):
                self.storage.get_item(self.allowed / 'movie.mkv')

    def test_symlink_target_outside_authorization_is_rejected(self):
        link = self.allowed / 'outside'
        try:
            link.symlink_to(self.denied, target_is_directory=True)
        except OSError:
            self.skipTest('Windows host does not allow creating test symlinks')
        with self.assertRaises(PermissionError):
            self.storage.get_item(link / 'secret.txt')
        self.assertEqual(self.storage.list(SimpleNamespace(path=str(self.allowed))), [])


if __name__ == '__main__':
    unittest.main()
