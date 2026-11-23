#!/usr/bin/env python3
"""
hookscore.py - score the first line of a Reel on the five things strong hooks
have in common, and rank a batch of them against each other.

What this is:  five local heuristics, computed on your machine from the text
alone. They measure properties that hooks which hold attention tend to share -
a length you can say in under three seconds, a concrete marker, something at stake,
the payload at the front rather than the back, and a viewer to aim it at.

What this is NOT:  a view predictor. It was tested against 74 real short-form
hooks, transcribed from the first three seconds of the top eight and bottom
eight performers on five channels. Separating a real hook from a deliberately
bad one it does well: AUC 0.83, and 9 of 10 written-to-be-bad hooks scored
below the real median. Separating a good creator's hits from that same
creator's misses it barely does at all: AUC 0.56, where 0.50 is a coin flip.

So use it for what it measured well. It catches greetings, preambles, hooks
with nothing concrete in them and hooks that take five seconds to say. It will
not tell you which of two decent hooks will travel, and nothing that reads text
can, because that is decided by your face, your edit, your audio and who
Instagram shows it to. Trust the retention graph over this script.

Each check returns 0 to 100. Higher is better.

Langue: --lang fr|en|auto (défaut auto, détecté ligne par ligne). Le français
a ses propres listes (chiffres dits à l'oral, €, tension, ouvertures molles,
tu/vous) et ses propres dealbreakers ("arrête de scroller", "dans cette vidéo").

Usage
  python3 hookscore.py hooks.txt              # one hook per line, ranked
  python3 hookscore.py hooks.txt --lang fr
  python3 hookscore.py --hook "I lost $18,000 on one missing contract."
  pbpaste | python3 hookscore.py -
  python3 hookscore.py hooks.txt --json
"""

import argparse
import json
import re
import statistics
import sys

WORD_RE = re.compile(r"[A-Za-z0-9$%'’-]+")
NUMBER_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"                       # money, whole
    r"|\b\d[\d,]*(?:\.\d+)?\s?"                      # a figure, with or
    r"(?:%|k\b|x\b|hrs?\b|hours?\b|mins?\b|minutes?\b"  # without a unit
    r"|days?\b|weeks?\b|months?\b|years?\b)?",
    re.IGNORECASE)
PROPER_RE = re.compile(r"(?<!^)\b[A-Z][a-z]{2,}\b")
HASHTAG_RE = re.compile(r"(?:^|\s)#\w+")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")

# Spoken hooks say their numbers out loud. "Zero dollars" and "twenty grand"
# are as concrete as "$0" and "$20,000", and counting only digits missed them.
# "one" and "first" are deliberately absent: they are filler far more often
# than they are a quantity.
SPOKEN_NUMBERS = {
    "zero", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "dozen", "half", "twice", "triple",
}
MONEY_WORDS = {
    "dollars", "dollar", "bucks", "grand", "percent", "cents",
    "millionaire", "billionaire", "revenue", "profit", "salary", "rent",
}

# Words that put something on the line. A hook with none of these is a
# statement; a hook with one is a reason to keep watching.
STAKES = {
    "stop", "never", "wrong", "mistake", "mistakes", "lost", "lose", "losing",
    "cost", "costs", "broke", "broken", "failed", "failure", "fail", "nobody",
    "no", "not", "don't", "dont", "doesn't", "didn't", "can't", "won't",
    "quit", "quitting", "fired", "deleted", "delete", "killed", "kills", "kill",
    "replaced", "replaces", "cut", "beat", "free", "paid", "charged", "hired",
    "saved", "first",
    "banned", "illegal", "worst", "hate", "hated", "wasted", "waste", "scam",
    "lie", "lied", "lying", "truth", "secret", "hidden", "stole", "stolen",
    "before", "until", "instead", "but", "except", "unless", "problem",
    "risk", "danger", "warning", "regret", "wish", "should", "shouldn't",
    "still", "already", "only", "without", "versus", "vs", "actually",
}

# Openers that spend the first second saying nothing.
WEAK_OPENERS = [
    "so", "ok", "okay", "hey", "hi", "hello", "guys", "yo", "alright",
    "welcome", "today", "basically", "honestly", "look", "listen", "um",
    "just", "let", "lets", "let's", "i wanted", "i want", "one of",
    "have you", "did you", "do you", "are you", "in this", "in today",
    "the thing", "a lot", "there is", "there are", "this is", "it is",
    "as a", "when it", "if you've", "you know",
]

# Imperatives that earn the front position.
IMPERATIVES = {
    "stop", "steal", "copy", "delete", "try", "watch", "read", "save",
    "use", "build", "make", "write", "send", "take", "start", "quit",
    "never", "always", "don't", "dont", "do", "put", "run", "check",
}

