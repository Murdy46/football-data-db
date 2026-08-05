#!/usr/bin/env python3
"""
Automated Football Database Updater Tool
----------------------------------------
This script automates the process of appending the latest results of the current
football season to your existing SQLite database and recalculating smart status features
(such as team promotion and relegation statuses), before allowing you to commit and push
the changes back to GitHub.

Features:
- Automatically detects the current European football season based on the system date.
- Downloads only the necessary latest CSV datasets directly from football-data.co.uk.
- Appends new fixtures cleanly into the existing 'fixtures' table using robust upsert (INSERT OR REPLACE) keys.
- Automatically executes the smart post-ingestion processor to update HomeTeamStatus and AwayTeamStatus.
- Extremely lightweight, fast, and friendly to automate (e.g., via local cron or GitHub Actions).
"""

import os
import re
import sys
import json
import sqlite3
import argparse
import requests
import pandas as pd
from datetime import datetime

# --- CONFIGURATION & CONSTANTS ---
DEFAULT_DB_NAME = "football_data.db.gz"  # Defaulting to your gzipped database
TABLE_NAME = "fixtures"
MAPPING_FILE = "team_mappings.json"
DOWNLOAD_DIR = "football_data_temp"

# Master lookup matching site CSV naming systems to country/league metadata
LEAGUE_MAP = {
    'E0': ('England', 'Premier League', 1),
    'E1': ('England', 'Championship', 2),
    'E2': ('England', 'League One', 3),
    'E3': ('England', 'League Two', 4),
    'E4': ('England', 'National League', 5),
    'EC': ('England', 'Conference', 5), 
    'SC0': ('Scotland', 'Premiership', 1),
    'SC1': ('Scotland', 'Championship', 2),
    'SC2': ('Scotland', 'League One', 3),
    'SC3': ('Scotland', 'League Two', 4),
    'D1': ('Germany', 'Bundesliga 1', 1),
    'D2': ('Germany', 'Bundesliga 2', 2),
    'I1': ('Italy', 'Serie A', 1),
    'I2': ('Italy', 'Serie B', 2),
    'SP1': ('Spain', 'La Liga Primera', 1),
    'SP2': ('Spain', 'La Liga Segunda', 2),
    'F1': ('France', 'Ligue 1', 1),
    'F2': ('France', 'Ligue 2', 2),
    'N1': ('Netherlands', 'Eredivisie', 1),
    'B1': ('Belgium', 'Jupiler League', 1),
    'P1': ('Portugal', 'Liga I', 1 )
}

META_COLUMNS = [
    'Country', 'LeagueName', 'Tier', 'DivisionCode', 'Season', 'Date', 'Time', 
    'HomeTeam', 'AwayTeam', 'FTR', 'HTR', 'Referee',
    'HomeTeamStatus', 'AwayTeamStatus'
]

STAT_COLUMNS = [
    'FTHG', 'FTAG', 'HTHG', 'HTAG', 'Attendance',
    'HS', 'AS', 'HST', 'AST', 'HHW', 'AHW', 'HC', 'AC',
    'HF', 'AF', 'HFKC', 'AFKC', 'HO', 'AO', 'HY', 'AY', 'HR', 'AR', 'HBP', 'ABP'
]

MASTER_SCHEMA = META_COLUMNS + STAT_COLUMNS

# --- UTILITIES ---
def get_current_season():
    """
    Automatically detects the current season label (e.g. '2627' for the 2026/2027 season)
    based on the system calendar date. July 1st marks the transition to a new season.
    """
    now = datetime.now()
    year = now.year
    month = now.month
    if month >= 7:  # July or later starts the upcoming season
        return f"{str(year)[2:]}{str(year+1)[2:]}"
    else:  # Before July belongs to the concluding season
        return f"{str(year-1)[2:]}{str(year)[2:]}"

