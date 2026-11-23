@echo off
REM Collecte ~48 hooks FR (6 chaines x 4 top + 4 bottom) depuis des Shorts publics.
REM Besoin de Python 3.10+ installe. Lance ce fichier en double-cliquant dessus.
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
%PY% -m pip install -q --upgrade yt-dlp
%PY% collect_fr_hooks.py ^
  --search "trouver des clients freelance" ^
  --search "site internet entrepreneur" ^
  --search "instagram business conseil" ^
  --search "auto entrepreneur conseil" ^
  --search "prospection clients independant" ^
  --search "marketing petite entreprise" ^
  --max-channels 6 --per-band 4 --out corpus_fr.tsv
echo.
echo Termine. Le fichier corpus_fr.tsv est pret, dis-le a Claude.
pause
