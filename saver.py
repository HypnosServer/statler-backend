from nbt import nbt
from datetime import datetime
import schedule
import sqlite3
import time
import sys


def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS objectives (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        internal_name TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        criteria_name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS scores (
        snapshot_id INTEGER NOT NULL,
        objective_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        score INTEGER NOT NULL,

        PRIMARY KEY (snapshot_id, objective_id, player_id),

        FOREIGN KEY (snapshot_id) REFERENCES snapshots(id),
        FOREIGN KEY (objective_id) REFERENCES objectives(id),
        FOREIGN KEY (player_id) REFERENCES players(id)
    );

    CREATE INDEX IF NOT EXISTS idx_scores_player_objective
    ON scores(player_id, objective_id);

    CREATE INDEX IF NOT EXISTS idx_scores_objective_snapshot
    ON scores(objective_id, snapshot_id);
    """)


def parse_scoreboard_dat(file_path) -> dict:
    nbt_file = nbt.NBTFile(file_path, "rb")
    data = nbt_file["data"]

    result = {}

    if "Objectives" in data:
        for obj in data["Objectives"]:
            internal_name = str(obj["Name"].value)
            result[internal_name] = {
                "displayName": str(obj["DisplayName"].value),
                "criteriaName": str(obj["CriteriaName"].value),
                "stats": []
            }

    if "PlayerScores" in data:
        for score_entry in data["PlayerScores"]:
            objective_name = str(score_entry["Objective"].value)

            if objective_name not in result:
                continue

            player_name = str(score_entry["Name"].value)
            if player_name.lower() == "total":
                continue
            score = int(score_entry["Score"].value)

            result[objective_name]["stats"].append((player_name, score))

    for obj_data in result.values():
        total_score = 0
        for player, score in obj_data["stats"]:
            total_score += score
        obj_data["stats"].append(("Total", total_score))

    return result


def insert_snapshot(conn, scoreboard_data):
    cur = conn.cursor()

    created_at = datetime.utcnow()

    cur.execute("""
        INSERT INTO snapshots(created_at)
        VALUES (?)
    """, (created_at,))

    snapshot_id = cur.lastrowid

    for objective_name, obj_data in scoreboard_data.items():

        # ---- OBJECTIVES (SQLite-safe UPSERT) ----
        cur.execute("""
            INSERT OR IGNORE INTO objectives(
                internal_name,
                display_name,
                criteria_name
            )
            VALUES (?, ?, ?)
        """, (
            objective_name,
            obj_data["displayName"],
            obj_data["criteriaName"]
        ))

        cur.execute("""
            UPDATE objectives
            SET display_name = ?,
                criteria_name = ?
            WHERE internal_name = ?
        """, (
            obj_data["displayName"],
            obj_data["criteriaName"],
            objective_name
        ))

        cur.execute("""
            SELECT id
            FROM objectives
            WHERE internal_name=?
        """, (objective_name,))
        objective_id = cur.fetchone()[0]

        for player_name, score in obj_data["stats"]:

            # ---- PLAYERS (SQLite-safe INSERT IGNORE) ----
            cur.execute("""
                INSERT OR IGNORE INTO players(name)
                VALUES (?)
            """, (player_name,))

            cur.execute("""
                SELECT id
                FROM players
                WHERE name=?
            """, (player_name,))
            player_id = cur.fetchone()[0]

            cur.execute("""
                SELECT sc.score
                FROM scores sc
                JOIN snapshots s ON sc.snapshot_id = s.id
                WHERE sc.player_id=?
                  AND sc.objective_id=?
                ORDER BY s.created_at DESC
                LIMIT 1
            """, (player_id, objective_id))

            row = cur.fetchone()
            previous_score = row[0] if row else None

            if previous_score == score:
                continue

            cur.execute("""
                INSERT INTO scores(
                    snapshot_id,
                    objective_id,
                    player_id,
                    score
                )
                VALUES (?, ?, ?, ?)
            """, (snapshot_id, objective_id, player_id, score))

    conn.commit()


def take_snapshot():
    try:
        scoreboard_data = parse_scoreboard_dat(sys.argv[1])

        conn = sqlite3.connect("scoreboard.db")
        init_db(conn)
        insert_snapshot(conn, scoreboard_data)
        conn.close()

    except Exception as e:
        raise e
        print(f"[{datetime.now()}] ERROR: {e}")


if __name__ == "__main__":
    schedule.every().hour.do(take_snapshot)
    while True:
        schedule.run_pending()
        time.sleep(1)
