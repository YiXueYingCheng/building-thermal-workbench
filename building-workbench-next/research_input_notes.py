"""Study-specific input notes, independent of numerical result acceptance.

This notice applies only to the identified five-storey source and the user's
2026-11-11 two-face substrate optics decision. It is not a general building rule.
"""
import math
from foundation import digest

BUILDING='building2_5f_verified'
MODEL_SHA='8c1eed0033002e991c3f3c5f4a6c3f037c408e46ed527c7341ac72b13a4f6551'
ISSUE='five-storey-substrate-optics-20261111'
EXPECTED='135 面外墙基材的室内外两侧：太阳反射率 0.45、发射率 0.85。'
SOURCE_NOTE='这份建筑原始快照的外墙基材反射率为 0.93，部分发射率为 0.988；后来确认的研究基准为 0.45／0.85，修正保存在方案局部构造覆盖中，原快照保持。'

def describe(record,catalog):
    if not isinstance(record,dict) or not isinstance(record.get('factors'),dict) or not isinstance(record['factors'].get('building'),dict):
        raise ValueError('方案建筑配置格式无效。')
    b=record.get('factors',{}).get('building',{})
    if b.get('id')!=BUILDING:return None
    s=catalog.get('ordinary_buildings',{}).get(BUILDING,{})
    out=dict(issue=ISSUE,record_sha256=digest(record),basis='2026-11-11 用户确认的五层基材光学约定',
        expected=EXPECTED,source_note=SOURCE_NOTE,scope='仅核对外墙基材两侧的保存配置；ECA 研究层的 A/B 光学参数另行定义。',
        numerical_acceptance_unchanged=True,source_identity=MODEL_SHA,total_sides=270,matched_sides=0,
        corrected_baseline=dict(id='draft_f919f264196547babf5d46062a6c95f7',revision=6,name='五层建筑 · 原构造基材修正版'))
    def unknown(reason):
        return dict(out,status='unverified',label='基材光学需核对',message=reason)
    if b.get('model_snapshot',{}).get('sha256')!=MODEL_SHA or s.get('models',{}).get('controlled',{}).get('sha256')!=MODEL_SHA:
        return unknown('来源版本已不同，不能沿用此前的基材修正判断。请重新核对研究输入。')
    envelope=s.get('envelope',{})
    selected={k:v for k,v in envelope.items() if v.get('kind')=='BuildingSurface:Detailed' and v.get('type')=='Wall' and v.get('boundary')=='Outdoors'}
    if len(selected)!=135:return unknown('外墙清单与已核对来源不一致，不能判断修正是否齐备。')
    overrides=b.get('envelope_overrides',{})
    if not isinstance(overrides,dict):return unknown('局部构造配置格式待核对。')
    from ordinary_envelope import validate_overrides
    try:validate_overrides(overrides,envelope)
    except (ValueError,KeyError,TypeError,AttributeError):return unknown('局部构造配置尚未通过校验，请先核对修改内容。')
    matched=0;different=[]
    for ident,base in selected.items():
        entry=overrides.get(ident,{})
        if not isinstance(entry,dict):return unknown('局部构造配置格式待核对。')
        layers=entry.get('layers',base.get('layers',[]))
        if not isinstance(layers,list) or len(layers)<2 or len(layers)!=len(base.get('layers',[])):
            return unknown('局部构造层位与来源不同，不能据此确认基材两侧。')
        for side,layer in (('室外侧',layers[0]),('室内侧',layers[-1])):
            values=layer.get('values',{}) if isinstance(layer,dict) else {}
            valid=True
            for field,expected in (('solar_absorptance',.55),('thermal_absorptance',.85)):
                v=values.get(field)
                valid=valid and type(v) in (int,float) and math.isfinite(v) and math.isclose(v,expected,rel_tol=0,abs_tol=1e-12)
            if valid:matched+=1
            else:different.append(dict(surface=ident,side=side))
    out.update(matched_sides=matched,different_sides=different)
    if matched==270:
        return dict(out,status='matches',label='基材光学符合本研究约定',message='此版本的 135 面外墙基材两侧均为反射率 0.45、发射率 0.85。数值警告的复核状态另行显示。')
    return dict(out,status='differs',label='基材光学与本研究约定不同',
        message=f'此版本仅 {matched}/270 个基材侧面符合 0.45／0.85 约定。可保留作历史输入与结果核对，不用于本研究修正基准下的材料对比结论。')

def export_text(note):
    return '' if not note else note['label']+'：'+note['message']+' '+note['scope']
