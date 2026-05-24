from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import sqlite3

app = Flask(__name__)

DB_PATH = "scoreboard.db"


def query_player_objective(
    conn,
    player_name,
    objective_name,
    start_time,
    end_time
):
    cur = conn.cursor()
    print(start_time)
    print(end_time)

    cur.execute("""
        SELECT id
        FROM players
        WHERE name=?
    """, (player_name,))

    row = cur.fetchone()
    if not row:
        return []

    player_id = row[0]

    cur.execute("""
        SELECT id
        FROM objectives
        WHERE internal_name=?
    """, (objective_name,))

    row = cur.fetchone()
    if not row:
        return []

    objective_id = row[0]

    cur.execute("""
        SELECT sc.score
        FROM scores sc
        JOIN snapshots s ON sc.snapshot_id = s.id
        WHERE sc.player_id = ?
          AND sc.objective_id = ?
          AND datetime(s.created_at) <= datetime(?)
        ORDER BY s.created_at DESC
        LIMIT 1
    """, (player_id, objective_id, start_time))

    row = cur.fetchone()
    current_score = row[0] if row else None

    cur.execute("""
        SELECT id, created_at
        FROM snapshots
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        ORDER BY created_at
    """, (start_time, end_time))

    snapshots = cur.fetchall()

    if not snapshots:
        return []

    cur.execute("""
        SELECT snapshot_id, score
        FROM scores
        WHERE player_id = ?
          AND objective_id = ?
    """, (player_id, objective_id))

    changes = dict(cur.fetchall())

    result = []

    for snapshot_id, ts in snapshots:

        if snapshot_id in changes:
            current_score = changes[snapshot_id]

        if current_score is None:
            continue

        result.append({
            "timestamp": ts,
            "score": current_score
        })

    return result

@app.route("/api/players")
def players():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT name FROM players ORDER BY name")
    data = [r[0] for r in cur.fetchall()]

    conn.close()

    return jsonify({"players": data})


@app.route("/api/objectives")
def objectives():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT internal_name, display_name FROM objectives ORDER BY internal_name")
    data = [
        {"internal_name": r[0], "display_name": r[1]}
        for r in cur.fetchall()
    ]

    conn.close()

    return jsonify({"objectives": data})

@app.route("/api/query")
def query_endpoint():

    player = request.args.get("player")
    objective = request.args.get("objective")
    start = request.args.get("start")
    end = request.args.get("end")

    if not all([player, objective, start, end]):
        return jsonify({
            "error": (
                "Missing parameters. "
                "Required: "
                "player, objective, start, end"
            )
        }), 400

    conn = sqlite3.connect(DB_PATH)

    data = query_player_objective(
        conn,
        player,
        objective,
        start,
        end
    )

    conn.close()

    return jsonify({
        "player": player,
        "objective": objective,
        "start": start,
        "end": end,
        "data": data
    })

def get_monday_00_utc():
    now = datetime.utcnow()
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def get_top5_weekly_gainers_selected_objectives(conn, objective_names):
    if not objective_names:
        return []

    cur = conn.cursor()

    monday_start = get_monday_00_utc().strftime("%Y-%m-%d %H:%M:%S")

    placeholders = ",".join(["?"] * len(objective_names))
    cur.execute(f"""
        SELECT id, internal_name
        FROM objectives
        WHERE internal_name IN ({placeholders})
    """, objective_names)

    objective_ids = [row[0] for row in cur.fetchall()]

    if not objective_ids:
        return []

    obj_placeholders = ",".join(["?"] * len(objective_ids))

    query = f"""
    WITH first_scores AS (
        SELECT
            sc.player_id,
            sc.objective_id,
            sc.score AS first_score
        FROM scores sc
        JOIN snapshots s ON sc.snapshot_id = s.id
        WHERE s.created_at = (
            SELECT MIN(s2.created_at)
            FROM scores sc2
            JOIN snapshots s2 ON sc2.snapshot_id = s2.id
            WHERE sc2.player_id = sc.player_id
              AND sc2.objective_id = sc.objective_id
              AND s2.created_at >= ?
        )
          AND sc.objective_id IN ({obj_placeholders})
    ),

    last_scores AS (
        SELECT
            sc.player_id,
            sc.objective_id,
            sc.score AS last_score
        FROM scores sc
        JOIN snapshots s ON sc.snapshot_id = s.id
        WHERE s.created_at = (
            SELECT MAX(s2.created_at)
            FROM scores sc2
            JOIN snapshots s2 ON sc2.snapshot_id = s2.id
            WHERE sc2.player_id = sc.player_id
              AND sc2.objective_id = sc.objective_id
              AND s2.created_at >= ?
        )
          AND sc.objective_id IN ({obj_placeholders})
    ),

    gains AS (
        SELECT
            f.player_id,
            (l.last_score - f.first_score) AS gain
        FROM first_scores f
        JOIN last_scores l
          ON f.player_id = l.player_id
         AND f.objective_id = l.objective_id
    )

    SELECT
        p.name,
        SUM(g.gain) AS total_gain
    FROM gains g
    JOIN players p ON p.id = g.player_id
    WHERE p.name != 'Total'
    GROUP BY g.player_id
    ORDER BY total_gain DESC
    LIMIT 5;
    """

    params = [monday_start] + objective_ids + [monday_start] + objective_ids
    cur.execute(query, params)
    return cur.fetchall()


@app.route("/api/weekly", methods=["GET"])
def weekly_leaderboard():
    print(request.args)
    objectives = request.args.get("objectives", "")

    if not objectives.strip():
        return jsonify({
            "error": "Missing 'objectives' query parameter (e.g. stone,dirt)"
        }), 400

    objective_list = [o.strip() for o in objectives.split(",") if o.strip()]

    conn = sqlite3.connect(DB_PATH)

    try:
        results = get_top5_weekly_gainers_selected_objectives(conn, objective_list)

        return jsonify([
            {"player": name, "gain": gain}
            for name, gain in results
        ])

    finally:
        conn.close()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=11002,
        debug=False
    )
