"""Validated 1 min solve / 5 min decision / 60 min hold controller.

Temperature and outward-negative EP conduction are captured after reporting.
Decisions use the previous completed step; warmup is not feedback-controlled.
Optical control is independently installed by ordinary_orientation.
"""
from solid_eca import PREFIX as P

def programs(walls):
    fmt=lambda v:format(v,'.15g')
    init=[f'SET {P}_State = 1',f'SET {P}_Want = 1',f'SET {P}_Age = 0',f'SET {P}_Clock = 0',f'SET {P}_Ready = 0',f'SET {P}_Changed = 0',f'SET {P}_Vote = 0']
    update=[f'SET {P}_Changed = 0',f'IF WarmupFlag == 0 && {P}_Ready == 1',f'SET {P}_Age = {P}_Age + 1',f'SET {P}_Clock = {P}_Clock + 1',f'IF {P}_Clock >= 5',f'SET {P}_Clock = 0',f'SET {P}_Vote = 0']
    capture=['IF WarmupFlag == 0']
    for w in walls:
        name=f'{P}_{w["id"]}'
        init += [f'SET {name}_LastT = 20',f'SET {name}_LastQ = 0',f'SET {name}_Phase = 0',f'SET {name}_Vote = 0']
        update += [f'SET {name}_Phase = 0',f'SET {name}_Vote = 0',f'IF {name}_LastT < 18',f'SET {name}_Phase = -1',f'ELSEIF {name}_LastT > 26',f'SET {name}_Phase = 1','ENDIF',f'IF {name}_LastQ > 1 || {name}_LastQ < (0 - 1)',f'SET {name}_Vote = {name}_Phase * {name}_LastQ','ENDIF',f'SET {P}_Vote = {P}_Vote + ({name}_Vote * {fmt(w["net_m2"])})']
        capture += [f'SET {name}_LastT = {name}_T',f'SET {name}_LastQ = 0 - {name}_Q']
    area=fmt(sum(w['net_m2'] for w in walls))
    update += [f'SET {P}_Want = {P}_State',f'IF {P}_Vote > {area}',f'SET {P}_Want = 0',f'ELSEIF {P}_Vote < (0 - {area})',f'SET {P}_Want = 1','ENDIF',f'IF {P}_Want <> {P}_State && {P}_Age >= 60',f'SET {P}_State = {P}_Want',f'SET {P}_Age = 0',f'SET {P}_Changed = 1','ENDIF','ENDIF','ENDIF']
    capture += [f'SET {P}_Ready = 1','ENDIF']
    return dict(Initialize=init,Update=update,Capture=capture)

def control(m,walls,layer,mapping):
    if any(str(k).startswith(P) for obj in m.values() if isinstance(obj,dict) for k in obj):raise ValueError('反馈对象名称冲突。')
    def add(kind,name,value):m.setdefault(kind,{})[name]=value
    for w in walls:
        name=f'{P}_{w["id"]}'
        add('EnergyManagementSystem:Actuator',name+'_K',dict(actuated_component_unique_name=w['id']+':'+layer,actuated_component_type='CondFD Surface Material Layer',actuated_component_control_type='Thermal Conductivity'))
        for suffix,key,var in [('T',w['zone'],'Zone Mean Air Temperature'),('Q',w['id'],'Surface Outside Face Conduction Heat Transfer Rate per Area')]:
            add('EnergyManagementSystem:Sensor',name+'_'+suffix,dict(output_variable_or_output_meter_index_key_name=key,output_variable_or_output_meter_name=var))
    ps=programs(walls)
    ps['Apply']=[f'IF {P}_State == 0',f'SET {P}_Keff = {mapping["states"]["R"]["conductivity"]:.15g}','ELSE',f'SET {P}_Keff = {mapping["states"]["C"]["conductivity"]:.15g}','ENDIF']+[f'SET {P}_{w["id"]}_K = {P}_Keff' for w in walls]
    variables=[P+'_'+s for s in ('State','Want','Age','Clock','Ready','Changed','Vote','Keff')]+[f'{P}_{w["id"]}_{s}' for w in walls for s in ('LastT','LastQ','Phase','Vote')]
    add('EnergyManagementSystem:GlobalVariable',P+'_Variables',dict(variables=[dict(erl_variable_name=v) for v in variables]))
    for k,lines in ps.items():add('EnergyManagementSystem:Program',P+'_'+k,dict(lines=[dict(program_line=s) for s in lines]))
    for name,point,names in [('Init','BeginNewEnvironment',['Initialize']),('Reset','AfterNewEnvironmentWarmUpIsComplete',['Initialize']),('Control','BeginZoneTimestepBeforeInitHeatBalance',['Update','Apply']),('Capture','EndOfZoneTimestepAfterZoneReporting',['Capture'])]:
        add('EnergyManagementSystem:ProgramCallingManager',P+'_'+name,dict(energyplus_model_calling_point=point,programs=[dict(program_name=P+'_'+n) for n in names]))
    # Small summaries. Detailed minute probes belong to isolated diagnostics.
    for s,kind in [('State','Averaged'),('Changed','Summed')]:
        name=P+'_'+s+'Output'
        add('EnergyManagementSystem:OutputVariable',name,dict(ems_variable_name=P+'_'+s,type_of_data_in_variable=kind,update_frequency='ZoneTimestep'))
        for freq in ('Daily','Monthly','RunPeriod'):add('Output:Variable',name+'_'+freq,dict(key_value='*',variable_name=name,reporting_frequency=freq))
