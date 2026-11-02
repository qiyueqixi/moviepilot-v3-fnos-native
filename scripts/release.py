"""Merge architecture reports before the final delivered-archive verification."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
config = json.loads((ROOT / 'upstream.json').read_text())
info = {}
for arch in ('x86', 'arm'):
    part = json.loads((DIST / f'BUILD_INFO-{arch}.json').read_text())
    for key, value in config.items():
        assert part[key] == value, f'Build input mismatch: {arch}: {key}'
    assert json.loads((DIST / f'SMOKE-{arch}.json').read_text())['passed']
    assert len(json.loads((DIST / f'VALIDATION-{arch}.json').read_text())['packages']) == 2
    info[arch] = part
    for line in (DIST / f'SHA256SUMS-{arch}.txt').read_text().splitlines():
        expected, name = line.split(maxsplit=1)
        with (DIST / name).open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected, name
(DIST / 'BUILD_INFO.json').write_text(json.dumps({'resolved': config, 'architectures': info}, indent=2) + '\n')
artifacts = sorted(DIST.glob('*.fpk')) + sorted(DIST.glob('*.tgz'))
assert len(artifacts) == 6
with (DIST / 'SHA256SUMS.txt').open('w') as output:
    for path in artifacts:
        with path.open('rb') as stream:
            output.write(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}\n")
version = f"{config['version']}-{config['native_revision']}"
(DIST / 'RELEASE_NOTES.md').write_text(f'''MoviePilot V3 fnOS {version}

独立 V3 应用，可与 V2 共存。后端 v{config['version']}，配对前端 v{config['frontend']}。

- 下载对应架构的完整 `.fpk`，在飞牛应用中心手动安装或升级并保留数据。
- `_installer.fpk` 为拆分包，需将同批次对应架构的 runtime `.tgz` 上传到 `moviepilot-v3/runtime`。
- x86/ARM 均已执行包内 Python 3.14 的 Linux 安全模式启动、真实数据库用户、重启及 Cookie 测试。
- fnOS 实机安装及订阅、下载、整理等业务验收仍待完成。
- Chromium、ffmpeg、rclone 等可选工具未内置；代理沿用 MP 原生设置和网络规则。
- `SHA256SUMS.txt` 为六个二进制附件的校验值，`VALIDATION.json` 和 `BUILD_INFO.json` 记录验证范围与来源。

上游源码：{config['commit']}
''', encoding='utf-8')
(ROOT / '.build').mkdir(exist_ok=True)
