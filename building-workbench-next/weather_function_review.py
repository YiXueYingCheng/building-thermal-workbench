"""Bounded full-year weather-function evidence. Never runs or changes a building."""
import datetime as dt,math,re,time

def require(ok,message):
 if not ok:raise ValueError(message)

def weather_values(rows):
 values=[[float(r[k]) for k in (6,8,9)] for r in rows]
 # Exact WeatherManager.cc: RH >110 increments an out-of-range counter but
 # remains the hourly value; negative/missing RH and invalid pressure follow
 # replacement paths. Reject those unsupported replacement paths here.
 # Values over 110 remain source-quality notes, never silently clamped.
 require(all(all(math.isfinite(x) for x in row) and -90<=row[0]<=70 and 0<=row[1]<999 and 31000<row[2]<=120000 for row in values),'气象包含缺测、替换或超出本次函数核查范围的温度、湿度或压力；原文件未修正。')
 return values

def scan(rows,state,psy,ns):
 require(len(rows)==8760,'函数核查需要完整 8760 小时气象。')
 values=weather_values(rows);events=[];max_error=0.;mismatch=0;finite=True;nonconverged=0;start=time.monotonic()
 psat=lambda t:psy.saturation_pressure(state,t)
 for hour,b in enumerate(values):
  a=values[hour-1]
  for step in range(1,13):
   f=step/12;dry,rh,p=[x*(1-f)+y*f for x,y in zip(a,b)]
   w=psy.humidity_ratio_c(state,dry,rh/100,p);wet=psy.wet_bulb(state,dry,w,p);trace=ns['wet_iteration'](dry,w,p,psat)
   error=abs(trace['wet_C']-wet);max_error=max(max_error,error);mismatch+=error>1e-7;finite&=all(math.isfinite(v) for v in (w,wet,trace['wet_C']));nonconverged+=not trace['converged']
   if trace['extreme_guesses_C'] or not trace['converged'] or error>1e-7:
    stamp=dt.datetime(2001,1,1)+dt.timedelta(minutes=hour*60+step*5)
    trace=ns['wet_iteration'](dry,w,p,psat,keep=True);roots=ns['branch_roots'](ns['quantize'](dry),ns['quantize'](w),ns['quantize'](p),psat)
    events.append(dict(time=stamp.strftime('%m/%d %H:%M'),dry_C=dry,RH_pct=rh,pressure_Pa=p,humidity_ratio=w,native_wet_C=wet,trace=trace,bounded_roots=roots,trace_API_delta_C=error))
 return dict(sample_count=105120,all_API_outputs_finite=finite,max_trace_API_difference_C=max_error,mismatch_count=mismatch,nonconverged_count=nonconverged,events=events,elapsed_seconds=time.monotonic()-start,RH_above_100_hours=sum(v[1]>100 for v in values),RH_above_110_hours=sum(v[1]>110 for v in values),RH_above_110_examples=[dict(month=int(r[1]),day=int(r[2]),hour=int(r[3]),RH_pct=v[1]) for r,v in zip(rows,values) if v[1]>110][:10],max_RH_pct=max(v[1] for v in values),weather_values_changed=False,
  limits=['逐个天气输入的函数实验，不声称重放原建筑的完整缓存状态。','1 月 1 日的前一小时采用循环年末时刻；须同时吻合原计算首个事件、总次数与极值。'])

def validate(scan,blocks):
 require(len(blocks)==2 and all(b[0]=='Temperature out of range [-100. to 200.] (PsyPsatFnTemp)' for b in blocks),'函数日志类型超出本次方法。')
 first=' '.join(blocks[0]);summary=' '.join(blocks[1])
 require('Routine=PsyTwbFnTdbWPb' in first,'越界事件不是已核对的湿球函数路径。')
 t=re.search(r'Simulation time=(\d+)/(\d+) (\d+):(\d+) - (\d+):(\d+)',first)
 count=re.search(r'This error occurred (\d+) total times;',summary)
 extremes=re.search(r'Max=([-+\d.eE]+) C\s+Min=([-+\d.eE]+) C',summary)
 input_value=re.search(r'Input Temperature=([-+\d.eE]+)',first)
 require(t and count and extremes and input_value,'原日志缺少事件时刻、次数或极值。')
 require('during Warmup 0 times;' in summary and 'during Sizing 0 times.' in summary,'含预热或设计日事件，需独立分析。')
 require(scan['sample_count']==105120 and scan['all_API_outputs_finite'] and scan['mismatch_count']==0 and scan['nonconverged_count']==0,'全年函数核查含不收敛、非有限或重放差异，不能直接接受。')
 events=scan['events'];values=[v for e in events for v in e['trace']['extreme_guesses_C']]
 require(events,'全年函数核查没有对应事件。')
 cached_repeats=0
 if len(values)!=int(count[1]):
  # A narrowly bounded cache case: repeated, exactly identical weather inputs,
  # one extreme per raw solve, one unique cache key and one logged warning.
  # Do not allow arbitrary under-counts or merely similar temperatures.
  first_event=events[0];inputs=('dry_C','RH_pct','pressure_Pa','humidity_ratio')
  key=tuple(first_event.get(k) for k in inputs)
  quantized=first_event['trace'].get('quantized_inputs')
  require(int(count[1])==1 and len(events)>1 and len(values)==len(events)
      and all(v is not None and math.isfinite(v) for v in key) and isinstance(quantized,dict)
      and set(quantized)=={'dry_C','humidity_ratio','pressure_Pa'}
      and all(tuple(e.get(k) for k in inputs)==key
              and e['trace'].get('quantized_inputs')==quantized
              and e['trace']['extreme_guesses_C']==first_event['trace']['extreme_guesses_C']
              and e['native_wet_C']==first_event['native_wet_C'] for e in events),
      '全年函数越界次数与原日志不一致，需要进一步分析缓存或调用路径。')
  cached_repeats=len(events)-1
 mo,day,hh,mm,endh,endm=map(int,t.groups());stamp=dt.datetime(2001,mo,day)+dt.timedelta(hours=endh,minutes=endm)
 require(events[0]['time']==stamp.strftime('%m/%d %H:%M'),'函数首次事件与原日志时刻不一致。')
 require(abs(values[0]-float(input_value[1]))<=.00501,'首次越界值与日志不一致。')
 require(abs(max(values)-float(extremes[1]))<=.000000501 and abs(min(values)-float(extremes[2]))<=.000000501,'全年越界极值与原日志不一致。')
 for e in events:
  roots=e['bounded_roots']
  require(e['trace']['converged'] and len(roots)==1 and abs(e['native_wet_C']-roots[0]['wet_C'])<1e-7 and e['trace_API_delta_C']<1e-7,'事件最终值与独立有界求根不一致。')
 return dict(event_count=int(count[1]),raw_exception_samples=len(events),cache_equivalent_repeats=cached_repeats,
  count_basis='identical_input_cache_reuse' if cached_repeats else 'exact_raw_count',
  first_time=events[0]['time'],max_extreme_C=max(values),min_extreme_C=min(values),all_events_converged=True,all_roots_match=True,all_log_summary_fields_match=True)
