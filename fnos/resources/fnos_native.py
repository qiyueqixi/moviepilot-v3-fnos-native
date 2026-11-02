"""fnOS integration for MoviePilot V3; upstream application services stay intact."""
from __future__ import annotations

import functools
import inspect
import os
from pathlib import Path
import secrets
import signal
import threading


def restart_backend():
    """Ask our supervisor for one graceful restart, without an fnOS CLI call."""
    marker = Path(os.environ['TRIM_PKGVAR']) / '.backend-restart'
    marker.touch(mode=0o600)
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return True, ""


def ensure_native_admin() -> None:
    """Create a real database identity on a fresh installation, once only."""
    if os.environ.get("MOVIEPILOT_NO_AUTH") != "1":
        return
    from sqlalchemy import select
    from app.db.models.user import User
    from app.db.session import SessionFactory
    from app.application.security.token import get_password_hash

    with SessionFactory() as db:
        if db.execute(select(User.id).limit(1)).first() is not None:
            return
        db.add(User(
            name="admin", hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            email="admin@localhost", is_active=True, is_superuser=True,
            is_otp=False, permissions={}, settings={}, avatar="",
        ))
        db.commit()


def authorized_roots(*, internal: bool = False) -> tuple[Path, ...]:
    filename = os.environ.get("MOVIEPILOT_ALLOWED_PATHS_FILE")
    try:
        raw = Path(filename).read_text(encoding="utf-8") if filename else os.environ.get("TRIM_DATA_ACCESSIBLE_PATHS", "")
    except OSError:
        raw = ""  # Revocation or an unreadable authorization snapshot must fail closed.
    values = raw.strip().split(":")
    if internal:
        values += [os.environ.get("CONFIG_DIR", ""), os.environ.get("TRIM_PKGVAR", "")]
    roots = []
    for value in values:
        if not value or not Path(value).is_absolute():
            continue
        try:
            root = Path(value).resolve()
        except (OSError, RuntimeError):
            continue
        if root != Path(root.anchor) and root not in roots:
            roots.append(root)
    return tuple(roots)


def path_allowed(value, *, internal: bool = True) -> bool:
    if not value:
        return False
    try:
        path = Path(value).resolve()
        return any(path == root or root in path.parents for root in authorized_roots(internal=internal))
    except (ValueError, OSError, RuntimeError, TypeError):
        return False


def require_path(value) -> None:
    if not path_allowed(value):
        raise PermissionError(f"请先在飞牛应用设置中授权此目录：{value}")


def local_storage(cls):
    """Wrap V3 operations without replacing its fsproxy, atomic copies or reflinks."""
    methods = (
        "list", "create_folder", "get_folder", "get_item", "get_item_strict",
        "detail", "delete", "rename", "download", "upload", "copy", "move",
        "link", "softlink", "reflink",
    )
    for name in methods:
        original = getattr(cls, name)
        signature = inspect.signature(original)

        def wrap(function, sig, operation):
            @functools.wraps(function)
            def guarded(self, *args, **kwargs):
                arguments = sig.bind(self, *args, **kwargs).arguments
                item = arguments.get("fileitem")
                if operation == "list" and item is not None and item.path in ("", "/"):
                    return [self._LocalStorage__get_diritem(root)
                            for root in authorized_roots() if root.is_dir()]
                if item is not None:
                    require_path(item.path)
                for key in ("path", "target_file"):
                    if arguments.get(key) is not None:
                        require_path(arguments[key])
                leaf = arguments.get("new_name") or arguments.get("name")
                if leaf:
                    if leaf in (".", "..") or "/" in leaf or "\\" in leaf:
                        raise PermissionError("文件名不能包含目录跳转")
                    parent = arguments.get("path") if operation in ("copy", "move", "upload") else Path(item.path)
                    if operation == "rename":
                        parent = parent.parent
                    require_path(Path(parent) / leaf)
                result = function(self, *args, **kwargs)
                if operation == "list":
                    return [entry for entry in result if path_allowed(entry.path)]
                return result
            return guarded
        setattr(cls, name, wrap(original, signature, name))
    return cls
