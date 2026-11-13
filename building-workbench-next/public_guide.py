"""User-facing scope for clean workspaces and the authorized public examples."""
from pathlib import Path
from foundation import read_json

FACTORS=[
 dict(key='building',name='建筑',available='公开示例采用 Drawing26：1 层、11 个房间、6 个空调房，保留原作息、内部得热与四阈值温控。可查看平面和房间配置，另存方案后编辑当前支持的参数。',pending='导入其他兼容 ACCDB/MDB 时需逐项检查转换条件。普通新建筑不会自动获得 Drawing26 的研究材料和反馈适配。'),
 dict(key='materials',name='材料',available='ECA 为单层等效热阻材料，R（蓬松）与 C（压缩）的热阻及双面光学参数可分别保存版本。Drawing26 示例在原 14 段外墙外侧应用。',pending='本示例沿用不计等效层蓄热的近似；其他材料模型、层位与构件需要相应适配。修改材料库不会改写已保存方案或计算结果。'),
 dict(key='condition',name='工况',available='示例分为固定两态、热阻反馈和逐日翻面。热阻反馈采用原 7 段参与墙，其余 7 段保持蓬松；翻面采用同建筑、同气象和同运行条件的原构造逐日参考。',pending='材料热阻反馈阈值与房间四阈值空调控制是两套设置。翻面日历不能跨建筑、气象或使用条件套用；缺少有效参考时先完成参考计算。'),
 dict(key='scope',name='范围',available='公开示例使用长沙 CSWD 气象。地点、统计日期和求解步长随方案版本保存；可导入其他 EPW，并核对完整性与来源。',pending='两日或31日结果只代表所选工况；月度行也只包含所选日期。单地点结果不代表全年或区域平均，建筑显热需求不等于设备电耗。')]

def guide(version,catalog,root):
    folder=Path(root)/'data/examples'
    def receipt(name):
        path=folder/name
        return read_json(path) if path.exists() else {}
    fixed=receipt('fixed-comparison.json');controls=receipt('control-examples.json');flip=receipt('orientation-example.json')
    period=flip.get('period')
    flip_period=f'{period[0]} 月 {period[1]} 日—{period[2]} 月 {period[3]} 日' if period else '取得有效全年逐日参考后，选取切换日前后31日'
    examples=[dict(name='固定热阻两态对照',period='1 月 1—2 日 · 5 分钟',description='原参与组 7 段墙分别固定为 R 或 C，A 面朝外；其余 7 段保持 R。先熟悉保存、计算、比较与导出。',records=[dict(label=label,**row) for state,label in [('R','蓬松方案'),('C','压缩方案')] if (row:=fixed.get('records',{}).get(state))]),
      dict(name='两日热阻反馈',period='1 月 1—2 日 · 5 分钟',description='同一组 7 段墙按上一完整步的室温和热流统一反馈。低/高温阈值为 18/26 °C，热流死区 1 W/m²，最短保持 60 分钟，初始为压缩态；A 面固定朝外。',records=[dict(label='热阻反馈方案',**controls['records']['feedback'])] if controls else []),
      dict(name='跨切换日的翻面对照',period=flip_period+' · 5 分钟',description='热阻固定为蓬松态，对照固定 A 面与全部 14 段墙按逐日日历翻面。日历根据全年原构造冷热需求生成；31日窗口用于观察切换过程。',records=[dict(label=label,**row) for key,label in [('fixed_A','固定 A 面方案'),('orientation','翻面方案')] if (row:=flip.get('records',{}).get(key))])]
    return dict(kind='public_preparation',version=version,title='建筑热环境工作台 · 使用说明',
      introduction='围绕建筑、材料、工况和范围建立研究方案，核对输入后运行计算，再比较和导出结果。当前为 v0.72.1 公开源码分发包，可在本机使用。自有代码采用 MIT，示例与文档采用 CC BY 4.0；署名和第三方例外见包根目录说明。',factors=FACTORS,examples=examples,
      steps=['先打开一个示例，查看建筑、材料、工况、地点和时段。来源与已保存历史版本保持只读。',
        '需要修改时“另存为研究方案”，编辑四因素并保存版本；查看“计算安排”，确认步长及算例。',
        '生成输入、核对清单并提交“计算队列”。结果通过核验后，在“对照总览”选择对应版本的实际结果批次。',
        '导出表格、PNG、SVG、PDF或结果包；结果保留所用方案版本、时段和来源信息。'],
      notes=['示例用于检查操作流程和既定模型行为。原设备得热 40 W/m²、原温控及求解器预热保留，不自动增加连续天气前置。',
        '反馈示例中的 R/C 切换与翻面示例中的 A/B 切换分别演示；本轮不把两种控制组合成新研究结论。',
        '打开示例或查看说明不会自动开始计算。修改日期、气象或运行配置后，应重新核对支持范围和参考日历。'],
      documents=[dict(id='public-examples',name='示例安装与复现'),dict(id='public-install',name='安装与首次使用'),dict(id='public-weather',name='气象来源与下载说明')])