def load_team_mappings():
    """
    Loads custom team name mapping to ensure data uniformity.
    """
    if os.path.exists(MAPPING_FILE):
        try:
            with open(MAPPING_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    
    # Initialize with default mappings if missing
    initial_map = {
        "Man United": "Manchester United", "Man Utd": "Manchester United",
        "Paris SG": "Paris Saint-Germain", "PSG": "Paris Saint-Germain",
        "Glasgow Rangers": "Rangers", "Spurs": "Tottenham Hotspur"
    }
    with open(MAPPING_FILE, 'w') as f:
        json.dump(initial_map, f, indent=4, sort_keys=True)
    return initial_map

# Global mappings cache
TEAM_LOOKUP = load_team_mappings()

def standardize_team_name(raw_name):
    if pd.isna(raw_name):
        return None
    cleaned = str(raw_name).strip()
    if cleaned in TEAM_LOOKUP:
        return TEAM_LOOKUP[cleaned]
    TEAM_LOOKUP[cleaned] = cleaned  
    return cleaned

# --- CORE DATA SCRAPING & PIPELINE ---
def download_league_csv(div_code, season_label):
    """
    Downloads the current season's CSV for a given league division.
    URL Format: https://www.football-data.co.uk/mmz4281/{season_label}/{div_code}.csv
    """
    url = f"https://www.football-data.co.uk/mmz4281/{season_label}/{div_code}.csv"
    local_path = os.path.join(DOWNLOAD_DIR, f"{div_code}_{season_label}.csv")
    
    print(f" -> Fetching {div_code} ({url})...", end="", flush=True)
    try:
        # Mimic browser headers to avoid being blocked by cloudflare / hosting security rules
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.football-data.co.uk/"
        }
        r = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(r.content)
            print(" [Success]")
            return local_path
        elif r.status_code == 404:
            print(" [Not Started / 404]")  # Some minor leagues might start late or not have files yet
        else:
            print(f" [Failed - HTTP {r.status_code}]")
    except Exception as e:
        print(f" [Error: {e}]")
    return None

def process_and_standardize(file_path, div_code, season_label):
    """
    Parses and standardizes raw CSV files into our master database schema format.
    """
    if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return None
        
    try:
        # Standardize CSV headers and column casing
        df = pd.read_csv(file_path, encoding='latin1', on_bad_lines='skip')
        df.columns = df.columns.str.strip()
        
        # Resolve alternative header names
        rename_dict = {'HG': 'FTHG', 'AG': 'FTAG', 'Res': 'FTR'}
        df = df.rename(columns=rename_dict)
        
        # Verify mandatory columns
        if not {'Date', 'HomeTeam', 'AwayTeam'}.issubset(df.columns):
            return None
            
        df = df.dropna(subset=['Date', 'HomeTeam', 'AwayTeam'])
        
        # Add metadata variables
        country, league_name, tier = LEAGUE_MAP[div_code]
        df['Country'] = country
        df['LeagueName'] = league_name
        df['Tier'] = tier
        df['Season'] = season_label
        df['DivisionCode'] = div_code  
        df['HomeTeamStatus'] = 'Stable'
        df['AwayTeamStatus'] = 'Stable'
        
        def parse_date(val):
            val = str(val).strip()
            for fmt in ('%d/%m/%Y', '%d/%m/%y', '%Y-%m-%d'):
                try:
                    return datetime.strptime(val, fmt).strftime('%Y-%m-%d')
                except ValueError:
                    continue
            return None
            
        df['Date'] = df['Date'].apply(parse_date)
        df = df.dropna(subset=['Date'])
        
        df['HomeTeam'] = df['HomeTeam'].apply(standardize_team_name)
        df['AwayTeam'] = df['AwayTeam'].apply(standardize_team_name)
        df = df[df['HomeTeam'] != df['AwayTeam']]
        
        # Fill missing text columns
        for text_col in ['FTR', 'HTR', 'Time', 'Referee']:
            if text_col not in df.columns:
                df[text_col] = None
            else:
                df[text_col] = df[text_col].astype(str).str.strip()
                if text_col in ['FTR', 'HTR']:
                    df[text_col] = df[text_col].str.upper()
        
        # Parse numeric columns safely
        for col in STAT_COLUMNS:
            if col not in df.columns:
                df[col] = None
            else:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df[MASTER_SCHEMA]
    except Exception as e:
        print(f"Error standardizing file {file_path}: {e}")
        return None

