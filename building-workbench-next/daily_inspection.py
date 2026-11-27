"""Read-only progress and source-checked reuse for daily reference input inspection."""
from calendar_inspection import InspectionJobs
from foundation import digest
from group_candidates import CandidateReceipts
from inspection_io import reading
from recent_batch_views import file_marks
from source_locations import resolve
import daily_reference
import daily_workflow


class DailyInspections(InspectionJobs):
    def __init__(self,root,requests):
        super().__init__(root,'daily-input-view')
        self.requests=requests
        self.workflow_receipts=CandidateReceipts(root)

    def start(self,record,catalog):
        sites=record['factors']['scope']['site_ids']
        # File changes during an active inspection must also distinguish a new request.
        paths=[resolve(catalog['sites'][s]['weather'],catalog)[0]['path'] for s in sites
               if (catalog['sites'].get(s) or {}).get('weather')]
        key=digest([daily_reference.record_key(record),catalog,file_marks(paths)])
        return self.enqueue(key,record,catalog)

    def run(self,job,record,catalog):
        key=job['key']
        sites=record['factors']['scope']['site_ids']
        total=len(sites)

        def report(stage,done=0,city=''):
            self.update(job,state='running',progress=dict(stage=stage,completed=done,total=total,city=city))

        try:
            with self.requests.enter():
                report('检查核对依据')
                cached=self.cache.get(key)
                reused=bool(cached and cached['evidence'].valid())
                if reused:
                    preview,evidence=cached['preview'],cached['evidence']
                else:
                    positions={s:i for i,s in enumerate(sites)}
                    def case_started(site):
                        report('核对原构造输入',positions[site],catalog['sites'][site]['name'])
                    with reading(case_started=case_started) as reads:
                        preview=daily_reference.build(record,catalog,self.root)
                        report('复查输入来源',len(preview['rows']))
                    evidence=reads.evidence()

                done=len(preview['rows'])
                report('核对已有清单与批次',done)
                if reused and self.workflow_receipts.valid(cached['receipt']):
                    result,receipt=cached['result'],cached['receipt']
                else:
                    result=self.workflow_receipts.read(lambda:daily_workflow.enrich(dict(preview),record,catalog,self.root))
                    receipt=result.pop('read_receipt')
                if preview['input_ready']:
                    self.cache[key]=dict(preview=preview,evidence=evidence,result=result,receipt=receipt)
                    self.cache.move_to_end(key)
                    if len(self.cache)>6:self.cache.popitem(last=False)
                else:
                    self.cache.pop(key,None)
                self.update(job,state='ready',result=result,reused=reused,
                            progress=dict(stage='核对完成',completed=done,total=total,city=''))
        except Exception as exc:
            self.cache.pop(key,None)
            self.update(job,state='error',error=str(exc))
