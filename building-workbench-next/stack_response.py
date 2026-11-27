"""Selected material boundaries in the frozen wall construction, outside to inside."""
import csv
import datetime as dt
import math

from foundation import sha

NODE = 'CondFD Surface Temperature Node '
FACE = 'NX_SC_FaceOutput'
STATE = 'NX_SC_StackStateOutput'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def finite_difference(model, wall):
    for kind, field, key in (
        ('SurfaceProperty:HeatTransferAlgorithm', 'surface_name', wall['surface']),
        ('SurfaceProperty:HeatTransferAlgorithm:Construction', 'construction_name', wall['construction']),
    ):
        for rule in model.get(kind, {}).values():
            if rule[field].casefold() == key.casefold():
                return rule['algorithm'].casefold() == 'conductionfinitedifference'
    global_rule = next(iter(model.get('HeatBalanceAlgorithm', {}).values()), {})
    return global_rule.get('algorithm', '').casefold() == 'conductionfinitedifference'


def grid_elements(model):
    timestep = 3600 / next(iter(model['Timestep'].values()))['number_of_timesteps_per_hour']
    delta = int(timestep / math.ceil(timestep / 200))
    settings = next(iter(model.get('HeatBalanceSettings:ConductionFiniteDifference', {}).values()), {})
    spacing = settings.get('space_discretization_constant', 3.)
    def elements(name):
        if name in model.get('Material:NoMass', {}) or name in model.get('Material:AirGap', {}):
            return 1
        m = model.get('Material', {}).get(name)
        require(m, '无法核对原构造层的有限差分节点：' + name)
        alpha = m['conductivity'] / (m['density'] * m['specific_heat'])
        return max(1, int(m['thickness'] / math.sqrt(alpha * delta * spacing)))
    return elements

def request_writer(model,contract):
    requests = model.setdefault('Output:Variable', {})
    known = {(r.get('key_value','*').upper(), r['variable_name'].upper(), r['reporting_frequency'].upper())
             for r in requests.values()}
    def request(key, variable):
        for frequency in (('Timestep','Monthly','RunPeriod') if contract == 'timeseries_timestep_v1' else ('Timestep',)):
            token = (key.upper(),variable.upper(),frequency.upper())
            if token in known or ('*',*token[1:]) in known:
                continue
            name = 'WB_StackTrace_' + str(len(requests))
            while name in requests:
                name += '_'
            requests[name] = dict(key_value=key, variable_name=variable, reporting_frequency=frequency)
            known.add(token)
    return request


def configure(model, audit, choices, contract):
    require(audit.get('model') == 'layer_stack_v1', '材料响应选项对应的组合材料已经变更，请重新选墙、选层。')
    require(isinstance(choices, list), '材料响应选择无效。')
    require(contract != 'daily_sensible_reference_v1', '逐日原墙参考不能包含组合材料测点。')
    walls = {row['surface']: row for row in audit['surfaces']}
    layers = audit['layers']
    elements = grid_elements(model)
    request = request_writer(model,contract)
    results = []
    seen = set()
    for choice in choices:
        require(isinstance(choice,dict), '请选择材料响应墙与层。')
        wall = walls.get(choice.get('wall'))
        n = choice.get('layer')
        require(wall and type(n) is int and 1 <= n <= len(layers), '所选墙或层已离开本方案铺设范围，请重新选择。')
        leaf = layers[n-1]
        require(leaf['model'] != 'optical_surface_v1' and choice.get('sha256') == leaf['sha256'],
                '所选层版本已改变，或是无独立厚度的表面涂层，请重选实体层。')
        require((wall['surface'],n) not in seen, '材料响应测点重复。')
        seen.add((wall['surface'],n))
        require(finite_difference(model,wall), wall['surface']+' 当前传热算法未计算内部节点温度，请移除此测点或选择有限差分构件。')
        solid_index = sum(x['model']!='optical_surface_v1' for x in layers[:n])-1
        key = wall['inserted_layers'][solid_index]
        prefix = wall['layers_after'][:wall['layers_after'].index(key)+1]
        grid = [(name,elements(name)) for name in prefix]
        outside = 1+sum(count for _,count in grid[:-1])
        inside = outside+grid[-1][1]
        face = audit.get('face') if audit.get('position')=='exterior' else None
        switched = bool(audit.get('calendar_optics'))
        feedback = wall.get('thermal_mode') == 'feedback'
        control = audit.get('controlled_layer')
        current = layers[control-1] if control else leaf
        if switched:
            request('*', FACE)
        if feedback:
            request('*', STATE)
        for node in (outside,inside):
            request(wall['surface'],NODE+str(node))
        results.append(dict(wall=wall['surface'],layer=n,name=leaf['name'],revision=leaf['revision'],sha256=leaf['sha256'],
                            outside=outside,inside=inside,grid=grid,face=face,switched=switched,feedback=feedback,
                            control_layer=control,control_name=current['name'],fixed_state=current['state']))
    return results


