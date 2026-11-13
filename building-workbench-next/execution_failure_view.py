"""Bounded, read-only explanations for failed attempts; no scientific acceptance."""
from pathlib import Path
import hashlib,re,math
from foundation import owned
import output_storage


def describe(job,root):
    if job.get('status')!='failed' or not re.fullmatch(r'attempt_[a-f0-9]{32}',str(job.get('attempt',''))):return None
    try:
        path=output_storage.attempt_folder(root,job['attempt'])/'run/eplusout.err'
        if not path.is_file():return None
        with path.open('rb') as f:raw=f.read(2*1024*1024+1)
    except (OSError,ValueError):
        # Keep the queue's original error visible even when its result disk is
        # unavailable. Missing evidence never becomes a diagnosis or acceptance.
        return None
    truncated=len(raw)>2*1024*1024
    text=raw[:2*1024*1024].decode('utf-8',errors='replace')
    severe=[s.strip() for s in re.findall(r'^\s*\*\*\s+Severe\s+\*\*\s*(.*)$',text,re.M)]
    fatal=[s.strip() for s in re.findall(r'^\s*\*\*\s+Fatal\s+\*\*\s*(.*)$',text,re.M)]
    warmup=[re.fullmatch(r'CheckWarmupConvergence: Loads Initialization, Zone="([^"]+)" did not converge after (\d+) warmup days\.',s) for s in severe]
    known=not truncated and bool(severe) and not fatal and all(warmup)
    zones=[dict(zone=m[1],warmup_days=int(m[2])) for m in warmup if m]
    checks=[]
    labels={'Max Temp':'最高温度','Min Temp':'最低温度','Max Heat Load':'供暖负荷','Max Cool Load':'制冷负荷'}
    if known:
        for block in re.split(r'^\s*\*\*\s+(?:Severe|Warning|Fatal)\s+\*\*\s*',text,flags=re.M)[1:]:
            header=re.match(r'CheckWarmupConvergence: Loads Initialization, Zone="([^"]+)" did not converge after (\d+) warmup days\.',block)
            if not header:continue
            for measure,value,kind,tolerance,decision in re.findall(r'\.\.(Max Temp|Min Temp|Max Heat Load|Max Cool Load) Comparison = ([-+\d.eE]+) vs (Temperature|Loads) Convergence Tolerance=([-+\d.eE]+) - (Pass|Fail) Convergence',block):
                if decision!='Fail':continue
                try:value,tolerance=float(value),float(tolerance)
                except ValueError:continue
                if not (math.isfinite(value) and math.isfinite(tolerance)):continue
                if (kind=='Temperature')!=measure.endswith('Temp'):continue
                checks.append(dict(zone=header[1],measure=measure,label=labels[measure],
                    value=value,tolerance=tolerance,unit='°C' if kind=='Temperature' else '比值'))
    temperature_rooms={c['zone'] for c in checks if c['unit']=='°C'}
    heating_rooms={c['zone'] for c in checks if c['measure']=='Max Heat Load'}
    cooling_rooms={c['zone'] for c in checks if c['measure']=='Max Cool Load'}
    summary='、'.join(f'{label} {len(rooms)} 间' for label,rooms in [('温度',temperature_rooms),('供暖负荷',heating_rooms),('制冷负荷',cooling_rooms)] if rooms)
    return dict(kind='warmup_convergence' if known else 'engine_error',
        title=f'预热未收敛：{len(zones)} 间房' if known else '引擎报告错误，需要核查',
        explanation='日志显示达到原预热天数上限后，部分房间仍未满足收敛条件。执行到全年结束不代表本项已通过。' if known else '请结合原始日志核查具体原因，当前不作为可用研究结果。',
        next_step='先核对原因，再决定是否修正输入或进行隔离验证。此项不纳入汇总；已通过的其他项保留。',
        severe_records=len(severe),fatal_records=len(fatal),zones=zones[:100],
        failed_checks=checks[:400],failed_checks_summary=summary,
        log_excerpt=(severe+fatal)[:40],truncated=truncated,
        log_path=str(path),log_sha256=None if truncated else hashlib.sha256(raw).hexdigest(),
        log_only=True,acceptance_changed=False)