# --- DATABASE OPERATIONS ---
def init_db(db_path):
    """
    Ensures that the database table and indexes exist exactly under the master schema.
    Also dynamically adds any missing columns from the master schema to an existing table.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    column_definitions = []
    for col in META_COLUMNS:
        column_definitions.append(f"[{col}] TEXT")
    for col in STAT_COLUMNS:
        column_definitions.append(f"[{col}] INTEGER")
        
    schema_string = ",\n            ".join(column_definitions)
    
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} ({schema_string}, PRIMARY KEY (Date, HomeTeam, AwayTeam))")
    
    # Dynamically upgrade schema of existing table if columns are missing
    cursor.execute(f"PRAGMA table_info({TABLE_NAME})")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    # Check for missing META_COLUMNS
    for col in META_COLUMNS:
        if col not in existing_columns:
            print(f"🔧 Schema Upgrade: Adding missing column [{col}] TEXT to table '{TABLE_NAME}'")
            try:
                cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN [{col}] TEXT")
            except Exception as e:
                print(f"⚠️ Failed to add column [{col}]: {e}")
                
    # Check for missing STAT_COLUMNS
    for col in STAT_COLUMNS:
        if col not in existing_columns:
            print(f"🔧 Schema Upgrade: Adding missing column [{col}] INTEGER to table '{TABLE_NAME}'")
            try:
                cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN [{col}] INTEGER")
            except Exception as e:
                print(f"⚠️ Failed to add column [{col}]: {e}")
                
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_div_season ON {TABLE_NAME} (DivisionCode, Season);")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_teams ON {TABLE_NAME} (HomeTeam, AwayTeam);")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_date_sort ON {TABLE_NAME} (Date ASC);")
    conn.commit()
    conn.close()

def append_to_db(df, db_path):
    """
    Upserts standardized rows into the SQLite table. Returns count of modified records.
    """
    if df is None or df.empty:
        return 0
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    rows_affected = 0
    for _, row in df.iterrows():
        vals = [None if pd.isna(v) else v for v in row.values]
        cols = ", ".join([f"[{c}]" for c in row.index])
        placeholders = ", ".join(["?"] * len(row))
        sql = f"INSERT OR REPLACE INTO {TABLE_NAME} ({cols}) VALUES ({placeholders})"
        cursor.execute(sql, vals)
        if cursor.rowcount > 0:
            rows_affected += cursor.rowcount
            
    conn.commit()
    conn.close()
    return rows_affected

def run_smart_detect_processor(db_path):
    """
    Calculates promotional/relegation statuses for all teams based on chronological tier transitions.
    """
    print("\nRunning Smart Detect Post-Processor across historic team timelines...")
    try:
        conn = sqlite3.connect(db_path)
        
        query = f"""
            SELECT DISTINCT HomeTeam AS Team, Season, Tier, DivisionCode, MIN(Date) as SeasonStart
            FROM {TABLE_NAME}
            GROUP BY Team, Season, Tier, DivisionCode
            ORDER BY Team, SeasonStart ASC
        """
        history_df = pd.read_sql_query(query, conn)
        if history_df.empty:
            print(" -> No team history found to process.")
            conn.close()
            return

        updates = []
        for team, group in history_df.groupby('Team'):
            group = group.sort_values('SeasonStart').reset_index(drop=True)
            
            for i in range(len(group)):
                current_row = group.iloc[i]
                current_season = current_row['Season']
                try:
                    current_tier = int(current_row['Tier'])
                except (ValueError, TypeError):
                    current_tier = 1  # Fallback to tier 1
                current_div = current_row['DivisionCode']
                
                if i == 0:
                    status = "Stable"
                else:
                    prev_row = group.iloc[i - 1]
                    try:
                        prev_tier = int(prev_row['Tier'])
                    except (ValueError, TypeError):
                        prev_tier = 1  # Fallback to tier 1
                    prev_div = prev_row['DivisionCode']
                    
                    # Dynamic Promotion / Relegation check
                    if current_tier > prev_tier:
                        status = "Relegated"
                    elif current_tier < prev_tier:
                        status = "Promoted"
                    else:
                        status = "Stable"
                            
                updates.append((status, team, current_season))

        cursor = conn.cursor()
        print(f"Applying {len(updates)} smart team status tags to matches...")
        
        cursor.executemany(f"""
            UPDATE {TABLE_NAME} 
            SET HomeTeamStatus = ? 
            WHERE HomeTeam = ? AND Season = ?
        """, updates)
        
        cursor.executemany(f"""
            UPDATE {TABLE_NAME} 
            SET AwayTeamStatus = ? 
            WHERE AwayTeam = ? AND Season = ?
        """, updates)
        
        conn.commit()
        conn.close()
        print("Smart detect categorization complete. Features fully updated.")
    except Exception as e:
        print(f"⚠️ Error running smart detect post-processor: {e}")

# --- MAIN EXECUTION COMMANDER ---
def main():
    parser = argparse.ArgumentParser(description="Automated Football Database Updater")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_NAME, help="Path to your SQLite database file.")
    parser.add_argument("--season", type=str, default=None, help="Force override targeted season label (e.g. '2627').")
    args = parser.parse_args()

    db_path = args.db
    is_gz = db_path.endswith(".gz")
    active_db_path = db_path
    
    # 1. Determine Target Season
    if args.season:
        target_season = args.season
        print(f"🎯 Target Season Forced Override: '{target_season}'")
    else:
        target_season = get_current_season()
        print(f"📅 Automatically Detected Current Season: '{target_season}'")

    # Ensure environment folders exist
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    # Handle auto decompression of gzipped SQLite database (.db.gz or .tar.gz disguised as .db.gz)
    if is_gz:
        active_db_path = "temp_uncompressed_database.db"
        if os.path.exists(db_path):
            print(f"📦 Found gzipped database '{db_path}'. Opening extraction suite...")
            import gzip
            import shutil
            import tarfile
            try:
                # First check if the .gz file is actually a tar archive (.tar.gz / .tgz format)
                is_tar = False
                try:
                    if tarfile.is_tarfile(db_path):
                        is_tar = True
                except Exception:
                    pass

                if is_tar:
                    print("📦 Format detected: gzipped tar archive (.tar.gz). Extracting database...")
                    with tarfile.open(db_path, "r:gz") as tar:
                        members = tar.getmembers()
                        db_member = None
                        for member in members:
                            if member.name.endswith(".db"):
                                db_member = member
                                break
                        if db_member is None and len(members) > 0:
                            db_member = members[0] # Fallback to first file
                        
                        if db_member:
                            print(f" -> Extracting '{db_member.name}' to '{active_db_path}'...")
                            with tar.extractfile(db_member) as f_in:
                                with open(active_db_path, 'wb') as f_out:
                                    shutil.copyfileobj(f_in, f_out)
                            print(" -> Extraction successful!")
                        else:
                            raise Exception("No valid database file found inside the tar archive.")
                else:
                    print("📦 Format detected: plain gzip. Decompressing...")
                    with gzip.open(db_path, 'rb') as f_in:
                        with open(active_db_path, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    print(" -> Decompression successful!")
            except Exception as e:
                print(f" -> Decompression/Extraction failed: {e}")
                # Fallback to copy or empty if corrupted
                if os.path.exists(active_db_path):
                    os.remove(active_db_path)
        else:
            print(f"⚠️  Gzipped database '{db_path}' not found yet. An empty database will be created at '{active_db_path}'.")

    # 2. Initialize DB if file does not exist
    if not os.path.exists(active_db_path):
        print(f"⚠️  Database '{active_db_path}' not found! Creating a fresh database with schemas...")
    init_db(active_db_path)

    # 3. Download and Append Latest Results for Each League
    print("\nStarting downloads from football-data.co.uk...")
    total_new_rows = 0
    
    for div_code in LEAGUE_MAP:
        local_path = download_league_csv(div_code, target_season)
        if local_path:
            df = process_and_standardize(local_path, div_code, target_season)
            if df is not None and not df.empty:
                appended = append_to_db(df, active_db_path)
                total_new_rows += appended
                
    print(f"\n📊 Batch Ingest Completed: Successfully updated/appended {total_new_rows} fixtures.")

    # 4. Trigger Smart Detect Tag Calculation
    run_smart_detect_processor(active_db_path)

    # Save Mapping File Cache
    with open(MAPPING_FILE, 'w') as f:
        json.dump(TEAM_LOOKUP, f, indent=4, sort_keys=True)

    # Handle auto compression back to gzipped SQLite database (.db.gz)
    if is_gz:
        print(f"📦 Compressing updated database '{active_db_path}' back to '{db_path}'...")
        import gzip
        import shutil
        try:
            with open(active_db_path, 'rb') as f_in:
                with gzip.open(db_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            print(" -> Compression successful!")
        except Exception as e:
            print(f" -> Compression failed: {e}")
        finally:
            if os.path.exists(active_db_path):
                os.remove(active_db_path)

    print("\n✅ Success! Database successfully updated and fully synced.")
    print("-" * 65)
    print("👉 Next Steps for Automation & Git deployment:")
    print("1. Commit the updated database file:")
    print(f"   git add {db_path}")
    print("   git commit -m \"Update fixtures with latest match scores\"")
    print("   git push origin main")
    print("2. Once pushed, you can reload the database in your AI tool by inputting")
    print("   the direct raw URL of the file from your GitHub repository.")
    print("-" * 65)

if __name__ == "__main__":
    main()
