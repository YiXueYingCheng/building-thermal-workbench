"""Prepare a saved baseline via the existing input and execution pipeline."""
from foundation import digest
from daily_reference import require_baseline,CONTRACT,record_key
from input_pipeline import build_bundle,EVENTS
from preparation_gate import slot
from preparation_recovery import prepare


def freeze(root,store,catalog,ident,revision,expected_record_sha256,progress=None):
    record=store.get(ident,revision)
    if record_key(record)!=expected_record_sha256:raise ValueError('准备内容与保存版本不同，请保存方案并重新核对。')
    require_baseline(record)
    progress=progress or (lambda **v:None)
    with slot(root,progress):
        manifest=build_bundle(record,catalog,root,progress=lambda **v:progress(phase='generate',**v))
        progress(phase='prepare',bundle_id=manifest['id'],stage='核对逐日输出并准备预算清单',completed=0,total=manifest['case_count'],case_seconds=[])
        token=EVENTS.set(lambda **v:progress(phase='prepare',**v))
        try:return prepare(root,manifest['id'],store,dict(id=ident,revision=revision),output_contract=CONTRACT)
        finally:EVENTS.reset(token)
