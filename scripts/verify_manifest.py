"""Verify the original distribution files without modifying the workspace."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys


def verify(root):
    root = Path(root).resolve()
    errors = []
    checked = 0
    seen = set()
    try:
        lines = (root / 'MANIFEST.sha256').read_text(encoding='utf-8-sig').splitlines()
    except (OSError, UnicodeError) as error:
        return 0, [f'无法读取 MANIFEST.sha256：{error}']
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        match = re.fullmatch(r'([0-9a-fA-F]{64}) [ *](.+)', line)
        if not match:
            errors.append(f'清单第 {number} 行格式错误。')
            continue
        expected, name = match.groups()
        relative = PurePosixPath(name)
        key = name.casefold()
        if (relative.is_absolute() or PureWindowsPath(name).drive or '\\' in name
                or '..' in relative.parts or name in {'.', 'MANIFEST.sha256'}):
            errors.append(f'清单第 {number} 行路径无效：{name}')
            continue
        if key in seen:
            errors.append(f'清单第 {number} 行重复列出文件：{name}')
            continue
        seen.add(key)
        try:
            target = (root / name).resolve()
            if not target.is_relative_to(root):
                errors.append(f'文件路径超出包目录：{name}')
                continue
            with target.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            checked += 1
            if actual != expected.lower():
                errors.append(f'内容不一致：{name}')
        except FileNotFoundError:
            errors.append(f'文件缺失：{name}')
        except (OSError, ValueError) as error:
            errors.append(f'无法读取 {name}：{error}')
    if not seen:
        errors.append('清单没有可核对的文件。')
    return checked, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1], help='解压后的包根目录')
    args = parser.parse_args(argv)
    checked, errors = verify(args.root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(f'校验未通过：已读取 {checked} 个文件，发现 {len(errors)} 个问题。', file=sys.stderr)
        print('若已主动修改配置或源码，请在一份新解压的原始包中再次校验。', file=sys.stderr)
        return 1
    print(f'校验通过：清单中的 {checked} 个文件内容均一致。')
    print('仅核对清单所列文件；本检查不验证物理模型或数值准确性。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
