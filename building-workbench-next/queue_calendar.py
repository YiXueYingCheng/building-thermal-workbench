"""Calendar preview from accepted, input-matched daily queue results. No execution."""
import copy
from pathlib import Path
from foundation import digest,sha,read_json
from model_adapter import VerifiedReader
from component_library import Library
import reference_readiness as rr
import daily_results
import calendar_preview as cp

ACCEPTANCE='accepted_queue_daily_v1'


def choose(candidates):
    eligible=[c for c in candidates if c['input_match'] and c['accepted'] and c['daily']['usable']]
    if not eligible:raise ValueError('没有输入匹配、完整且已接受的逐日参考；未自动补算。')
    if len({c['daily']['csv_sha256'] for c in eligible})!=1:
        raise ValueError('有多份匹配但逐日数值不同的已接受参考，需要明确来源后再保存日历。')
    # Identical CSVs may be repeated/reused queue results. Pin the newest candidate,
    # which reference_readiness orders by batch creation, rather than merge sources.
    return eligible[0],len(eligible)


def derive(candidate,row,root,reader):
    registered=daily_results.registered(root,candidate['batch_id'],candidate['index'])
    if registered!=candidate['daily']:raise ValueError('核对期间逐日来源变化，请重新预览。')
    evidence=candidate['evidence'];result_ref=dict(path=evidence['result_path'],sha256=evidence['result_sha256'])
    result=reader.json(result_ref)
    refs=[result_ref,*[dict(path=p,sha256=h) for p,h in result['artifacts'].items()]]
    review=result.get('scientific_review')
    if review:
        refs += [dict(path=review['original_result'],sha256=review['original_result_sha256']),dict(path=review['evidence'],sha256=review['evidence_sha256'])]
    batches,_=rr.queue_snapshot(root);batch=next(b for b in batches if b['id']==candidate['batch_id'])
    plan,_,folder=rr.frozen_batch(batch,root);case=plan['cases'][candidate['index']]
    refs += [dict(path=str(folder/'plan.json'),sha256=batch['checksum']),dict(path=str(folder/'record.json'),sha256=sha(folder/'record.json')),
        dict(path=str(Path(root)/'data/model-inputs'/plan['bundle_id']/'manifest.json'),sha256=plan['bundle_sha256'])]
    refs += [dict(path=p,sha256=h) for p,h in {**case['dependencies'],**plan['engine_files']}.items()]
    rule_source=dict(path=str(Path(cp.__file__).resolve()),sha256=sha(cp.__file__))
    refs.append(rule_source)
    for ref in refs:reader.check(ref)
    daily=result['daily_reference']['daily']
    preview=cp.calculate([d['heating_kWh'] for d in daily],[d['cooling_kWh'] for d in daily])
    faces=[d['face'] for d in preview['days']]
    entry=dict(source_kind=ACCEPTANCE,source_id=candidate['batch_id']+':'+str(candidate['index']),batch_id=candidate['batch_id'],index=candidate['index'],
        reference_record=dict(id=plan['record_id'],revision=plan['revision'],name=plan['record_name']),
        daily=dict(path=registered['csv_path'],sha256=registered['csv_sha256']),result=result_ref,
        data_sha256=registered['data_sha256'],weather_sha256=row['weather_sha256'],physical_sha256=row['required_physical_sha256'],
        rule_source=rule_source,evidence=sorted({r['path']:r for r in refs}.values(),key=lambda r:r['path']),
        acceptance_label='附说明接受' if review else '核验通过',scientific_review=copy.deepcopy(evidence.get('scientific_review')),
        warnings=result.get('reviewed_warnings',result.get('warnings',[])),calendar=faces,calendar_sha256=digest(faces),switches=preview['switches'],site_id=row['site_id'],city=row['city'])
    preview.update(name=row['city'],source=dict(warnings=entry['warnings'],batch_id=entry['batch_id'],acceptance_label=entry['acceptance_label']),rule=cp.PARAMETERS)
    return preview,entry


