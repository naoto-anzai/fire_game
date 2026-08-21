# -*- coding: utf-8 -*-
import random, re
from game import *
def plain(s): return re.sub(r'\033\[[0-9;]*m','',s)

print("### CARDS")
for c in CARDS.values():
    f=[]
    if c.heat: f.append(f"発熱{c.heat:g}")
    if c.mult!=1: f.append(f"累計×{c.mult:g}")
    if c.catalyst!=1: f.append(f"触媒×{c.catalyst:g}")
    if c.chain_p: f.append(f"連鎖{c.chain_p:g}/{c.chain_n[0]}-{c.chain_n[1]}→{c.spawn}")
    if c.special: f.append(f"sp={c.special}")
    print(f"|{c.name}|{c.ign}|{'、'.join(f) or '—'}|{'/'.join(c.tags)}|{c.desc}|")

print("\n### 追体験ログ（seed固定）")
hand=[CARDS[n] for n in ("麻屑","杉の葉","乾いた薪","松脂","松ぼっくり","送風","小麦粉")]
best,bL,nv=solve_hand(hand,0.0,14,0)
print("最適:", " → ".join(c.name for c in best), f"= 10^{bL:.2f}  ({nv}通り)")
for label,st in (("昇順",ascending(best)),("最適",best)):
    r=resolve(st,0.0,14,0,random.Random(4))
    print(f"\n--- {label}: {' → '.join(c.name for c in st)} ---")
    for l in r.log: print(plain(l))
