"""
Automatic Football Data SQLite Database Ingestion & Update Script
Downloads multi-season CSV files from football-data.co.uk and updates football_data.db
"""

import os
import sys
import sqlite3
import csv
import time
import gzip
import subprocess
import shutil
import tempfile
import zipfile
from datetime import datetime
import urllib.request
import urllib.error
import re


DB_FILE = "football_data.db"
BACKUP_FILE = f"football_data_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
MAX_RETRIES = 3
RETRY_DELAY = 3
TIMEOUT = 20

# Season mapping (code -> URL segment)
SEASONS = {
    "0001": "0001",
    "0102": "0102",
    "0203": "0203",
    "0304": "0304",
    "0405": "0405",
    "0506": "0506",
    "0607": "0607",
    "0708": "0708",
    "0809": "0809",
    "0910": "0910",
    "1011": "1011",
    "1112": "1112",
    "1213": "1213",
    "1314": "1314",
    "1415": "1415",
    "1516": "1516",
    "1617": "1617",
    "1718": "1718",
    "1819": "1819",
    "1920": "1920",
    "2021": "2021",
    "2122": "2122",
    "2223": "2223",
    "2324": "2324",
    "2425": "2425",
    "2526": "2526",
    "2627": "2627",
}

# Division mapping (code -> Full League Name, Country, Tier)
DIVISIONS = {
    "E0": ("Premier League", "England", "1"),
    "E1": ("Championship", "England", "2"),
    "E2": ("League One", "England", "3"),
    "E3": ("League Two", "England", "4"),
    "EC": ("National League", "England", "5"),
    "SC0": ("Scottish Premiership", "Scotland", "1"),
    "SC1": ("Scottish Championship", "Scotland", "2"),
    "SC2": ("Scottish League One", "Scotland", "3"),
    "SC3": ("Scottish League Two", "Scotland", "4"),
    "D1": ("Bundesliga", "Germany", "1"),
    "D2": ("2. Bundesliga", "Germany", "2"),
    "I1": ("Serie A", "Italy", "1"),
    "I2": ("Serie B", "Italy", "2"),
    "SP1": ("La Liga", "Spain", "1"),
    "SP2": ("La Liga 2", "Spain", "2"),
    "F1": ("Ligue 1", "France", "1"),
    "F2": ("Ligue 2", "France", "2"),
    "N1": ("Eredivisie", "Netherlands", "1"),
    "P1": ("Primeira Liga", "Portugal", "1"),
    "B1": ("Belgian Pro League", "Belgium", "1"),
}


def fetch_csv(url):
    """Fetch CSV content from URL with retry logic."""
    for attempt in range(MAX_RETRIES):
        # Try curl first (bypasses Cloudflare / Apache TLS fingerprint bot filters on cloud runners)
        try:
            cmd = [
                'curl', '-s', '-L',
                '--max-time', str(TIMEOUT),
                '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
                '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                '-H', 'Accept-Language: en-US,en;q=0.9',
                '-H', 'Referer: https://www.football-data.co.uk/',
                url
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and res.stdout and len(res.stdout) > 50:
                if not res.stdout.lower().startswith('<!doctype') and '503 service' not in res.stdout.lower():
                    return res.stdout
        except Exception:
            pass

        # Fallback to urllib if curl is unavailable
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'Referer': 'https://www.football-data.co.uk/'
            }
            req = urllib.request.Request(
                url,
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return response.read().decode('utf-8', errors='replace')
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"    [Failed - {e}]")
                return None


def parse_csv_content(csv_text):
    """Parse CSV text handling header anomalies."""
    lines = [line for line in csv_text.splitlines() if line.strip()]
    if not lines:
        return []

    reader = csv.reader(lines)
    rows = list(reader)
    return rows


def parse_int(val):
    """Safe integer parser."""
    if val is None or val == "":
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def parse_float(val):
    """Safe float parser."""
    if val is None or val == "":
        return None
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None