def gather(record,catalog,root,transition_confirmations=None,basis=None):
    import transition_confirmation as tc
    choices=tc.selections(tc.saved_selections(record) if transition_confirmations is None else transition_confirmations)
    tc.require(set(choices)<=set(record['factors']['scope']['site_ids']),'季节确认地点不在当前范围。')
    annual=copy.deepcopy(record);annual['factors']['scope']['period']=[1,1,12,31]
    inspected=rr.build(annual,catalog,root,accepted_only=True);reader=VerifiedReader(catalog);rows=[];entries=[]
    issues=list(inspected['issues'])
    for position,row in enumerate(inspected['rows']):
        from inspection_io import progress
        progress('推导光学切换日历',position,len(inspected['rows']),row['city'])
        item=dict(site_id=row['site_id'],city=row['city'],ready=False,issues=list(row['issues']),preview=None);rows.append(item)
        try:
            candidate,count=choose(row['candidates']);preview,entry=derive(candidate,row,root,reader)
            item.update(preview=preview,source=dict(batch_id=entry['batch_id'],index=entry['index'],record=entry['reference_record'],
                acceptance_label=entry['acceptance_label'],scientific_review=entry['scientific_review'],identical_candidates=count))
            if item['issues']:continue
            if preview['transition_review_needed'] or row['site_id'] in choices:
                if basis is None and len(preview['switches'])>=4:
                    from calendar_library import definition
                    basis=definition(record,catalog)
                approved,status=tc.review_entry(basis or {},preview,entry,choices);item['transition_review']=status
                if approved is None:raise ValueError('出现多段或不确定季节，可查看完整曲线，但保存前需共同确认，不自动合并。')
                entry=approved
                item['preview']=tc.applied_preview(preview,entry)
            entries.append(entry);item['ready']=True
        except (ValueError,KeyError,TypeError,OSError) as exc:item['issues'].append(str(exc))
    try:reader.unchanged()
    except (ValueError,OSError) as exc:
        issues.append(str(exc));entries=[]
        for row in rows:row.update(ready=False,preview=None);row['issues'].append('核对期间来源变化。')
    return rows,entries,issues


def history(content,root):
    from calendar_library import verify_reference,snapshot_reference
    rows=[];latest={}
    for s in Library(root).all('calendar'):
        c=s['content']
        if c.get('schema_version')!=2 or c.get('acceptance')!=ACCEPTANCE or c.get('basis',{}).get('building',{}).get('id')!=content['basis']['building']['id']:continue
        verify_reference(snapshot_reference(s))
        rows.append({k:s[k] for k in ('id','revision','name','created','sha256')} | dict(matches_current=c==content if 'sites' in content else None))
        if s['revision']>latest.get(s['id'],{}).get('revision',0):latest[s['id']]=s
    return rows,[{k:s[k] for k in ('id','revision','name')} for s in latest.values()]


