import os
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

DB_URL = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql")

HTML = """<!DOCTYPE html>
<html><head><title>MEGA-AI Log Query</title>
<style>body{font-family:monospace;margin:20px;background:#1a1a2e;color:#e0e0e0}
h2{color:#00d4ff}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #444;padding:6px;text-align:left}th{background:#333;color:#00d4ff}
tr:hover{background:#2a2a4e}input{background:#222;color:#fff;border:1px solid #555;padding:4px}
button{background:#00d4ff;color:#000;border:none;padding:6px 12px;cursor:pointer;font-weight:bold}
button:hover{background:#00b8d9}.badge{padding:2px 6px;border-radius:3px}
.done{background:#1a472a}.failed{background:#5c2323}.running{background:#1a3a5c}</style>
</head><body>
<h2>MEGA-AI Execution Trace</h2>
<form method="get" action="/trace">
  Job ID: <input name="job_id" value="{{ job_id }}" size="40">
  <button type="submit">Search</button>
</form>
{% if rows %}
<p>{{ rows|length }} events found for job <strong>{{ job_id }}</strong></p>
<table>
<tr><th>Seq</th><th>Agent</th><th>Event</th><th>Latency</th><th>Tokens</th><th>Violation</th><th>Time</th></tr>
{% for r in rows %}
<tr><td>{{r.seq}}</td><td>{{r.agent_id}}</td><td>{{r.event_type}}</td>
<td>{{r.latency_ms|round(1)}}ms</td><td>{{r.token_count}}</td>
<td>{{r.policy_violation or ''}}</td><td>{{r.timestamp}}</td></tr>
{% endfor %}
</table>
{% elif job_id %}
<p>No events found for job ID: {{ job_id }}</p>
{% endif %}
</body></html>"""


@app.route("/")
def index():
    return render_template_string(HTML, rows=[], job_id="")


@app.route("/trace")
def trace():
    job_id = request.args.get("job_id", "")
    rows = []
    if job_id:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT seq, agent_id, event_type, latency_ms, token_count,
                   policy_violation, timestamp
            FROM execution_events WHERE job_id = %s ORDER BY seq
        """, (job_id,))
        rows = cur.fetchall()
        conn.close()
    return render_template_string(HTML, rows=rows, job_id=job_id)


@app.route("/api/trace/<job_id>")
def api_trace(job_id):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM execution_events WHERE job_id = %s ORDER BY seq", (job_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=False)
