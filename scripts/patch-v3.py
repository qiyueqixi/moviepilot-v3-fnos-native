"""Apply checked, repeatable V3 patches. Never run V2 replacement rules on V3."""
from pathlib import Path
import sys


def replace(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f"V3 patch target changed: {path}: {old[:90]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def patch(root: Path):
    access = root / "app/adapters/web/security/access.py"
    replace(access, "import datetime\n", "import datetime\nimport os\n")
    replace(access, "    name=get_runtime_setting('PROJECT_NAME'),",
            '    name=os.getenv("MOVIEPILOT_RESOURCE_COOKIE_NAME") or get_runtime_setting(\'PROJECT_NAME\'),')
    replace(access, "    project_name = get_runtime_setting('PROJECT_NAME')",
            '    project_name = os.getenv("MOVIEPILOT_RESOURCE_COOKIE_NAME") or get_runtime_setting(\'PROJECT_NAME\')')
    replace(access, "        key=project_name,\n", '        key=project_name,\n        path=os.getenv("GATEWAY_PREFIX", "").rstrip("/") + "/",\n')
    replace(access, "    if jwt_token:\n", '    if os.getenv("MOVIEPILOT_NO_AUTH") == "1":\n        return _create_superuser_token_payload()\n    if jwt_token:\n')
    replace(access,
            '    return _validate_token_identity(_decode_or_http_error(resource_token, "resource"))',
            '    if os.getenv("MOVIEPILOT_NO_AUTH") == "1":\n        return _create_superuser_token_payload()\n    return _validate_token_identity(_decode_or_http_error(resource_token, "resource"))')
    composition = root / "app/startup/composition/security.py"
    replace(composition, "    users = build_transactional_user_repository()\n",
            "    from fnos_native import ensure_native_admin\n    ensure_native_admin()\n    users = build_transactional_user_repository()\n")
    login = root / "app/api/endpoints/login.py"
    replace(login, "import asyncio\n", "import asyncio\nimport os\n")
    replace(login, "    runtime_config = resolve_api_runtime_config(runtime_config)\n",
            '''    runtime_config = resolve_api_runtime_config(runtime_config)
    if os.getenv("MOVIEPILOT_NO_AUTH") == "1":
        from app.adapters.web.security.access import _create_superuser_token_payload
        payload = _create_superuser_token_payload()
        token = create_access_token(
            userid=payload.sub, username=payload.username, super_user=True,
            expires_delta=timedelta(days=3650), level=payload.level,
        )
        set_or_refresh_resource_token_cookie(request, response, payload)
        return _SchemaToken(
            access_token=token, token_type="bearer", super_user=True,
            user_id=payload.sub, user_name=payload.username,
            level=payload.level, permissions={},
        )
''')
    local = root / "app/modules/filemanager/storages/local.py"
    replace(local, "class LocalStorage(StorageBase):",
            "from fnos_native import local_storage\n\n\n@local_storage\nclass LocalStorage(StorageBase):")
    state = root / "app/runtime/state.py"
    replace(state, "        return (\n            (\n                is_docker()",
            '        if os.getenv("MOVIEPILOT_NO_AUTH") == "1":\n            return True\n        return (\n            (\n                is_docker()')
    replace(state, "        if not is_frozen() and is_windows():\n",
            '        if os.getenv("MOVIEPILOT_NO_AUTH") == "1":\n            from fnos_native import restart_backend\n            return restart_backend()\n        if not is_frozen() and is_windows():\n')
    system = root / "app/api/endpoints/system.py"
    for statement in (
        "    result = runtime.system.upgrade(mode)",
        '    result = runtime.system.download_update(request.target if request else "application")',
        '    result = runtime.system.install_update(request.target if request else "application")',
    ):
        replace(system, statement,
                '    from os import getenv\n    if getenv("MOVIEPILOT_NO_AUTH") == "1":\n'
                '        return _SchemaResponse(success=False, message="请在飞牛应用中心安装 MoviePilot V3 的 FPK 更新包。")\n' + statement)


if __name__ == "__main__":
    patch(Path(sys.argv[1]))