DEALBREAKERS = [
    (re.compile(r"(?i)^\s*(?:stop scrolling|don'?t scroll)"),
     "Opens with \"stop scrolling\". Asking for attention proves you have not earned it."),
    (re.compile(r"(?i)\b(?:in (?:this|today'?s) (?:video|reel)|i'?m going to show you|i'?ll show you how)\b"),
     "Video preamble. Delete it and open on the payoff."),
    (re.compile(r"(?i)^\s*(?:hey |hi |what'?s up |welcome )"),
     "Greeting. Nobody came to the feed to be greeted."),
    (HASHTAG_RE,
     "Hashtag in the hook. Hashtags belong at the bottom of the caption, if anywhere."),
    (EMOJI_RE,
     "Emoji in the hook. On-screen text at hook size has room for words or for an emoji, not both."),
]


# ---------------------------------------------------------------------------
# Français. Même logique, vocabulaire du français parlé. Un mot = ce qui est
# entre deux espaces, donc "j'ai" compte pour un mot (c'est aussi comme ça
# que se mesure le débit de 165 mots/min en français).
# ---------------------------------------------------------------------------

FR_WORD_RE = re.compile(r"[\w$€%'’-]+")
FR_NUMBER_RE = re.compile(
    r"(?:€|\$)\s?\d[\d\s.,]*\d|(?:€|\$)\s?\d"                 # €18 000
    r"|\b\d[\d.,]*(?:[   ]\d{3})*(?:[.,]\d+)?\s?"   # un chiffre
    r"(?:€|euros?\b|balles\b|%|k\b|k€|x\b|h\b|heures?\b|min\b|minutes?\b"
    r"|jours?\b|semaines?\b|mois\b|ans\b|années?\b|fois\b|clients?\b|sites?\b)?",
    re.IGNORECASE)
FR_PROPER_RE = re.compile(r"(?<!^)\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]{2,}\b")
FR_ELISION_RE = re.compile(r"^(?:[ljmtsdcn]|qu|jusqu|lorsqu|puisqu)['’]", re.IGNORECASE)

