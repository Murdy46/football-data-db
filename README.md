# ⚽ Automated Football Database Repository

An automated, self-updating SQLite database repository providing clean, standardized historic and live season football match results and detailed statistics across major European leagues.

Data is continuously ingested and normalized from [football-data.co.uk](https://www.football-data.co.uk/) and compressed into `football_data.db.gz`.

---

## 🌟 Key Features

- **Automated Daily Ingestion**: Runs via GitHub Actions to fetch the latest scores and match statistics for current active seasons.
- **Match Stats Focus**: Captures goals, half-time results, shots, corners, fouls, cards, and referees. *(Betting odds are intentionally excluded for a clean, performance-focused database structure).*
- **Smart Status Detection**: Features a post-processing algorithm that dynamically calculates team promotion and relegation statuses (`HomeTeamStatus`, `AwayTeamStatus`) across multi-season timelines.
- **Standardized Schema**: Unifies varying legacy CSV header formats, normalizes date representations (`YYYY-MM-DD`), and maps team names across different leagues and years.
- **Compressed SQLite Storage**: Maintained as a gzipped SQLite archive (`football_data.db.gz`) for ultra-fast downloads and lightweight web app loading.

---

## 🏆 Covered Leagues (21 Divisions)

| Country | League Name | Division Code | Tier |
| :--- | :--- | :---: | :---: |
| 🏴󠁧󠁢󠁥󠁮󠁧󠁿 **England** | Premier League | `E0` | 1 |
| 🏴󠁧󠁢󠁥󠁮󠁧󠁿 **England** | Championship | `E1` | 2 |
| 🏴󠁧󠁢󠁥󠁮󠁧󠁿 **England** | League One | `E2` | 3 |
| 🏴󠁧󠁢󠁥󠁮󠁧󠁿 **England** | League Two | `E3` | 4 |
| 🏴󠁧󠁢󠁥󠁮󠁧󠁿 **England** | National League / Conference | `E4` / `EC` | 5 |
| 🏴󠁧󠁢󠁳󠁣󠁴󠁿 **Scotland** | Premiership | `SC0` | 1 |
| 🏴󠁧󠁢󠁳󠁣󠁴󠁿 **Scotland** | Championship | `SC1` | 2 |
| 🏴󠁧󠁢󠁳󠁣󠁴󠁿 **Scotland** | League One | `SC2` | 3 |
| 🏴󠁧󠁢󠁳󠁣󠁴󠁿 **Scotland** | League Two | `SC3` | 4 |
| 🇩🇪 **Germany** | Bundesliga 1 | `D1` | 1 |
| 🇩🇪 **Germany** | Bundesliga 2 | `D2` | 2 |
| 🇮🇹 **Italy** | Serie A | `I1` | 1 |
| 🇮🇹 **Italy** | Serie B | `I2` | 2 |
| 🇪🇸 **Spain** | La Liga Primera Division | `SP1` | 1 |
| 🇪🇸 **Spain** | La Liga Segunda Division | `SP2` | 2 |
| 🇫🇷 **France** | Ligue 1 | `F1` | 1 |
| 🇫🇷 **France** | Ligue 2 | `F2` | 2 |
| 🇳🇱 **Netherlands** | Eredivisie | `N1` | 1 |
| 🇧🇪 **Belgium** | Jupiler League | `B1` | 1 |
| 🇵🇹 **Portugal** | Liga I | `P1` | 1 |

---

## 📊 Database Schema (`fixtures` table)

Primary Key: `(Date, HomeTeam, AwayTeam)`

### Metadata Columns
- `Country` *(e.g. England, Spain, Scotland)*
- `LeagueName` *(e.g. Premier League, La Liga Primera Division)*
- `Tier` *(e.g. 1, 2, 3)*
- `DivisionCode` *(e.g. E0, SP1, SC1)*
- `Season` *(e.g. 2526, 2627)*
- `Date` *(Standardized ISO date `YYYY-MM-DD`)*
- `Time` *(Kickoff time format `HH:MM` where available)*
- `HomeTeam` / `AwayTeam` *(Standardized team names)*
- `FTR` *(Full-Time Result: `H` = Home, `D` = Draw, `A` = Away)*
- `HTR` *(Half-Time Result: `H`, `D`, `A`)*
- `Referee` *(Match official)*
- `HomeTeamStatus` / `AwayTeamStatus` *(`Stable`, `Promoted`, or `Relegated`)*

### Match Statistics Columns
- **Goals**: `FTHG` (Full-time home goals), `FTAG` (Full-time away goals), `HTHG` (Half-time home goals), `HTAG` (Half-time away goals)
- **Shots**: `HS` (Home shots), `AS` (Away shots), `HST` (Home shots on target), `AST` (Away shots on target), `HHW` (Home hit woodwork), `AHW` (Away hit woodwork)
- **Set Pieces & Discipline**: `HC` (Home corners), `AC` (Away corners), `HF` (Home fouls), `AF` (Away fouls), `HY` (Home yellow cards), `AY` (Away yellow cards), `HR` (Home red cards), `AR` (Away red cards), `HBP` / `ABP` (Booking points)
- **Other Stats**: `Attendance`, `HO` / `AO` (Offsides), `HFKC` / `AFKC` (Fouls conceded)

---

## 🛠 Local Setup & Usage

### Prerequisites
Make sure you have Python 3 installed along with the required libraries:
```bash
pip install pandas requests

Running the Database Updater
To update or test the pipeline locally on your machine:
code
Bash
python db_updater.py --db football_data.db.gz
Optional Flags:
Force override a target season (e.g., 2025/2026 season):
code
Bash
python db_updater.py --db football_data.db.gz --season 2526
🤖 GitHub Actions Workflow
This repository automatically syncs match results using a GitHub Action workflow defined in .github/workflows/update-db.yml.
Sets up Python and dependencies.
Decompresses football_data.db.gz.
Downloads the latest league CSV files for the active season.
Performs an INSERT OR REPLACE upsert on new and updated fixtures.
Recalculates team promotion and relegation statuses across history.
Re-compresses and commits the updated football_data.db.gz file back to the repository.
📄 License & Data Sources
Match results and statistics source: football-data.co.uk
For personal, educational, and analytical use.
