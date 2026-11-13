"""Native, user-visible database selection. This helper only returns a path."""
import json,sys,threading,subprocess
from pathlib import Path
from foundation import ROOT,config

PICKER_LOCK=threading.Lock()

def browse(root=ROOT,initial='',kind='database'):
 if kind not in ('database','weather','source','engine'):raise ValueError('不支持的文件类型。')
 if not isinstance(initial,str) or len(initial)>32768:raise ValueError('原路径格式无效。')
 if not PICKER_LOCK.acquire(blocking=False):raise ValueError('文件选择窗口已打开，请先完成或取消该窗口。')
 try:
  flags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,'CREATE_NO_WINDOW') else 0
  result=subprocess.run([config(root)['python'],'-X','utf8',str(ROOT/'database_picker.py')],input=json.dumps(dict(initial=initial,kind=kind)),
   capture_output=True,text=True,encoding='utf-8',timeout=300,creationflags=flags)
  if result.returncode:raise ValueError('文件浏览窗口未能打开，可暂用完整路径输入。')
  value=json.loads(result.stdout);path=value.get('path')
  if path is None:return dict(path=None,cancelled=True)
  if not isinstance(path,str):raise ValueError('文件选择结果无效。')
  p=Path(path).resolve(strict=True)
  if not p.is_file() or (kind!='source' and p.suffix.lower() not in (('.epw',) if kind=='weather' else ('.exe',) if kind=='engine' else ('.accdb','.mdb'))):raise ValueError('请选择 EPW 气象文件。' if kind=='weather' else '请选择 ACCDB 或 MDB 数据库文件。')
  return dict(path=str(p),cancelled=False)
 except subprocess.TimeoutExpired:raise ValueError('文件浏览窗口等待超时，已关闭；可重新点击浏览。')
 finally:PICKER_LOCK.release()

def main():
 import tkinter as tk
 from tkinter import filedialog
 sys.stdout.reconfigure(encoding='utf-8');request=json.load(sys.stdin);initial=Path(request.get('initial') or Path.home()/'Documents')
 directory=initial if initial.is_dir() else initial.parent
 app=tk.Tk();app.withdraw();app.attributes('-topmost',True)
 try:
  weather=request.get('kind')=='weather';source=request.get('kind')=='source';engine=request.get('kind')=='engine'
  value=filedialog.askopenfilename(parent=app,title='选择 energyplus.exe' if engine else '选择原文件副本' if source else '选择 EPW 气象文件' if weather else '选择 DeST 建筑数据库',filetypes=[('EnergyPlus 引擎','energyplus.exe')] if engine else [('原文件副本','*.*')] if source else [('EPW 气象文件','*.epw')] if weather else [('DeST 建筑数据库','*.accdb *.mdb')],
   initialdir=str(directory) if directory.is_dir() else str(Path.home()/'Documents'))
  print(json.dumps(dict(path=value or None),ensure_ascii=False))
 finally:app.destroy()

if __name__=='__main__':main()
