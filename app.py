from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import pickle
import numpy as np
import sqlite3
import json
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from collections import defaultdict
import logging

# Suppress the Werkzeug development server warning
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = "your_secret_key"  # 🔒 Change in production

# ------------------ DATABASE SETUP ------------------
DATABASE = 'liver_disease.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    with conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
                        phone TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        password TEXT NOT NULL
                    )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS doctors (
                        doctor_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        phone TEXT NOT NULL,
                        password TEXT NOT NULL
                    )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS patients_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        phone TEXT NOT NULL,
                        name TEXT NOT NULL,
                        features TEXT NOT NULL,
                        prediction INTEGER NOT NULL,
                        status TEXT DEFAULT 'Pending'
                    )''')
    conn.close()

# Initialize DB
init_db()

# ------------------ ADMIN ------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"


# ------------------ LOAD MODEL ------------------
MODEL_PATH = os.path.join("models", "Liver2.pkl")
model = None
try:
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
except Exception as e:
    print("⚠️ Error loading model:", e)

# ------------------ ROUTES ------------------

@app.route("/")
def home():
    return render_template("home.html")

# ------------------ PATIENT REGISTER ------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not name or not phone or not password:
            flash("All fields are required", "danger")
            return redirect(url_for("register"))

        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (phone, name, password) VALUES (?, ?, ?)",
                         (phone, name, generate_password_hash(password)))
            conn.commit()
            flash("✅ Registered successfully! Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Phone number already registered", "warning")
            return redirect(url_for("register"))
        finally:
            conn.close()

    return render_template("register.html")

# ------------------ PATIENT LOGIN ------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_phone"] = user["phone"]
            session["user_name"] = user["name"]
            flash("✅ Logged in successfully!", "success")
            return redirect(url_for("form"))

        flash("❌ Invalid credentials", "danger")

    return render_template("login.html")

# ------------------ PATIENT LOGOUT ------------------
@app.route("/logout")
def logout():
    session.pop("user_phone", None)
    session.pop("user_name", None)
    flash("👋 Logged out", "info")
    return redirect(url_for("home"))

# ------------------ LIVER FORM ------------------
@app.route("/form", methods=["GET", "POST"])
def form():
    if "user_phone" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        try:
            features = [
                float(request.form.get("Age", 0)),
                int(request.form.get("Gender", 0)),
                float(request.form.get("Total_Bilirubin", 0)),
                float(request.form.get("Alkaline_Phosphotase", 0)),
                float(request.form.get("Alamine_Aminotransferase", 0)),
                float(request.form.get("Aspartate_Aminotransferase", 0)),
                float(request.form.get("Total_Protiens", 0)),
                float(request.form.get("Albumin", 0)),
                float(request.form.get("Albumin_and_Globulin_Ratio", 0))
            ]
        except ValueError:
            flash("⚠️ Please enter valid numbers!", "danger")
            return redirect(url_for("form"))

        if model is None:
            flash("⚠️ Model not loaded.", "danger")
            return redirect(url_for("form"))

        arr = np.array(features).reshape(1, -1)
        prediction_val = int(model.predict(arr)[0])
        
        # In ILPD datasets, often 1 is Disease and 2 is No Disease. 
        is_disease = 1 if prediction_val == 1 else 0
        
        result_text = "You have liver disease. Consult a doctor! ⚠️" if is_disease else "No liver disease detected. Stay healthy 😊"

        # Save to DB
        conn = get_db_connection()
        conn.execute("INSERT INTO patients_history (date, phone, name, features, prediction) VALUES (?, ?, ?, ?, ?)",
                     (datetime.now().strftime("%Y-%m-%d"), 
                      session["user_phone"], 
                      session["user_name"], 
                      json.dumps(features), 
                      is_disease))
        conn.commit()
        conn.close()

        return render_template("result.html", prediction=result_text, is_disease=is_disease, features=features)

    return render_template("form.html")

# ------------------ ADMIN LOGIN ------------------
@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
  
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = username
            flash("✅ Admin logged in successfully!", "success")
            return redirect(url_for("admin_dashboard"))

        flash("❌ Invalid admin credentials", "danger")
    return render_template("admin_login.html")

# ------------------ ADMIN DASHBOARD ------------------
@app.route("/admin-dashboard")
def admin_dashboard():
    if "admin" not in session:
        flash("⚠️ Please login as admin first", "warning")
        return redirect(url_for("admin_login"))

    conn = get_db_connection()
    
    # Get Doctors
    doctors_rows = conn.execute("SELECT * FROM doctors").fetchall()
    doctors = {d["doctor_id"]: {"name": d["name"], "phone": d["phone"]} for d in doctors_rows}
    
    # Get History
    history_rows = conn.execute("SELECT * FROM patients_history ORDER BY date DESC").fetchall()
    conn.close()

    total_patients = len(history_rows)
    total_doctors = len(doctors)

    patients_by_date = defaultdict(list)
    for row in history_rows:
        entry = dict(row)
        entry["features"] = json.loads(entry["features"])
        patients_by_date[entry["date"]].append(entry)

    sorted_dates = sorted(patients_by_date.keys(), reverse=True)

    return render_template(
        "admin_dashboard.html",
        total_patients=total_patients,
        total_doctors=total_doctors,
        doctors=doctors,
        patients_by_date=patients_by_date,
        sorted_dates=sorted_dates
    )

# ------------------ ADMIN LOGOUT ------------------
@app.route("/admin-logout")
def admin_logout():
    session.pop("admin", None)
    flash("👋 Admin logged out", "info")
    return redirect(url_for("home"))

# ------------------ ADD DOCTOR ------------------
@app.route("/admin/add_doctor", methods=["GET", "POST"])
def add_doctor():
    if "admin" not in session:
        flash("⚠️ Admin access required", "danger")
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        doctor_id = request.form.get("doctor_id", "").strip()
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()

        if not doctor_id or not name or not phone or not password:
            flash("All fields are required!", "danger")
            return redirect(url_for("add_doctor"))

        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO doctors (doctor_id, name, phone, password) VALUES (?, ?, ?, ?)",
                         (doctor_id, name, phone, generate_password_hash(password)))
            conn.commit()
            flash(f"✅ Doctor {name} added successfully!", "success")
            return redirect(url_for("admin_dashboard"))
        except sqlite3.IntegrityError:
            flash("Doctor ID already exists!", "warning")
            return redirect(url_for("add_doctor"))
        finally:
            conn.close()

    return render_template("add_doctor.html")

# ------------------ DELETE PATIENT ------------------
@app.route("/admin/delete_patient/<phone>", methods=["POST"])
def delete_patient(phone):
    if "admin" not in session:
        flash("⚠️ Admin access required", "danger")
        return redirect(url_for("admin_login"))

    conn = get_db_connection()
    # Delete from users
    conn.execute("DELETE FROM users WHERE phone = ?", (phone,))
    # Delete from history
    conn.execute("DELETE FROM patients_history WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

    flash("✅ Patient and history deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))

# ------------------ DELETE DOCTOR ------------------
@app.route("/admin/delete_doctor/<doctor_id>", methods=["POST"])
def delete_doctor(doctor_id):
    if "admin" not in session:
        flash("⚠️ Admin access required", "danger")
        return redirect(url_for("admin_login"))

    conn = get_db_connection()
    conn.execute("DELETE FROM doctors WHERE doctor_id = ?", (doctor_id,))
    conn.commit()
    conn.close()

    flash(f"✅ Doctor {doctor_id} deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))

# ------------------ DOCTOR LOGIN ------------------
@app.route("/doctor-login", methods=["GET", "POST"])
def doctor_login():
    if request.method == "POST":
        doctor_id = request.form.get("doctor_id", "").strip()
        password = request.form.get("password", "")

        conn = get_db_connection()
        doctor = conn.execute("SELECT * FROM doctors WHERE doctor_id = ?", (doctor_id,)).fetchone()
        conn.close()

        if doctor and check_password_hash(doctor["password"], password):
            session["doctor_id"] = doctor_id
            session["doctor_name"] = doctor["name"]
            flash(f"✅ Welcome Dr. {doctor['name']}", "success")
            return redirect(url_for("doctor_dashboard"))

        flash("❌ Invalid credentials", "danger")

    return render_template("doctor_login.html")

# ------------------ DOCTOR DASHBOARD ------------------
@app.route("/doctor-dashboard")
def doctor_dashboard():
    if "doctor_id" not in session:
        flash("⚠️ Please login first", "warning")
        return redirect(url_for("doctor_login"))

    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM patients_history ORDER BY date DESC").fetchall()
    conn.close()
    
    patients = []
    for row in rows:
        p = dict(row)
        try:
            p["features"] = json.loads(p["features"])
        except:
             p["features"] = [] # Fallback
        patients.append(p)

    return render_template("doctor_dashboard.html",
                           doctor_name=session["doctor_name"],
                           patients=patients)

# ------------------ UPDATE STATUS ------------------
@app.route("/update_status/<int:id>", methods=["POST"])
def update_status(id):
    if "doctor_id" not in session:
        return {"success": False, "message": "Unauthorized"}, 401

    data = request.json
    status = data.get("status", "Pending")

    conn = get_db_connection()
    conn.execute("UPDATE patients_history SET status = ? WHERE id = ?", (status, id))
    conn.commit()
    conn.close()

    return {"success": True}

# ------------------ DOCTOR LOGOUT ------------------
@app.route("/doctor-logout")
def doctor_logout():
    session.pop("doctor_id", None)
    session.pop("doctor_name", None)
    flash("👋 Doctor logged out", "info")
    return redirect(url_for("home"))

# ------------------ RUN APP ------------------
if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
