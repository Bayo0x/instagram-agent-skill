#!/usr/bin/env python3
"""
caption.py - lint an Instagram caption and show exactly what the feed shows
before the "... more".

Instagram gives a caption about 125 characters in the feed and hides the rest
behind a tap. Almost every caption that fails, fails there: the hook is in
sentence three, or the first line is a greeting, or the whole thing opens on a
hashtag. This prints the visible window as a box so you can read it the way a
scrolling stranger does, then checks the eight things that are worth checking.

The 125-character cut is an approximation. The real number moves with the
device, the font size and where your line breaks fall, which is exactly why
you want a margin rather than a caption engineered to end at 125. Change it
with --truncate if you want to test a tighter one.

French: --lang fr (or auto). French asks ("commente SITE", "écris-moi en DM",
"enregistre", "lien en bio"), accented hashtags, € amounts, .fr/.be/.ch links.

Usage
  python3 caption.py caption.txt --lang fr
  python3 caption.py caption.txt --keywords "proposal software,client contract"
  pbpaste | python3 caption.py -
  python3 caption.py caption.txt --json
"""

import argparse
import json
import re
import sys
import textwrap

LIMIT = 2200             # Instagram's hard caption limit.
TRUNCATE = 125           # Roughly where the feed cuts to "... more".
HASHTAG_LIMIT = 5        # Instagram's cap per post or reel since 18 Dec 2025,
                         # down from 30. Announced by the @Creators account:
                         # "using fewer (up to 5) more targeted hashtags,
                         # rather than many generic ones, can improve both your
                         # content's performance and people's experience".

HASHTAG_RE = re.compile(r"(?:^|\s)(#[A-Za-z0-9_]+)")
MENTION_RE = re.compile(r"(?:^|\s)(@[A-Za-z0-9_.]+)")
LINK_RE = re.compile(r"https?://\S+|\bwww\.\S+|\b[a-z0-9-]+\.(?:com|co|io|net|org|ai|app)/\S*",
                     re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿←-⇿️]")
