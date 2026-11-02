"""Optional real V3 startup test on Windows with isolated test data and dependencies."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / '.build/smoke-source'
    if not (source / 'app/application/site/sites.cp314-win_amd64.pyd').exists():
        raise RuntimeError('Prepare the isolated Windows smoke source and sites resource first')
    config = ROOT / '.build/smoke-config'
    config.mkdir(exist_ok=True)
    python = ROOT / '.build/python-windows/cpython-3.14.10-windows-x86_64-none/python.exe'
    env = dict(os.environ, PYTHONPATH=str(ROOT / '.build/deps-win') + os.pathsep + str(source),
               CONFIG_DIR=str(config), TRIM_PKGVAR=str(config), HOST='127.0.0.1', PORT='39123', NGINX_PORT='0',
               MOVIEPILOT_SAFE_MODE='true', MOVIEPILOT_NO_AUTH='1', MOVIEPILOT_AUTO_UPDATE='false',
               AUTO_UPDATE_RESOURCE='false', GATEWAY_PREFIX='/app/moviepilot-v3',
               MOVIEPILOT_RESOURCE_COOKIE_NAME='MoviePilotV3', PYTHON_THREAD_INHERIT_CONTEXT='0',
               PYTHONIOENCODING='utf-8')
    base = 'http://127.0.0.1:39123'

    def request(route, data=None):
        req = urllib.request.Request(base + route, data=data)
        if data is not None:
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response), response.headers

    def start(log):
        process = subprocess.Popen([str(python), '-u', '-m', 'app.main'], cwd=source, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f'Backend exited {process.returncode}; see .build/smoke-backend.log')
            try:
                request('/health/ready')
                return process
            except Exception:
                time.sleep(0.5)
        process.kill()
        process.wait()
        raise RuntimeError('Readiness timeout')

    def stop(process):
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    first_id = None
    with (ROOT / '.build/smoke-backend.log').open('wb') as log:
        process = None
        try:
            for iteration in range(2):
                process = start(log)
                session, headers = request('/api/v1/login/access-token', b'username=admin&password=fnos')
                assert session['super_user'] and session['user_id'] > 0 and session['access_token']
                assert 'MoviePilotV3=' in headers['Set-Cookie']
                assert 'Path=/app/moviepilot-v3/' in headers['Set-Cookie']
                current, _ = request('/api/v1/user/current')
                current = current['data']
                assert current['id'] == session['user_id']
                assert current['is_superuser']
                request('/api/v1/system/global?token=moviepilot')
                blocked, _ = request('/api/v1/system/update/install', b'')
                assert blocked['success'] is False and 'FPK' in blocked['message']
                if first_id is None:
                    first_id = session['user_id']
                    restarted, _ = request('/api/v1/system/restart')
                    assert restarted['success']
                    process.wait(timeout=10)
                    assert (config / '.backend-restart').exists()
                    (config / '.backend-restart').unlink()
                else:
                    assert session['user_id'] == first_id
                    summary = {key: session[key] for key in ['user_id', 'user_name', 'super_user', 'level']}
                    (ROOT / '.build/smoke-result.json').write_text(json.dumps(summary) + '\n', encoding='utf-8')
                    print('Windows V3 safe-mode startup, real database user, persistent identity, Cookie scope, update guard and restart tests passed')
                stop(process)
        finally:
            stop(process)


if __name__ == '__main__':
    main()
