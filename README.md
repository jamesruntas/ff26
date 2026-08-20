# ADP Master: 2026, PPR, 12-team

Blends FFC, MFL, and ESPN ADP feeds into one master board, plus a live draft-day tracker.

## Quickstart

```
pip install -r requirements.txt
python main.py                          # builds the ADP board
python -m streamlit run draft_gui.py    # live draft tracker, localhost:8501
```

Reference data (offense/bye-week rankings) is already filled in for 2026. Re-run `python main.py` any time for fresher ADP; board writes to `output/adp_master_2026_ppr_12tm.csv`.

## Sources

FFC (mock drafts), MFL (real home-league drafts), ESPN (platform drafts); none aggregate each other, so blending isn't double counting. Add your own: drop a CSV with a `player` column and an ADP-like column (`adp`/`consensus`/`average`/`avg`) into `reference/custom_sources/`, or upload one from the tracker's sidebar. `python main.py --templates` writes blank reference files for a fresh season.

## Columns

`adp_rank` `adp_master` `player` `pos` `team` `is_rookie` `off_flag` `bye_week` `adp_<source>` `sources_n` `adp_spread` `mfl_id`. `adp_master` is the median raw ADP ("where he goes"); `adp_rank` is the median of within-source ranks (scale-safe ordering across feeds of different depth); `adp_spread` is max minus min across sources (platform disagreement signal).

## The hand-maintained files

`reference/offense.csv` and `reference/byeweeks.csv`, 32 teams each, validated hard on load. No free API for either.

## Live draft tracker

`python -m streamlit run draft_gui.py`. Manual pick entry (search, or the quick-draft box), no network calls. Derives whose turn it is from your draft slot (sidebar, live-editable).

Per-row badges: tier + live depletion, O-line context (RB/QB only, gold `TOP5 OL` / red `BOT6 OL`, see `config.OLINE_TOP5`/`OLINE_BOTTOM`), `ROOKIE`, offense `TOP5`/`BOT5`, bye week (red on collision with a starter), `value_delta` (+ fractional rounds), survival probability (conditioned on already being available now, not the raw unconditional tail), `NEED` (fills an open roster slot), `ACT NOW`/`VALUE SAFE` (value + survival combined). "Biggest Fallers" ranks by scarcity-weighted value.

Mock-draft CPU opponents pick with weighted randomness, not pure rank order; one-click auto-finish once your roster's full. Start Over resets the pick log (keeps your slot).

## Known failure modes

FFC/custom sources match by name; an ambiguous crosswalk collision (two players sharing a suffix-stripped name) is refused rather than guessed, add an override to `ids.MANUAL_MFL_IDS`. MFL's filtered pool can be empty in early preseason (try `PERIOD=ALL` or a lower `CUTOFF`). ESPN ADP-vs-editorial-rank correlation above ~0.98 suggests autodraft contamination.

## Attribution

ADP data courtesy of Fantasy Football Calculator, MyFantasyLeague, and ESPN. Player ID crosswalk from DynastyProcess.
