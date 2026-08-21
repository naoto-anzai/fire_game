#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火起こし × ローグライク — プレイアブル・プロトタイプ v2

決定事項:
  (a) 着火判定は「色の段」（対数スケール）で行う。
  (b) 解決順は 1枚ごとのループ。爆発はとにかく大きく。

v2 で入れた「桁を跳ねさせる」構造:
  1. 相転移      解決中に段が上がるたび、以降の全乗算に +PHASE_BONUS（正のフィードバック）
  2. 触媒の連鎖  触媒同士が隣接すると倍率が掛け算で合成される（×3,×3 → ×9）
  3. 共鳴の格上げ 3連以上は発熱だけでなく累計にも乗算
  4. 連鎖の乗算化 チェーンの子が加算ではなく乗算を持つ → 臨界で本当に発散する
  5. 二乗        「炎そのもの」は温度を二乗する（段が倍になる）
  6. 粉塵爆発    ここまでに適用した倍率の総積を、もう一度累計に掛ける
  7. 太陽        1つにつき ×10（一つ昇るごとに世界が一段上がる）

  python3 game.py          対話プレイ
  python3 game.py --sim    昇順ソートが最適解になる割合を総当たりで計測
"""
import math, random, sys, itertools
from dataclasses import dataclass, field

# ---------------------------------------------------------------- チューニング
START_TEMP      = 1.0
START_OXYGEN    = 14
HAND_SIZE       = 7
STACK_SIZE      = 5
ROUNDS_PER_CH   = 2
METRA           = 3.0     # ラウンド終わりに温度を割る値
METRA_FLOOR     = 1       # 到達最高段から何段までしか落ちないか
PHASE_BONUS     = 0.75    # 相転移1回につき以降の乗算に加算される値
RESONANCE_BASE  = 2.5     # 同タグ連続の指数の底
DUST_MULT       = 4.0
CHAIN_CAP_GEN   = 60


# ---------------------------------------------------------------- log10 空間
# 温度は 10^L として L（指数）だけを持つ。float64 の 10^308 の壁を越えるため。
NEG = float("-inf")

def ladd(L, h):
    """10^L + h を log10 で返す。"""
    if h <= 0: return L
    lh = math.log10(h)
    if L == NEG: return lh
    if L - lh > 18: return L
    if lh - L > 18: return lh
    return max(L, lh) + math.log10(1 + 10 ** (-abs(L - lh)))

def lmul(L, m):
    """10^L × m を log10 で返す。"""
    return NEG if m <= 0 else L + math.log10(m)

# ---------------------------------------------------------------- 色の段
TIER_NAMES = ["燻り","赤熱","橙炎","白熱","青炎","蒼閃","虚炎","劫火","白劫","焦熱",
              "大焦熱","無間","壊劫","空劫","成劫","住劫","初禅","二禅","三禅","四禅",
              "梵天","光音","遍浄","広果","無想","無煩","無熱","善現","善見","色究竟",
              "空無辺","識無辺","無所有","非想","不可説","不可説転","阿僧祇","那由他","恒河沙","無量大数"]
TIER_COLORS = ["\033[90m","\033[31m","\033[33m","\033[97m","\033[94m","\033[96m",
               "\033[95m","\033[91m","\033[93m","\033[92m"]
RESET = "\033[0m"

def tname(t):
    t = max(0, t)
    return TIER_NAMES[t] if t < len(TIER_NAMES) else f"第{t}段"

def tier_of(L):
    return 0 if L < 0 or L != L else int(L)

def fmt(L):
    if L < 0: return "0"
    if L < 7: return f"{10 ** L:,.0f}"
    e = int(L); return f"{10 ** (L - e):.2f}×10^{e:,}"

def paint(L):
    t = tier_of(L)
    return f"{TIER_COLORS[t % len(TIER_COLORS)]}{fmt(L)}°({tname(t)}){RESET}"

# ---------------------------------------------------------------- カード
@dataclass
class Card:
    name: str
    ign: int = 0
    heat: float = 0.0
    mult: float = 1.0
    catalyst: float = 1.0
    tags: tuple = ()
    chain_p: float = 0.0
    chain_n: tuple = (0, 0)
    spawn: str = ""
    special: str = ""
    desc: str = ""

def C(*a, **k): return Card(*a, **k)

CARDS = {c.name: c for c in [
    # --- 第1階梯 ------------------------------------------------------------
    C("麻屑",      0, heat=3,  tags=("屑",),        special="tinder", desc="以降の必要段-1"),
    C("杉の葉",    0, heat=4,  tags=("屑","木"),    chain_p=0.40, chain_n=(1,2), spawn="火の粉",
      desc="40%で火の粉1-2（火の粉は累計×1.3）"),
    C("松ぼっくり",0, heat=5,  tags=("木",),        chain_p=0.55, chain_n=(1,3), spawn="爆ぜた種",
      desc="55%で爆ぜた種1-3（種は累計×1.6でさらに連鎖）"),
    C("乾いた薪",  1, heat=14, tags=("木",)),
    C("松脂",      0, catalyst=3.0, tags=("樹脂",), desc="次の発熱×3。触媒同士は掛け算で合成"),
    C("炭",        1, heat=9,  tags=("炭",)),
    C("生木",      4, heat=45, mult=2.0, tags=("湿","木"), desc="罠。届かないと1段落ちる"),
    # --- 第2階梯 ------------------------------------------------------------
    C("コークス",  2, heat=34, tags=("炭",)),
    C("重油",      2, heat=26, mult=1.5, tags=("油",), special="oil", desc="直後2枚の必要段-2"),
    C("送風",      0, tags=("行動",), special="bellows", desc="同時燃焼本数だけ累計を乗算"),
    C("マグネシウム",3, heat=70, mult=2.0, tags=("粉","金属"), chain_p=0.45, chain_n=(1,2), spawn="火の粉"),
    C("小麦粉",    1, tags=("粉",), desc="単体では無意味。粉2枚で粉塵爆発"),
    C("テルミット",3, heat=140, tags=("金属",), special="thermite", desc="金属3つ以上で発熱×10"),
    C("酸素ボンベ",0, tags=("行動",), special="oxygen", desc="酸素+12"),
    # --- 第3階梯 ------------------------------------------------------------
    C("水",        5, heat=4000, mult=3.0, tags=("湿",), desc="届かないと1段落ちる"),
    C("灰",        1, tags=("灰",), special="ash", desc="ここまでの発熱の平均で燃える"),
    C("炎そのもの",5, tags=("概念","火"), special="square", desc="★温度を二乗する"),
    C("雷",        4, heat=600, mult=2.0, tags=("金属",), chain_p=0.50, chain_n=(1,3), spawn="火の粉"),
    C("燃えない何か",0, tags=("概念",), special="unburnable", desc="以降の着火判定を無視"),
    # --- 第4階梯 ------------------------------------------------------------
    C("時間",      6, mult=1.0, tags=("概念",), special="time", desc="★ここまでの倍率の総積をもう一度掛ける"),
    C("名前",      4, tags=("概念",), special="copy", desc="直前の1枚をもう一度解決する"),
    C("太陽",      7, tags=("概念","火"), special="sun", desc="★空の太陽の数だけ温度を累乗する"),
    # --- 生成物 -------------------------------------------------------------
    C("火の粉",    0, heat=6,  mult=1.30, tags=("屑",)),
    C("爆ぜた種",  0, heat=11, mult=1.60, tags=("木",), chain_p=0.35, chain_n=(1,2), spawn="爆ぜた種"),
]}

STARTER = ["麻屑","麻屑","杉の葉","杉の葉","松ぼっくり","松ぼっくり","乾いた薪","乾いた薪",
           "松脂","松脂","炭","炭","小麦粉","送風","生木"]

CHAPTERS = [
    ("一・熾", "枯野",             5,   "灰"),
    ("二・流", "大河",             9,   "水"),
    ("三・淵", "底の見えない湖",   18,  "炎そのもの"),
    ("四・満", "大海",             30,  "酸素ボンベ"),
    ("五・輪", "金輪・水輪・風輪", 60,  "時間"),
    ("六・軸", "須弥山",           90,  "太陽"),
    ("七・限", "火",               180, ""),
]

# ---------------------------------------------------------------- 解決エンジン
@dataclass
class Result:
    T: float
    oxygen: int
    log: list = field(default_factory=list)
    burned: int = 0
    critical: bool = False

def resolve(stack, L, oxygen, suns, rng, _depth=0):
    """L は log10(温度)。返り値も L。"""
    log = []
    relief_global = suns // 2
    relief_extra  = 0
    ignore_ign    = False
    oil_left      = 0
    catalyst      = 1.0
    streak        = 1
    prev_tags     = ()
    heats         = []
    burned        = 0
    critical      = False
    phase         = 0
    mp_log        = 0.0        # 適用した倍率の総積（log10）
    prev_card     = None

    n_dust  = sum(1 for c in stack if "粉"   in c.tags)
    n_metal = sum(1 for c in stack if "金属" in c.tags)

    def bump(a, b):
        nonlocal phase
        d = tier_of(b) - tier_of(a)
        if d > 0:
            phase += d
            log.append(f"     ⤴ 相転移 ×{d} — 炉は用済みになった（以降の乗算 +{PHASE_BONUS*phase:g}）")

    def mul(L, m, why):
        nonlocal mp_log
        if m == 1.0: return L
        m_eff = m + PHASE_BONUS * phase
        mp_log += math.log10(m_eff)
        b = L; L = lmul(L, m_eff)
        log.append(f"     {why} ×{m_eff:,.2f} → {paint(L)}")
        bump(b, L)
        return L

    i = 0
    while i < len(stack):
        c = stack[i]; i += 1
        # --- 1 着火判定 -----------------------------------------------------
        need = max(0, c.ign - relief_global - relief_extra - (2 if oil_left > 0 else 0))
        if oil_left > 0: oil_left -= 1
        if not ignore_ign and need > tier_of(L):
            log.append(f"  ✗ {c.name}: 要{tname(need)} / 現在{tname(tier_of(L))}"
                       f" — 伝播が止まり上の{len(stack)-i}枚は不発")
            if "湿" in c.tags:
                L -= 1.0
                log.append(f"     湿ったものが火を奪う → {paint(L)}")
            break

        # --- 2 発熱の確定 ---------------------------------------------------
        base = c.heat
        if   c.special == "ash":  base = (sum(heats)/len(heats)) if heats else 1.0
        elif c.special == "thermite" and n_metal >= 3: base = c.heat * 10

        common = set(c.tags) & set(prev_tags)
        streak = streak + 1 if common else 1
        res  = RESONANCE_BASE ** (streak - 1)
        heat = base * catalyst * res

        # --- 3 加算 ---------------------------------------------------------
        b = L
        L = ladd(L, heat)
        burned += 1
        heats.append(base)
        note = []
        if catalyst != 1.0: note.append(f"触媒×{catalyst:g}")
        if res != 1.0:      note.append(f"共鳴×{res:g}({streak}連[{'/'.join(common)}])")
        log.append(f"  ● {c.name:<7} +{heat:<12,.0f} {' '.join(note)} → {paint(L)}")
        bump(b, L)

        # 触媒同士が隣接したら掛け算で合成される
        catalyst = catalyst * c.catalyst if (c.catalyst != 1.0 and catalyst != 1.0) else c.catalyst
        prev_tags = c.tags

        # --- 4 累計への乗算 -------------------------------------------------
        if streak >= 3:
            L = mul(L, RESONANCE_BASE ** (streak - 2), f"共鳴{streak}連")
        m = float(burned) if c.special == "bellows" else c.mult
        L = mul(L, m, c.name)

        # --- 特殊 -----------------------------------------------------------
        if   c.special == "tinder":  relief_extra += 1
        elif c.special == "oil":     oil_left = 2
        elif c.special == "oxygen":  oxygen += 12; log.append("     酸素+12")
        elif c.special == "unburnable":
            ignore_ign = True
            log.append("     燃えるという条件そのものが無効になった")
        elif c.special == "square":
            b = L; L = L * 2 if L > 0 else L
            log.append(f"     ★ 火が火を燃やす: 二乗 → {paint(L)}"); bump(b, L)
        elif c.special == "time":
            b = L; L += mp_log; mp_log *= 2
            log.append(f"     ★ 時間: ここまでの倍率の総積(×10^{mp_log/2:,.1f})を再適用 → {paint(L)}")
            bump(b, L)
        elif c.special == "sun":
            b = L; e = 1 + 0.35 * max(1, suns)
            L = L * e if L > 0 else L
            log.append(f"     ★ 太陽: 温度を {e:.2f} 乗 → {paint(L)}"); bump(b, L)
        elif c.special == "copy" and prev_card is not None and _depth < 3:
            log.append(f"     ★『{prev_card.name}』をもう一度")
            r = resolve([prev_card], L, oxygen, suns, rng, _depth+1)
            L, oxygen = r.T, r.oxygen
            log += ["  " + x for x in r.log]

        # --- 5 チェーン -----------------------------------------------------
        if c.chain_p > 0 and oxygen > 0:
            bonus = 0.15 * (streak - 1)
            m_eff = min(0.95, c.chain_p + bonus) * (sum(c.chain_n) / 2)
            if m_eff >= 1.0:
                critical = True
                log.append(f"     ⚠ 臨界 (m={m_eff:.2f} ≥ 1) — 酸素が尽きるまで止まらない")
            b = L
            L, oxygen, spawned, gens = run_chain(c, L, oxygen, rng, bonus, phase)
            if spawned:
                log.append(f"     連鎖 {gens}世代 / {spawned}回発火 (酸素残{oxygen}) → {paint(L)}")
                bump(b, L)

        prev_card = c

    # --- 6 全体再点火 -------------------------------------------------------
    if n_dust >= 2 and burned >= 1:
        add_log = math.log10(DUST_MULT) * (n_dust - 1) + max(0.0, mp_log)
        L += add_log
        log.append(f"  ◆ 粉塵爆発 (粉{n_dust}枚) 累計×10^{add_log:,.1f} → {paint(L)}")
    if suns >= 1:
        L += suns
        log.append(f"  ☀ 空の太陽 {suns}つ ×10^{suns} → {paint(L)}")

    return Result(L, oxygen, log, burned, critical)

def run_chain(src, L, oxygen, rng, bonus, phase):
    queue, spawned, gens = [src], 0, 0
    while queue and oxygen > 0 and gens < CHAIN_CAP_GEN:
        gens += 1
        nxt = []
        for s in queue:
            if not s.spawn: continue
            if rng.random() >= min(0.95, s.chain_p + bonus): continue
            for _ in range(rng.randint(*s.chain_n)):
                if oxygen <= 0: break
                oxygen -= 1
                ch = CARDS[s.spawn]
                L = lmul(ladd(L, ch.heat), ch.mult + PHASE_BONUS * phase * 0.25)
                spawned += 1
                nxt.append(ch)
        queue = nxt
    return L, oxygen, spawned, max(0, gens - 1)

# ---------------------------------------------------------------- 状態
class Run:
    def __init__(self, seed=None):
        self.rng  = random.Random(seed)
        self.deck = [CARDS[n] for n in STARTER]
        self.rng.shuffle(self.deck)
        self.disc = []
        self.T    = math.log10(START_TEMP)
        self.oxy  = START_OXYGEN
        self.suns = 0
        self.peak = 0
    def draw(self, n):
        hand = []
        for _ in range(n):
            if not self.deck:
                self.deck, self.disc = self.disc, []
                self.rng.shuffle(self.deck)
            if not self.deck: break
            hand.append(self.deck.pop())
        return hand

def show_hand(hand):
    print("\n  手札:")
    for i, c in enumerate(hand, 1):
        bits = []
        if c.heat:          bits.append(f"発熱+{c.heat:g}")
        if c.catalyst != 1: bits.append(f"次×{c.catalyst:g}")
        if c.mult != 1:     bits.append(f"累計×{c.mult:g}")
        if c.chain_p:       bits.append(f"連鎖{int(c.chain_p*100)}%")
        print(f"   {i}) {c.name:<7} 要{tname(c.ign):<5} {' '.join(bits):<24} [{'/'.join(c.tags)}]"
              + (f"  … {c.desc}" if c.desc else ""))

def best_permutation(stack, T, oxy, suns, trials=6):
    best, bestT = None, float("-inf")
    for p in itertools.permutations(stack):
        tot = sum(resolve(list(p), T, oxy, suns, random.Random(k)).T for k in range(trials))
        if tot / trials > bestT: bestT, best = tot / trials, p
    return best, bestT

def ascending(stack): return sorted(stack, key=lambda c: c.ign)

def solve_hand(hand, L, oxy, suns, trials=4, max_slots=STACK_SIZE):
    """手札から「何枚選ぶか・どれを選ぶか・どう並べるか」を全探索する。
    連鎖が確率的なので複数シードの平均（期待値）で比較する。
    同名カードは同一オブジェクトなので各深さで一度しか試さない（枝刈り）。"""
    best, bl, visited = None, float("-inf"), 0
    cur, used = [], [False] * len(hand)

    def rec():
        nonlocal best, bl, visited
        if cur:
            v = sum(resolve(cur, L, oxy, suns, random.Random(k * 977 + len(cur))).T
                    for k in range(1, trials + 1)) / trials
            visited += 1
            if v > bl: bl, best = v, list(cur)
        if len(cur) >= max_slots: return
        tried = set()
        for i, c in enumerate(hand):
            if used[i] or c.name in tried: continue
            tried.add(c.name)
            used[i] = True; cur.append(c); rec(); cur.pop(); used[i] = False

    rec()
    return best, bl, visited

# ---------------------------------------------------------------- 対話プレイ
def play(seed=None):
    run = Run(seed)
    print("\n" + "="*70)
    print("  世界のすべての火が消えた。手元に残ったのは種火が一つ。")
    print("="*70)
    for ci, (chname, boss, target, reward) in enumerate(CHAPTERS, 1):
        print(f"\n\n{'─'*70}\n  第{ci}章 {chname} — 燃やす対象:『{boss}』")
        print(f"  発火点: {tname(target)} (10^{target}°)   空の太陽: {run.suns}つ"
              + (f" [必要段 -{run.suns//2}]" if run.suns//2 else ""))
        print("─"*70)
        for rd in range(1, ROUNDS_PER_CH + 1):
            print(f"\n [ラウンド {rd}/{ROUNDS_PER_CH}]  現在 {paint(run.T)}  酸素 {run.oxy}")
            hand = run.draw(HAND_SIZE)
            if len(hand) < STACK_SIZE: print("  燃料が尽きた。"); return
            show_hand(hand)
            while True:
                raw = input(f"\n  下から積む順に{STACK_SIZE}枚（例: 1 3 5 2 4 / q=中断）> ").strip()
                if raw in ("q","quit"): return
                try:
                    idx = [int(x)-1 for x in raw.split()]
                    assert len(idx) == STACK_SIZE and len(set(idx)) == STACK_SIZE
                    assert all(0 <= i < len(hand) for i in idx); break
                except Exception: print("  入力が不正です。")
            stack = [hand[i] for i in idx]
            rest  = [c for j, c in enumerate(hand) if j not in idx]
            print("\n  くべる: " + " → ".join(c.name for c in stack) + "\n")
            r = resolve(stack, run.T, run.oxy, run.suns, run.rng)
            for line in r.log: print(line)
            asc = ascending(stack)
            aT = resolve(asc, run.T, run.oxy, run.suns, random.Random(0)).T
            bp, bT = best_permutation(stack, run.T, run.oxy, run.suns)
            sv, sT, nv = solve_hand(hand, run.T, run.oxy, run.suns)
            print(f"\n  ├ あなたの並び   : {paint(r.T)}")
            print(f"  ├ 着火点の昇順   : {paint(aT)}  ({' → '.join(c.name for c in asc)})")
            print(f"  ├ 同じ5枚の最適  : {paint(bT)}  ({' → '.join(c.name for c in bp)})")
            print(f"  └ 手札からの最適 : {paint(sT)}  ({' → '.join(c.name for c in sv)})"
                  f"   [{nv:,}通り探索]")
            run.T, run.oxy = r.T, r.oxygen
            run.peak = max(run.peak, tier_of(run.T))
            run.disc += stack + rest
            if rd < ROUNDS_PER_CH:
                run.T = max(run.T - math.log10(METRA), float(max(0, run.peak - METRA_FLOOR)))
                print(f"\n  ── メトラ（定めの分だけ消える） → {paint(run.T)}")
                if run.T < 0: print("\n  火が消えた。夜明けは来ない。"); return
        print(f"\n  『{boss}』の発火点は {tname(target)}。現在 {paint(run.T)}")
        if tier_of(run.T) >= target:
            run.suns += 1
            print(f"  ▲ {boss} が燃えた。空に {run.suns}つ目の太陽が昇る。")
            if reward:
                run.disc.append(CARDS[reward]); print(f"  ▲ 灰を拾った: 『{reward}』がデッキに加わった。")
            run.oxy = max(run.oxy, START_OXYGEN)
        else:
            print(f"  ✗ 届かなかった。火は『{boss}』の前で燃え尽きる。"); return
    print("\n" + "="*70)
    print("  七つ目の太陽が昇った。焼き尽くされた宇宙は、また同じ形で始まる。")
    print("="*70)

# ---------------------------------------------------------------- 検証
def sim(n=120):
    rng = random.Random(0)
    pool = [CARDS[x] for x in STARTER] + [CARDS[x] for x in
            ("コークス","重油","マグネシウム","テルミット","炎そのもの","灰","水","雷",
             "酸素ボンベ","時間","名前","太陽","燃えない何か")]
    asc_best = 0; ratios = []; feas = 0; gains = []
    for _ in range(n):
        T = rng.uniform(0, 6); suns = rng.randint(0, 5)
        stack = rng.sample(pool, STACK_SIZE)
        bp, bT = best_permutation(stack, T, START_OXYGEN, suns)
        aT = sum(resolve(ascending(stack), T, START_OXYGEN, suns, random.Random(k)).T
                 for k in range(6)) / 6
        if bT <= T + 0.01: continue
        feas += 1
        if aT >= bT - 0.01: asc_best += 1
        ratios.append(min(1.0, 10 ** (aT - bT)))
        gains.append(bT - T)
    print(f"\n  有効サンプル: {feas}")
    print(f"  昇順ソートが最適だった割合 : {asc_best/max(1,feas)*100:.1f}%")
    print(f"  昇順ソートの平均達成率     : {sum(ratios)/max(1,len(ratios))*100:.1f}% (最適比)")
    print(f"  最適プレイ1ラウンドの伸び  : 平均 +{sum(gains)/max(1,len(gains)):.1f}段"
          f" / 最大 +{max(gains):.1f}段")

if __name__ == "__main__":
    if "--sim" in sys.argv:
        a = sys.argv
        sim(int(a[a.index("--sim")+1]) if len(a) > a.index("--sim")+1 else 120)
    else:
        try: play()
        except (KeyboardInterrupt, EOFError): print("\n  火が消えた。")
