"""Resource budgets for independent fixed-model EnergyPlus processes.

Performance preferences never enter a physical result identity. A budget gates
new dispatch only; an already running simulation is not killed for memory use.
"""
import ctypes
import math
import os
import shutil
import cpu_budget
from ctypes import wintypes as w

GiB = 2**30
PROFILES = {
    'light': dict(label='轻量', max_parallel=1, reserve_gib=3.0, priority='below_normal'),
    'balanced': dict(label='平衡', max_parallel=4, reserve_gib=2.0, priority='below_normal'),
    'high': dict(label='集中计算', max_parallel=8, reserve_gib=2.0, priority='normal'),
    'custom': dict(label='自定义', max_parallel=2, reserve_gib=2.0, priority='below_normal'),
}


def settings(value=None):
    value = value or {}
    profile = value.get('profile', 'balanced')
    if profile not in PROFILES:
        raise ValueError('请选择有效的性能档位。')
    out = dict(PROFILES[profile], profile=profile, disk_reserve_gib=5.0)
    if profile == 'custom':
        for key in ('max_parallel', 'reserve_gib', 'priority', 'disk_reserve_gib'):
            if key in value:
                out[key] = value[key]
    elif any(key in value and value[key]!=out[key] for key in ('max_parallel','reserve_gib','disk_reserve_gib','priority')):
        raise ValueError('手动修改数值时请选择自定义档位；预设档位不能忽略您的修改。请刷新页面后重试。')
    if type(out['max_parallel']) is not int or not 1 <= out['max_parallel'] <= min(8, os.cpu_count() or 1):
        raise ValueError('并行上限应为1至8的整数，且不超过本机逻辑处理器数。')
    for key, low, high in [('reserve_gib', 1.0, 64.0), ('disk_reserve_gib', 2.0, 1000.0)]:
        v = out[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError('内存保留至少1 GiB，磁盘保留至少2 GiB；请输入范围内有限数值。')
    if out['priority'] not in ('below_normal', 'normal'):
        raise ValueError('进程优先级只支持较低或普通。')
    out['cpu_limit_enabled'] = value.get('cpu_limit_enabled', False)
    out['cpu_limit_percent'] = value.get('cpu_limit_percent', 80)
    if type(out['cpu_limit_enabled']) is not bool:
        raise ValueError('CPU 控制开关须为开启或关闭。')
    v = out['cpu_limit_percent']
    if type(v) not in (int, float) or not math.isfinite(v) or not 10 <= v <= 100:
        raise ValueError('CPU 目标占用应为 10–100% 的有限数值。')
    return out


def snapshot(path):
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [('length', w.DWORD), ('load', w.DWORD)] + [(n, ctypes.c_ulonglong) for n in
            ('total', 'available', 'commit_limit', 'commit_available', 'virtual_total', 'virtual_available', 'extended')]
    m = MEMORYSTATUSEX(); m.length = ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        raise OSError('无法读取本机内存状态，暂不派发新任务。')
    return dict(total_gib=m.total/GiB, available_gib=m.available/GiB,
                commit_available_gib=m.commit_available/GiB,
                disk_free_gib=shutil.disk_usage(path).free/GiB, logical_cpus=os.cpu_count(),cpu=cpu_budget.snapshot())


def process_memory(handle):
    class COUNTERS(ctypes.Structure):
        _fields_ = [('cb', w.DWORD), ('faults', w.DWORD)] + [(n, ctypes.c_size_t) for n in
            ('peak', 'working', 'qp', 'qpu', 'qn', 'qnu', 'commit', 'peak_commit')]
    m = COUNTERS(); m.cb = ctypes.sizeof(m)
    fn = ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]; fn.restype = w.BOOL
    if not fn(w.HANDLE(int(handle)), ctypes.byref(m), m.cb):
        return dict(working_gib=0, peak_gib=0, commit_gib=0, peak_commit_gib=0)
    return dict(working_gib=m.working/GiB, peak_gib=m.peak/GiB,
                commit_gib=m.commit/GiB, peak_commit_gib=m.peak_commit/GiB)


def estimate_job_gib(samples):
    """Learn only from completed attempts in the same batch and operation mode."""
    samples=[x for x in samples if isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>0]
    if len(samples)<3:return .75
    return max(.5,max(samples)*1.25+.05)

def dispatch_budget(policy,machine,running,per_job_gib=.75,per_job_disk_gib=.1,*,per_job_commit_gib=None,exclusive=False):
    commit_estimate=per_job_gib if per_job_commit_gib is None else per_job_commit_gib
    growing=sum(max(0,r.get('reserved_gib',per_job_gib)-r.get('working_gib',0)) for r in running)
    commit_growth=sum(max(0,r.get('reserved_commit_gib',r.get('reserved_gib',commit_estimate))-r.get('commit_gib',0)) for r in running)
    needed=policy['reserve_gib']+per_job_gib+growing
    commit_needed=policy['reserve_gib']+commit_estimate+commit_growth
    disk_needed=policy['disk_reserve_gib']+per_job_disk_gib*(len(running)+1)
    reason=None
    if exclusive and running:reason='等待当前算例结束后独占运行'
    elif any(r.get('exclusive') for r in running):reason='独占算例运行中，其他算例等待'
    elif len(running)>=policy['max_parallel']:reason='已达到当前并行上限'
    elif exclusive and min(machine['available_gib'],machine['commit_available_gib'])<=policy['reserve_gib']:reason='等待可用内存和系统可提交内存均高于保留线'
    elif not exclusive and machine['available_gib']<needed:reason=f'等待内存：新增一路前需可用 {needed:.2f} GiB，当前 {machine["available_gib"]:.2f} GiB'
    elif not exclusive and machine['commit_available_gib']<commit_needed:reason=f'等待系统可提交内存：需 {commit_needed:.2f} GiB，当前 {machine["commit_available_gib"]:.2f} GiB'
    elif machine['disk_free_gib']<disk_needed:reason='等待磁盘：剩余空间低于保留线'
    cpu = cpu_budget.admission(policy, machine, running)
    if reason is None and not exclusive and cpu['reason']:reason=cpu['reason']
    return dict(reason=reason,allowed=reason is None,exclusive=exclusive,reserve_gib=policy['reserve_gib'],next_job_gib=per_job_gib,
        running_growth_gib=growing,required_available_gib=needed,available_gib=machine['available_gib'],
        required_commit_gib=commit_needed,available_commit_gib=machine['commit_available_gib'],cpu=cpu)

def dispatch_reason(policy,machine,running,per_job_gib=.75,per_job_disk_gib=.1):
    return dispatch_budget(policy,machine,running,per_job_gib,per_job_disk_gib)['reason']