CONCRETE_RE = re.compile(r"\$\s?\d|\b\d[\d,.]*\b|(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)

ASKS = [
    (re.compile(r"(?i)\bcomment (?:the word |\")?[A-Z0-9]{2,}\b"), "comment a keyword"),
    (re.compile(r"(?i)\b(?:dm|message) me\b"), "DM me"),
    (re.compile(r"(?i)\bsave (?:this|it)\b"), "save this"),
    (re.compile(r"(?i)\bshare (?:this|it)\b"), "share this"),
    (re.compile(r"(?i)\bfollow (?:me|for)\b"), "follow"),
    (re.compile(r"(?i)\blink in (?:my )?bio\b"), "link in bio"),
    (re.compile(r"(?i)\b(?:swipe|tap) (?:through|left|right|for|to)\b"), "swipe or tap"),
    (re.compile(r"(?i)\btell me\b|\bwhat would you\b|\bwhich one\b"), "answer a question"),
]

# Français : appels à l'action, hashtags génériques, € et noms accentués.
FR_HASHTAG_RE = re.compile(r"(?:^|\s)(#[\w]+)")
FR_LINK_RE = re.compile(r"https?://\S+|\bwww\.\S+|\b[a-z0-9-]+\.(?:com|co|io|net|org|ai|app|fr|be|ch|lu|ca)\b/?\S*",
                        re.IGNORECASE)
FR_CONCRETE_RE = re.compile(r"(?:€|\$)\s?\d|\b\d[\d,.]*\b|(?<!^)\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]{2,}\b",
                            re.MULTILINE)
FR_ASKS = [
    (re.compile(r"(?i)\b(?:commente|commentez|écris|écrivez|tape|tapez)\b[^.!?\n]{0,25}?"
                r"[\"«“]?\s*\b[A-Z0-9ÀÉÈ]{2,}\b"), "commenter un mot-clé"),
    (re.compile(r"(?i)\b(?:envoie|envoyez)[- ]moi\b|\b(?:écris|écrivez)[- ]moi en (?:dm|mp|privé)\b"
                r"|\ben (?:dm|mp)\b"), "m'écrire en DM"),
    (re.compile(r"(?i)\b(?:enregistre|enregistrez|sauvegarde|sauvegardez)\b"), "enregistrer"),
    (re.compile(r"(?i)\b(?:partage|partagez)\b"), "partager"),
    (re.compile(r"(?i)\babonne[- ]toi\b|\babonnez[- ]vous\b|\bsuis[- ]moi\b|\bsuivez[- ]moi\b"),
     "s'abonner"),
    (re.compile(r"(?i)\blien (?:en|dans (?:ma|la)) bio\b"), "lien en bio"),
    (re.compile(r"(?i)\b(?:swipe|glisse|glissez|fais défiler)\b"), "swiper"),
    (re.compile(r"(?i)\b(?:dis|dites)[- ]moi\b|\b(?:tu|vous) en pense[sz] quoi\b|\blequel\b"
                r"|\blaquelle\b|\btu préfères\b|\bvous préférez\b"), "répondre à une question"),
    (re.compile(r"(?i)\b(?:réserve|réservez|prends|prenez) (?:ton|votre) (?:appel|rdv|rendez-vous|créneau)\b"),
     "réserver un appel"),
]
FR_FILLER_TAGS = {"#pourtoi", "#pourtoii", "#pourtoiii", "#explorer", "#tendance",
                  "#abonnetoi", "#instafrance", "#france", "#reelsfrance", "#viralfrance"}
_FR_MARKERS = {"le", "la", "les", "des", "est", "une", "et", "pour", "pas", "que",
               "qui", "dans", "sur", "avec", "je", "tu", "vous", "mon", "ton",
               "c'est", "j'ai", "ça", "mais", "plus", "ce", "cette", "au", "du"}
_EN_MARKERS = {"the", "and", "is", "you", "to", "of", "that", "it", "for", "with",
               "this", "my", "your", "i", "was", "are", "how", "what", "on", "in"}


def detect_lang(text):
    toks = re.findall(r"[\w'’]+", text.lower())
    fr = sum(1 for t in toks if t.replace("’", "'") in _FR_MARKERS)
    en = sum(1 for t in toks if t in _EN_MARKERS)
    fr += len(re.findall(r"[éèêàùçôîâ]", text.lower())) * 0.5
    return "fr" if fr > en else "en"


FILLER_TAGS = {"#viral", "#fyp", "#explore", "#explorepage", "#foryou", "#foryoupage",
               "#trending", "#instagood", "#love", "#follow", "#like4like", "#reels",
               "#reelsinstagram", "#viralreels", "#instadaily"}


def visible_window(text, cut):
    """What the feed shows. Instagram cuts mid-word, so this does too."""
    flat = text.strip()
    return flat if len(flat) <= cut else flat[:cut]


def render_box(window, truncated, out=sys.stdout, width=52):
    print("\n  WHAT THE FEED SHOWS", file=out)
    print("  +" + "-" * (width + 2) + "+", file=out)
    lines = []
    for raw in window.split("\n"):
        lines.extend(textwrap.wrap(raw, width) or [""])
    for line in lines[:8]:
        print(f"  | {line:<{width}} |", file=out)
    tail = "... more" if truncated else "(whole caption fits)"
    print("  +" + "-" * (width + 2 - len(tail) - 2) + f" {tail} " + "+", file=out)


def analyse(text, cut=TRUNCATE, keywords=None, lang=None):
    lang = lang if lang in ("en", "fr") else detect_lang(text)
    fr = lang == "fr"
    hashtag_re = FR_HASHTAG_RE if fr else HASHTAG_RE
    link_re = FR_LINK_RE if fr else LINK_RE
    concrete_re = FR_CONCRETE_RE if fr else CONCRETE_RE
    asks_list = FR_ASKS + ASKS if fr else ASKS
    filler_tags = FILLER_TAGS | FR_FILLER_TAGS if fr else FILLER_TAGS
    text = text.rstrip()
    stripped = text.strip()
    chars = len(stripped)
    lines = [l for l in stripped.split("\n")]
    first_line = lines[0].strip() if lines else ""
    tags = hashtag_re.findall(stripped)
    mentions = MENTION_RE.findall(stripped)
    links = link_re.findall(stripped)
    emoji = EMOJI_RE.findall(stripped)
    window = visible_window(stripped, cut)
    truncated = chars > cut
    asks = []
    for pattern, name in asks_list:
        if pattern.search(stripped) and name not in asks:
            asks.append(name)
    if fr:   # the English "DM me"/"follow" patterns can double-count a French ask
        asks = [a for a in asks if a not in ("DM me", "follow", "save this", "share this")
                or not any(x in asks for x in ("m'écrire en DM", "s'abonner", "enregistrer", "partager"))]
    filler = [t for t in tags if t.lower() in filler_tags]
    keywords = [k.strip() for k in (keywords or []) if k.strip()]

    checks = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    add("LENGTH", "FAIL" if chars > LIMIT else "PASS",
        f"{chars} / {LIMIT} characters" + (f", {chars - LIMIT} over the limit"
                                           if chars > LIMIT else ""))

    if not first_line:
        add("FIRST LINE", "FAIL", "the caption opens on a blank line")
    elif first_line.startswith("#") or first_line.startswith("@"):
        add("FIRST LINE", "FAIL",
            "opens on a hashtag or a mention, which is the one position worth a sentence")
    elif len(first_line) > cut:
        add("FIRST LINE", "WARN",
            f"{len(first_line)} characters, so it gets cut at {cut} mid-thought. "
            "Fine if the cut is a cliffhanger, bad if it is a subordinate clause")
    else:
        add("FIRST LINE", "PASS", f"{len(first_line)} characters, lands whole")

    add("HOOK IS CONCRETE", "PASS" if concrete_re.search(window) else "WARN",
        f"{len(concrete_re.findall(window))} number(s) or name(s) in the visible window"
        + ("" if concrete_re.search(window) else " - nothing checkable before the tap"))

    if len(tags) > HASHTAG_LIMIT:
        add("HASHTAGS", "FAIL", f"{len(tags)} tags, over Instagram's cap of {HASHTAG_LIMIT}. "
                                "Tags past the fifth do not count and the block reads as old")
    elif len(tags) == HASHTAG_LIMIT and filler:
        add("HASHTAGS", "WARN", f"{len(tags)} tags, at the cap, and "
                                f"{len(filler)} of them generic. Spend the five on topics")
    elif filler:
        add("HASHTAGS", "WARN", f"{len(tags)} tags, {len(filler)} of them generic "
                                f"({', '.join(filler[:3])}). Those describe nothing")
    else:
        add("HASHTAGS", "PASS", f"{len(tags)} tag(s)" + (f": {' '.join(tags)}" if tags else ""))

    if not tags:
        add("TAG PLACEMENT", "PASS", "no tags to place")
    elif any(re.search(r"(?:^|\s)" + re.escape(t) + r"\b", window) for t in tags):
        add("TAG PLACEMENT", "WARN", "a hashtag is inside the visible window, "
                                     "spending feed space on a label")
    else:
        add("TAG PLACEMENT", "PASS", "tags are below the fold")

    add("LINKS", "WARN" if links else "PASS",
        f"{len(links)} link(s) in the caption, and captions are not clickable. "
        f"Move it to the bio or the DM" if links else "no dead links in the body")

    if len(asks) == 1:
        add("ONE ASK", "PASS", f"one call to action: {asks[0]}")
    elif not asks:
        add("ONE ASK", "WARN", "no call to action. Decide what this post is for")
    else:
        add("ONE ASK", "WARN", f"{len(asks)} asks ({', '.join(asks)}). "
                               "Two asks is the same as none")

    density = len(emoji) * 100 / max(chars, 1)
    add("EMOJI", "WARN" if density > 4 else "PASS",
        f"{len(emoji)} emoji, {density:.1f} per 100 characters"
        + (" - reads as decoration" if density > 4 else ""))

    if keywords:
        low = stripped.lower()
        found = [k for k in keywords if k.lower() in low]
        missing = [k for k in keywords if k.lower() not in low]
        in_window = [k for k in found if k.lower() in window.lower()]
        status = "PASS" if not missing else ("WARN" if found else "FAIL")
        add("SEARCH TERMS", status,
            f"{len(found)}/{len(keywords)} present"
            + (f", {len(in_window)} in the visible window" if found else "")
            + (f". Missing: {', '.join(missing)}" if missing else ""))

    fails = sum(1 for c in checks if c["status"] == "FAIL")
    warns = sum(1 for c in checks if c["status"] == "WARN")
    verdict = "FIX" if fails else ("REVIEW" if warns else "READY")

    return {
        "lang": lang,
        "characters": chars, "limit": LIMIT, "truncate_at": cut,
        "visible": window, "truncated": truncated,
        "first_line_chars": len(first_line),
        "hashtags": tags, "mentions": mentions, "links": links,
        "emoji": len(emoji), "asks": asks,
        "checks": checks, "verdict": verdict,
    }


def render(a, out=sys.stdout):
    head = (f"CAPTION LINT  ·  {a['characters']} / {a['limit']} chars  ·  "
            f"{len(a['hashtags'])} hashtags  ·  {len(a['asks'])} ask(s)")
    print("\n" + head, file=out)
    print("=" * max(len(head), 62), file=out)
    render_box(a["visible"], a["truncated"], out=out)
    print("", file=out)
    for c in a["checks"]:
        print(f"  {c['status']:<5} {c['check']:<17} {c['detail']}", file=out)
    print("-" * max(len(head), 62), file=out)
    print(f"  VERDICT  {a['verdict']}\n", file=out)


def main():
    ap = argparse.ArgumentParser(description="Lint an Instagram caption.")
    ap.add_argument("input", nargs="?", default="-", help="caption file, or - for stdin")
    ap.add_argument("--truncate", type=int, default=TRUNCATE,
                    help=f"characters shown before '... more' (default {TRUNCATE})")
    ap.add_argument("--keywords", default="", help="comma-separated terms you want to be found for")
    ap.add_argument("--lang", choices=["auto", "fr", "en"], default="auto",
                    help="langue de la légende (défaut: auto)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    a = analyse(raw, cut=args.truncate, keywords=args.keywords.split(","),
                lang=None if args.lang == "auto" else args.lang)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0 if a["verdict"] == "READY" else 1)


if __name__ == "__main__":
    main()