def parse_date(date_str):
    """Standardize date strings to YYYY-MM-DD."""
    if not date_str:
        return None
    date_str = str(date_str).strip()

    formats = [
        "%d/%m/%Y", "%d/%m/%y",
        "%Y-%m-%d", "%d-%m-%Y", "%d-%m-%y",
        "%Y/%m/%d"
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # Handle 2-digit year edge cases
            if dt.year < 100:
                if dt.year > 50:
                    dt = dt.replace(year=1900 + dt.year)
                else:
                    dt = dt.replace(year=2000 + dt.year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str


def init_db(conn):
    """Initialize SQLite database schema."""
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fixtures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        DivisionCode TEXT NOT NULL,
        LeagueName TEXT NOT NULL,
        Country TEXT NOT NULL,
        Tier TEXT,
        Season TEXT NOT NULL,
        Date TEXT NOT NULL,
        Time TEXT,
        HomeTeam TEXT NOT NULL,
        AwayTeam TEXT NOT NULL,
        FTHG INTEGER,
        FTAG INTEGER,
        FTR TEXT,
        HTHG INTEGER,
        HTAG INTEGER,
        HTR TEXT,
        Referee TEXT,
        Attendance INTEGER,
        HS INTEGER,
        [AS] INTEGER,
        HST INTEGER,
        AST INTEGER,
        HHW INTEGER,
        AHW INTEGER,
        HC INTEGER,
        AC INTEGER,
        HF INTEGER,
        AF INTEGER,
        HFKC INTEGER,
        AFKC INTEGER,
        HO INTEGER,
        AO INTEGER,
        HY INTEGER,
        AY INTEGER,
        HR INTEGER,
        AR INTEGER,
        HBP INTEGER,
        ABP INTEGER,
        HomeTeamStatus TEXT,
        AwayTeamStatus TEXT,
        UNIQUE(DivisionCode, Season, Date, HomeTeam, AwayTeam) ON CONFLICT REPLACE
    )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fixtures_teams ON fixtures(HomeTeam, AwayTeam)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fixtures_season ON fixtures(Season)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fixtures_div_season ON fixtures(DivisionCode, Season)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fixtures_date ON fixtures(Date)")

    # Ensure [AS] column exists if upgrading from an older database schema
    cursor.execute("PRAGMA table_info(fixtures)")
    cols = [r[1] for r in cursor.fetchall()]
    if "AS" not in cols:
        cursor.execute("ALTER TABLE fixtures ADD COLUMN [AS] INTEGER")

    conn.commit()


def process_csv_rows(cursor, rows, div_code, season_code):
    """Process CSV rows and upsert into SQLite database."""
    if not rows or len(rows) < 2:
        return 0, 0

    header = [col.strip().upper() for col in rows[0]]

    # Map column names to indices
    col_map = {}
    for idx, col_name in enumerate(header):
        col_map[col_name] = idx

    # Required columns
    if "HOMETEAM" not in col_map and "HOME" not in col_map:
        return 0, 0

    home_col = col_map.get("HOMETEAM", col_map.get("HOME"))
    away_col = col_map.get("AWAYTEAM", col_map.get("AWAY"))
    date_col = col_map.get("DATE")

    if home_col is None or away_col is None or date_col is None:
        return 0, 0

    league_name, country, tier = DIVISIONS.get(div_code, (div_code, "Unknown", "1"))

    inserted = 0
    updated = 0

    for row in rows[1:]:
        if not row or len(row) <= max(home_col, away_col, date_col):
            continue

        home_team = row[home_col].strip() if home_col < len(row) else ""
        away_team = row[away_col].strip() if away_col < len(row) else ""
        raw_date = row[date_col].strip() if date_col < len(row) else ""

        if not home_team or not away_team or not raw_date:
            continue

        match_date = parse_date(raw_date)
        if not match_date:
            continue

        def get_val(col_names, parser_func=parse_int):
            for name in col_names:
                idx = col_map.get(name)
                if idx is not None and idx < len(row):
                    val = parser_func(row[idx])
                    if val is not None:
                        return val
            return None

        def get_str(col_names):
            for name in col_names:
                idx = col_map.get(name)
                if idx is not None and idx < len(row):
                    val = row[idx].strip()
                    if val:
                        return val
            return None

        time_val = get_str(["TIME"])
        fthg = get_val(["FTHG", "HG"])
        ftag = get_val(["FTAG", "AG"])
        ftr = get_str(["FTR", "Res", "RES"])
        hthg = get_val(["HTHG"])
        htag = get_val(["HTAG"])
        htr = get_str(["HTR"])
        referee = get_str(["REFEREE"])
        attendance = get_val(["ATTENDANCE"])

        hs = get_val(["HS"])
        as_stats = get_val(["AS"])
        hst = get_val(["HST"])
        ast = get_val(["AST"])
        hhw = get_val(["HHW"])
        ahw = get_val(["AHW"])
        hc = get_val(["HC"])
        ac = get_val(["AC"])
        hf = get_val(["HF"])
        af = get_val(["AF"])
        hfkc = get_val(["HFKC"])
        afkc = get_val(["AFKC"])
        ho = get_val(["HO"])
        ao = get_val(["AO"])
        hy = get_val(["HY"])
        ay = get_val(["AY"])
        hr = get_val(["HR"])
        ar = get_val(["AR"])
        hbp = get_val(["HBP"])
        abp = get_val(["ABP"])

        cursor.execute("""
            INSERT INTO fixtures (
                DivisionCode, LeagueName, Country, Tier, Season, Date, Time,
                HomeTeam, AwayTeam, FTHG, FTAG, FTR, HTHG, HTAG, HTR,
                Referee, Attendance, HS, [AS], HST, AST, HHW, AHW, HC, AC,
                HF, AF, HFKC, AFKC, HO, AO, HY, AY, HR, AR, HBP, ABP
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(DivisionCode, Season, Date, HomeTeam, AwayTeam) DO UPDATE SET
                FTHG=excluded.FTHG,
                FTAG=excluded.FTAG,
                FTR=excluded.FTR,
                HTHG=excluded.HTHG,
                HTAG=excluded.HTAG,
                HTR=excluded.HTR,
                Referee=excluded.Referee,
                Attendance=excluded.Attendance,
                HS=excluded.HS,
                [AS]=excluded.[AS],
                HST=excluded.HST,
                AST=excluded.AST,
                HC=excluded.HC,
                AC=excluded.AC,
                HF=excluded.HF,
                AF=excluded.AF,
                HY=excluded.HY,
                AY=excluded.AY,
                HR=excluded.HR,
                AR=excluded.AR
        """, (
            div_code, league_name, country, tier, season_code, match_date, time_val,
            home_team, away_team, fthg, ftag, ftr, hthg, htag, htr,
            referee, attendance, hs, as_stats, hst, ast, hhw, ahw, hc, ac,
            hf, af, hfkc, afkc, ho, ao, hy, ay, hr, ar, hbp, abp
        ))

        if cursor.rowcount == 1:
            inserted += 1
        else:
            updated += 1

    return inserted, updated


def compress_db():
    """Gzip compress football_data.db to football_data.db.gz for GitHub size optimization."""
    if os.path.exists(DB_FILE):
        gz_file = f"{DB_FILE}.gz"
        print(f"Compressing {DB_FILE} -> {gz_file}...")
        with open(DB_FILE, 'rb') as f_in:
            with gzip.open(gz_file, 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
        print(f"Compressed size: {os.path.getsize(gz_file) / (1024*1024):.2f} MB")


def decompress_db_if_needed():
    """Decompress existing football_data.db.gz if uncompressed football_data.db does not exist."""
    gz_file = f"{DB_FILE}.gz"
    if not os.path.exists(DB_FILE) and os.path.exists(gz_file):
        print(f"Decompressing {gz_file} -> {DB_FILE}...")
        with gzip.open(gz_file, 'rb') as f_in:
            with open(DB_FILE, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        print(f"Decompressed database size: {os.path.getsize(DB_FILE) / (1024*1024):.2f} MB")


def main():
    """Main updater function."""
    print("=== Football Data Database Ingestion & Updater ===")
    print(f"Execution started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    decompress_db_if_needed()

    conn = sqlite3.connect(DB_FILE)
    init_db(conn)

    total_inserted = 0
    total_updated = 0

    # Daily updater targets active current season ("2627") to be fast, reliable, and avoid 503 errors on legacy paths
    # Pass "--all-seasons" if full historical rebuild is explicitly requested
    target_seasons = SEASONS if "--all-seasons" in sys.argv else {"2627": "2627"}
    print(f"Targeting active seasons: {list(target_seasons.keys())}")

    for season_code, season_segment in target_seasons.items():
        cursor = conn.cursor()
        print(f"\n--- Fetching Season {season_code} ({season_segment}) ---")
        season_inserted = 0
        season_updated = 0

        for div_code in DIVISIONS:
            url = f"https://www.football-data.co.uk/mmz4281/{season_segment}/{div_code}.csv"
            print(f"  -> Fetching {div_code} ({url})...", end="", flush=True)

            # Polite delay between requests to prevent 503 rate-limiting bans
            time.sleep(1.2)
            csv_text = fetch_csv(url)
            if not csv_text:
                continue

            rows = parse_csv_content(csv_text)
            if not rows:
                print("    [Empty or Invalid CSV]")
                continue

            inserted, updated = process_csv_rows(cursor, rows, div_code, season_code)
            season_inserted += inserted
            season_updated += updated
            print(f"    [{inserted} inserted, {updated} updated]")

        conn.commit()
        total_inserted += season_inserted
        total_updated += season_updated
        print(f"Season {season_code} Complete: {season_inserted} new, {season_updated} updated.")

    conn.close()

    print("\n=== Database Ingestion Summary ===")
    print(f"Total inserted: {total_inserted}")
    print(f"Total updated: {total_updated}")

    compress_db()
    print("Update complete!")


if __name__ == "__main__":
    main()
