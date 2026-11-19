"""Registration explanations and adoption guard; no changes to solver adapters."""
import copy

MODELS={
 'optical_surface_v1':'optical',
 'solid_layer_v1':'storage',
 'solid_variable_v1':'storage',
 'equivalent_resistance_no_layer_storage':'resistance',
}
MODES=[
 dict(id='optical',name='仅表面光学',storage=False,resistance=False,
      description='忽略新增材料自身的热阻和蓄热，只改变覆盖后的表面光学；原墙体继续传热和储热。限贴覆不透明墙面／屋面。',
      inputs='覆盖后的太阳吸收率或反射率、长波发射率；可见光参数按需填写。',
      capability='当前按固定光学参数组计算。不计入新增材料层蓄热，当前不能用于新版可调热阻工况。'),
 dict(id='storage',name='计入热阻与蓄热',storage=True,resistance=True,
      description='用完整物性表示实体层；薄膜、涂层和其他材料采用此方式时，均按同一种实体层方法计算。',
      inputs='每个状态的厚度、导热率、密度、比热及表面光学。',
      capability='实体层可固定计算。两态面质量和比热一致时，可在工况中启用统一热阻反馈。双面实体材料可采用各地点的光学切换日历。'),
 dict(id='resistance',name='仅计热阻，不计自身蓄热',storage=False,resistance=True,
      description='用等效热阻表示新增材料层，忽略该层蓄热；原墙体蓄热仍保留。热阻可直接填写或由厚度和导热率计算。',
      inputs='现有等效热阻路线的两个状态及 A/B 两组光学参数；不填写密度、比热。',
      capability='当前不能用于新版可调热阻工况。固定态及固定热阻下的表面光学切换仍受建筑和接法限制，采用时核对；不自动作为任意建筑的通用层。'),
]

def mode(definition):return MODELS.get(definition.get('model'))

def describe(definition):
 key=mode(definition)
 return copy.deepcopy(next((r for r in MODES if r['id']==key),None))

def resistance_template():
 return dict(id='user_resistance_material',name='',kind='single_layer',model='equivalent_resistance_no_layer_storage',state_identity='independent',source_note='',
  states=[dict(id=k,name='状态 '+str(i+1),thermal_input='resistance',resistance_m2K_W=None) for i,k in enumerate(('R','C'))],
  optics={k:dict(input_basis='solar_absorptance',solar_absorptance=None,reflectance=None,emissivity=None) for k in ('A_R','B_R','A_C','B_C')},optics_depend_on_state=False)

def inventory():
 return dict(modes=copy.deepcopy(MODES),models=copy.deepcopy(MODELS),resistance_template=resistance_template(),
  principle='材料名称和形态说明不决定计算方式。计算方式、状态数量与控制工况分别核对。',
  history_note='旧 Drawing26 已保存方案按原适配器和接受范围保留；历史控制能力不作为新登记材料的通用能力。未修改旧输入或结果。')

def check_adoption(record,definition):
 profile=describe(definition)
 if profile and not profile['storage'] and any(c.get('channel')=='thermal' and c.get('mode')=='feedback' for c in record['factors']['condition'].get('controls',[])):
  raise ValueError('此材料不计入新增材料层蓄热，当前不能用于新版可调热阻工况。请先另存并明确改为固定热学状态，再预览选用；已有方案和结果未改变。')
