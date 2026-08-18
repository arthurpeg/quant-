"""ETAPE 2 -- moisson de la litterature et generation du catalogue d'hypotheses.

    python research/scripts/02_harvest_papers.py [--offline] [--max-per-query 100]

CE QUE CE SCRIPT FAIT, ET SURTOUT CE QU'IL NE FAIT PAS.

Il moissonne des METADONNEES (titre, resume, mecanisme annonce, lien) sur
quatre sources, puis il RATTACHE chaque papier a une des cinq familles de
signaux du mandat par un classifieur a mots-cles. Il ne lit pas les formules
dans les PDF : aucun extracteur de formule n'est fiable sans modele de langue
dans la boucle, et une formule mal extraite est pire qu'absente parce qu'elle
serait ensuite mesuree comme si elle etait la bonne.

La consequence est explicite et portee dans le JSON : le champ
`formula_provenance` vaut "template" partout. La litterature apporte la
PROVENANCE et le MECANISME ; la formule vient de la bibliotheque `signals.py`,
ou elle est ecrite et versionnee a la main. Un papier qui documente le momentum
intraday appuie la famille "intraday_momentum_breakout" -- il ne dicte pas le
`n` de la moyenne.

QUATRE SOURCES, ET LEUR ETAT REEL.
  arXiv     API Atom publique, categories q-fin.{TR,ST,PM,CP}. Fonctionne.
  NBER      listing JSON public. Fonctionne.
  OpenAlex  index ouvert couvrant SSRN, NBER et les revues. Fonctionne.
  SSRN      l'API `api.ssrn.com/content/v1/papers?searchTerm=` rend 401
            Unauthorized sans cle : SSRN n'est donc PAS moissonne en direct.
            Il est atteint indirectement via OpenAlex, et le depot porte deja
            un corpus SSRN hors ligne (`ssrn_candidates_mass.csv`, 2 351
            resumes) qui est relu ici. C'est ecrit plutot que contourne.

Sortie : `research/data/literature.json` (les papiers) et
`research/data/hypotheses.json` (le catalogue de definitions de signal, source
et mecanisme rattaches). L'expansion actif x UT x horizon est faite par
l'etape 3, sinon le catalogue ferait 30 000 lignes redondantes.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
import signals as SG

LOG = C.get_logger("02_harvest")

UA = "quant-research/1.0 (mailto:rosremy06@gmail.com)"
ARXIV_CATS = ["q-fin.TR", "q-fin.ST", "q-fin.PM", "q-fin.CP"]
QUERIES = [
    "intraday momentum", "opening range", "overnight returns", "reversal",
    "volatility spillover", "order flow imbalance", "mean reversion",
    "calendar anomaly", "lead lag", "volume toxicity",
]

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:                                    # pragma: no cover
    _CTX = None


def _get(url: str, tries: int = 3, pause: float = 3.0) -> bytes | None:
    """GET poli : 3 s entre appels (regle arXiv), 3 essais, echec non fatal."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45, context=_CTX) as f:
                data = f.read()
            time.sleep(pause)
            return data
        except Exception as e:
            LOG.warning("GET echec (%d/%d) %s : %r", i + 1, tries,
                        url.split("?")[0], e)
            time.sleep(pause * (i + 1))
    return None


# ------------------------------------------------------------------ arXiv
def harvest_arxiv(max_per_query: int) -> list[dict]:
    out, seen = [], set()
    cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATS)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for q in QUERIES:
        got = 0
        for start in range(0, max_per_query, 100):
            url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({
                "search_query": f"({cats}) AND all:\"{q}\"",
                "start": start, "max_results": min(100, max_per_query - start),
                "sortBy": "relevance", "sortOrder": "descending"})
            raw = _get(url)
            if raw is None:
                break
            try:
                feed = ET.fromstring(raw)
            except ET.ParseError as e:
                LOG.warning("arXiv XML illisible pour '%s' : %r", q, e)
                break
            entries = feed.findall("a:entry", ns)
            if not entries:
                break
            for e in entries:
                aid = (e.findtext("a:id", "", ns) or "").rsplit("/", 1)[-1]
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                out.append(dict(
                    source="arXiv", ref=f"arXiv:{aid}",
                    title=" ".join((e.findtext("a:title", "", ns) or "").split()),
                    abstract=" ".join((e.findtext("a:summary", "", ns) or "").split()),
                    url=e.findtext("a:id", "", ns),
                    date=(e.findtext("a:published", "", ns) or "")[:10],
                    query=q))
                got += 1
            if len(entries) < 100:
                break
        LOG.info("arXiv  '%-22s' : %3d papiers", q, got)
    return out


