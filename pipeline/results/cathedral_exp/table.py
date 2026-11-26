import json
bp=json.load(open('art/final/meta/cathedral_blueprint.json'))['parts']
cnt={k:v['count'] for k,v in bp.items()}
KEY=['portal_main','portal_side','rose','front_window','gallery_arcade','aisle_window','aisle_window_left','clerestory_window','clerestory_window_left',
 'side_buttress','side_buttress_left','pinnacle','pinnacle_left','flying_buttress','flying_buttress_left','belfry_opening','parapet','apse','apse_window','apse_flying_buttress']
out={}
for R in 'AB':
    d=json.load(open(f'out/cathedral_exp/run_{R}.json'))
    checks=[(a['tag'],g) for a in d['attempts'] for g in a['grids']]
    best=min(checks,key=lambda t:len(t[1]['missing']))
    out[R]=dict(best=best[0]+'_g'+str(best[1]['grid']),best_missing=len(best[1]['missing']),
      n_checks=len(checks),miss_per_check=[len(g['missing']) for _,g in checks],
      parts={k:dict(best_present=k not in best[1]['missing'],best_seen=best[1]['parts'][k]['count_seen'],
         best_detail_missing=best[1]['parts'][k]['detail_missing'],
         pass_rate=sum(k not in g['missing'] for _,g in checks),
         max_seen=max(g['parts'].get(k,{}).get('count_seen',0) or 0 for _,g in checks)) for k in cnt},
      depth={t+'_g'+str(g['grid']):{v:(c['recess'],c['open']) for v,c in g['depth_count'].items()} for t,g in checks},
      present_all=sum(k not in best[1]['missing'] for k in cnt))
json.dump(out,open('out/cathedral_exp/table.json','w'),indent=1)
print('part count | A best: present seen | A pass/8 | B best | B pass/8')
for k in cnt:
    a=out['A']['parts'][k]; b=out['B']['parts'][k]
    print(f"{k:24s}{cnt[k]:3d} | {'Y' if a['best_present'] else '-'} {a['best_seen']:3} | {a['pass_rate']}/8 max{a['max_seen']} | {'Y' if b['best_present'] else '-'} {b['best_seen']:3} | {b['pass_rate']}/8 max{b['max_seen']}")
for R in 'AB': print(R,out[R]['best'],out[R]['best_missing'],out[R]['miss_per_check'], 'keypresent', sum(out[R]['parts'][k]['best_present'] for k in KEY), 'keypassrate', sum(out[R]['parts'][k]['pass_rate'] for k in KEY))
for R in 'AB':
  for t,v in out[R]['depth'].items(): print(t,v)
for R in 'AB':
  print(R,'detail_missing count on key parts (best):', sum(len(out[R]['parts'][k]['best_detail_missing']) for k in KEY))
