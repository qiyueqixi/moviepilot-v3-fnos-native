"""Boot the actual shipped Linux runtime and source, with isolated fresh data."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', required=True, choices=['x86', 'arm'])
    args = parser.parse_args()
    cfg = json.loads((ROOT / 'upstream.json').read_text())
    package = ROOT / 'dist' / f"moviepilot-v3_{cfg['version']}-{cfg['native_revision']}_{args.platform}_installer.fpk"
    work = ROOT / '.build/linux-smoke'
    if work.exists():
        shutil.rmtree(work)
    source = work / 'source'
    source.mkdir(parents=True)
    with tarfile.open(package, 'r:gz') as outer:
        environment = work / 'environment'
        environment.write_bytes(outer.extractfile('cmd/environment').read())
        with tarfile.open(fileobj=outer.extractfile('app.tgz'), mode='r|gz') as inner:
            inner.extractall(source, filter='data')
    runtime = ROOT / 'dist' / f'moviepilot-v3-runtime-{args.platform}-python314.tgz'
    with tarfile.open(runtime, 'r:gz') as archive:
        archive.extractall(work, filter='data')
    python = work / 'venv/bin/python3'
    config = work / 'config'
    config.mkdir()
    env = dict(os.environ, CONFIG_DIR=str(config), TRIM_PKGVAR=str(config), HOST='127.0.0.1',
               PORT='39123', NGINX_PORT='0', MOVIEPILOT_SAFE_MODE='true', MOVIEPILOT_NO_AUTH='1',
               MOVIEPILOT_AUTO_UPDATE='false', AUTO_UPDATE_RESOURCE='false', GATEWAY_PREFIX='/app/moviepilot-v3',
               MOVIEPILOT_RESOURCE_COOKIE_NAME='MoviePilotV3', PYTHON_THREAD_INHERIT_CONTEXT='0',
               PYTHONIOENCODING='utf-8', PATH=str(python.parent) + os.pathsep + os.environ['PATH'])
    env['HOME'] = '/home/moviepilot-v3'
    prepared = subprocess.check_output(['bash', '-c', 'set -e; source "$1"; prepare_native_environment; env -0',
                                        '--', str(environment)], env=env)
    env = dict(entry.split('=', 1) for entry in prepared.decode().split('\0') if entry)
    # Exercise native modules and the real SQLite CJK extension before startup.
    doctor = '''import sqlite3, ssl, lxml.etree, cryptography, greenlet, orjson, PIL.Image, psutil, zstandard, crcmod
import os
from pathlib import Path
from cloakbrowser.config import get_cache_dir
assert Path.home() == Path(os.environ['TRIM_PKGVAR']) / 'home'
assert get_cache_dir() == Path(os.environ['TRIM_PKGVAR']) / 'cache/cloakbrowser'
test = get_cache_dir() / '.write-test'; test.write_text('ok'); test.unlink()
import app.application.site.sites
c=sqlite3.connect(':memory:'); c.enable_load_extension(True); c.load_extension(%r)
print('Linux native dependency and CJK imports passed')
''' % str(work / 'venv/lib/moviepilot/libfts5_cjk.so')
    subprocess.run([python, '-c', doctor], cwd=source, env=env, check=True)
    subprocess.run([python, '-m', 'compileall', '-q', source / 'app', source / 'fnos_native.py'], check=True)

    def request(route, data=None):
        req = urllib.request.Request('http://127.0.0.1:39123' + route, data=data)
        if data is not None:
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response), response.headers

    first_id = None
    with (ROOT / '.build/linux-smoke.log').open('wb') as log:
        process = None
        try:
            for iteration in range(2):
                process = subprocess.Popen([python, '-u', '-m', 'app.main'], cwd=source, env=env,
                                           stdout=log, stderr=subprocess.STDOUT)
                for _ in range(120):
                    if process.poll() is not None:
                        raise RuntimeError(f'Backend exited {process.returncode}')
                    try:
                        request('/health/ready')
                        break
                    except Exception:
                        time.sleep(0.5)
                else:
                    raise RuntimeError('Readiness timeout')
                session, headers = request('/api/v1/login/access-token', b'username=admin&password=fnos')
                assert session['super_user'] and session['user_id'] > 0 and session['access_token']
                assert 'MoviePilotV3=' in headers['Set-Cookie']
                assert 'Path=/app/moviepilot-v3/' in headers['Set-Cookie']
                current, _ = request('/api/v1/user/current')
                assert current['data']['id'] == session['user_id'] and current['data']['is_superuser']
                request('/api/v1/system/global?token=moviepilot')
                blocked, _ = request('/api/v1/system/update/install', b'')
                assert not blocked['success'] and 'FPK' in blocked['message']
                if first_id is None:
                    first_id = session['user_id']
                    restarted, _ = request('/api/v1/system/restart')
                    assert restarted['success']
                    process.wait(timeout=15)
                    assert (config / '.backend-restart').exists()
                    (config / '.backend-restart').unlink()
                else:
                    assert session['user_id'] == first_id
                    process.terminate()
                    process.wait(timeout=15)
            report = {'passed': True, 'mode': 'safe', 'fresh_database': True, 'persistent_user_id': first_id,
                      'native_imports': True, 'sqlite_cjk': True, 'cookie_scope': True,
                      'update_guard': True, 'restart': True, 'browser_cache_writable': True,
                      'nas_installation': 'pending'}
            (ROOT / 'dist' / f'SMOKE-{args.platform}.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report))
        except Exception:
            log.flush()
            print((ROOT / '.build/linux-smoke.log').read_text(errors='replace')[-16000:])
            raise
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
