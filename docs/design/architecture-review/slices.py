import json,sys,collections
g=json.load(open(sys.argv[1]))
S={
'kernel':'taskloop repo task printable',
'tracker':'tracker tracker_client claim_lease',
'hold':'hold hold_cause hold_facts hold_guide hold_status hold_store hold_text',
'engine.attempt':'attempt attempt_entry attempt_loads attempt_reads attempt_result attempt_status attempt_store attempt_types session launch command_sink activity_file evidence_files owned_processes factory_schema admit admit_chain admit_rows',
'engine.slot':'slots slot_lock slot_release slot_state slot_env prepare environment access setup_store git_views',
'engine.flow':'operations steps step_text verifier verdict factory_commit repeat profile machine_config',
'steps.plan':'plan_step publish',
'steps.implement':'implement_step',
'steps.checks':'checks check_admit check_entry check_release check_status check_store validate',
'steps.land':'land land_check land_close land_data land_gate land_guide land_push land_render land_status land_store land_summary land_target',
'compose':'composition cli_composition dash_composition agent_credentials slot_files',
'rounds':'round rounds round_log round_reader round_trail selection rounds_lock interrupts',
'dash':'dash_board dash_model dash_server dash_task dash_tracker',
'cli':'__main__ cli cli_step exit_codes result_data step_render step_guide show_render',
}
R={'kernel':1,'tracker':2,'hold':2,'engine':2,'steps':3,'compose':4,'rounds':4,'dash':5,'cli':5}
m2s={}
for s,v in S.items():
  for m in v.split(): m2s['taskloop' if m=='taskloop' else 'taskloop.'+m]=s
miss=[m for m in g['internal'] if m not in m2s]; print('unassigned',miss, len(m2s))
top=lambda s:s.split('.')[0]
viol=collections.defaultdict(list); kinds=collections.Counter()
for a,ts in g['internal'].items():
  for b in ts:
    sa,sb=m2s[a],m2s[b]
    if sa==sb: continue
    ra,rb=R[top(sa)],R[top(sb)]
    k=None
    if rb>ra: k='up'
    elif top(sa)=='steps' and top(sb)=='steps': k='step-step'
    elif ra==rb==2 and top(sa)!=top(sb): k='peer'
    if k: viol[(sa,sb,k)].append(f"{a[9:]}->{b[9:]}"); kinds[k]+=1
print(kinds, sum(kinds.values()))
for (sa,sb,k),es in sorted(viol.items(),key=lambda x:-len(x[1]))[:16]:
  print(len(es),k,sa,'->',sb,es[:3])
