"""Carry explicit user review notes into every detached table and figure."""
from foundation import digest,write_json

def reviews(data):
    found={}
    def visit(value):
        if isinstance(value,dict):
            if value.get('evidence_kind')=='user_review_with_notes_v1' and value.get('user_decision'):
                found[digest(value)]=value
            else:
                for item in value.values():visit(item)
        elif isinstance(value,(list,tuple)):
            for item in value:visit(item)
    visit(data)
    return list(found.values())

def summary(data):
    notes=[]
    for review in reviews(data):
        d=review['user_decision']
        notes.append(('用户强制采用' if d.get('acceptance_mode')=='bulk_force' else '用户审阅后采用')+'；审阅人：'+d['reviewer']+'；理由：'+d['reason']+'；用途：'+d['scope']+'；未自动证明警告无害')
    return ' | '.join(notes)

def annotate(rows,data):
    note=summary(data)
    return [dict(row,user_review_notice=note) for row in rows] if note else rows

def export_notes(folder,data,root):
    entries=reviews(data)
    if entries:
        write_json(folder/'user-review-notes.json',dict(label='用户审阅后采用',automatic_warning_clearance=False,reviews=entries),root)
        (folder/'用户审阅说明.txt').write_text(summary(data)+'\n原警告、结果身份和采用依据见 JSON。表中统一说明涵盖本次导出采用的全部结果，逐项对应关系见数据快照。',encoding='utf-8-sig')