# ------------------------------------------------------------------ NBER
def harvest_nber(max_per_query: int) -> list[dict]:
    out, seen = [], set()
    for q in QUERIES:
        url = ("https://www.nber.org/api/v1/working_page_listing/contentType/"
               "working_paper/_/_/search?" + urllib.parse.urlencode(
                   {"q": q, "page": 1, "perPage": min(100, max_per_query),
                    "sortBy": "public_date"}))
        raw = _get(url, pause=1.0)
        if raw is None:
            continue
        try:
            js = json.loads(raw)
        except json.JSONDecodeError:
            LOG.warning("NBER JSON illisible pour '%s'", q)
            continue
        got = 0
        for r in js.get("results", []):
            title = re.sub(r"<[^>]+>", "", r.get("title", "")).strip()
            key = title.lower()[:120]
            if not title or key in seen:
                continue
            seen.add(key)
            out.append(dict(source="NBER", ref=r.get("displaypaper", "") or "NBER WP",
                            title=title,
                            abstract=re.sub(r"<[^>]+>", "", r.get("abstract", "") or ""),
                            url="https://www.nber.org" + (r.get("url", "") or ""),
                            date=(r.get("displaydate", "") or "")[:10], query=q))
            got += 1
        LOG.info("NBER   '%-22s' : %3d papiers", q, got)
    return out


# ------------------------------------------------------------------ OpenAlex
def _reconstruct(inv: dict) -> str:
    """OpenAlex sert le resume en index inverse ; on le remonte tel quel."""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def harvest_openalex(max_per_query: int) -> list[dict]:
    """Index ouvert : c'est par ici que SSRN et les revues entrent."""
    out, seen = [], set()
    for q in QUERIES:
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode({
            "search": q, "per-page": min(100, max_per_query),
            "filter": "type:article|preprint",
            "mailto": "rosremy06@gmail.com"})
        raw = _get(url, pause=0.5)
        if raw is None:
            continue
        try:
            js = json.loads(raw)
        except json.JSONDecodeError:
            continue
        got = 0
        for r in js.get("results", []):
            oid = r.get("id", "")
            if not oid or oid in seen:
                continue
            seen.add(oid)
            loc = (r.get("primary_location") or {}).get("source") or {}
            out.append(dict(
                source="OpenAlex", ref=(loc.get("display_name") or "OpenAlex"),
                title=r.get("title") or "",
                abstract=_reconstruct(r.get("abstract_inverted_index") or {}),
                url=r.get("doi") or oid,
                date=(r.get("publication_date") or "")[:10], query=q))
            got += 1
        LOG.info("OpenAlex '%-20s' : %3d papiers", q, got)
    return out


# ------------------------------------------------------------------ SSRN
def harvest_ssrn() -> list[dict]:
    """Tentative directe, consignee. Sans cle l'API rend 401 ; on ne bricole pas."""
    url = "https://api.ssrn.com/content/v1/papers?searchTerm=intraday+momentum&index=0&count=5"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30, context=_CTX) as f:
            js = json.loads(f.read())
        LOG.info("SSRN : recherche directe disponible (%d resultats)",
                 len(js.get("papers", [])))
        return [dict(source="SSRN", ref=str(p.get("id", "")),
                     title=p.get("title", ""), abstract=p.get("abstract", ""),
                     url=p.get("url", ""), date=str(p.get("approved_date", ""))[:10],
                     query="intraday momentum")
                for p in js.get("papers", [])]
    except urllib.error.HTTPError as e:
        LOG.warning("SSRN : recherche par mot-cle refusee (HTTP %s). "
                    "SSRN est atteint via OpenAlex et via le corpus local.", e.code)
    except Exception as e:                            # pragma: no cover
        LOG.warning("SSRN : indisponible (%r)", e)
    return []


# ------------------------------------------------------------------ corpus local
def harvest_local() -> list[dict]:
    """Le corpus deja constitue par ce depot (moisson SSRN/OpenAlex anterieure)."""
    p = C.REPO / "ssrn_candidates_mass.csv"
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            t = (r.get("title") or "").strip()
            if not t:
                continue
            out.append(dict(source="corpus_local", ref=(r.get("publisher") or "").strip(),
                            title=t, abstract=(r.get("summary") or "").strip(),
                            url=(r.get("url") or "").strip(), date="",
                            query=(r.get("matched_keyword") or "").strip()))
    LOG.info("corpus local (ssrn_candidates_mass.csv) : %d papiers", len(out))
    return out


