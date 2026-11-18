"""Versioned regional selection aid. Previews never write schemes or submit jobs."""
from pathlib import Path
import copy
from foundation import read_json, digest, ROOT
from scope_management import scope_value, weather_detail, registered
from starter_library import bundled_file

REGIONS = frozenset('110000 120000 130000 140000 150000 210000 220000 230000 310000 320000 330000 340000 350000 360000 370000 410000 420000 430000 440000 450000 460000 500000 510000 520000 530000 540000 610000 620000 630000 640000 650000 710000 810000 820000'.split())


def public_preset(catalog):
    """Resolve bundled download identities to this workspace's registered site IDs."""
    rows=[r for r in read_json(bundled_file('examples/weather/sources.json'))['weather'] if r['source_group']=='china34']
    regions=[]
    for row in rows:
        candidates=sorted((s for s in registered(catalog).values() if s.get('eligible') and s.get('weather',{}).get('sha256')==row['epw_sha256']),key=lambda s:s['id'])
        site=candidates[0] if candidates else {}
        candidate=dict(site_id=site.get('id',row['id']),default=True,city=row['name'],climate=site.get('climate'),
            sha256=row['epw_sha256'],dataset=row['dataset'],source_url=row['source_url'],
            reason='公开下载清单中的地区预设地点；按气象文件校验值匹配本工作区登记。',
            climate_sampling='沿用本工作区已登记分类；未分类不自动推断。',
            header={k:site.get(k) for k in ('station','elevation','latitude','longitude')},metrics=None)
        regions.append(dict(id=row['id'].removeprefix('china34_'),name=row['region'],candidates=[candidate]))
    data=dict(kind='public_download_catalog',regions=regions,
        note='本预设来自随包公开的下载清单；先在“气象下载”选择中国 34 地区，下载并登记后回来选择。仅下载到文件夹还不算登记；同名城市的不同气象文件不自动替代。')
    return dict(data=data,sha256=digest(data))


def describe(catalog, root=ROOT):
    file=Path(root)/'data/china34-preset.json'
    packet = read_json(file) if file.is_file() else public_preset(catalog)
    data = packet['data']
    if digest(data) != packet['sha256']:
        raise ValueError('中国 34 地区预设内容校验失败。')
    regions = data['regions']
    if len(regions) != 34 or {r['id'] for r in regions} != REGIONS:
        raise ValueError('预设地区清单不完整。')
    result = copy.deepcopy(data)
    result['checksum'] = packet['sha256']
    seen = set()
    for region in result['regions']:
        options = region['candidates']
        if not options or sum(bool(c['default']) for c in options) != 1:
            raise ValueError('每个地区应有一个默认地点。')
        for c in options:
            ident = c['site_id']
            if ident in seen:
                raise ValueError('预设含重复地点或地区归属。')
            seen.add(ident)
            site = catalog['sites'].get(ident, {})
            c['available'] = bool(site.get('eligible') and site.get('weather', {}).get('sha256') == c['sha256'] and site.get('climate') == c['climate'])
            c['unavailable_reason'] = '' if c['available'] else ('此预设气象尚未登记；请到“气象下载”下载并登记后重新打开。' if data.get('kind')=='public_download_catalog' else '登记气象缺失、暂缓，或内容标识/气候分类已变化，请核对来源。')
    result['available_regions']=sum(any(c['available'] for c in r['candidates']) for r in result['regions'])
    return result


def preview(current, selection, checksum, catalog, root=ROOT):
    data = describe(catalog, root)
    if checksum != data['checksum']:
        raise ValueError('预设已更新，请关闭后重新打开。')
    if not isinstance(selection, dict) or set(selection) != REGIONS or any(not isinstance(v,str) for v in selection.values()):
        raise ValueError('请为 34 个地区分别选择一个地点。')
    before = scope_value(current, catalog, allow_empty=True)
    selected = []
    for region in data['regions']:
        c = next((c for c in region['candidates'] if c['site_id'] == selection[region['id']]), None)
        if not c or not c['available']:
            raise ValueError('请选择本地区可用候选：'+region['name'])
        checked = weather_detail(c['site_id'], catalog)
        if checked['status'] != 'matches' or checked['actual_sha256'] != c['sha256']:
            raise ValueError(region['name']+' · '+c['city']+'：气象文件无法通过身份核对，请检查来源。')
        selected.append(dict(region_id=region['id'],region=region['name'],site_id=c['site_id'],city=c['city'],climate=c['climate'],dataset=c['dataset'],sha256=c['sha256']))
    ids = [c['site_id'] for c in selected]
    after = scope_value(dict(site_ids=ids, period=before['period']), catalog)
    after['site_ids'] = [i for i in current['site_ids'] if i in ids]+[i for i in ids if i not in before['site_ids']]
    return dict(checksum=data['checksum'],selection=selection,scope=after,regions=selected,
                added=[i for i in ids if i not in before['site_ids']],removed=[i for i in current['site_ids'] if i not in ids],
                files_checked=True,period_preserved=True,
                note='替换当前全部地点；时段和其他因素保留。各城市结果不代表全省平均，当前结果仍沿用地点及气候类型视图。')
