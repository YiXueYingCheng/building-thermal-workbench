"""Preview adoption of a pinned component's newer version, without writes or control resets."""
import copy
from foundation import ROOT,digest,now
from component_library import Library,verify
from contracts import normalize,validate,recipe_digest

def pinned(record,kind):
    if kind=='usage':return record['factors']['building'].get('usage_profile')
    if kind=='material':return record['factors']['materials'].get('definition_reference')
    raise ValueError('当前更新支持建筑使用配置和材料版本。')

def describe(record,root=ROOT):
    rows=[]
    for kind,label in (('usage','建筑使用配置'),('material','材料')):
        old=pinned(record,kind)
        row=dict(kind=kind,label=label,current=None,latest=None,status='unbound',note='当前使用方案内取值，未绑定可检查更新的库版本。')
        if old:
            verify(old,kind);versions=[v for v in Library(root).all(kind) if v['id']==old['id']]
            current=next((v for v in versions if v['revision']==old['revision']),None)
            row.update(current=copy.deepcopy(old),status='pinned_only',note='保留方案中的版本快照；当前库未包含该保存版本。')
            if current and current!=old:row.update(status='conflict',note='库中同编号版本与方案快照不同，需先核对来源。')
            elif current:
                latest=max(versions,key=lambda v:v['revision']);newer=latest['revision']>old['revision']
                row.update(latest=latest,status='update_available' if newer else 'current',note='发现新版本，采用前查看差异。' if newer else '当前已绑定此配置的最新库版本。')
        rows.append(row)
    # Keep enumeration small; full content is returned only by the preview.
    for row in rows:
        for key in ('current','latest'):
            if row[key]:row[key]={k:v for k,v in row[key].items() if k!='content'}
    return dict(components=rows,record_sha256=digest(record),checked_at=now(),note='库的新版本不会自动追改方案。日计划继续随建筑配置快照保留；日计划更新先在建筑配置中明确采用。')

def preview(record,kind,target,catalog,root=ROOT):
    old=pinned(record,kind)
    if not old:raise ValueError('当前未绑定该类库版本，请从原编辑入口选择配置。')
    verify(old,kind)
    if not isinstance(target,dict) or set(target)!={'id','revision','sha256'}:raise ValueError('请选择明确的新版本及其校验标识。')
    if target['id']!=old['id'] or type(target['revision']) is not int or target['revision']<=old['revision']:raise ValueError('本入口只采用同一配置的较新版本，不更换建筑或材料身份。')
    versions=Library(root).all(kind)
    if next((v for v in versions if v['id']==old['id'] and v['revision']==old['revision']),None)!=old:raise ValueError('原库版本缺失或与方案快照不一致，请先核对来源。')
    new=next((v for v in versions if v['id']==target['id'] and v['revision']==target['revision']),None)
    if not new or new['sha256']!=target['sha256']:raise ValueError('所选新版本内容已变化或不存在，请刷新列表。')
    out=copy.deepcopy(record);notes=[];room_diff=None;fields=[]
    if kind=='usage':
        from building_configuration import preview as configuration_preview,validate_content
        from room_configuration import differences,context_notes
        context=configuration_preview(record,catalog,root)
        validate_content(old['content'],context['base']);validate_content(new['content'],context['base'])
        room_diff=differences(old['content'],new['content'],context['base'],context['gain_defaults'])
        notes=context_notes(room_diff,new['content'],record['factors']['condition']['operation'].get('overrides',{}),record['factors']['condition']['operation']['mode'])
        out['factors']['building']['usage_profile']=copy.deepcopy(new)
    else:
        definitions=normalize(record)['factors']['materials']['definitions']
        normalized_old=normalize({'factors':{'materials':{'definitions':[old['content']]}}})['factors']['materials']['definitions']
        if definitions!=normalized_old:raise ValueError('当前材料有未入库修改，请先保存材料版本，不能覆盖这些编辑。')
        if new['content'].get('id')!=old['content'].get('id'):raise ValueError('新版本改变了材料身份，需从材料应用入口核对后选择。')
        from model_adapter import changes
        fields=changes(old['content'],new['content'])
        out['factors']['materials']['definitions']=[copy.deepcopy(new['content'])]
        out['factors']['materials']['definition_reference']=copy.deepcopy(new)
        notes=['保留当前材料应用、构件范围、固定/反馈规则及热学状态和光学参数组；本入口不恢复模板控制。']
    out=normalize(out);errors=validate(out,catalog['sites'])
    if errors:raise ValueError('更新后配置不完整：'+'；'.join(errors))
    from model_adapter import capability
    cap=capability(out,catalog)
    if not cap['supported']:raise ValueError('该更新与本方案不兼容：'+'；'.join(cap['reasons']))
    return dict(kind=kind,before=old,after=new,checked_at=now(),content_changed=old['content']!=new['content'],
        fields=fields,room_diff=room_diff,notes=notes,generation=cap,record_sha256=digest(record),
        recipe_before=recipe_digest(record),recipe_after=recipe_digest(out),
        note='仅更新当前编辑所绑定的这一配置版本，仍需保存方案。其他方案、旧版本、计算清单和结果保持原绑定。')
