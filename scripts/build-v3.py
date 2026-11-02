#!/usr/bin/env python3
"""Build standalone fnOS V3 packages on Windows or Linux (no Docker runtime)."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / '.build'
DOWNLOADS = BUILD / 'downloads'
FNOS = ROOT / 'fnos'
CONFIG = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
CPUS = {'x86': 'x86_64', 'arm': 'aarch64'}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, name):
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    path = DOWNLOADS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'moviepilot-v3-fnos-builder'})
            with urllib.request.urlopen(request, timeout=60) as response, path.with_suffix('.part').open('wb') as target:
                shutil.copyfileobj(response, target)
            path.with_suffix('.part').replace(path)
            print(f'Downloaded {name}', flush=True)
            return path
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2)


def run(command, **kwargs):
    subprocess.run(list(map(str, command)), check=True, **kwargs)


def normalize(member):
    member.uid = member.gid = 0
    member.uname = member.gname = 'root'
    executable = member.name.startswith(('cmd/', 'public/node/bin/', 'venv/bin/'))
    member.mode = 0o755 if member.isdir() or executable or member.mode & 0o111 else 0o644
    return member


def add_bytes(archive, name, data, mode=0o644):
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mode = mode
    archive.addfile(member, io.BytesIO(data))


def verify_elf(data, platform, name):
    if not data.startswith(b'\x7fELF'):
        raise ValueError(f'Expected a Linux ELF binary: {name}')
    machine = int.from_bytes(data[18:20], 'little')
    if machine != {'x86': 62, 'arm': 183}[platform]:
        raise ValueError(f'Wrong ELF architecture: {name}: {machine}')
    versions = {tuple(map(int, v.split(b'.'))) for v in re.findall(rb'GLIBC_(\d+\.\d+)', data)}
    if any(v > (2, 36) for v in versions):
        raise ValueError(f'Requires a newer libc than Debian 12: {name}: {sorted(versions)}')


def prepare_source():
    source = BUILD / 'source'
    reference = ROOT / '.reference/MoviePilot'
    if not reference.exists():
        run(['git', 'clone', '--depth', '1', '--branch', f"v{CONFIG['version']}",
             f"https://github.com/{CONFIG['repository']}.git", reference])
    commit = subprocess.check_output(['git', '-C', str(reference), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != CONFIG['commit']:
        run(['git', '-C', reference, 'fetch', '--depth', '1', 'origin', CONFIG['commit']])
        run(['git', '-C', reference, 'checkout', '--detach', CONFIG['commit']])
        if subprocess.check_output(['git', '-C', str(reference), 'rev-parse', 'HEAD'], text=True).strip() != CONFIG['commit']:
            raise ValueError('Upstream checkout does not match upstream.json')
    fingerprint = json.dumps(CONFIG, sort_keys=True)
    stamp = BUILD / 'source-inputs.json'
    if source.exists() and (not stamp.exists() or stamp.read_text() != fingerprint):
        shutil.rmtree(source)
    if not source.exists():
        shutil.copytree(reference, source, ignore=shutil.ignore_patterns('.git', '.github', 'tests', '__pycache__'))
        stamp.write_text(fingerprint)
    proxy_files = ['app/runtime/config.py', 'app/adapters/network/http.py', 'app/modules/bangumi/bangumi.py']
    provenance = {**CONFIG, 'proxy_defaults_sha256': {name: sha256(reference / name) for name in proxy_files}}
    run([os.sys.executable, ROOT / 'scripts/patch-v3.py', source])
    for name in proxy_files:
        if sha256(source / name) != provenance['proxy_defaults_sha256'][name]:
            raise ValueError(f'Upstream proxy behavior modified: {name}')
    (source / 'native-upstream.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(FNOS / 'resources/fnos_native.py', source / 'fnos_native.py')
    return source


def prepare_public():
    public = BUILD / 'public'
    stamp = BUILD / 'frontend-version.txt'
    if public.exists() and (not stamp.exists() or stamp.read_text() != CONFIG['frontend']):
        shutil.rmtree(public)
    if not public.exists():
        frontend = download(f"https://github.com/jxxghp/MoviePilot-Frontend/releases/download/v{CONFIG['frontend']}/dist.zip", f"frontend-{CONFIG['frontend']}.zip")
        with zipfile.ZipFile(frontend) as archive:
            for name in archive.namelist():
                path = Path(name)
                if path.is_absolute() or '..' in path.parts or not name.startswith('dist/'):
                    raise ValueError(f'Unexpected frontend entry: {name}')
            archive.extractall(BUILD / 'frontend')
        shutil.copytree(BUILD / 'frontend/dist', public)
        stamp.write_text(CONFIG['frontend'])
    index = public / 'index.html'
    text = index.read_text(encoding='utf-8')
    script = '<script src="./no-auth.js"></script>'
    if script not in text:
        if not re.search(r'(?m)^\s*<head>\s*$', text):
            raise ValueError('Frontend head changed')
        text = text.replace('<head>', '<head>' + script, 1)
        index.write_text(text, encoding='utf-8', newline='\n')
    for name in ['service.js', 'no-auth.js', 'backend-supervisor.sh', 'loading-background.jpg']:
        shutil.copy2(FNOS / 'resources' / name, public / name)
    shutil.copy2(FNOS / 'package.json', public / 'package.json')
    lock = FNOS / 'package-lock.json'
    if lock.exists():
        shutil.copy2(lock, public / lock.name)
    npm = shutil.which('npm.cmd') or shutil.which('npm')
    run([npm, 'ci' if lock.exists() else 'install', '--omit=dev', '--ignore-scripts', '--no-fund', '--no-audit'], cwd=public)
    if not lock.exists():
        shutil.copy2(public / 'package-lock.json', lock)
    return public


def prepare_deps(source, platform, uv):
    requirements = BUILD / 'requirements-v3.txt'
    run([uv, 'export', '--project', source, '--frozen', '--no-dev', '--group', 'runtime-standard',
         '--no-emit-project', '--format', 'requirements-txt', '--output-file', requirements], stdout=subprocess.DEVNULL)
    target = BUILD / f'deps-{platform}'
    if target.exists():
        shutil.rmtree(target)
    run([uv, 'pip', 'install', '--target', target, '--python-version', '3.14',
         '--python-platform', f'{CPUS[platform]}-manylinux_2_36', '--link-mode', 'copy',
         '--require-hashes', '--no-deps', '-r', requirements])
    return target


def build_runtime(deps, platform):
    cpu = CPUS[platform]
    release = CONFIG['python_release']
    python = download(f"https://github.com/astral-sh/python-build-standalone/releases/download/{release}/cpython-{CONFIG['python']}%2B{release}-{cpu}-unknown-linux-gnu-install_only_stripped.tar.gz", f"python-{CONFIG['python']}-{release}-{platform}.tgz")
    runtime = FNOS / 'runtime' / f'venv-runtime-{platform}.tgz'
    runtime.parent.mkdir(exist_ok=True)
    native_count = 0
    temporary_runtime = runtime.with_suffix('.incomplete')
    with tarfile.open(temporary_runtime, 'w:gz', compresslevel=6) as target:
        with tarfile.open(python, 'r:gz') as archive:
            for member in archive:
                if not member.name.startswith('python/') or '..' in Path(member.name).parts:
                    raise ValueError(f'Unexpected Python archive path: {member.name}')
                member.name = 'venv/' + member.name[len('python/'):]
                if member.isfile():
                    data = archive.extractfile(member).read()
                    if data.startswith(b'\x7fELF'):
                        verify_elf(data, platform, member.name)
                    target.addfile(normalize(member), io.BytesIO(data))
                else:
                    target.addfile(normalize(member))
        for path in sorted(deps.rglob('*')):
            relative = path.relative_to(deps)
            if relative.parts[0] == 'bin' or '__pycache__' in relative.parts or path.suffix == '.pyc' or not path.is_file():
                continue  # uv on Windows generates Windows launchers; regenerate Linux ones below.
            data = path.read_bytes()
            if relative.parts[:2] == ('discord', 'bin') and path.suffix == '.dll':
                continue  # The universal discord.py wheel also ships unused Windows Opus DLLs.
            if relative.parts[0] == 'setuptools' and path.suffix == '.exe':
                continue  # Universal setuptools wheels include Windows launcher templates.
            if data.startswith(b'\x7fELF'):
                verify_elf(data, platform, relative)
                native_count += 1
            elif path.suffix in ('.pyd', '.dll', '.exe'):
                raise ValueError(f'Windows binary in Linux dependencies: {relative}')
            mode = 0o755 if data.startswith(b'\x7fELF') and path.suffix != '.so' else 0o644
            add_bytes(target, f'venv/lib/python3.14/site-packages/{relative.as_posix()}', data, mode)
        for dist in importlib.metadata.distributions(path=[str(deps)]):
            for entry in dist.entry_points:
                if entry.group != 'console_scripts' or '/' in entry.name or '\\' in entry.name:
                    continue
                module, function = entry.value.split(':', 1)
                function = function.split('[')[0].strip()
                launcher = ('#!/bin/sh\n\'\'\'exec\' "$(dirname "$0")/python3" "$0" "$@"\n\' \'\'\'\n'
                            f'import importlib, sys\nvalue = importlib.import_module({module!r})\n'
                            f'for part in {function!r}.split("."): value = getattr(value, part)\nsys.exit(value())\n')
                add_bytes(target, f'venv/bin/{entry.name}', launcher.encode(), 0o755)
        cjk = BUILD / f'libfts5_cjk-{platform}.so'
        if not cjk.is_file():
            raise ValueError(f'Compile the V3 CJK extension first: {cjk}')
        verify_elf(cjk.read_bytes(), platform, cjk)
        target.add(cjk, arcname='venv/lib/moviepilot/libfts5_cjk.so', filter=normalize)
        metadata = {'python': CONFIG['python'], 'architecture': platform,
                    'requirements_sha256': sha256(BUILD / 'requirements-v3.txt'),
                    'python_archive_sha256': sha256(python), 'native_elf_count': native_count}
        add_bytes(target, 'venv/native-runtime.json', json.dumps(metadata, indent=2).encode())
    temporary_runtime.replace(runtime)
    print(f'Built {runtime.name}: {native_count} native dependency binaries checked', flush=True)
    return runtime


def compile_cjk(source, platform, zig):
    output = BUILD / f'libfts5_cjk-{platform}.so'
    directory = source / 'native/fts5_cjk'
    run([zig, 'cc', '-target', f'{CPUS[platform]}-linux-gnu.2.28', '-shared', '-fPIC', '-O2',
         '-Wall', '-Wextra', '-I', directory / 'vendor', directory / 'fts5_cjk.c', '-o', output])


def build_app(source, public, runtime, platform, full):
    cpu = CPUS[platform]
    resources_ref = CONFIG['resources_commit']
    sites = f'sites.cpython-314-{cpu}-linux-gnu.so'
    resource_files = [download(f'https://raw.githubusercontent.com/jxxghp/MoviePilot-Resources/{resources_ref}/resources.v3/{name}', f'{resources_ref}/{name}')
                      for name in [sites, 'user.sites.v3.bin']]
    verify_elf(resource_files[0].read_bytes(), platform, sites)
    node_arch = 'x64' if platform == 'x86' else 'arm64'
    node = download(f"https://nodejs.org/dist/v{CONFIG['node']}/node-v{CONFIG['node']}-linux-{node_arch}.tar.xz", f"node-{CONFIG['node']}-{platform}.tar.xz")
    app_archive = BUILD / f'app-{platform}-{"full" if full else "installer"}.tgz'
    with tarfile.open(app_archive, 'w:gz', compresslevel=6) as target:
        for path in sorted(source.iterdir()):
            if path.name.startswith('.') or path.name in ('docker', 'frontend-dist'):
                continue
            target.add(path, arcname=path.name, filter=lambda m: None if '__pycache__' in Path(m.name).parts else normalize(m))
        target.add(public, arcname='public', filter=lambda m: None if '__pycache__' in Path(m.name).parts else normalize(m))
        target.add(FNOS / 'ui', arcname='ui', filter=normalize)
        for path in resource_files:
            target.add(path, arcname=f'app/application/site/{path.name}', filter=normalize)
        with tarfile.open(node, 'r:xz') as archive:
            for member in archive:
                name = member.name.partition('/')[2]
                if not name or name.startswith(('include/', 'share/')):
                    continue
                member.name = 'public/node/' + name
                if member.isfile():
                    data = archive.extractfile(member).read()
                    if name == 'bin/node':
                        verify_elf(data, platform, 'Node.js')
                    target.addfile(normalize(member), io.BytesIO(data))
                else:
                    target.addfile(normalize(member))
        metadata = {'python': CONFIG['python'], 'platform': platform, 'sha256': sha256(runtime)}
        add_bytes(target, 'runtime/expected.json', json.dumps(metadata).encode())
        if full:
            target.add(runtime, arcname='runtime/venv.tgz', filter=normalize)
    return app_archive


def build_fpk(app, platform, full):
    version = f"{CONFIG['version']}-{CONFIG['native_revision']}"
    suffix = '' if full else '_installer'
    output = ROOT / 'dist' / f'moviepilot-v3_{version}_{platform}{suffix}.fpk'
    output.parent.mkdir(exist_ok=True)
    values = {}
    for line in (FNOS / 'manifest').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    with app.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'md5').hexdigest()
    values.update(version=version, platform=platform, checksum=checksum)
    manifest = '\n'.join(f'{key} = {value}' for key, value in values.items()) + '\n'
    with tarfile.open(output, 'w:gz', compresslevel=6) as target:
        add_bytes(target, 'manifest', manifest.encode('utf-8'))
        for name in ['ICON.PNG', 'ICON_256.PNG', 'LICENSE', 'LICENSE.en', 'cmd', 'config', 'wizard']:
            target.add(FNOS / name, arcname=name, filter=normalize)
        target.add(app, arcname='app.tgz', filter=normalize)
    print(f'Built {output}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=['x86', 'arm', 'all'], default='all')
    parser.add_argument('--uv', default=shutil.which('uv') or str(BUILD / 'tools/uv.exe'))
    parser.add_argument('--reuse-runtime', action='store_true')
    parser.add_argument('--zig', default=shutil.which('zig') or str(BUILD / 'tools/zig-npm/package/zig.exe'))
    args = parser.parse_args()
    if CONFIG['supported_major'] != 3 or not CONFIG['version'].startswith('3.'):
        raise ValueError('This project builds V3 only')
    for path in [*(FNOS / 'cmd').iterdir(), FNOS / 'resources/backend-supervisor.sh']:
        if b'\r' in path.read_bytes():
            raise ValueError(f'Linux lifecycle scripts must use LF line endings: {path}')
    source = prepare_source()
    public = prepare_public()
    platforms = CPUS if args.platform == 'all' else [args.platform]
    for platform in platforms:
        runtime = FNOS / 'runtime' / f'venv-runtime-{platform}.tgz'
        if not args.reuse_runtime or not runtime.exists():
            compile_cjk(source, platform, args.zig)
            runtime = build_runtime(prepare_deps(source, platform, args.uv), platform)
        for full in (True, False):
            build_fpk(build_app(source, public, runtime, platform, full), platform, full)
        shutil.copy2(runtime, ROOT / 'dist' / f'moviepilot-v3-runtime-{platform}-python314.tgz')
    artifacts = sorted((ROOT / 'dist').glob('*.fpk')) + sorted((ROOT / 'dist').glob('*.tgz'))
    (ROOT / 'dist/SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in artifacts), encoding='utf-8')
    info = {**CONFIG, 'inputs': {p.relative_to(DOWNLOADS).as_posix(): sha256(p) for p in DOWNLOADS.rglob('*') if p.is_file() and p.suffix != '.part'},
            'validation': 'See VALIDATION.json for archive checks; NAS installation test pending.'}
    (ROOT / 'dist/BUILD_INFO.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
