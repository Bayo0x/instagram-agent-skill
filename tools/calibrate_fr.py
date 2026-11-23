#!/usr/bin/env python3
"""
calibrate_fr.py - measure hookscore.py and hooks.fr.json on a real French corpus.

Same three measurements as the original author's English test:
  1. Real hooks vs deliberately bad hooks (AUC). Does it catch bad hooks?
  2. Top band vs bottom band of the same channels (AUC). Does it pick winners?
  3. Formula coverage: share of real hooks that a hooks.fr.json regex names.
Plus the median of each check per band, to see which checks measure anything.

Usage
  python3 calibrate_fr.py corpus.tsv
  python3 calibrate_fr.py corpus.tsv --unclassified     # list hooks no formula names
"""

import argparse
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REEL = os.path.join(HERE, "..", "skills", "ig-reel")
sys.path.insert(0, REEL)
from hookscore import run, CHECKS  # noqa: E402

BAD = [
    "Salut tout le monde, aujourd'hui on va parler de stratégie de contenu",
    "Coucou, j'espère que vous allez bien, petite vidéo rapide",
    "Dans cette vidéo je vais vous montrer comment avoir plus de clients",
    "Alors aujourd'hui je voulais vous parler d'un sujet important",
    "Bonjour à tous et bienvenue sur ma chaîne",
    "Arrête de scroller si tu veux réussir sur Instagram 🔥",
    "Hello, c'est moi, on se retrouve pour une nouvelle vidéo",
    "Bon, euh, je sais pas trop par où commencer mais voilà",
    "Il y a beaucoup de choses à dire sur le marketing digital en général",
    "Petit rappel important pour tous ceux qui nous suivent #business",
]


def auc(pos, neg):
    """Probability a random positive outranks a random negative (ties = 0.5)."""
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def load(path):
    lines = [l for l in open(path, encoding="utf-8").read().splitlines() if l.strip()]
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--hooks", default=os.path.join(REEL, "hooks.fr.json"))
    ap.add_argument("--unclassified", action="store_true")
    args = ap.parse_args()

    rows = load(args.corpus)
    d = json.load(open(args.hooks, encoding="utf-8"))
    by = {h["id"]: h for h in d["hooks"]}
    formulas = [(i, by[i]["name"], re.compile(by[i]["match"], re.I)) for i in d["classify_order"]]

    def classify(t):
        return next(((i, n) for i, n, p in formulas if p.search(t)), (None, None))

    for r in rows:
        res, overall, verdict, flags = run(r["hook"], "fr")
        r["score"], r["checks"] = overall, {c: res[c][0] for c in CHECKS}
        r["fid"], r["fname"] = classify(r["hook"])

    real = [r["score"] for r in rows]
    bad = [run(h, "fr")[1] for h in BAD]
    top = [r for r in rows if r.get("band") == "top"]
    bottom = [r for r in rows if r.get("band") == "bottom"]
    med_real = statistics.median(real)

    print(f"\nCORPUS  {len(rows)} hooks, {len({r['account'] for r in rows})} chaînes, "
          f"{len(top)} top / {len(bottom)} bottom")
    a1 = auc(real, bad)
    print(f"\n1. Vrais hooks vs hooks pourris   AUC {a1:.2f}   "
          f"({sum(1 for b in bad if b < med_real)}/10 pourris sous la médiane réelle)")
    a2 = auc([r["score"] for r in top], [r["score"] for r in bottom])
    print(f"2. Top vs bottom (mêmes chaînes)  AUC {a2:.2f}   (0.50 = pile ou face)"
          if a2 is not None else "2. pas de colonne band")
    named = sum(1 for r in rows if r["fid"])
    print(f"3. Formules reconnues             {named}/{len(rows)} = {named * 100 / len(rows):.0f} %")

    print("\nMÉDIANE PAR CHECK          top    bottom   écart")
    for c in CHECKS:
        t = statistics.median(r["checks"][c] for r in top) if top else 0
        b = statistics.median(r["checks"][c] for r in bottom) if bottom else 0
        print(f"  {c:<14}        {t:6.1f}  {b:6.1f}   {t - b:+6.1f}")

    counts = {}
    for r in rows:
        if r["fname"]:
            counts[r["fname"]] = counts.get(r["fname"], 0) + 1
    print("\nFORMULES LES PLUS VUES")
    for n, c in sorted(counts.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {c:>3}  {n}")
    if args.unclassified:
        print("\nNON RECONNUS")
        for r in rows:
            if not r["fid"]:
                print(f"  [{r.get('band', '')}] {r['hook']}")
    print()


if __name__ == "__main__":
    main()