FR_SPOKEN_NUMBERS = {
    "zéro", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "onze", "douze", "quinze", "vingt", "trente", "quarante",
    "cinquante", "soixante", "cent", "cents", "mille", "million", "millions",
    "milliard", "milliards", "douzaine", "moitié", "double", "triple",
}
FR_MONEY_WORDS = {
    "euros", "euro", "balles", "centimes", "pourcent", "salaire", "loyer",
    "smic", "devis", "facture", "factures", "bénéfice", "bénéf", "marge",
    "chiffre", "ca", "millionnaire", "prix", "tarif", "tarifs",
}
FR_STAKES = {
    "arrête", "arrêtez", "stop", "jamais", "faux", "erreur", "erreurs",
    "perdu", "perdre", "perds", "perte", "coûte", "coûté", "coûter", "fauché",
    "cassé", "raté", "rater", "échec", "échoué", "personne", "pas", "rien",
    "aucun", "aucune", "quitté", "viré", "supprimé", "supprime",
    "tué", "tue", "remplacé", "remplace", "gratuit", "payé", "payer", "paie",
    "embauché", "économisé", "premier", "première", "interdit", "illégal",
    "pire", "déteste", "détesté", "gaspillé", "arnaque", "mensonge", "menti",
    "vérité", "secret", "caché", "volé", "avant", "jusqu'à", "lieu", "mais",
    "sauf", "problème", "risque", "danger", "attention", "regret",
    "regrette", "aurais", "devrais", "encore", "déjà", "seulement", "sans",
    "contre", "vs", "vraiment", "honte", "flop", "flopé", "ruiné",
}
FR_WEAK_OPENERS = [
    "alors", "bon", "ok", "okay", "salut", "coucou", "hello", "hey", "yo",
    "bonjour", "bonsoir", "bienvenue", "aujourd'hui", "aujourd’hui",
    "en gros", "honnêtement", "franchement", "écoute", "écoutez", "euh",
    "bah", "ben", "juste", "laisse", "laissez", "je voulais", "je vais",
    "je veux", "l'un des", "l’un des", "un des", "une des", "est-ce que",
    "vous avez", "tu as", "t'as", "t’as", "as-tu", "avez-vous", "dans cette",
    "dans ce", "il y a", "y'a", "y’a", "ceci est", "il est", "en tant que",
    "quand on", "si vous avez", "si tu as", "tu sais", "vous savez",
    "petit rappel", "petite astuce",
]
FR_IMPERATIVES = {
    "arrête", "arrêtez", "stop", "vole", "volez", "pique", "piquez", "copie",
    "copiez", "supprime", "supprimez", "essaie", "essaye", "essayez",
    "regarde", "regardez", "lis", "lisez", "enregistre", "enregistrez",
    "sauvegarde", "utilise", "utilisez", "construis", "fais", "faites",
    "écris", "écrivez", "envoie", "envoyez", "prends", "prenez", "commence",
    "commencez", "quitte", "jamais", "toujours", "ne", "mets", "mettez",
    "lance", "lancez", "vérifie", "vérifiez", "garde", "oublie", "oubliez",
    "change", "changez", "demande", "demandez", "note", "notez", "teste",
    "testez", "évite", "évitez",
}
FR_DEALBREAKERS = [
    (re.compile(r"(?i)^\s*(?:arr[êe]te[zs]? de scroller|stop(?:pe)? (?:ton|le) scroll"
                r"|ne scrolle[zs]? pas|attends?,? ne scrolle)"),
     "Ouvre sur \"arrête de scroller\". Demander l'attention prouve qu'on ne l'a pas méritée."),
    (re.compile(r"(?i)\b(?:dans (?:cette|la) vidéo|dans ce (?:réel|reel)|aujourd['’]hui je vais"
                r"|je vais (?:te|vous) (?:montrer|expliquer|apprendre))\b"),
     "Préambule de vidéo. Supprime-le et ouvre sur le résultat."),
    (re.compile(r"(?i)^\s*(?:salut|coucou|hello|hey|bonjour|bonsoir|bienvenue|yo)\b"),
     "Salutation. Personne n'est venu sur le feed pour se faire saluer."),
    (HASHTAG_RE,
     "Hashtag dans le hook. Les hashtags vont en bas de la légende, si on en met."),
    (EMOJI_RE,
     "Emoji dans le hook. En texte à l'écran à taille de hook, c'est des mots ou un emoji, pas les deux."),
]
FR_YOU_RE = re.compile(r"(?i)(?<![\w])(?:tu|te|toi|ton|ta|tes|vous|votre|vos|t['’])(?![\w])|(?<![\w])t['’]")
FR_ME_RE = re.compile(r"(?i)(?<![\w])(?:je|me|moi|mon|ma|mes|nous|notre|nos|on)(?![\w])|(?<![\w])[jm]['’]")

# Mots-outils qui trahissent la langue. Sert à --lang auto.
_FR_MARKERS = {"le", "la", "les", "des", "est", "une", "et", "pour", "pas", "que",
               "qui", "dans", "sur", "avec", "je", "tu", "vous", "mon", "ton",
               "c'est", "j'ai", "ça", "mais", "plus", "ce", "cette", "au", "du"}
_EN_MARKERS = {"the", "and", "is", "you", "to", "of", "that", "it", "for", "with",
               "this", "my", "your", "i", "was", "are", "how", "what", "on", "in"}


def detect_lang(text):
    """'fr' ou 'en', sur les mots-outils et les accents."""
    toks = re.findall(r"[\w'’]+", text.lower())
    fr = sum(1 for t in toks if t.replace("’", "'") in _FR_MARKERS)
    en = sum(1 for t in toks if t in _EN_MARKERS)
    fr += len(re.findall(r"[éèêàùçôîâ]", text.lower())) * 0.5
    return "fr" if fr > en else "en"


def clamp(n):
    return max(0.0, min(100.0, n))


def words(text, lang="en"):
    if lang == "fr":
        # "18 000 €" se dit d'un bloc : un seul mot ici aussi.
        text = re.sub(r"(?<=\d)[   .](?=\d{3}\b)", "", text)
        return FR_WORD_RE.findall(text)
    # "$18,000" is one word when it is spoken, so it is one word here too.
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))


def norm(token, lang="en"):
    """Lower-case, strip quotes; in French also drop the elision (n'ai -> ai)."""
    t = token.lower().strip("'’")
    if lang == "fr":
        t = FR_ELISION_RE.sub("", t).replace("’", "'")
    return t


def cfg(lang):
    if lang == "fr":
        return dict(number=FR_NUMBER_RE, proper=FR_PROPER_RE, spoken=FR_SPOKEN_NUMBERS,
                    money=FR_MONEY_WORDS, stakes=FR_STAKES, openers=FR_WEAK_OPENERS,
                    imperatives=FR_IMPERATIVES, dealbreakers=FR_DEALBREAKERS,
                    max_chars=65, price=r"(?:€|\$)\s?\d|\d\s?(?:€|euros?\b|k€)")
    return dict(number=NUMBER_RE, proper=PROPER_RE, spoken=SPOKEN_NUMBERS,
                money=MONEY_WORDS, stakes=STAKES, openers=WEAK_OPENERS,
                imperatives=IMPERATIVES, dealbreakers=DEALBREAKERS,
                max_chars=60, price=r"\$\s?\d")


