from flask import Flask, render_template, request, redirect, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)

RESTAURANT_NAME = "The Grill House"
AVG_COVER_SPEND = 28
AVG_MISSED_SPEND = 56


def get_db():
    conn = sqlite3.connect("bookings.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            guests INTEGER,
            time TEXT,
            source TEXT,
            notes TEXT,
            status TEXT DEFAULT 'confirmed',
            created TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS missed_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            time TEXT DEFAULT (datetime('now')),
            action TEXT,
            outcome TEXT DEFAULT 'Awaiting reply',
            status TEXT DEFAULT 'pending'
        )
    """)

    conn.commit()
    conn.close()


init_db()


@app.route("/")
def dashboard():
    conn = get_db()
    bookings = conn.execute("SELECT * FROM bookings ORDER BY created DESC").fetchall()
    missed = conn.execute("SELECT * FROM missed_calls ORDER BY time DESC").fetchall()
    conn.close()

    total_guests = sum(b["guests"] for b in bookings)
    recovered = sum(1 for m in missed if m["status"] == "recovered")

    stats = {
        "total_bookings": len(bookings),
        "missed_recovered": recovered,
        "estimated_revenue": total_guests * AVG_COVER_SPEND,
        "missed_revenue": recovered * AVG_MISSED_SPEND,
    }

    return render_template(
        "dashboard.html",
        bookings=bookings,
        missed=missed,
        stats=stats,
        restaurant=RESTAURANT_NAME
    )


@app.route("/chat")
def chat_page():
    return render_template("chat.html", restaurant=RESTAURANT_NAME)


@app.route("/api/chat", methods=["POST"])
def ai_chat():
    import re

    data = request.get_json()
    messages = data.get("messages", [])

    if not messages:
        return jsonify({"reply": "Please type your booking request."})

    message = messages[-1]["content"].lower()

    name = "Guest"
    guests = 2
    time = "Tonight"
    phone = "Unknown"

    # Guest count
    g = re.search(r'(\d+)', message)
    if g:
        guests = int(g.group(1))

    # Time
    t = re.search(r'(\d{1,2})(:\d{2})?\s?(am|pm)', message)
    if t:
        time = t.group(0)

    # Date words
    if "tomorrow" in message:
        time = "Tomorrow " + time
    elif "tonight" in message:
        time = "Tonight " + time

    # Name
    n = re.search(r'(under|name is|this is)\s+([a-zA-Z]+)', message)
    if n:
        name = n.group(2).capitalize()

    if "book" in message or "table" in message:
        conn = get_db()
        conn.execute(
            "INSERT INTO bookings (name, phone, guests, time, source, status) VALUES (?, ?, ?, ?, ?, ?)",
            (name, phone, guests, time, "AI Chat", "confirmed")
        )
        conn.commit()
        conn.close()

        return jsonify({
            "reply": f"Perfect, {name}. Your table for {guests} at {time} is confirmed. See you soon.",
            "booking_created": {
                "name": name,
                "guests": guests,
                "time": time
            }
        })

    return jsonify({
        "reply": "I can help you book a table. Tell me number of guests, time, and name."
    })


@app.route("/api/bookings", methods=["POST"])
def create_booking():
    data = request.get_json()

    name = data.get("name", "Guest")
    phone = data.get("phone", "Unknown")
    guests = int(data.get("guests", 2))
    time = data.get("time", "Tonight")
    source = data.get("source", "Walk-in")
    notes = data.get("notes", "")
    status = data.get("status", "confirmed")

    conn = get_db()
    conn.execute(
        "INSERT INTO bookings (name, phone, guests, time, source, notes, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, phone, guests, time, source, notes, status)
    )
    conn.commit()

    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    booking = dict(conn.execute("SELECT * FROM bookings WHERE id=?", (new_id,)).fetchone())

    conn.close()

    return jsonify({"success": True, "booking": booking})


@app.route("/api/bookings/<int:id>", methods=["DELETE"])
def delete_booking(id):
    conn = get_db()
    conn.execute("DELETE FROM bookings WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True})


@app.route("/api/missed-call", methods=["POST"])
def missed_call():
    data = request.get_json() or {}
    phone = data.get("phone", "07XXXXXXX")

    conn = get_db()
    conn.execute(
        "INSERT INTO missed_calls (phone, action) VALUES (?, ?)",
        (phone, "AI SMS sent")
    )
    conn.commit()

    mc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    return jsonify({"success": True, "id": mc_id, "action": "AI SMS sent"})


@app.route("/api/missed-call/<int:mc_id>/recover", methods=["POST"])
def recover_missed_call(mc_id):
    data = request.get_json() or {}
    phone = data.get("phone", "07XXXXXXX")

    conn = get_db()

    conn.execute(
        "UPDATE missed_calls SET status='recovered', outcome=? WHERE id=?",
        ("Booked: 2 covers tonight 8PM", mc_id)
    )

    conn.execute(
        "INSERT INTO bookings (name, phone, guests, time, source, notes, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Missed Caller", phone, 2, "Tonight 8PM", "Missed Call", "Recovered via AI SMS", "confirmed")
    )

    conn.commit()
    conn.close()

    return jsonify({"success": True, "outcome": "Booked: 2 covers tonight 8PM"})


@app.route("/api/analytics")
def analytics():
    conn = get_db()
    bookings = conn.execute("SELECT * FROM bookings").fetchall()
    missed = conn.execute("SELECT * FROM missed_calls").fetchall()
    conn.close()

    total_guests = sum(b["guests"] for b in bookings)
    recovered = sum(1 for m in missed if m["status"] == "recovered")
    ai_bookings = sum(1 for b in bookings if b["source"] == "AI Chat")

    source_counts = {}
    for b in bookings:
        source_counts[b["source"]] = source_counts.get(b["source"], 0) + 1

    return jsonify({
        "total_bookings": len(bookings),
        "total_guests": total_guests,
        "estimated_revenue": total_guests * AVG_COVER_SPEND,
        "missed_recovered": recovered,
        "missed_revenue": recovered * AVG_MISSED_SPEND,
        "ai_bookings": ai_bookings,
        "source_breakdown": source_counts,
    })


if __name__ == "__main__":
    app.run(debug=True)
