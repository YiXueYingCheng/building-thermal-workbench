"""Display saved comparisons using their pinned versions, never latest plan names."""

from presentation import library_metadata

def describe(store,index=None):
    records={}
    rows=[]
    for comparison in store.comparisons():
        details={}
        for side in ('left','right'):
            ref=comparison[side];key=(ref['id'],ref['revision'])
            if key not in records:
                try:
                    r=store.get(*key)
                    records[key]=dict(name=r['name'],revision=r['revision'],period=r['factors']['scope']['period'],
                        site_count=len(r['factors']['scope']['site_ids']),step_minutes=r['numerics']['step_minutes'],
                        batch_count=library_metadata([r],index or {})[r['id']]['batch_count'],
                        group='archived' if r['archived'] else 'workspace' if r['status']=='draft' else 'sources')
                except (KeyError,ValueError) as error:
                    records[key]=dict(name=ref['id'],revision=ref['revision'],issue=str(error))
            details[side]=records[key]
        rows.append(dict(**comparison,display=details))
    return rows
