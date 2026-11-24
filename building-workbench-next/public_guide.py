"""User-facing scope for clean workspaces and the authorized public examples."""
from pathlib import Path
from foundation import read_json
from material_types import support_paths

FACTORS=[
 dict(key='building',name='建筑',available='公开示例采用 Drawing26：1 层、11 个房间、6 个空调房，保留原作息、内部得热与四阈值温控。可查看平面和房间配置，另存方案后编辑当前支持的参数。',pending='导入其他兼容 ACCDB/MDB 时需逐项检查转换条件。普通新建筑不会自动获得 Drawing26 的研究材料和反馈适配。'),
 dict(key='materials',name='材料',available='先选仅表面光学、计入热阻与蓄热、或仅计热阻。薄膜、气凝胶等是材料形态说明；计入蓄热时都填写厚度、导热率、密度、比热和物性依据。公用参考库可复制材料与构造，明确外到内层序后采用固定构造版本。',pending='不计新增层蓄热时，当前不能用于新版可调热阻工况。计入蓄热的通用入口仍按所选状态固定计算，双态可分别对照，不代表已支持动态调节。旧 ECA 方案保留原接法和历史范围。库更新不会改写已有方案或结果。'),
 dict(key='condition',name='工况',available='示例分为固定两态、热阻反馈和逐日光学切换。方案指定已铺墙段、参与反馈的墙段及其他墙段的固定状态；表面光学切换采用同建筑、同气象和同运行条件的原构造逐日参考。',pending='材料热阻反馈阈值与房间四阈值空调控制是两套设置。光学切换日历不能跨建筑、气象或使用条件套用；缺少有效参考时先完成参考计算。'),
 dict(key='scope',name='范围',available='气象下载清单提供中国 34 地区和全球 30 类预设；目前有 29 类可下载，Csc 待补来源。支持批量下载、校验、质量核对及明确登记，再在方案范围选用。',pending='气候标签沿用历史表，不代表重新分类。两日或31日结果只代表所选时段；单地点不代表区域平均，建筑显热需求不等于设备电耗。')]

def guide(version,catalog,root):
    folder=Path(root)/'data/examples'
    def receipt(name):
        path=folder/name
        return read_json(path) if path.exists() else {}
    fixed=receipt('fixed-comparison.json');controls=receipt('control-examples.json');flip=receipt('orientation-example.json')
    period=flip.get('period')
    flip_period=f'{period[0]} 月 {period[1]} 日—{period[2]} 月 {period[3]} 日' if period else '取得有效全年逐日参考后，选取切换日前后31日'
    examples=[dict(name='固定热阻两态对照',period='1 月 1—2 日 · 5 分钟',description='原参与组 7 段墙分别固定为 R 或 C，固定 A；其余 7 段保持 R。先熟悉保存、计算、比较与导出。',records=[dict(label=label,**row) for state,label in [('R','蓬松方案'),('C','压缩方案')] if (row:=fixed.get('records',{}).get(state))]),
      dict(name='两日热阻反馈',period='1 月 1—2 日 · 5 分钟',description='同一组 7 段墙按上一完整步的室温和热流统一反馈。低/高温阈值为 18/26 °C，热流死区 1 W/m²，最短保持 60 分钟，初始为压缩态；固定 A。',records=[dict(label='热阻反馈方案',**controls['records']['feedback'])] if controls else []),
      dict(name='跨切换日的表面光学切换对照',period=flip_period+' · 5 分钟',description='热阻固定为蓬松态，对照固定 A与全部 14 段墙按逐日日历切换表面光学参数。日历根据全年原构造冷热需求生成；31日窗口用于观察切换过程。',records=[dict(label=label,**row) for key,label in [('fixed_A','固定 A方案'),('orientation','表面光学切换方案')] if (row:=flip.get('records',{}).get(key))])]
    return dict(kind='public_preparation',version=version,title='建筑热环境工作台 · 使用说明',material_support=support_paths(),
      introduction=f'围绕不透明围护结构的材料、施加位置及热工／光学配置，研究建筑冷热显热需求和自然室温；建筑、人员、作息及温控是基础，原窗户仍参与传热与太阳得热。当前为 {version} 开发工作区。自有代码采用 MIT，自有示例和文档采用 CC BY 4.0；作息和公用配置库已按作者确认的范围随包提供，保留原来源与第三方条件。',factors=FACTORS,examples=examples,
      steps=['先打开一个示例，查看建筑、材料、工况、地点和时段。来源与已保存历史版本保持只读。',
        '需要修改时“另存为研究方案”，编辑四因素并保存版本；查看“计算安排”，确认步长及算例。',
        '生成输入、核对清单并提交“计算队列”。结果通过核验后，在“对照总览”选择对应版本的实际结果批次。',
        '导出表格、PNG、SVG、PDF或结果包；结果保留所用方案版本、时段和来源信息。'],
      notes=['示例用于检查操作流程和既定模型行为。原设备得热 40 W/m²、原温控及求解器预热保留，不自动增加连续天气前置。',
        '反馈示例中的 R/C 切换与表面光学切换示例中的 A/B 切换分别演示；本轮不把两种控制组合成新研究结论。',
        '打开示例或查看说明不会自动开始计算。修改日期、气象或运行配置后，应重新核对支持范围和参考日历。'],
      documents=[dict(id='result-timeline',name='结果输出频率与逐日查看'),dict(id='storage-management',name='空间、方案与结果清理'),dict(id='workflow-management',name='作息、方案入口与计算状态'),dict(id='material-semantics',name='材料参数含义与推算用法'),dict(id='material-agent',name='Agent 材料版本与核对接口'),dict(id='reference-materials',name='公用库、材料与气象下载用法'),dict(id='public-examples',name='示例安装与复现'),dict(id='public-install',name='安装与首次使用'),dict(id='public-weather',name='气象来源与下载说明')])