def change_step(model,case,contract):
    elements = grid_elements(model)
    model['Output:Variable'] = {k:v for k,v in model['Output:Variable'].items() if not k.startswith('WB_StackTrace_')}
    request = request_writer(model,contract)
    for item in case['stack_response']:
        grid = [(name,elements(name)) for name,_ in item['grid']]
        outer = 1+sum(n for _,n in grid[:-1])
        item.update(grid=grid,outside=outer,inside=outer+grid[-1][1])
        for _, key, name in signals(item):
            request('*' if key=='EMS' else key,name)


def signals(item):
    values = [('outside',item['wall'],NODE+str(item['outside'])),('inside',item['wall'],NODE+str(item['inside']))]
    if item['switched']:
        values.append(('face','EMS',FACE))
    if item['feedback']:
        values.append(('state','EMS',STATE))
    return values


def attach(model, folder, row, record, contract):
    choices = record.get('execution',{}).get('stack_response',[])
    if not choices:
        return []
    from input_pipeline import read_audit
    audit = read_audit(folder,row).get('material_application',{})
    return configure(model,audit,choices,contract)


def dictionary(db,item):
    ids = {}
    for field,key,var in signals(item):
        rows = db.execute("""SELECT ReportDataDictionaryIndex,Units FROM ReportDataDictionary
              WHERE ReportingFrequency='Zone Timestep' AND KeyValue=? COLLATE NOCASE AND Name=? COLLATE NOCASE""",(key,var)).fetchall()
        require(len(rows)==1 and (field not in ('outside','inside') or rows[0][1]=='C'),
                item['wall']+' 缺少指定逐步输出或单位不符：'+var)
        ids[rows[0][0]] = field
    return ids


def verify(db, folder, items, steps):
    grids = {}
    eio = folder/'eplusout.eio'
    with eio.open(encoding='utf8',errors='replace',newline='') as f:
        for line in csv.reader(f):
            if line and line[0].strip()=='Material CondFD Summary':
                grids.setdefault(line[1].strip().upper(),set()).add(int(line[3]))
    checked = set()
    for item in items:
        for name,count in item['grid']:
            require(grids.get(name.upper())=={count}, '引擎报告的层网格与所选温度节点不符：'+name)
        for ident,field in dictionary(db,item).items():
            if ident in checked:
                continue
            n,u,lo,hi = db.execute("""SELECT count(r.Value),count(DISTINCT r.TimeIndex),min(r.Value),max(r.Value)
                FROM ReportData r JOIN Time t USING(TimeIndex) WHERE r.ReportDataDictionaryIndex=?
                AND t.IntervalType=-1 AND coalesce(t.WarmupFlag,0)=0""",(ident,)).fetchone()
            require(n==u==steps and math.isfinite(lo) and math.isfinite(hi), '材料响应逐步记录缺失或重复。')
            if field in ('face','state'):
                require(not db.execute('SELECT 1 FROM ReportData WHERE ReportDataDictionaryIndex=? AND Value NOT IN (0,1) LIMIT 1',(ident,)).fetchone(),
                        '材料控制信号出现非离散值。')
            checked.add(ident)
    return dict(selections=items,steps=steps,grid_sha256=sha(eio))


def read(root,batch,index,wall,layer,date):
    from result_timeline import source
    with source(root,batch,index) as (db,raw,env,out):
        items = raw.get('stack_response',{}).get('selections',[])
        item = next((i for i in items if i['wall']==wall and i['layer']==layer),None)
        require(item, '该结果未保存这面墙和这一层的逐步响应。')
        start = dt.date(2025,*out['period'][:2])
        end = dt.date(2025,*out['period'][2:])
        try:
            day = dt.date.fromisoformat('2025-'+date)
        except (ValueError,TypeError) as exc:
            raise ValueError('日期格式应为 MM-DD。') from exc
        require(start<=day<=end, '请选择计算时段内的日期。')
        ids = dictionary(db,item)
        step = raw['step_minutes']
        previous = day-dt.timedelta(days=1)
        slots = {}
        for ident,field in ids.items():
            for m,d,minute,v in db.execute("""SELECT t.Month,t.Day,t.Hour*60+t.Minute,r.Value
                FROM ReportData r JOIN Time t USING(TimeIndex)
                WHERE r.ReportDataDictionaryIndex=? AND t.EnvironmentPeriodIndex=? AND t.IntervalType=-1
                AND coalesce(t.WarmupFlag,0)=0 AND ((t.Month=? AND t.Day=?)
                OR (t.Month=? AND t.Day=? AND t.Hour*60+t.Minute=1440))""",
                (ident,env,day.month,day.day,previous.month,previous.day)):
                slot = minute-step if (m,d)==(day.month,day.day) else -step
                point = slots.setdefault(slot, {})
                require(field not in point and math.isfinite(v),'响应时刻重复或数值无效。')
                point[field] = v
        expected = list(range(0,1440,step))
        if day>start:
            expected.insert(0,-step)
        require(sorted(slots)==expected and all(len(p)==len(ids) for p in slots.values()), '所选日期的响应时间轴不完整。')
        out.update(selection=item,date=date,points=[
            [t,slots[t]['outside'],slots[t]['inside'],('A' if slots[t]['face']==1 else 'B') if item['switched'] else item['face'],
             ('C' if slots[t]['state']==1 else 'R') if item['feedback'] else item['fixed_state']] for t in expected])
    return out
