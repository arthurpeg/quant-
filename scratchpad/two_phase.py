"""Two books, one account: an aggressive book for the CHALLENGE, a defensive one once FUNDED.

The user's proposal, and it generalises what wiki/system.md already recommends. system.md
says to change the SIZE between phases ("pass the challenge at 1.0% for speed, drop to
0.50% once funded for protection"); this changes the SLEEVE MIX as well:

    challenge : D = b1 + b2 + b3 + b4 + KAER@0.5 + KELT@0.5   at 1.00%/trade
    funded    : E = b1 + b2 + b3@0.5 + b4 + KELT@0.5          at 0.50%/trade

The two phases have genuinely different objective functions, which is the whole argument:
  * the challenge is a FIRST-PASSAGE problem — you want to touch +15% before -10%, and
    time is money only through the entry fee. Return per unit of drawdown matters less
    than raw speed, and a failed attempt costs a fee, not the account.
  * funded is a RUIN problem — the account is an asset with an expected lifetime, and the
    figure of merit is E[withdrawn per year] against P(losing the account per year).
A book that is wrong for one can be right for the other. That is the hypothesis.

The simulation runs both phases on ONE bootstrapped path per replicate: challenge with the
challenge book until pass or fail, then, if passed, the remainder of the horizon funded
with the funded book. Failing the challenge costs a fee and a retry, so the expected
number of attempts is reported and the fee is left for the reader to price.
"""
import sys, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

from book_optimise import sleeves, perf, NAMES

N = 20000
BLOCK = 14
HORIZON = 730          # 2 years of calendar days
TARGET, DDFLOOR, DAILY = 0.15, 0.10, 0.05
PAYOUT_DAYS = 30


def path(R, L, rng):
    out = []
    while len(out) < L:
        st = rng.integers(0, len(R) - BLOCK)
        out.extend(R[st:st + BLOCK])
    return np.array(out[:L])


def run(Rc, Rf, risk_c, risk_f, n=N, seed=11, horizon=HORIZON):
    """One account over `horizon` days: challenge on Rc at risk_c, then funded on Rf.

    A failed challenge is retried immediately (a new fee); the clock keeps running, so a
    slow or fragile challenge book is penalised twice — in fees and in funded days lost.
    """
    rng = np.random.default_rng(seed)
    Tc, DDc, DAYc = TARGET / risk_c, DDFLOOR / risk_c, DAILY / risk_c
    DDf = DDFLOOR / risk_f
    got_funded = np.zeros(n, bool)
    attempts = np.zeros(n)
    days_to_pass = np.full(n, np.nan)
    withdrawn = np.zeros(n)
    ruined = np.zeros(n, bool)
    funded_days = np.zeros(n)

    for k in range(n):
        pc = path(Rc, horizon, rng)
        pf = path(Rf, horizon, rng)
        t, e, att = 0, 0.0, 1
        passed_at = None
        while t < horizon:
            x = pc[t]
            t += 1
            if x <= -DAYc:                      # daily-loss breach -> account failed
                att += 1; e = 0.0
                continue
            e += x
            if e <= -DDc:                       # total-DD breach -> account failed
                att += 1; e = 0.0
                continue
            if e >= Tc:
                passed_at = t
                break
        attempts[k] = att
        if passed_at is None:
            continue
        got_funded[k] = True
        days_to_pass[k] = passed_at
        e, w, d0 = 0.0, 0.0, passed_at
        for t in range(passed_at, horizon):
            e += pf[t - passed_at]
            if e <= -DDf:
                ruined[k] = True
                break
            if (t - d0 + 1) % PAYOUT_DAYS == 0 and e > 0:
                w += e; e = 0.0
        withdrawn[k] = w * risk_f * 100
        funded_days[k] = (horizon if not ruined[k] else t) - passed_at

    return dict(p_funded=got_funded.mean(),
                attempts=attempts.mean(),
                months=np.nanmedian(days_to_pass) / 30.44,
                withdrawn_2y=withdrawn.mean(),
                withdrawn_if_funded=withdrawn[got_funded].mean() if got_funded.any() else 0.0,
                p_ruin=ruined[got_funded].mean() if got_funded.any() else np.nan,
                funded_months=funded_days[got_funded].mean() / 30.44 if got_funded.any() else 0.0)


def main():
    M, (s0, s1) = sleeves()
    mid = M.index[len(M) // 2]
    W = {
        'A  4 briques @1R':                 (1, 1, 1, 1, 0, 0),
        'D  A + KAER@0.5 + KELT@0.5':       (1, 1, 1, 1, .5, .5),
        'E  b3@0.5 + KELT@0.5':             (1, 1, .5, 1, 0, .5),
        'F  E + KAER@0.5':                  (1, 1, .5, 1, .5, .5),
    }
    S = {nm: pd.Series(M[NAMES].to_numpy() @ np.array(w), index=M.index)
         for nm, w in W.items()}

    print('pire journee de chaque livre (la regle -5% quotidienne mord a 1%/trade '
          'si le pire jour depasse -5 R):')
    for nm, s in S.items():
        print(f'  {nm:<30} pire jour {s.min():+.2f} R  ->  a 1%/trade = {s.min():+.2f}% '
              f'({"OK" if s.min() > -5 else "BREACH"})')

    for tag, sl in (('ECHANTILLON COMPLET', slice(None)),
                    ('2e MOITIE SEULE (proxy forward-test)', slice(mid, None))):
        print('\n' + '=' * 112)
        print(f'PLAN EN DEUX PHASES sur 2 ans — {tag}')
        print('=' * 112)
        plans = [
            ('ta proposition : D@1.00% -> E@0.50%', 'D  A + KAER@0.5 + KELT@0.5', 0.01,
             'E  b3@0.5 + KELT@0.5', 0.005),
            ('un seul livre : E@1.00% -> E@0.50%', 'E  b3@0.5 + KELT@0.5', 0.01,
             'E  b3@0.5 + KELT@0.5', 0.005),
            ('un seul livre : A@1.00% -> A@0.50%', 'A  4 briques @1R', 0.01,
             'A  4 briques @1R', 0.005),
            ('un seul livre : D@1.00% -> D@0.50%', 'D  A + KAER@0.5 + KELT@0.5', 0.01,
             'D  A + KAER@0.5 + KELT@0.5', 0.005),
            ('variante : D@0.75% -> E@0.50%', 'D  A + KAER@0.5 + KELT@0.5', 0.0075,
             'E  b3@0.5 + KELT@0.5', 0.005),
            ('variante : F@1.00% -> E@0.50%', 'F  E + KAER@0.5', 0.01,
             'E  b3@0.5 + KELT@0.5', 0.005),
            ('conservateur : E@0.75% -> E@0.50%', 'E  b3@0.5 + KELT@0.5', 0.0075,
             'E  b3@0.5 + KELT@0.5', 0.005),
        ]
        print(f"{'plan':<38}{'P(funded)':>11}{'essais':>8}{'delai med':>11}"
              f"{'mois funded':>13}{'retire/2ans':>13}{'P(ruine)':>10}")
        for nm, ck, cr, fk, fr in plans:
            r = run(S[ck].loc[sl].values, S[fk].loc[sl].values, cr, fr)
            print(f"{nm:<38}{r['p_funded']:>10.1%}{r['attempts']:>8.2f}"
                  f"{r['months']:>10.1f}mo{r['funded_months']:>12.1f}mo"
                  f"{r['withdrawn_2y']:>12.1f}%{r['p_ruin']:>10.1%}")


if __name__ == '__main__':
    main()
