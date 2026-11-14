"""A user-invoked native folder picker; opening it never registers or selects storage."""
import json,sys,threading,subprocess
from pathlib import Path
from foundation import ROOT,config
LOCK=threading.Lock()

def browse(root=ROOT,initial='',title='选择新版计算结果的独立空文件夹'):
    if not isinstance(initial,str) or len(initial)>32768:raise ValueError('原路径格式无效。')
    if not LOCK.acquire(blocking=False):raise ValueError('文件夹选择窗口已打开，请先完成或取消。')
    try:
        result=subprocess.run([config(root)['python'],'-X','utf8',str(Path(__file__).resolve())],
            input=json.dumps(dict(initial=initial,title=title)),capture_output=True,text=True,encoding='utf8',
            timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise ValueError('文件夹浏览窗口未能打开，可暂用完整路径输入。')
        value=json.loads(result.stdout);p=value.get('path')
        if p is None:return dict(path=None,cancelled=True)
        if not isinstance(p,str) or not Path(p).is_dir():raise ValueError('请选择现有文件夹；也可在路径框填写新文件夹。')
        return dict(path=str(Path(p).resolve()),cancelled=False)
    except subprocess.TimeoutExpired:raise ValueError('文件夹选择等待超时，窗口已关闭；可重新浏览。')
    finally:LOCK.release()

def main():
    import tkinter as tk
    from tkinter import filedialog
    sys.stdout.reconfigure(encoding='utf8');v=json.load(sys.stdin)
    p=Path(v.get('initial') or Path.home()/'Documents');p=p if p.is_dir() else p.parent
    app=tk.Tk();app.withdraw();app.attributes('-topmost',True)
    try:
        value=filedialog.askdirectory(parent=app,title=v.get('title','选择文件夹'),mustexist=True,
                                      initialdir=str(p) if p.is_dir() else str(Path.home()/'Documents'))
        print(json.dumps(dict(path=value or None),ensure_ascii=False))
    finally:app.destroy()

if __name__=='__main__':main()
