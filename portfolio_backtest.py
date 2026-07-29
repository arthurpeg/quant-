"""
portfolio_backtest.py — CANEVAS multi-strategies pour assembler des "briques" decorrelees.

Idee (loi fondamentale du management actif, cf. wiki/concepts/breadth.md,
information-coefficient-and-ir.md) : les rendements s'ADDITIONNENT lineairement, mais le
Sharpe ne monte qu'avec la DECORRELATION. Ce module :
  1. lance N briques (chacune = une config de l'EA breakout, sur un actif),
  2. aligne leurs R en serie MENSUELLE et calcule la matrice de correlation,
  3. donne les stats du portefeuille (equal-risk) : R/an, Sharpe annuel,
  4. calcule combien de briques de qualite donnee il faut pour un Sharpe/R cible,
     et le PLAFOND de Sharpe impose par la correlation moyenne.

Pour ajouter une brique : ajoute une entree dans BRICKS (name, symbol, cfg). Pour une
VRAIE brique decorrelee il faut un mecanisme/actif/horizon different — pas une n-ieme
variante du meme breakout (elles seraient ~1.0 correlees et n'ajoutent pas de breadth).
"""
import numpy as np, pandas as pd
import backtest_breakout_nas100 as B

# --- definition des briques : (nom, symbole, override de config) ---
# ETAT ACTUEL (2026-07-27) : UNE seule brique retenue = NAS100 breakout 16:30 (exp-005).
# US30 ecarte (PF ~1.09 a son vrai spread ~26pt = trop mince). Les variantes 16:20/highvol
# etaient des demos (16:20 = surajustement non-significatif, cf. memory overfitting-guardrails).
# Pour ETENDRE : ajouter une brique a VRAI mecanisme different (ex. mean-reversion), pas une
# variante de parametre. Decommente/ajoute des lignes ci-dessous.
BRICKS = [
    ("NAS100-lowvol", "NAS100", {}),                          # brique principale, seule retenue
    # ("US30-lowvol",     "US30",   {}),                      # ecarte : trop faible (garde comme exemple)
    # ("NAS100-highvol",  "NAS100", {"regime_mode": "high"}), # exemple : jours disjoints -> decorrele
    # ("NAS100-meanrev",  "NAS100", {...}),                   # A CODER : brique mean-reversion (vraie breadth)
]
DEFAULT_SPREAD = 15.0

def brick_trades():
    data = {}
    out = {}
    for name, sym, cfg in BRICKS:
        if sym not in data:
            data[sym] = B.load(sym)
        m10, amap = data[sym]
        c = dict(cfg); c.setdefault("spread_pts", DEFAULT_SPREAD)
        t = B.run(cfg=c, date_from="2018-01-01", m10=m10, amap=amap)
        t["date"] = pd.to_datetime(t["date"])
        out[name] = t[["date", "R"]].copy()
    return out

def monthly_matrix(trades):
    """serie R mensuelle par brique, alignee sur un calendrier commun (mois sans trade -> 0)."""
    series = {}
    for name, t in trades.items():
        s = t.set_index("date").R.resample("MS").sum()
        series[name] = s
    idx = pd.period_range(min(s.index.min() for s in series.values()),
                          max(s.index.max() for s in series.values()), freq="M").to_timestamp()
    return pd.DataFrame({n: s.reindex(idx, fill_value=0.0) for n, s in series.items()})

def ann_stats(monthly_R):
    """R/an et Sharpe annuel a partir d'une serie mensuelle de R."""
    mu, sd = monthly_R.mean(), monthly_R.std()
    return mu * 12, (mu / sd * np.sqrt(12) if sd > 0 else np.nan)

def sharpe_N(s1, rho, N):
    """Sharpe d'un portefeuille de N briques identiques (Sharpe s1) a correlation moyenne rho."""
    denom = 1 + (N - 1) * rho
    return s1 * np.sqrt(N / denom) if denom > 0 else np.nan

def N_for_sharpe(s1, rho, target):
    """N briques pour atteindre 'target' de Sharpe (inf si le plafond s1/sqrt(rho) est sous la cible)."""
    ceil = s1 / np.sqrt(rho) if rho > 0 else np.inf
    if target >= ceil:
        return np.inf, ceil
    # sharpe_N croissant en N -> resolution numerique
    for N in range(1, 100000):
        if sharpe_N(s1, rho, N) >= target:
            return N, ceil
    return np.inf, ceil

if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    trades = brick_trades()
    M = monthly_matrix(trades)

    print("=" * 92)
    print("BRIQUES (R/an, Sharpe annuel, sur serie mensuelle 2018-2026)")
    print("-" * 92)
    for name in M.columns:
        rpy, sh = ann_stats(M[name])
        print(f"  {name:20s}: R/an={rpy:+6.1f}  Sharpe_an={sh:+.2f}")

    if len(M.columns) > 1:
        print("\nMATRICE DE CORRELATION (R mensuels) :")
        corr = M.corr()
        print(corr.round(2).to_string())

        print("\nPORTEFEUILLE equal-weight (somme des R) :")
        port = M.sum(axis=1)
        rpy, sh = ann_stats(port)
        ind_sh = [ann_stats(M[c])[1] for c in M.columns]
        print(f"  R/an={rpy:+.1f}  Sharpe_an={sh:+.2f}   (moyenne Sharpe individuels={np.mean(ind_sh):.2f})")
        off = corr.values[~np.eye(len(corr), dtype=bool)]
        rho = off.mean()
        print(f"\nCorrelation moyenne inter-briques rho = {rho:+.2f}")
    else:
        print("\n(1 seule brique -> pas de matrice de correlation. Ajoute une brique a mecanisme"
              "\n different pour construire de la breadth. La theorie ci-dessous montre la cible.)")

    print("\n" + "=" * 92)
    print("COMBIEN DE BRIQUES POUR 20R/AN 'PROPRE' ? (brique de reference : la NAS100-lowvol)")
    print("-" * 92)
    s1 = ann_stats(M["NAS100-lowvol"])[1]        # Sharpe annuel de la brique de reference
    r1 = ann_stats(M["NAS100-lowvol"])[0]        # R/an de la brique de reference
    print(f"Brique de reference : R/an={r1:+.1f}, Sharpe_an={s1:.2f}")
    print("\nPour ATTEINDRE 20R/an en esperance (les R s'additionnent) :")
    print(f"  ~ {np.ceil(20/max(r1,1e-9)):.0f} briques de cette taille (peu importe la correlation)")
    print("\nPour un BON algo (Sharpe cible), selon la correlation moyenne des briques :")
    print(f"  {'rho':>6} | {'plafond Sharpe':>15} | {'N pour Sh=1.5':>13} | {'N pour Sh=2.0':>13}")
    for rho_test in (0.0, 0.1, 0.2, 0.3, 0.5):
        n15, ceil = N_for_sharpe(s1, rho_test, 1.5)
        n20, _ = N_for_sharpe(s1, rho_test, 2.0)
        f = lambda x: ("infini" if np.isinf(x) else f"{x:.0f}")
        cf = ("∞" if np.isinf(ceil) else f"{ceil:.2f}")
        print(f"  {rho_test:6.2f} | {cf:>15} | {f(n15):>13} | {f(n20):>13}")
    print("\nLecture : la correlation PLAFONNE le Sharpe (plafond = s1/sqrt(rho)). Au-dela, ajouter")
    print("des briques n'aide plus. -> chercher des edges DECORRELES, pas des copies du meme.")