# ------------------------------------------------------------------ classement
# Un papier est rattache a une famille quand son titre ou son resume porte des
# marqueurs de son MECANISME. C'est volontairement grossier et lisible : la
# seule chose qu'on demande a ce classement est de dire "ce papier soutient
# cette famille", pas d'en tirer une formule.
FAMILY_MARKERS = {
    "intraday_momentum_breakout": [
        "intraday momentum", "opening range", "time series momentum", "breakout",
        "trend following", "momentum strategy", "last half-hour", "first half-hour",
        "range breakout", "continuation"],
    "mean_reversion_extreme": [
        "mean reversion", "reversal", "contrarian", "overreaction", "vwap",
        "bollinger", "oversold", "overbought", "short-term reversal",
        "price reversal", "reverting"],
    "microstructure_session_seasonality": [
        "order flow", "order imbalance", "toxicity", "vpin", "microstructure",
        "market open", "market close", "closing auction", "calendar anomaly",
        "day of the week", "turn of the month", "seasonality", "intraday pattern",
        "london fix", "fixing", "overnight return", "night effect"],
    "cross_asset_lead_lag": [
        "lead lag", "lead-lag", "spillover", "cross-asset", "cross asset",
        "information transmission", "pairs trading", "cointegration",
        "cross-sectional momentum", "relative strength", "contagion"],
    "volatility_skew_dynamics": [
        "realized volatility", "volatility spillover", "variance risk",
        "skewness", "volatility of volatility", "volatility clustering",
        "realized skewness", "vol-of-vol", "volatility timing",
        "volatility managed", "garch"],
}


def classify(paper: dict) -> list[tuple[str, int]]:
    txt = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    hits = []
    for fam, marks in FAMILY_MARKERS.items():
        n = sum(1 for m in marks if m in txt)
        if n:
            hits.append((fam, n))
    return sorted(hits, key=lambda x: -x[1])


# ------------------------------------------------------------------ catalogue
def build_catalog(papers: list[dict]) -> list[dict]:
    """Catalogue des definitions de signal, chacune rattachee a sa litterature.

    L'identifiant est stable et lisible : FAMILLE_TYPE_paramhash. Il est
    reutilise tel quel par l'etape 4 pour composer le `hypothesis_id` final
    avec l'actif, l'UT et l'horizon.
    """
    by_fam: dict[str, list[dict]] = {f: [] for f in FAMILY_MARKERS}
    for p in papers:
        for fam, score in classify(p):
            by_fam[fam].append(dict(p, _score=score))
    for f in by_fam:
        by_fam[f].sort(key=lambda x: (-x["_score"], x.get("source") != "arXiv"))
        LOG.info("famille %-38s : %5d papiers rattaches", f, len(by_fam[f]))

    fam_abbr = {"intraday_momentum_breakout": "MOM",
                "mean_reversion_extreme": "REV",
                "microstructure_session_seasonality": "SES",
                "cross_asset_lead_lag": "XAS",
                "volatility_skew_dynamics": "VOL"}

    catalog, i_by_fam = [], {f: 0 for f in FAMILY_MARKERS}
    seen = set()
    for sym in C.UNIVERSE:
        for spec in SG.instantiate(sym):
            key = SG.spec_key(spec)
            if key in seen:
                continue
            seen.add(key)
            fam = spec["family"]
            refs = by_fam.get(fam, [])
            # rotation : chaque definition porte un papier different de sa
            # famille, pour que la provenance soit tracable et pas decorative
            ref = refs[i_by_fam[fam] % len(refs)] if refs else None
            i_by_fam[fam] += 1
            catalog.append(dict(
                signal_id=f"{fam_abbr[fam]}_{key}",
                family=fam,
                signal_type=spec["type"],
                params=spec["params"],
                sign_prior=spec["sign_prior"],
                formula_description=SG.FORMULA[spec["type"]],
                formula_provenance="template",
                mechanism=(ref or {}).get("title", "") or
                          "genere par le moteur combinatoire (aucun papier rattache)",
                source=(f"{(ref or {}).get('source', 'generative')}"
                        f":{(ref or {}).get('ref', '')}".rstrip(":")),
                source_url=(ref or {}).get("url", ""),
                n_papers_family=len(refs),
            ))
    return catalog


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="n'utilise que le corpus local deja dans le depot")
    ap.add_argument("--max-per-query", type=int, default=200)
    a = ap.parse_args()

    papers: list[dict] = []
    if a.offline:
        LOG.info("mode HORS LIGNE : seul le corpus local est lu")
    else:
        papers += harvest_arxiv(a.max_per_query)
        papers += harvest_nber(a.max_per_query)
        papers += harvest_openalex(a.max_per_query)
        papers += harvest_ssrn()
    papers += harvest_local()

    # OpenAlex et NBER servent des entites HTML (&amp;, &#39;) dans les titres.
    for p in papers:
        for f in ("title", "abstract"):
            p[f] = html.unescape(p.get(f) or "")

    # dedoublonnage sur le titre normalise
    uniq, seen = [], set()
    for p in papers:
        k = re.sub(r"[^a-z0-9]+", "", (p.get("title") or "").lower())[:120]
        if not k or k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    LOG.info("moisson : %d papiers bruts -> %d uniques", len(papers), len(uniq))

    (C.DATA / "literature.json").write_text(
        json.dumps(uniq, indent=1, ensure_ascii=False), encoding="utf-8")

    catalog = build_catalog(uniq)
    (C.DATA / "hypotheses.json").write_text(
        json.dumps(catalog, indent=1, ensure_ascii=False), encoding="utf-8")
    LOG.info("ETAPE 2 terminee : %d definitions de signal dans le catalogue",
             len(catalog))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
