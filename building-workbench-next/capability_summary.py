"""Read-only editor feedback using the unchanged model-generation authority."""
from contracts import normalize, validate
from model_adapter import capability

GUIDE = [
 dict(key='building',name='建筑',available='Drawing26 全球来源和已验证的五层建筑支持人数/功率、工作日/周末作息、日计划版本、房间复用与差异核对。分别保留原 6/5 与 50/25 空调归属。五层及通过导入核对的普通建筑可局部编辑原构造各层热物性和光学、等效门窗参数；成对表面按反向层位同步，保留几何和接地；构件可按类型/楼层/房间查找，修改汇总显示原值与有效值，并与平面双向定位。旧动态来源继续继承原配置。',pending='兼容 ACCDB 已接通检查、转换、配置映射及登记。其他门型、非直接接地、季节/特殊日、空调归属调整及更多材料仍需适配。'),
 dict(key='materials',name='材料',available='独立公用材料库可登记现有 ECA 定义、追加版本、查找并明确选入方案；普通构造材料来源目录只读且保留名称依据。单层 ECA 等效热阻；Drawing26 支持 R/C 独立状态、分态光学及原 14 段外墙外侧应用。五层建筑已接通全部 135 面外墙的外侧附加层，固定蓬松 R 或固定压缩 C、制冷面 A 朝外，支持面积/层序预览、状态切换及草稿采用。',pending='内侧、中间层、其他构件与材料模型可记录研究意图，尚不能由当前适配器生成。'),
 dict(key='condition',name='工况',available='Drawing26 全球来源和五层建筑支持自然/温控、建筑默认继承和原空调房启停温度/可用时段覆盖。五层建筑支持全外墙固定 R/A 或 C/A，以及双面材料固定 R 按本建筑已接受逐日日历翻面；Drawing26 支持固定朝向、原 7 段墙统一或分组反馈；旧动态来源保留绑定的本地日历；工况页可逐地点核对原构造参考及逐日数据缺口，并独立核对旧逐日资料、下载合并清单；北京示例已验收；当前方案可预览匹配的逐日日历、保存版本、明确采用和撤销，并显示参考条件变化。',pending='五层建筑的热阻反馈调节、C 态翻面尚未接通。建筑使用或温控改变后不套用旧日历；34 城已登记且匹配的参考可采用；其他地点须先准备并接受本建筑同条件逐日参考，另一面物性缺项不会自动补齐。'),
 dict(key='scope',name='范围',available='登记地点筛选、气候覆盖、范围组合、EPW 浏览/逐时检查/独立登记及显式选用；新增中国 34 省级地区预设，每地区一个默认点和替换候选，共 76 份可选气象，可比较气候类型、海拔、冷热月和度日，预览后采用到草稿。Kiva 建筑同步气象与位置。可核对依赖、预览气象更新并保存新方案版本；旧结果保留。',pending='单城市结果不等于全省平均；太阳时序已支持只读线索筛查和报告下载，来源口径归因、研究所需区域权重、固定地温和新参考日历待推进；缺数据保持为空，未分类地点不自动填入气候地图。')
]

def describe(record,catalog):
    try:
        normalized=normalize(record)
        errors=validate(normalized,catalog['sites'])
        if errors:return dict(status='incomplete',supported=False,valid=False,reasons=errors)
        result=capability(normalized,catalog)
        from calendar_library import status
        return dict(status='ready' if result['supported'] else 'unsupported',supported=result['supported'],valid=True,reasons=result['reasons'],calendar_status=status(normalized,catalog))
    except (KeyError,TypeError,AttributeError,ValueError) as error:
        return dict(status='incomplete',supported=False,valid=False,reasons=['设置尚未完整：'+str(error)])

def factors(catalog):
    if catalog.get('catalog_kind')=='standalone_v1':
        from public_guide import FACTORS
        return FACTORS
    return GUIDE

def guide(version,catalog=None,root=None):
    if catalog and catalog.get('catalog_kind')=='standalone_v1':
        from public_guide import guide as public
        return public(version,catalog,root)
    return dict(version=version,factors=GUIDE,completed=[
        '方案版本、输入生成、清单恢复、后台队列和结果核验已接通。',
        '比较关系、气候地图、单地点年度/月度图表、论文数据导出和已导出快照回看已接通。',
        'T05b / T14：建筑与材料页可查看模型平面，按标高分层、定位房间与外墙，查看当前研究材料范围并进入原房间/构造配置。',
        'T14：来源与迁移增加当前方案来源概览，已登记库版本和气象更新集中查看，再从单方案预览并显式采用；旧结果保持原绑定。',
        'T13：结果索引按建筑、地点/名称和步长查找保存比较、批次及原平台历史；各自沿用固定版本，打开结果时核验文件。',
        'T01：编辑时检查当前组合，使用模型生成器的同一能力判断。',
        'T04：统一当前能力、后续待办、维护与回归入口；历史回执保留原阶段语境。',
        'T11：清单准备后自动核验复用与需算数量，同类实测支持耗时和成果保留量估算；已有日志可核对实际并行、运行窗口及吞吐，新增执行目录磁盘采样。',
        'T12：存储与外置依赖清单、本地工作区备份及隔离恢复核验已接通，支持随时重新校验备份包。'],
        next=[dict(id='T05a / T02 / T03',name='现有建筑完整配置',status='当前 Drawing26 配置范围完成；房间复用已通过体验'),dict(id='T05b',name='普通建筑接入与新数据库导入',status='五层建筑和兼容 ACCDB 首轮接通，浏览/撤销体验通过；其他源模型和动态材料另行适配'),dict(id='T06 / T14',name='气象导入与来源更新',status='当前方案来源概览已接通；气象、建筑配置及材料支持显式更新；原路径恢复体验通过，位置登记已接通；跨建筑房间复用及累计核对已通过体验；五层建筑固定蓬松 ECA 体验及短期核查完成；固定压缩配置已接通；北京全年原构造/固定蓬松对照已完成并附说明接受，沿用原有预热；其他材料范围、批量迁移和新参考日历待推进'),dict(id='T09 / T10',name='数值可靠性整理与论文 Origin 工作流',status='固定 5/15 min 分析、五层短期热工复核已完成；单周前置诊断已收尾，0.1% 不作为推进门槛；北京全年统计与单地点导出已完成，供暖降低、制冷增加、合计需求降低 14.18%；动态可靠性和指定论文图版待推进'),dict(id='T11 / T12',name='计算预算与恢复后续',status='空间预算接入已占输入、确定新增模型副本、同类历史与本批采样，样本不足不外推；同条件性能对照与异盘备份按用户意见暂缓')])