def check_length(text, lang="en"):
    """A hook has to land before the thumb moves. Roughly two seconds."""
    c = cfg(lang)
    w = words(text, lang)
    n = len(w)
    secs = n / 2.75                      # ~165 words per minute, spoken (EN and FR)
    chars = len(text.strip())
    if 5 <= n <= 12:
        score = 100.0
    elif n < 5:
        score = clamp(100 - (5 - n) * 20)
    else:
        score = clamp(100 - (n - 12) * 11)
    if chars > c["max_chars"]:           # two lines of big on-screen text
        score -= 12
    if lang == "fr":
        return clamp(score), f"{n} mots, {chars} caractères, ~{secs:.1f}s à l'oral (viser 5-12 mots)"
    return clamp(score), f"{n} words, {chars} chars, ~{secs:.1f}s spoken (want 5-12 words)"


def check_specificity(text, lang="en"):
    """One concrete thing beats three abstract ones."""
    c = cfg(lang)
    nums = [n.strip() for n in c["number"].findall(text) if n.strip()]
    propers = set(c["proper"].findall(text))
    low = [norm(w, lang) for w in words(text, lang)]
    spoken = [w for w in low if w in c["spoken"] or w in c["money"]]
    hits = len(nums) + len(propers) + len(spoken)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    found = ", ".join(nums[:2] + sorted(propers)[:2] + spoken[:2])
    if lang == "fr":
        return score, (f"{hits} élément(s) concret(s)" + (f" : {found}" if found else
                       " - aucun chiffre, aucun nom, rien de vérifiable"))
    return score, (f"{hits} concrete marker(s)" + (f": {found}" if found else
                   " - no number, no name, nothing checkable"))


def check_stakes(text, lang="en"):
    """Tension, cost, negation. Something the viewer might lose."""
    c = cfg(lang)
    w = [norm(x, lang) for x in words(text, lang)]
    hits = [x for x in w if x in c["stakes"]]
    markers = sorted(set(hits))
    if lang == "fr" and re.search(r"(?i)(?<![\w])n['’]|\bne\b", text) and "pas" not in markers:
        markers.append("négation")
    if re.search(c["price"], text):
        markers.append("un prix" if lang == "fr" else "a price")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    if lang == "fr":
        detail = f"{n} marqueur(s) de tension" + (f" : {', '.join(markers[:4])}" if markers else
                                                  " - rien n'est en jeu dans cette phrase")
    else:
        detail = f"{n} tension marker(s)" + (f": {', '.join(markers[:4])}" if markers else
                                             " - nothing is at stake in this line")
    return clamp(score), detail


def check_frontload(text, lang="en"):
    """The interesting word cannot be in position nine."""
    c = cfg(lang)
    w = words(text, lang)
    if not w:
        return 0.0, "empty"
    low = [norm(x, lang) for x in w]
    penalty = 0
    hit_opener = None
    if lang == "fr":
        head = text.strip().lower().lstrip("\"“«' ")
        for weak in c["openers"]:
            if re.match(re.escape(weak) + r"(?![\w])", head):
                penalty, hit_opener = 30, weak
                break
    else:
        opener = " ".join(low[:2])
        for weak in c["openers"]:
            if opener.startswith(weak) or low[0] == weak:
                penalty, hit_opener = 30, weak
                break
    payload = None
    for i, token in enumerate(low):
        if (token in c["stakes"] or token in c["spoken"] or token in c["money"]
                or c["number"].match(w[i]) or (i and c["proper"].match(w[i]))):
            payload = i
            break
    fr = lang == "fr"
    if payload is None:
        base = 30.0
        where = "aucun mot fort dans la phrase" if fr else "no payload word anywhere in the line"
    elif payload <= 3:
        base = 100.0
        where = (f"mot fort en position {payload + 1}" if fr else f"payload at word {payload + 1}")
    elif payload <= 6:
        base = 70.0
        where = (f"mot fort en position {payload + 1}, peut avancer" if fr
                 else f"payload at word {payload + 1}, could move forward")
    else:
        base = 40.0
        where = (f"mot fort en position {payload + 1}, trop tard" if fr
                 else f"payload at word {payload + 1}, too late")
    if hit_opener:
        where += (f" ; ouverture molle \"{hit_opener}\"" if fr else f"; weak opener \"{hit_opener}\"")
    return clamp(base - penalty), where


