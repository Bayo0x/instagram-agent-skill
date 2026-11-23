#!/usr/bin/env bash
# Tests du fork FR.
# 1. Les sorties anglaises doivent rester identiques à l'original (baseline).
# 2. Chaque exemple de hooks.fr.json doit être classé dans sa propre formule.
# 3. Les scripts tournent en français sans erreur.
set -u
cd "$(dirname "$0")/fixtures"
S=../../skills
fail=0
en() {
  python3 -I $S/ig-reel/hookscore.py en_hooks.txt
  python3 -I $S/ig-reel/hookscore.py --hook "I lost \$18,000 because of one missing contract." --json
  python3 -I $S/ig-reel/beats.py en_script.txt --target 30 --json
  python3 -I $S/ig-caption/caption.py en_caption.txt --keywords "client contracts,freelance" --json
  python3 -I $S/ig-human/humanize.py en_slop.txt --json
  python3 -I $S/ig-human/detect.py en_slop.txt --json
  python3 -I $S/ig-viral/swipe.py en_swipe.tsv --json
}
if diff -q <(en 2>&1 | grep -v '"lang"') en_baseline.txt >/dev/null; then
  echo "PASS  anglais identique à l'original"
else
  echo "FAIL  les sorties anglaises ont changé"; fail=1
fi
python3 -I - "$S/ig-reel/hooks.fr.json" <<'PY' || fail=1
import json, re, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
by = {h["id"]: h for h in d["hooks"]}
order = [(i, re.compile(by[i]["match"], re.I)) for i in d["classify_order"]]
bad = []
for h in d["hooks"]:
    ex = h["example"].replace("{{N}}", "53").replace("{{", "").replace("}}", "")
    got = next((i for i, p in order if p.search(ex)), None)
    if got != h["id"]:
        bad.append((h["id"], got))
print("PASS  hooks.fr.json : 26 exemples bien classés" if not bad else f"FAIL  hooks.fr.json {bad}")
sys.exit(1 if bad else 0)
PY
for cmd in "ig-reel/hookscore.py fr_hooks.txt --lang fr" "ig-reel/beats.py fr_script.txt --lang fr" \
           "ig-caption/caption.py fr_caption.txt --lang fr" "ig-human/humanize.py fr_slop.txt --lang fr" \
           "ig-human/detect.py fr_slop.txt --lang fr" "ig-viral/swipe.py fr_swipe.tsv"; do
  python3 -I $S/$cmd >/dev/null 2>/tmp/igerr; rc=$?
  if [ $rc -le 1 ] && ! grep -q Traceback /tmp/igerr; then echo "PASS  $cmd"; else echo "FAIL  $cmd"; cat /tmp/igerr; fail=1; fi
done
exit $fail
