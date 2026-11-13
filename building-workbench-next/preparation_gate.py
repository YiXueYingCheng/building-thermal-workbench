"""Serialize input preparation within one workspace, never simulation workers."""
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

_locks=defaultdict(RLock)

@contextmanager
def slot(root,progress=None):
    lock=_locks[str(Path(root).resolve())]
    while not lock.acquire(timeout=1):
        if progress:progress(stage='等待其他输入准备完成，当前计算继续运行')
    try:yield
    finally:lock.release()

class PreparationPaused(Exception):pass
