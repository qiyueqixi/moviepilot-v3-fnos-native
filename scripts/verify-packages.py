"""Validate the delivered FPK archives, rather than only the build workspace."""
import hashlib
import argparse
import ast
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'upstream.json').read_text())
VERSION = f"{CONFIG['version']}-{CONFIG['native_revision']}"


def read(archive, name):
    return archive.extractfile(name).read()


def digest(stream, algorithm='sha256'):
    return hashlib.file_digest(stream, algorithm).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=['all', 'x86', 'arm'], default='all')
    args = parser.parse_args()
    results = []
    for platform, cpu in [('x86', 'x86_64'), ('arm', 'aarch64')]:
        if args.platform not in ('all', platform):
            continue
        runtime = ROOT / 'dist' / f'moviepilot-v3-runtime-{platform}-python314.tgz'
        with runtime.open('rb') as stream:
            runtime_hash = digest(stream)
        with tarfile.open(runtime, 'r:gz') as archive:
            metadata = json.loads(read(archive, 'venv/native-runtime.json'))
            assert metadata['python'] == CONFIG['python'] and metadata['architecture'] == platform
            python = read(archive, 'venv/bin/python3.14')
            assert python[:4] == b'\x7fELF'
            assert int.from_bytes(python[18:20], 'little') == {'x86': 62, 'arm': 183}[platform]
            assert archive.getmember('venv/bin/python').linkname == 'python3.14'
            names = archive.getnames()
            assert not any(name.endswith(('.exe', '.dll', '.pyd')) and
                           not name.startswith('venv/lib/python3.14/site-packages/pip/_vendor/distlib/')
                           for name in names)
            assert 'venv/lib/moviepilot/libfts5_cjk.so' in names
        for suffix in ['', '_installer']:
            package = ROOT / 'dist' / f'moviepilot-v3_{VERSION}_{platform}{suffix}.fpk'
            with tempfile.TemporaryDirectory(prefix='verify-', dir=ROOT / '.build') as temporary:
                inner = Path(temporary) / 'app.tgz'
                with tarfile.open(package, 'r:gz') as archive:
                    manifest = dict(line.split(' = ', 1) for line in read(archive, 'manifest').decode('utf-8-sig').splitlines())
                    assert manifest['appname'] == 'moviepilot-v3'
                    assert manifest['version'] == VERSION and manifest['platform'] == platform
                    privilege = json.loads(read(archive, 'config/privilege'))
                    assert privilege['defaults']['run-as'] == 'package'
                    assert privilege['username'] == privilege['groupname'] == 'moviepilot-v3'
                    resources = json.loads(read(archive, 'config/resource'))
                    assert {item['name'] for item in resources['data-share']['shares']} == {
                        'moviepilot-v3/config', 'moviepilot-v3/logs', 'moviepilot-v3/exports', 'moviepilot-v3/runtime'}
                    main = read(archive, 'cmd/main').decode()
                    assert 'PORT="3101"' in main and 'GATEWAY_PREFIX="/app/moviepilot-v3"' in main
                    for member in archive:
                        if member.isfile() and member.name.startswith('cmd/'):
                            assert b'\r' not in archive.extractfile(member).read(), member.name
                    with inner.open('wb') as output:
                        shutil.copyfileobj(archive.extractfile('app.tgz'), output)
                with inner.open('rb') as stream:
                    assert digest(stream, 'md5') == manifest['checksum']
                with tarfile.open(inner, 'r:gz') as app:
                    names = app.getnames()
                    assert ('runtime/venv.tgz' in names) == (suffix == '')
                    expected = json.loads(read(app, 'runtime/expected.json'))
                    assert expected['sha256'] == runtime_hash and expected['platform'] == platform
                    if suffix == '':
                        assert digest(app.extractfile('runtime/venv.tgz')) == runtime_hash
                    provenance = json.loads(read(app, 'native-upstream.json'))
                    for key in ('version', 'commit', 'frontend', 'resources_commit', 'python'):
                        assert provenance[key] == CONFIG[key], key
                    for name, expected_hash in provenance['proxy_defaults_sha256'].items():
                        assert hashlib.sha256(read(app, name)).hexdigest() == expected_hash, name
                    versions = {node.targets[0].id: ast.literal_eval(node.value)
                                for node in ast.parse(read(app, 'version.py')).body
                                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                                and node.targets[0].id in ('APP_VERSION', 'FRONTEND_VERSION')}
                    assert versions['APP_VERSION'] == 'v' + CONFIG['version']
                    assert versions['FRONTEND_VERSION'] == 'v' + CONFIG['frontend']
                    for name in ['fnos_native.py', 'app/adapters/web/security/access.py',
                                 'app/api/endpoints/login.py', 'app/modules/filemanager/storages/local.py',
                                 'app/runtime/state.py', 'app/api/endpoints/system.py']:
                        reference = ROOT / '.build/source' / name
                        if reference.exists():
                            assert read(app, name) == reference.read_bytes(), name
                    assert read(app, 'fnos_native.py') == (ROOT / 'fnos/resources/fnos_native.py').read_bytes()
                    for name in ['service.js', 'no-auth.js', 'backend-supervisor.sh']:
                        assert read(app, 'public/' + name) == (ROOT / 'fnos/resources' / name).read_bytes()
                    assert b'\r' not in read(app, 'public/backend-supervisor.sh')
                    ui = json.loads(read(app, 'ui/config'))['.url']['moviepilot-v3.Application']
                    assert ui['gatewayPrefix'] == '/app/moviepilot-v3'
                    assert ui['gatewaySocket'] == 'moviepilot-v3.sock'
                    sites = [name for name in names if '/sites.' in name and name.endswith('.so')]
                    assert sites == [f'app/application/site/sites.cpython-314-{cpu}-linux-gnu.so'], sites
                    assert 'app/application/site/user.sites.v3.bin' in names
                    assert not any(name.endswith('.pyd') or 'user.sites.v2.bin' in name for name in names)
                    assert 'src="./no-auth.js"' in read(app, 'public/index.html').decode()
            results.append({'name': package.name, 'bytes': package.stat().st_size, 'passed': True})
            print('Verified', package.name, flush=True)
    for line in (ROOT / 'dist/SHA256SUMS.txt').read_text().splitlines():
        expected, name = line.split(maxsplit=1)
        with (ROOT / 'dist' / name).open('rb') as stream:
            assert digest(stream) == expected, name
    report = {'packages': results, 'runtime_architecture': 'passed', 'manifest_and_inner_md5': 'passed',
              'release_sha256': 'passed', 'linux_lifecycle_line_endings': 'passed', 'nas_installation': 'pending'}
    smoke = ROOT / '.build/smoke-result.json'
    if smoke.exists():
        report['windows_backend_safe_mode'] = {'passed': True, 'identity': json.loads(smoke.read_text())}
    for platform in ('x86', 'arm'):
        smoke = ROOT / 'dist' / f'SMOKE-{platform}.json'
        if smoke.exists():
            report[f'linux_backend_{platform}'] = json.loads(smoke.read_text())
    name = 'VALIDATION.json' if args.platform == 'all' else f'VALIDATION-{args.platform}.json'
    (ROOT / 'dist' / name).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('All delivered packages and SHA-256 checksums passed')


if __name__ == '__main__':
    main()