def check_address(text, lang="en"):
    """Aimed at one viewer, or floating in the air."""
    c = cfg(lang)
    low = text.lower()
    w = [norm(x, lang) for x in words(text, lang)]
    if lang == "fr":
        if FR_YOU_RE.search(text):
            return 100.0, "parle au spectateur (tu/vous)"
        if w and w[0] in c["imperatives"]:
            return 90.0, f"ouvre sur un impératif (\"{w[0]}\")"
        if FR_ME_RE.search(text):
            return 70.0, "première personne, personne d'autre dans la pièce"
        return 35.0, "troisième personne, personne n'est visé"
    if re.search(r"\b(you|your|you're|youre|yourself)\b", low):
        return 100.0, "speaks to the viewer"
    if w and w[0] in c["imperatives"]:
        return 90.0, f"imperative opener (\"{w[0]}\")"
    if re.search(r"\b(i|my|me|we|our)\b", low):
        return 70.0, "first person, no viewer named"
    return 35.0, "third person, nobody in the room"


CHECKS = ["LENGTH", "SPECIFICITY", "STAKES", "FRONTLOAD", "ADDRESS"]


def run(text, lang=None):
    """Score one hook. lang: 'en', 'fr' or None to detect it from the text."""
    lang = lang if lang in ("en", "fr") else detect_lang(text)
    results = {
        "LENGTH": check_length(text, lang),
        "SPECIFICITY": check_specificity(text, lang),
        "STAKES": check_stakes(text, lang),
        "FRONTLOAD": check_frontload(text, lang),
        "ADDRESS": check_address(text, lang),
    }
    flags = [msg for pattern, msg in cfg(lang)["dealbreakers"] if pattern.search(text)]
    scores = [results[c][0] for c in CHECKS]
    # The weakest property caps the hook, same logic as detect.py: one bad
    # property is enough for the thumb to keep moving.
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15
    overall = clamp(overall)
    verdict = "STRONG" if overall >= 70 and min(scores) >= 55 and not flags else (
        "OK" if overall >= 50 else "WEAK")
    return results, overall, verdict, flags


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render_one(text, results, overall, verdict, flags, out=sys.stdout):
    print("\nHOOK SCORE", file=out)
    print("=" * 62, file=out)
    print(f"  \"{text.strip()}\"\n", file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HOOK SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    for f in flags:
        print(f"\n  DEALBREAKER  {f}", file=out)
    if verdict != "STRONG":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest property: {weakest}. Fix that one and re-run.", file=out)
    print("", file=out)


def render_table(rows, out=sys.stdout):
    print("\nHOOK RANKING\n" + "=" * 78, file=out)
    for i, r in enumerate(rows, 1):
        mark = "->" if i == 1 else "  "
        hook = r["hook"] if len(r["hook"]) <= 62 else r["hook"][:59] + "..."
        print(f"{mark} {r['score']:5.1f} {r['verdict']:<7} {hook}", file=out)
        print(f"        weakest: {r['weakest']} ({r['checks'][r['weakest']]['score']:.0f})", file=out)
        for f in r["flags"]:
            print(f"        dealbreaker: {f}", file=out)
    print("\nShoot the top one. If the top one is under 50, none of these are the hook.\n",
          file=out)


def main():
    ap = argparse.ArgumentParser(description="Score a Reel hook on five properties.")
    ap.add_argument("input", nargs="?", default="-", help="file with one hook per line, or -")
    ap.add_argument("--hook", help="score a single hook given on the command line")
    ap.add_argument("--lang", choices=["auto", "fr", "en"], default="auto",
                    help="langue du hook (défaut: auto-détection par ligne)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    lang = None if args.lang == "auto" else args.lang

    if args.hook:
        lines = [args.hook]
    else:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        print("nothing to score", file=sys.stderr)
        sys.exit(2)

    payload = []
    for line in lines:
        results, overall, verdict, flags = run(line, lang)
        payload.append({
            "hook": line,
            "lang": lang or detect_lang(line),
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "weakest": min(CHECKS, key=lambda c: results[c][0]),
            "flags": flags,
            "score": round(overall, 1),
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, ensure_ascii=False))
        return

    if len(payload) == 1:
        results, overall, verdict, flags = run(lines[0], lang)
        render_one(lines[0], results, overall, verdict, flags)
    else:
        render_table(sorted(payload, key=lambda r: -r["score"]))

    sys.exit(0 if max(p["score"] for p in payload) >= 70 else 1)


if __name__ == "__main__":
    main()
