import random, itertools, math
from game import *
def auto(seed):
    run = Run(seed); rows=[]
    for ci,(chn,boss,target,reward) in enumerate(CHAPTERS,1):
        for rd in range(ROUNDS_PER_CH):
            hand = run.draw(HAND_SIZE)
            if len(hand)<STACK_SIZE: return rows,"燃料切れ",ci
            best=None;bT=-1
            for combo in itertools.combinations(range(len(hand)),STACK_SIZE):
                st=[hand[i] for i in combo]
                p,v=best_permutation(st,run.T,run.oxy,run.suns,trials=3)
                if v>bT: bT,best=v,list(p)
            r=resolve(best,run.T,run.oxy,run.suns,run.rng)
            run.T,run.oxy=r.T,r.oxygen
            run.peak=max(run.peak,tier_of(run.T))
            run.disc+= hand
            if rd<ROUNDS_PER_CH-1:
                run.T=max(run.T-math.log10(METRA),float(max(0,run.peak-METRA_FLOOR)))
        rows.append((ci,boss,target,tier_of(run.T)))
        if tier_of(run.T)<target: return rows,"敗北",ci
        run.suns+=1
        if reward: run.disc.append(CARDS[reward])
        run.oxy=max(run.oxy,START_OXYGEN)
    return rows,"クリア",7
for s in (1,2,3):
    rows,res,ci=auto(s)
    print(f"seed{s}: {res}")
    for ci_,boss,tg,got in rows:
        print(f"   第{ci_}章 {boss:<16} 必要10^{tg:<3} 到達10^{got:<4} {'OK' if got>=tg else 'NG'}")
