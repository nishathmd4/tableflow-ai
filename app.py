from flask import Flask, render_template, request, jsonify
import sqlite3
import re

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


def extract_booking_details(messages):
    full_text = " ".join([m["content"].lower() for m in messages if m["role"] == "user"])

    details = {
        "name": None,
        "phone": None,
        "guests": None,
        "time": None,
        "notes": None,
    }

    # Guests
    guest_match = re.search(r'(\d+)\s*(people|persons|guests|covers|table for)?', full_text)
    if guest_match:
        details["guests"] = int(guest_match.group(1))

    if "me and my wife" in full_text or "me and my husband" in full_text or "two of us" in full_text:
        details["guests"] = 2

    # Time
    time_match = re.search(r'(\d{1,2})(:\d{2})?\s?(am|pm)', full_text)
    if time_match:
        details["time"] = time_match.group(0)

    if details["time"]:
        if "tomorrow" in full_text:
            details["time"] = "Tomorrow " + details["time"]
        elif "tonight" in full_text:
            details["time"] = "Tonight " + details["time"]
        elif "friday" in full_text:
            details["time"] = "Friday " + details["time"]
        elif "saturday" in full_text:
            details["time"] = "Saturday " + details["time"]
        elif "sunday" in full_text:
            details["time"] = "Sunday " + details["time"]

    # Name
    name_match = re.search(r'(under|name is|this is|for)\s+([a-zA-Z]+)', full_text)
    if name_match:
        details["name"] = name_match.group(2).capitalize()

    # Phone
    phone_match = re.search(r'(07\d{9}|\+44\s?7\d{9})', full_text)
    if phone_match:
        details["phone"] = phone_match.group(1)

    # Allergies / notes
    notes = []
    allergy_words = ["allergy", "allergic", "gluten", "nuts", "nut", "peanut", "dairy", "halal", "vegan", "vegetarian", "birthday", "anniversary", "wheelchair"]
    for word in allergy_words:
        if word in full_text:
            notes.append(word)

    if notes:
        details["notes"] = ", ".join(sorted(set(notes)))

    return details


@app.route("/api/chat", methods=["POST"])
def ai_chat():
    data = request.get_json()
    messages = data.get("messages", [])

    if not messages:
        return jsonify({"reply": "Of course — how many people is the table for?"})

    latest_message = messages[-1]["content"].lower()
    details = extract_booking_details(messages)

    booking_intent = any(word in latest_message for word in ["book", "table", "reserve", "reservation"])

    if not booking_intent and len(messages) <= 1:
        return jsonify({
            "reply": f"Welcome to {RESTAURANT_NAME}. I can help you book a table. How many people is the booking for?"
        })

    if not details["guests"]:
        return jsonify({
            "reply": "Of course — how many people is the table for?"
        })

    if not details["time"]:
        return jsonify({
            "reply": f"Great. What date and time would you like to book for {details['guests']} people?"
        })

    if not details["name"]:
        return jsonify({
            "reply": "Perfect. What name should I put the booking under?"
        })

    if not details["notes"]:
        return jsonify({
            "reply": f"Thanks, {details['name']}. Any allergies, dietary requirements, or special requests?"
        })

    phone = details["phone"] or "Unknown"
    notes = details["notes"] or "None"

    conn = get_db()
    conn.execute(
        "INSERT INTO bookings (name, phone, guests, time, source, notes, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (details["name"], phone, details["guests"], details["time"], "AI Chat", notes, "confirmed")
    )
    conn.commit()
    conn.close()

    return jsonify({
        "reply": f"Perfect, {details['name']}. Your table for {details['guests']} at {details['time']} is confirmed. We’ve noted: {notes}. See you soon.",
        "booking_created": {
            "name": details["name"],
            "guests": details["guests"],
            "time": details["time"]
        }
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
