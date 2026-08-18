---
type: reference
updated: 2026-08-16
---

# Lucid Trading (futures) — routeur de règles

> Page **routeur** : elle pointe vers la source officielle article par article. Les
> montants d'un prop firm changent sans préavis — ne jamais les citer d'ici sans
> revérifier le lien. Les seuls chiffres reproduits ci-dessous sont ceux **sans
> lesquels le raisonnement est illisible**, tous datés de la lecture du 2026-08-16.

Base de connaissances officielle : <https://support.lucidtrading.com/en/>
Tarifs : <https://lucidtrading.com/> (onglets LucidPro / LucidFlex / LucidDaily / LucidDirect)

| Sujet | Article officiel |
|---|---|
| Drawdown EOD (Pro) | [LucidPro Drawdown](https://support.lucidtrading.com/en/articles/12890136-lucidpro-drawdown) |
| Drawdown EOD (Flex) | [LucidFlex Drawdown](https://support.lucidtrading.com/en/articles/12945815-lucidflex-drawdown) |
| Éval Pro | [LucidPro Evaluation Account](https://support.lucidtrading.com/en/articles/12890029-lucidpro-evaluation-account) |
| Éval Flex | [LucidFlex Evaluation Account](https://support.lucidtrading.com/en/articles/12945790-lucidflex-evaluation-account) |
| Funded Pro / Flex | [Pro](https://support.lucidtrading.com/en/articles/12890069-lucidpro-funded-account) · [Flex](https://support.lucidtrading.com/en/articles/12945795-lucidflex-funded-account) |
| Payouts | [Pro](https://support.lucidtrading.com/en/articles/12890092-lucidpro-payouts) · [Flex](https://support.lucidtrading.com/en/articles/12945796-lucidflex-payouts) |
| Consistance | [Pro 40 %](https://support.lucidtrading.com/en/articles/12890109-lucidpro-consistency-percentage) · [Flex 50 % éval](https://support.lucidtrading.com/en/articles/12945805-lucidflex-consistency-percentage) |
| DLL (soft breach) | [LucidPro Daily Loss Limit](https://support.lucidtrading.com/en/articles/12890122-lucidpro-daily-loss-limit) |
| Scaling contrats (Flex funded) | [LucidFlex Scaling Plan](https://support.lucidtrading.com/en/articles/12945808-lucidflex-scaling-plan) |
| Horaires / flat obligatoire | [Allowed Trading Times](https://support.lucidtrading.com/en/articles/11404729-allowed-trading-times) |
| Automates, news, scalping | [Other Activities](https://support.lucidtrading.com/en/articles/11404728-other-activities) · [Microscalping](https://support.lucidtrading.com/en/articles/11404742-prohibited-microscalping) · [Hedging](https://support.lucidtrading.com/en/articles/11404734-prohibited-hedging) |
| Frais / resets | [Simulated Account Fees](https://support.lucidtrading.com/en/articles/11404620-simulated-account-fees) |

## Les trois faits qui décident de tout, pour NOTRE book

1. **Aucune tenue overnight ni week-end.** Tout est liquidé d'office à 16:45 ET, cinq
   jours sur sept ; réouverture 18:00 ET. → **les briques 2 (or turn-of-month), 3
   (crypto D1) et 4 (NAS100 IBS D1) sont inéligibles**. Il ne reste de
   [[system]] que les sleeves intraday : **b1, TLF, HMASTO**.
2. **Le Max Loss Limit est un trailing de FIN DE JOURNÉE qui se verrouille** :
   `MLL = min(plus haut solde de clôture − MLL_initial, solde_initial + 100)`.
   Sur 50 k : plancher 48 000, verrouillé à 50 100 dès que le compte dépasse 52 100.
   Les mèches intraday ne font PAS monter le plancher — c'est la règle la plus
   favorable de la place pour un book intraday.
3. **Les automates et copieurs sont explicitement autorisés**, news autorisées sur
   Pro/Flex, mais le **hedging inter-comptes est interdit** : on ne peut pas répartir
   b1 / TLF / HMASTO sur plusieurs comptes pour éviter qu'ils se compensent. Sur un
   compte futures en netting, il faut un **agrégateur de position nette** par symbole.

## Ce que la simulation en a tiré

Voir les **trois** entrées `2026-08-16` de [[log]] — chacune corrige la précédente ; seule
la troisième fait foi : cartographie complète Pro vs Flex, sizing en
micros entiers (MNQ 2 $/pt, MES 5 $/pt), Monte-Carlo achat-cramage sur 3 ans.
Résultat structurant, une fois le breach testé sur l'**equity** et non sur le solde
réalisé (le premier moteur était trop indulgent, un contrôle à dérive nulle l'a montré) :
sur un index **calendaire** (le bootstrap par jours actifs gonflait les EV/an d'un facteur
égal à l'inverse du taux d'activité), **b1+TLF est le meilleur book Lucid** (+3 201 $/an,
encore positif à 35 % d'edge) — b1 seule domine par *jour de trade* mais est inactive 74 %
du temps (+2 089 $/an). L'edge de rupture vaut **~30-35 %** de l'espérance backtestée ;
optimum de risque **1 %**.

⭐ **Mais la conclusion qui compte est ailleurs : sur ce book, FTMO écrase Lucid d'un
facteur ~3** (+6 197 $/an contre +2 089 $, et +1 941 contre +196 à 35 % d'edge). Ce qui
compte est le rapport **(drawdown autorisé)/(queue journalière)** — 10 R chez FTMO contre
4 R chez Lucid — et le fait que FTMO (compte **Swing**) laisse tourner le book COMPLET,
252 jours actifs par an contre 97. Lucid ne coûte pas du sizing, il coûte **l'amputation
de b2, b3 et b4**, c'est-à-dire toute la décorrélation du livre.
