"""Nonblocking Windows CPU observations and optional admission control.

Percentages use the whole machine (all logical processors), not one core.
Admission control never suspends or terminates an already running process.
"""
from collections import deque
import ctypes
from ctypes import wintypes as w
import math
import os
import threading
import time

WINDOW_SECONDS = 10
SETTLE_SECONDS = 10


def filetime(value):
    return (value.dwHighDateTime << 32) + value.dwLowDateTime


def system_times():
    if os.name != 'nt':
        raise OSError('当前系统未提供 Windows CPU 观测。')
    k = ctypes.windll.kernel32
    k.GetActiveProcessorGroupCount.restype = w.WORD
    if k.GetActiveProcessorGroupCount() > 1:
        raise OSError('此设备有多个处理器组，当前不能可靠读取整机 CPU；可关闭 CPU 控制继续使用内存限制。')
    idle, kernel, user = w.FILETIME(), w.FILETIME(), w.FILETIME()
    fn = k.GetSystemTimes
    fn.argtypes = [ctypes.POINTER(w.FILETIME)] * 3
    fn.restype = w.BOOL
    if not fn(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise OSError('未能读取整机 CPU 负载。')
    # Windows kernel time includes idle time; subtract it only once.
    return filetime(idle), filetime(kernel) + filetime(user)


class Samples:
    def __init__(self):
        self.rows = deque()
        self.error = ''

    def update(self, at, idle, total):
        if self.rows and (at - self.rows[-1][0] > 3 or idle < self.rows[-1][1] or total < self.rows[-1][2]):
            self.rows.clear()
        self.rows.append((at, idle, total))
        while len(self.rows) > 2 and self.rows[1][0] < at - WINDOW_SECONDS:
            self.rows.popleft()
        self.error = ''

    def read(self, at):
        base = dict(ready=False, percent=None, average_percent=None, window_seconds=0,
                    logical_cpus=os.cpu_count(), reason=self.error or '正在采样 CPU，约 2 秒后可用。')
        if len(self.rows) < 2:
            return base
        first, previous, last = self.rows[0], self.rows[-2], self.rows[-1]
        def percent(a, b):
            total, idle = b[2] - a[2], b[1] - a[1]
            if total <= 0 or not 0 <= idle <= total:
                return None
            return 100 * (total - idle) / total
        current, average = percent(previous, last), percent(first, last)
        span = last[0] - first[0]
        if self.error or at - last[0] > 3 or span < 2 or current is None or average is None:
            if at - last[0] > 3:
                base['reason'] = 'CPU 观测已过期，等待重新采样。'
            return base
        return dict(base, ready=True, percent=current, average_percent=average,
                    window_seconds=span, sampled_at=last[0], reason='')


_samples = Samples()
_lock = threading.Lock()
_thread = None


def _observe():
    while True:
        try:
            idle, total = system_times()
            with _lock:
                _samples.update(time.monotonic(), idle, total)
        except (OSError, AttributeError) as e:
            with _lock:
                _samples.rows.clear()
                _samples.error = str(e)
        time.sleep(1)


def snapshot():
    global _thread
    with _lock:
        if _thread is None:
            _thread = threading.Thread(target=_observe, name='workbench-cpu', daemon=True)
            _thread.start()
        return _samples.read(time.monotonic())


class ProcessSamples:
    def __init__(self):
        self.previous = None
        self.peak = 0.0
        self.percent = None

    def sample(self, handle):
        creation, exit_time, kernel, user = (w.FILETIME() for _ in range(4))
        fn = ctypes.windll.kernel32.GetProcessTimes
        fn.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
        fn.restype = w.BOOL
        if not fn(w.HANDLE(int(handle)), ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
            self.percent = None
            return
        at, used = time.monotonic(), (filetime(kernel) + filetime(user)) / 1e7
        if self.previous and at > self.previous[0]:
            self.percent = min(100.0, max(0.0, (used - self.previous[1]) / (at - self.previous[0]) / (os.cpu_count() or 1) * 100))
            self.peak = max(self.peak, self.percent)
        self.previous = at, used


def admission(policy, machine, running):
    cpu = machine.get('cpu') or {}
    enabled = policy.get('cpu_limit_enabled', False)
    limit = policy.get('cpu_limit_percent', 80)
    def valid(v):
        return type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 100
    ready = cpu.get('ready') and valid(cpu.get('percent')) and valid(cpu.get('average_percent'))
    # Single-thread EnergyPlus starts with one logical processor's share. Raise
    # the reservation if any current attempt has actually used more than this.
    estimate = max([100 / max(1, machine.get('logical_cpus') or os.cpu_count() or 1)] +
                   [r['cpu_peak_percent'] for r in running if valid(r.get('cpu_peak_percent'))])
    load = max(cpu['percent'], cpu['average_percent']) if ready else None
    projected = load + estimate if ready else None
    settling = max([0] + [r.get('cpu_settling_seconds', 0) for r in running])
    reason = None
    if enabled:
        if not ready:
            reason = '等待 CPU 观测：' + (cpu.get('reason') or '当前负载不可用，暂不启动新算例。')
        elif settling > 0:
            reason = f'等待 CPU 启动观察：约 {settling:.0f} 秒后再判断是否新增一路'
        elif projected > limit:
            reason = f'等待 CPU 余量：当前 / 近期负载 {load:.1f}% + 新增一路预算 {estimate:.1f}% 超过目标 {limit:g}%；已有任务继续运行'
    return dict(enabled=enabled, ready=bool(ready), limit_percent=limit, load_percent=load,
                next_job_percent=estimate, projected_percent=projected,
                additional_slots=max(0, min(policy['max_parallel']-len(running), math.floor((limit-load)/estimate))) if ready else None,
                startup_wait_seconds=settling, reason=reason,
                basis='当前与近期整机 CPU 取较高值；新任务至少预留一个逻辑处理器，结合本轮实际峰值上调。')
