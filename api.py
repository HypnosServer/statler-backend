from flask import Flask, request, jsonify
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


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
