"""Current project engine policy; historical models/results remain immutable."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
MODEL_VERSION = '26.2'
BUILD = '26.2.0-4bd7a1f26f'
ENGINE = ROOT / f'work/runtime/EnergyPlus-{BUILD}-Windows-x86_64/energyplus.exe'
VALIDATION = ROOT / 'outputs/01a0805a-fcec-7b73-9ee0-021b342ea2a4/drawing26-inputs/版本验证/EnergyPlus_26.2_BASE01_20261009'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def engine_record(executable=ENGINE):
    executable = Path(executable).resolve(strict=True)
    version = subprocess.check_output([str(executable), '--version'], text=True).strip()
    if BUILD not in version:
        raise ValueError(f'本项目后续计算统一使用 EnergyPlus {BUILD}，当前为 {version}')
    return {'version': version, 'executable_sha256': sha(executable),
            'installation': str(executable.parent)}


def use_current_version(model):
    """Upgrade a generated copy of the project's epJSON, never the source snapshot.

    This is intentionally not a general HVAC transition utility. Reject the
    26.1 object types whose field deletion/rename needs a separate migration.
    Other new 26.2 fields retain their documented default/inheritance behavior.
    """
    objects = model.get('Version', {})
    if len(objects) != 1:
        raise ValueError('模型必须有一个明确的 Version 对象。')
    item = next(iter(objects.values()))
    old = item['version_identifier']
    if old not in ('26.1', MODEL_VERSION):
        raise ValueError(f'不支持自动迁移模型版本 {old}；请使用官方转换器。')
    if old == '26.1':
        changed = {'CentralHeatPumpSystem', 'ChillerHeaterPerformance:Electric:EIR',
                   'ZoneControl:Humidistat'}
        if any(model.get(kind) for kind in changed):
            raise ValueError('该 HVAC 模型需要官方 26.1→26.2 字段转换，不能仅更新版本号。')
    item['version_identifier'] = MODEL_VERSION
    return model


def baseline_engine_record(baseline, executable=ENGINE):
    """Allow the sealed BASE01 via its existing, successful annual comparison."""
    baseline = Path(baseline).resolve()
    source = read(baseline / 'baseline.json')['engine']
    actual = engine_record(executable)
    if actual['executable_sha256'] == source['executable_sha256']:
        return actual
    evidence = read(VALIDATION / 'validation-state.json')
    comparison = read(VALIDATION / 'version-comparison.json')
    if not (baseline == Path(evidence['baseline']).resolve()
            and evidence['status'] == 'validated'
            and evidence['old_engine_sha256'] == source['executable_sha256']
            and evidence['new_engine_sha256'] == actual['executable_sha256']
            and comparison['numerical_reproduction']):
        raise ValueError('当前引擎与封存基准之间没有匹配的已验证版本迁移记录。')
    return dict(actual, baseline_engine=source,
                migration_validation=str(VALIDATION / 'version-comparison.json'))
