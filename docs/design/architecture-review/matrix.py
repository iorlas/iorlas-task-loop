import json,re,collections
G="/tmp/claude-501/-home-iorlas-Workspaces-iorlas-task-loop-b83c5d9a3f13cb9d-sleepy-nobel-d00460/b75c53f8-b204-48ba-bfee-a0095c237e4e/scratchpad/graph.json"
g=json.load(open(G))
I=g['internal']
pats=[('admit',r'^(admit|check_admit)'),('attempt',r'^attempt'),('check',r'^check(?!_admit)'),('land',r'^land'),('hold',r'^hold'),('slot',r'^slot'),('dash',r'^dash'),('round',r'^rounds?'),('step',r'^(step|steps|plan_step|implement_step)'),('tracker',r'^(tracker|task)'),('git/profile/repo',r'^(git_views|profile|repo)$')]
def cl(m):
    s=m.split('.',1)[1] if '.' in m else ''
    if s=='' : return 'root'
    for n,p in pats:
        if re.search(p,s): return n
    return 'other'
C={m:cl(m) for m in I}
cnt=collections.Counter(); ex=collections.defaultdict(list)
for a,bs in I.items():
    for b in bs:
        if C[a]!=C[b]:
            cnt[(C[a],C[b])]+=1; ex[(C[a],C[b])].append(f"{a}->{b}")
for k,v in cnt.most_common(12): print(k,v,ex[k][:2])
print('other members', [m for m in I if C[m]=='other'])
print(collections.Counter(C.values()))
print('total cross', sum(cnt.values()))
