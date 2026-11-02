"""Resolve stable V3 inputs once, share that immutable plan across CI runners."""
import argparse
import ast
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def api(route):
    return json.loads(subprocess.check_output(['gh', 'api', route], text=True, encoding='utf-8'))


def stable(tag):
    if not re.fullmatch(r'v?3\.\d+\.\d+', tag):
        raise ValueError(f'Only stable V3 releases are supported: {tag}')
    return tuple(map(int, tag.removeprefix('v').split('.')))


def select(releases):
    candidates = [r for r in releases if not r.get('draft') and not r.get('prerelease')
                  and re.fullmatch(r'v?3\.\d+\.\d+', r.get('tag_name', ''))]
    return max(candidates, key=lambda r: stable(r['tag_name']))


def declared_versions(code):
    values = {}
    for node in ast.parse(code).body:
        if isinstance(node, ast.Assign):
            for name in node.targets:
                if isinstance(name, ast.Name) and name.id in ('APP_VERSION', 'FRONTEND_VERSION'):
                    values[name.id] = ast.literal_eval(node.value).removeprefix('v')
    for value in values.values():
        stable(value)
    return values['APP_VERSION'], values['FRONTEND_VERSION']


def required_assets(config):
    version = f"{config['version']}-{config['native_revision']}"
    return {f'moviepilot-v3_{version}_{arch}{suffix}.fpk' for arch in ('x86', 'arm')
            for suffix in ('', '_installer')} | {
                f'moviepilot-v3-runtime-{arch}-python314.tgz' for arch in ('x86', 'arm')
            } | {'SHA256SUMS.txt', 'BUILD_INFO.json', 'VALIDATION.json'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    config = json.loads((ROOT / 'upstream.json').read_text())
    releases = api(f"repos/{config['repository']}/releases?per_page=100")
    version = (args.version or select(releases)['tag_name']).removeprefix('v')
    stable(version)
    release = api(f"repos/{config['repository']}/releases/tags/v{version}")
    assert not release['prerelease'] and not release['draft']
    commit = api(f"repos/{config['repository']}/commits/v{version}")['sha']

    def source(name):
        data = api(f"repos/{config['repository']}/contents/{name}?ref={commit}")
        return base64.b64decode(data['content']).decode('utf-8')

    backend, frontend = declared_versions(source('version.py'))
    assert backend == version, 'Upstream source version does not match release'
    requirement = tomllib.loads(source('pyproject.toml'))['project']['requires-python']
    # This package is deliberately tied to the CPython 3.14 sites extension.
    # A changed interpreter contract requires an explicit reviewed migration.
    if requirement != '>=3.14':
        raise RuntimeError(f'Python requirement changed to {requirement}; review runtime compatibility first')
    front = api(f'repos/jxxghp/MoviePilot-Frontend/releases/tags/v{frontend}')
    assert any(a['name'] == 'dist.zip' for a in front['assets']), 'Paired frontend is not available'
    if config['version'] != version:
        config['resources_commit'] = api('repos/jxxghp/MoviePilot-Resources/commits?per_page=1')[0]['sha']
    config.update(version=version, frontend=frontend, commit=commit)
    tag = f"v{version}-fnos.{config['native_revision']}"
    repository = os.environ.get('GITHUB_REPOSITORY', 'qiyueqixi/moviepilot-v3-fnos-native')
    existing = next((r for r in api(f'repos/{repository}/releases?per_page=100') if r['tag_name'] == tag), None)
    complete = existing and required_assets(config) <= {a['name'] for a in existing['assets'] if a['state'] == 'uploaded'}
    build = bool(args.force or not complete)
    if build and existing and not existing['draft']:
        raise RuntimeError('Refusing to overwrite a published release; increase native_revision')
    (ROOT / 'upstream.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    plan = {'build': build, 'version': version, 'release_tag': tag,
            'fpk_version': f"{version}-{config['native_revision']}"}
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for key, value in plan.items():
                stream.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')
    print(json.dumps({**plan, 'inputs': config}, indent=2))


if __name__ == '__main__':
    main()
