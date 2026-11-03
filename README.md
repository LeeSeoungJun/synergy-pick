# Synergy Pick

League of Legends champion recommendation app with a read-only local champion-select connection.

## Run on Windows

1. Install Python 3.10 or newer.
2. Download or clone this repository.
3. Double-click `START_WINDOWS.cmd`.
4. Open http://127.0.0.1:8765 and enable the live connection while the League client is running.

Alternatively:

```powershell
py -3 serve.py --open-browser
```

For a custom League installation:

```powershell
py -3 serve.py --open-browser --lockfile "D:/Riot Games/League of Legends/lockfile"
```

## Features

- Recommendations based on allied and opposing champion selections.
- Patch, tier, and role filters.
- Read-only LCU bridge for confirmed picks and bans; no automated picks or bans.
- Bundled model, validation report, champion data, and frontend assets.

## Project files

- `serve.py`: loopback HTTP server.
- `lcu_bridge.py`: local League client connection.
- `dist/`: runnable frontend and model files.
- `certs/riotgames.pem`: Riot CA certificate for the local client.
- `DESKTOP_TEST.md`: detailed desktop testing guide.

Predictions are experimental estimates. See `dist/model_report.json` for validation results.

Champion names and images belong to Riot Games. This project is not endorsed by Riot Games. Never upload your League client lockfile or credentials.

## Data collection and training

The repository includes 16,000 unique matches: 10,000 in `data/teams.csv` and 6,000 additional matches in `data/patch_16_20_platinum_plus/teams.csv`. Each match has two team rows. The additional sample uses patch 16.20 and requires all ten participants to be Platinum+ at collection time, not necessarily at match time.

- `collector.py`: collect a seed account's solo ranked games through Riot API.
- `collect_bulk.py`: expand collection through match participants.
- `collect_stratified.py`: collect a patch-specific sample from multiple rank tiers.
- `train.py`: train patch-specific logistic regression models and export `dist/model.json`.

Install training dependencies and retrain from the included CSV files:

```powershell
python -m pip install -r requirements.txt
python train.py
```

To collect a separate new sample, provide your own Riot API key in an ignored local file:

```powershell
python collector.py --riot-id "divert#KR1" --count 20 --key-file secrets/riot.key --data-dir data/new_sample
```

Use a separate data directory: raw API responses and collection checkpoints from the original run are not included, so the included CSV files alone cannot resume that collection safely. Do not commit API keys, raw responses, rank caches, or client lockfiles.

The application and LCU connection files use the current synergy-pick version.
