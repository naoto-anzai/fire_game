import random, itertools, math
from collections import defaultdict
from game import *

pool = [CARDS[x] for x in set(STARTER)] + [CARDS[x] for x in
        ("コークス","重油","マグネシウム","テルミット","炎そのもの","灰","水","雷","酸素ボンベ")]
pos = defaultdict(list)   # カード名 -> 最適順での正規化位置(0=一番下, 1=一番上)
first = defaultdict(int); last = defaultdict(int); seen = defaultdict(int)
rng = random.Random(3)
N = 260
for _ in range(N):
    L = rng.uniform(0, 5); suns = rng.randint(0, 4)
    stack = rng.sample(pool, STACK_SIZE)
    best, bl = best_permutation(stack, L, START_OXYGEN, suns, trials=3)
    if bl <= L + 0.01: continue
    for i, c in enumerate(best):
        pos[c.name].append(i / (STACK_SIZE - 1)); seen[c.name] += 1
    first[best[0].name] += 1; last[best[-1].name] += 1

rows = [(sum(v)/len(v), n, len(v)) for n, v in pos.items() if len(v) >= 8]
rows.sort()
print(f"{'燃料':<12}{'平均位置':>8}  {'最下段':>6}{'最上段':>6}  役割")
print("─"*74)
def role(c):
    r=[]
    if c.special=="bellows" or c.mult>1: r.append("累計乗算")
    if c.catalyst>1: r.append("触媒")
    if c.special in("square","time","sun"): r.append("爆発")
    if c.chain_p: r.append("連鎖")
    if c.heat>=30: r.append("大加算")
    if c.ign==0 and c.heat and c.heat<10: r.append("着火役")
    return "/".join(r) or "-"
for avg, n, k in rows:
    c = CARDS[n]
    bar = "▁▂▃▄▅▆▇█"[min(7, int(avg*7.99))]
    print(f"{n:<12}{avg:>7.2f} {bar} {first[n]/max(1,seen[n])*100:>5.0f}%{last[n]/max(1,seen[n])*100:>5.0f}%  要{tname(c.ign)} {role(c)}")
