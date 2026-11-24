"""Manage the lifetime of the private Windows Origin instance used by an export."""
import os
from contextlib import contextmanager
from pathlib import Path


def allocate_job(process):
    # An unnamed Windows job closes its member if the export worker exits or times out.
    import ctypes as ct
    from ctypes import wintypes as wt
    kernel = ct.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes = (wt.LPVOID,wt.LPCWSTR)
    kernel.CreateJobObjectW.restype = wt.HANDLE
    handle = kernel.CreateJobObjectW(None,None)
    if not handle:
        raise ct.WinError(ct.get_last_error())
    import _winapi
    try:
        class BasicLimits(ct.Structure):
            _fields_ = [('user_time',ct.c_int64),('job_time',ct.c_int64),('flags',wt.DWORD),
                ('min_ws',ct.c_size_t),('max_ws',ct.c_size_t),('active',wt.DWORD),
                ('affinity',ct.c_size_t),('priority',wt.DWORD),('scheduling',wt.DWORD)]
        class ExtendedLimits(ct.Structure):
            _fields_ = [('basic',BasicLimits),('io_counters',ct.c_uint64*6),('memory_limits',ct.c_size_t*4)]
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(wt.HANDLE(handle),9,ct.byref(limits),ct.sizeof(limits)):
            raise ct.WinError(ct.get_last_error())
        if not kernel.AssignProcessToJobObject(wt.HANDLE(handle),wt.HANDLE(process)):
            raise ct.WinError(ct.get_last_error())
        return handle
    except BaseException:
        _winapi.CloseHandle(handle)
        raise


@contextmanager
def private_session(op):
    import _winapi
    op.set_show(False)  # originpro creates Application(), a dedicated instance.
    process = job = None
    try:
        op.lt_exec(f'run -pyf "{Path(__file__).resolve()}";')
        pid = int(op.lt_float('wbPrivateOriginPid'))
        if pid<=0 or pid==os.getpid():
            raise ValueError('未能核对本次后台 Origin 会话。')
        process = _winapi.OpenProcess(0x100101,False,pid)  # synchronize, set quota, terminate
        job = allocate_job(process)
        yield
    finally:
        try:
            op.new()  # Release the project file and discard unsaved validation edits.
            op.po.SetCanClose(True)
            op.exit()
            if process and _winapi.WaitForSingleObject(process,1500)==_winapi.WAIT_TIMEOUT and not job:
                _winapi.TerminateProcess(process,0)
        finally:
            if job:
                _winapi.CloseHandle(job)
            if process:
                _winapi.CloseHandle(process)


if __name__=='__main__':
    # Executed by Origin's embedded Python in the dedicated instance itself.
    import PyOrigin
    PyOrigin.LT_set_var('wbPrivateOriginPid',os.getpid())