def prepare(record,catalog,root,out,basis,transition_confirmations=None):
    from calendar_library import stable_numbers
    rows,entries,issues=gather(record,catalog,root,transition_confirmations,basis)
    out.update(phase='inspected',source_kind=ACCEPTANCE,rows=rows,issues=issues,
        application_issues=['本建筑已接通日历预览和独立版本；表面光学切换尚待适配，本轮不能启用光学切换。'],
        acceptance_note='采用统一队列中已核验并接受的原构造逐日结果；保留原警告与具体接受依据。保存前会重新核对当前输入、结果文件和日历规则。',
        rule_note='参考年首尾循环衔接；全年次要冷热需求占比低于 2% 时沿用全年固定光学参数组分支。这里没有增加建筑预热或追加天气年。')
    out['history'],out['parent_options']=history(dict(basis=basis),root)
    if not rows or len(entries)!=len(rows) or issues:return out
    content=stable_numbers(dict(schema_version=2,basis=basis,rule=cp.PARAMETERS,sites=sorted(entries,key=lambda r:r['site_id']),acceptance=ACCEPTANCE))
    versions,parents=history(content,root)
    out.update(can_save=True,content=content,content_sha256=digest(content),versions=[v for v in versions if v['matches_current']],history=versions,parent_options=parents)
    from surface_materials import enabled as physical_surface
    if physical_surface(record) or record['provenance']['adapter']=='global_frozen_v011':
        from calendar_library import with_reference,temporary_snapshot
        from model_adapter import compile_case
        from inspection_io import progress
        candidate=with_reference(record,temporary_snapshot(content))
        for position,row in enumerate(rows):
            progress('核对表面光学切换模型',position,len(rows),row['city'])
            try:
                _,audit=compile_case(candidate,row['site_id'],catalog)
                row['orientation_input']=dict(status='input_ready',note='本方案日历、材料作用范围与模型输入核对通过。',calendar_sha256=audit['calendar_binding']['calendar_sha256'])
            except (ValueError,KeyError,TypeError,OSError) as exc:row['orientation_input']=dict(status='blocked',note=str(exc))
        progress('完成日历与输入核对',len(rows),len(rows),'')
        out['can_apply']=all(row['orientation_input']['status']=='input_ready' for row in rows)
        out['application_issues']=[row['orientation_input']['note'] for row in rows if row['orientation_input']['status']!='input_ready']
        return out
    from ordinary_orientation import inspect
    from inspection_io import progress
    for position,row in enumerate(rows):
        progress('核对表面光学切换模型',position,len(rows),row['city'])
        row['orientation_input']=inspect(record,catalog,content,row['site_id'])
    progress('完成日历与输入核对',len(rows),len(rows),'')
    if all(row['orientation_input']['status']=='input_ready' for row in rows):
        from ordinary_orientation import EXECUTION_VERIFIED
        out['can_apply']=EXECUTION_VERIFIED
        out['application_issues']=[] if EXECUTION_VERIFIED else ['双面材料与日历接线已核对；短期实跑尚未完成。']
    else:
        out['application_issues']=list(dict.fromkeys(row['orientation_input']['note'] for row in rows if row['orientation_input']['status']!='input_ready'))
    return out

def verify_for_site(record,catalog,ref,site_id,reader):
    """Recheck queue evidence, current annual physics and the derived calendar."""
    from calendar_library import bound
    from reference_readiness import baseline,physical
    from model_adapter import compile_case
    import transition_confirmation as tc
    content=ref['snapshot']['content'];row=bound(record,catalog,ref)[site_id]
    if content.get('acceptance')!=ACCEPTANCE:raise ValueError('需要已接受的本工作区逐日参考。')
    for source in [*row['evidence'],row['daily'],row['result']]:reader.check(source)
    original=baseline(record);original['factors']['scope']['period']=[1,1,12,31]
    model,audit=compile_case(original,site_id,catalog,reader,'controlled')
    dependencies={x['path']:x['sha256'] for x in audit['dependencies']}
    if physical(model,dependencies,reader)!=row['physical_sha256']:raise ValueError('当前原构造输入与逐日参考不同。')
    result=reader.json(row['result'])
    if result.get('status')!='passed':raise ValueError('日历参考结果尚未核验通过。')
    daily=result['daily_reference']['daily']
    verified=cp.calculate([d['heating_kWh'] for d in daily],[d['cooling_kWh'] for d in daily])
    tc.verify_entry(content['basis'],verified,row)


def check_parent(content,parent,library):
    if not isinstance(parent,dict) or set(parent)!={'id','revision'}:raise ValueError('日历父版本选择不完整。')
    old=[s for s in library.all('calendar') if s['id']==parent['id']]
    if not old:raise ValueError('所选日历版本不存在。')
    previous=max(old,key=lambda s:s['revision'])
    if previous['revision']!=parent['revision']:raise ValueError('该日历已有新版本，请重新预览。')
    c=previous['content']
    if c.get('schema_version')!=2 or c.get('acceptance')!=ACCEPTANCE or c['basis']['building']['id']!=content['basis']['building']['id']:
        raise ValueError('新版本必须属于同一建筑的队列逐日日历。')
    return previous
