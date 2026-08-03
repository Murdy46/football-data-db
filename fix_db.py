import gzip
import shutil
import sqlite3

gz_file = "football_data.db.gz"
db_file = "football_data.db"

# 1. Decompress
print("Decompressing football_data.db.gz...")
with gzip.open(gz_file, "rb") as f_in:
  with open(db_file, "wb") as f_out:
    shutil.copyfileobj(f_in, f_out)

# 2. Run SQL Updates
print("Applying division code fixes...")
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# Fix Scottish Championship mislabeled as SP1
cursor.execute("""
UPDATE fixtures
SET DivisionCode = 'SC1', Country = 'Scotland', LeagueName = 'Championship', Tier = '2'
WHERE DivisionCode = 'SP1' AND Season = '2627' AND (
  HomeTeam IN ('Ayr', 'Arbroath', 'Inverness C', 'Dunfermline', 'Livingston', 'Queens Park', 'Morton', 'Partick', 'Raith Rvs', 'St Johnstone', 'Airdrie Utd', 'Ross County', 'Falkirk')
  OR AwayTeam IN ('Ayr', 'Arbroath', 'Inverness C', 'Dunfermline', 'Livingston', 'Queens Park', 'Morton', 'Partick', 'Raith Rvs', 'St Johnstone', 'Airdrie Utd', 'Ross County', 'Falkirk')
);
""")

# Fix Scottish League One mislabeled as SP2
cursor.execute("""
UPDATE fixtures
SET DivisionCode = 'SC2', Country = 'Scotland', LeagueName = 'League One', Tier = '3'
WHERE DivisionCode = 'SP2' AND Season = '2627' AND (
  HomeTeam IN ('Alloa', 'East Fife', 'East Kilbride', 'Montrose', 'Cove Rangers', 'Peterhead', 'Hamilton', 'Stenhousemuir', 'Queen of Sth', 'Kelty Hearts', 'Dumbarton', 'Annan Athletic', 'Stirling')
  OR AwayTeam IN ('Alloa', 'East Fife', 'East Kilbride', 'Montrose', 'Cove Rangers', 'Peterhead', 'Hamilton', 'Stenhousemuir', 'Queen of Sth', 'Kelty Hearts', 'Dumbarton', 'Annan Athletic', 'Stirling')
);
""")

conn.commit()
print(f"Updated rows! (SC1 updated: {cursor.rowcount})")
conn.close()

# 3. Recompress back to .db.gz
print("Recompressing to football_data.db.gz...")
with open(db_file, "rb") as f_in:
  with gzip.open(gz_file, "wb") as f_out:
    shutil.copyfileobj(f_in, f_out)

print("Done! You can now commit football_data.db.gz back to GitHub.")
