"""Request-local read reuse, with full content revalidation before returning."""
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
from collections import OrderedDict
import copy, hashlib, os

_current=ContextVar('inspection_reads',default=None)

def current():return _current.get()
def raw_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def identity(path):return os.path.abspath(path)

class Reads:
    def __init__(self,progress=None,max_json_bytes=32*1024*1024):
        self.hashes={};self.json_values=OrderedDict();self.json_sizes={};self.max_json_bytes=max_json_bytes;self.paths={};self.memo={};self.values={};self.progress=progress
    def watch_value(self,key,loader,expected):
        if key not in self.values:self.values[key]=(loader,copy.deepcopy(expected))
    def watch(self,path):
        p=identity(path)
        if p not in self.hashes:
            try:self.hashes[p]=raw_hash(p)
            except FileNotFoundError:self.hashes[p]=None
        return self.hashes[p]
    def sha(self,path):
        value=self.watch(path)
        if value is None:raise FileNotFoundError(str(path))
        return value
    def json(self,path,loader):
        p=identity(path)
        if p not in self.json_values:
            before=self.sha(p);value=loader()
            if raw_hash(p)!=before:raise ValueError('核对期间来源改变，请重新核对：'+p)
            size=Path(p).stat().st_size
            if size>self.max_json_bytes:return value
            while self.json_values and (sum(self.json_sizes.values())+size>self.max_json_bytes or len(self.json_values)>=32):
                old,_=self.json_values.popitem(last=False);self.json_sizes.pop(old)
            self.json_values[p]=value;self.json_sizes[p]=size
        self.json_values.move_to_end(p)
        return copy.deepcopy(self.json_values[p])
    def resolve(self,path):
        p=identity(path)
        if p not in self.paths:self.paths[p]=str(Path(p).resolve())
        return self.paths[p]
    def valid(self):
        try:
            for p,expected in self.hashes.items():
                try:actual=raw_hash(p)
                except FileNotFoundError:actual=None
                if actual!=expected:return False
            return all(str(Path(p).resolve())==resolved for p,resolved in self.paths.items()) and all(loader()==expected for loader,expected in self.values.values())
        except Exception:return False
    def evidence(self):
        out=Reads();out.hashes=self.hashes.copy();out.paths=self.paths.copy();out.values=self.values.copy();return out

@contextmanager
def reading(progress=None):
    if current() is not None:
        yield current();return
    scope=Reads(progress);token=_current.set(scope)
    try:
        yield scope
        if not scope.valid():raise ValueError('核对期间来源或结果登记改变，请重新核对。')
    finally:_current.reset(token)

def resolve_path(path):return current().resolve(path) if current() else str(Path(path).resolve())
def progress(stage,completed,total,city=''):
    scope=current()
    if scope and scope.progress:scope.progress(dict(stage=stage,completed=completed,total=total,city=city))
