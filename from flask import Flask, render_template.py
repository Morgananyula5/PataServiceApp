from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import sqlite3
import json
import re
from datetime import datetime
import logging
import time
import random
from html import escape
import socket
from flask import send_from_directory
from flask import send_file
from flask import Flask, render_template  # Ensure this is at the top


# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session'
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

Session(app)

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'mp4', 'mov', 'wav', 'mp3'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, mode=0o755)

if not os.path.exists(app.config['SESSION_FILE_DIR']):
    os.makedirs(app.config['SESSION_FILE_DIR'], mode=0o755)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection(retries=5, delay=1):
    attempt = 0
    while attempt < retries:
        try:
            conn = sqlite3.connect("database.db", timeout=120, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                logging.warning(f"Database locked on attempt {attempt + 1}. Retrying in {delay} seconds...")
                time.sleep(delay * (2 ** attempt) + random.uniform(0, 0.1))
                attempt += 1
                continue
            logging.error(f"Database connection failed after {retries} attempts: {e}")
            raise
        except sqlite3.Error as e:
            logging.error(f"Database connection error: {e}")
            raise

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)

def update_messages_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in cursor.fetchall()}
        if 'is_pinned' not in columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN is_pinned INTEGER DEFAULT 0")
            logging.info("Added is_pinned column to messages table")
        if 'is_starred' not in columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN is_starred INTEGER DEFAULT 0")
            logging.info("Added is_starred column to messages table")
        if 'conversation_id' not in columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN conversation_id INTEGER")
            logging.info("Added conversation_id column to messages table")
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error updating messages table schema: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()

def create_tables():
    conn = get_db_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL,
                profile_picture TEXT,
                phone TEXT NOT NULL,
                service_description TEXT NOT NULL,
                areas_served TEXT NOT NULL,
                sub_county TEXT NOT NULL DEFAULT '',
                availability TEXT NOT NULL,
                custom_availability TEXT DEFAULT NULL,
                pricing TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                location TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (provider_id) REFERENCES providers (id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_provider_id ON bookings(provider_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                media_type TEXT DEFAULT NULL,
                media_path TEXT DEFAULT NULL,
                reaction TEXT DEFAULT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_read INTEGER DEFAULT 0,
                is_pinned INTEGER DEFAULT 0,
                is_starred INTEGER DEFAULT 0,
                conversation_id INTEGER,
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (receiver_id) REFERENCES users(id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id INTEGER NOT NULL,
                user2_id INTEGER NOT NULL,
                FOREIGN KEY (user1_id) REFERENCES users(id),
                FOREIGN KEY (user2_id) REFERENCES users(id)
            )
        """)
        update_messages_schema(conn)
        conn.commit()
        logging.info("Database schema verified or created successfully")
    except sqlite3.Error as e:
        logging.error(f"Database error creating tables: {e}")
        raise
    finally:
        conn.close()

try:
    create_tables()
except Exception as e:
    logging.critical(f"Failed to initialize database tables: {e}")
    raise

def search_web(query):
    mock_results = {
        "service provider": [
            {"title": "Best Service Providers in Nairobi", "url": "https://example.com/service-providers-nairobi"},
            {"title": "Top Rated Providers 2025", "url": "https://example.com/top-providers-2025"},
            {"title": "How to Choose a Service Provider", "url": "https://example.com/choose-provider"}
        ],
        "booking system": [
            {"title": "Online Booking Systems Guide", "url": "https://example.com/booking-systems"},
            {"title": "Best Booking Platforms", "url": "https://example.com/best-booking-platforms"},
            {"title": "Booking Software Reviews", "url": "https://example.com/booking-reviews"}
        ],
        "general": [
            {"title": "Wikipedia: General Knowledge", "url": "https://en.wikipedia.org/wiki/Main_Page"},
            {"title": "Google Search Tips", "url": "https://example.com/search-tips"},
            {"title": "Latest News 2025", "url": "https://example.com/latest-news-2025"}
        ]
    }
    query_lower = query.lower()
    if "service" in query_lower or "provider" in query_lower:
        return mock_results.get("service provider", mock_results["general"])
    elif "book" in query_lower or "booking" in query_lower:
        return mock_results.get("booking system", mock_results["general"])
    else:
        return mock_results["general"]

@app.route("/")
def home():
    logging.info("Home route accessed, Session: %s", session)
    return render_template("home.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"]
        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users (email, password, role) VALUES (?, ?, ?)",
                (email, hashed_password, role),
            )
            conn.commit()
            logging.info(f"Signup successful for email: {email}, role: {role}, Session: %s", session)
            flash("Signup successful! You can now log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            logging.warning(f"Signup failed: Email already registered - {email}, Session: %s", session)
            flash("Email already registered.", "error")
        finally:
            conn.close()
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        conn = get_db_connection()
        try:
            user = row_to_dict(conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone())
            logging.info(f"Attempting login for email: {email}, User found: {bool(user)}, Session: %s", session)
        except sqlite3.Error as e:
            logging.error(f"Database error during login for email {email}: {e}, Session: %s", session)
            flash("Database error. Please try again.", "error")
            return render_template("login.html")
        finally:
            conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_role"] = user["role"]
            session["user_email"] = user["email"]
            session.permanent = True
            logging.info(f"User logged in: {email}, Role: {user['role']}, Session ID: {session.sid if hasattr(session, 'sid') else 'N/A'}, Cookies: {request.cookies}, Session: %s", session)
            if user["role"] == "customer":
                return redirect(url_for("customer_dashboard"))
            else:
                return redirect(url_for("provider_dashboard"))
        else:
            logging.warning(f"Login failed for email: {email}, Session: %s", session)
            flash("Invalid email or password", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    if "user_id" in session:
        user_id = session["user_id"]
        logging.info(f"User logged out: ID {user_id}, Session ID: {session.sid if hasattr(session, 'sid') else 'N/A'}, Cookies: {request.cookies}, Session: %s", session)
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))

@app.route("/customer_dashboard")
def customer_dashboard():
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to customer dashboard, Session: %s", session)
        flash("Please log in as a customer to access this page.", "error")
        return redirect(url_for("login"))
    
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        providers = conn.execute("SELECT * FROM providers").fetchall()
        providers = [row_to_dict(provider) for provider in providers]
        unread_messages = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0",
            (user_id,)
        ).fetchone()[0]
        logging.info(f"Customer dashboard accessed by user ID {user_id}, Providers found: {len(providers)}, Unread messages: {unread_messages}, Session: %s", session)
    except sqlite3.Error as e:
        logging.error(f"Database error fetching providers for customer dashboard: {e}, Session: %s", session)
        flash("Error fetching providers. Please try again.", "error")
        providers = []
        unread_messages = 0
    finally:
        conn.close()
    
    return render_template("customer_dashboard.html", providers=providers, unread_messages=unread_messages)

@app.route("/book_provider/<int:provider_id>", methods=["GET", "POST"])
def book_provider(provider_id):
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to book provider, Session: %s", session)
        flash("Please log in as a customer to book a provider.", "error")
        return redirect(url_for("login"))
    
    conn = get_db_connection()
    try:
        provider = row_to_dict(conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone())
        if not provider:
            logging.warning(f"Provider ID {provider_id} not found, Session: %s", session)
            flash("Provider not found.", "error")
            return redirect(url_for("customer_dashboard"))
        
        if request.method == "POST":
            customer_name = request.form["name"]
            customer_phone = request.form["phone"]
            customer_email = request.form["email"]
            location = request.form["location"]
            
            conn.execute(
                "INSERT INTO bookings (provider_id, customer_name, customer_phone, customer_email, location) VALUES (?, ?, ?, ?, ?)",
                (provider_id, customer_name, customer_phone, customer_email, location)
            )
            conn.commit()
            logging.info(f"Booking successful for provider ID {provider_id} by customer email {customer_email}, Session: %s", session)
            flash("Booking successful! The provider will contact you soon.", "success")
            return redirect(url_for("customer_dashboard"))
        
    except sqlite3.Error as e:
        logging.error(f"Database error during booking for provider ID {provider_id}: {e}, Session: %s", session)
        flash("Error booking provider. Please try again.", "error")
        return redirect(url_for("customer_dashboard"))
    finally:
        conn.close()
    
    return render_template("book_provider.html", provider=provider)

@app.route("/provider_dashboard", methods=["GET", "POST"])
def provider_dashboard():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to provider dashboard, Session: %s", session)
        flash("Please log in as a provider to access this page.", "error")
        return redirect(url_for("login"))
    
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        provider = row_to_dict(conn.execute("SELECT * FROM providers WHERE user_id = ?", (user_id,)).fetchone())
        bookings = []
        unread_count = 0
        
        if provider:
            bookings = conn.execute(
                "SELECT * FROM bookings WHERE provider_id = ? ORDER BY created_at DESC",
                (provider["id"],)
            ).fetchall()
            bookings = [row_to_dict(booking) for booking in bookings]
            logging.info(f"Bookings fetched for provider ID {provider['id']}: {len(bookings)}, Session: %s", session)
            
            unread_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0",
                (user_id,)
            ).fetchone()[0]
            logging.info(f"Unread messages count for user ID {user_id}: {unread_count}, Session: %s", session)
        
        if request.method == "POST":
            action = request.form.get("action")
            name = request.form["name"]
            phone = request.form["phone"]
            service_description = request.form["service_description"]
            areas_served = request.form["areas_served"]
            sub_county = request.form.get("sub_county", "")
            availability = request.form["availability"]
            custom_availability = request.form.get("custom_availability", "") if availability == "Set Time" else None
            pricing = request.form["pricing"]
            profile_picture = request.files.get("profile_picture")
            
            profile_picture_path = provider["profile_picture"] if provider and provider["profile_picture"] else None
            if profile_picture and allowed_file(profile_picture.filename):
                filename = secure_filename(profile_picture.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{filename}"
                profile_picture.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                profile_picture_path = filename
                logging.info(f"Profile picture uploaded: {filename}, Session: %s", session)
            
            if action == "create":
                conn.execute(
                    """
                    INSERT INTO providers (user_id, name, profile_picture, phone, service_description, areas_served, sub_county, availability, custom_availability, pricing)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, name, profile_picture_path, phone, service_description, areas_served, sub_county, availability, custom_availability, pricing)
                )
                conn.commit()
                logging.info(f"Provider profile created for user ID {user_id}, Session: %s", session)
                flash("Profile created successfully!", "success")
            elif action == "edit" and provider:
                if profile_picture_path and provider["profile_picture"] and os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], provider["profile_picture"])):
                    os.remove(os.path.join(app.config["UPLOAD_FOLDER"], provider["profile_picture"]))
                    logging.info(f"Old profile picture removed: {provider['profile_picture']}, Session: %s", session)
                
                conn.execute(
                    """
                    UPDATE providers
                    SET name = ?, profile_picture = ?, phone = ?, service_description = ?, areas_served = ?, sub_county = ?, availability = ?, custom_availability = ?, pricing = ?
                    WHERE user_id = ?
                    """,
                    (name, profile_picture_path, phone, service_description, areas_served, sub_county, availability, custom_availability, pricing, user_id)
                )
                conn.commit()
                logging.info(f"Provider profile updated for user ID {user_id}, Session: %s", session)
                flash("Profile updated successfully!", "success")
            return redirect(url_for("provider_dashboard"))
        
        return render_template(
            "provider_dashboard.html",
            provider=provider,
            bookings=bookings,
            session_user_id=user_id,
            unread_messages=unread_count
        )
    except sqlite3.Error as e:
        logging.error(f"Database error in provider dashboard for user ID {user_id}: {e}, Session: %s", session)
        flash("Error accessing dashboard. Please try again.", "error")
        return redirect(url_for("provider_dashboard"))
    finally:
        conn.close()

@app.route("/delete_provider", methods=["POST"])
def delete_provider():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to delete provider, Session: %s", session)
        flash("Please log in as a provider to delete your profile.", "error")
        return redirect(url_for("login"))
    
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        provider = row_to_dict(conn.execute("SELECT * FROM providers WHERE user_id = ?", (user_id,)).fetchone())
        if provider and provider["profile_picture"] and os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], provider["profile_picture"])):
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], provider["profile_picture"]))
            logging.info(f"Profile picture deleted: {provider['profile_picture']}, Session: %s", session)
        
        conn.execute("DELETE FROM providers WHERE user_id = ?", (user_id,))
        conn.commit()
        logging.info(f"Provider profile deleted for user ID {user_id}, Session: %s", session)
        flash("Profile deleted successfully!", "success")
        return redirect(url_for("provider_dashboard"))
    except sqlite3.Error as e:
        logging.error(f"Database error deleting provider for user ID {user_id}: {e}, Session: %s", session)
        flash("Error deleting profile. Please try again.", "error")
        return redirect(url_for("provider_dashboard"))
    finally:
        conn.close()

@app.route("/search", methods=["GET"])
def search():
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to search, Session: %s", session)
        flash("Please log in as a customer to search for providers.", "error")
        return redirect(url_for("login"))
    
    query = request.args.get("query", "")
    if not query:
        logging.info("Empty search query, redirecting to customer dashboard, Session: %s", session)
        return redirect(url_for("customer_dashboard"))
    
    web_results = search_web(query)
    conn = get_db_connection()
    try:
        providers = conn.execute(
            """
            SELECT * FROM providers
            WHERE name LIKE ? OR service_description LIKE ? OR areas_served LIKE ?
            """,
            (f"%{query}%", f"%{query}%", f"%{query}%")
        ).fetchall()
        providers = [row_to_dict(provider) for provider in providers]
        logging.info(f"Search query '{query}' returned {len(providers)} providers, Session: %s", session)
    except sqlite3.Error as e:
        logging.error(f"Database error during search for query '{query}': {e}, Session: %s", session)
        flash("Error searching for providers. Please try again.", "error")
        providers = []
    finally:
        conn.close()
    
    return render_template("search_results.html", query=query, providers=providers, web_results=web_results)

@app.route("/get_unread_messages_count")
def get_unread_messages_count():
    if "user_id" not in session:
        logging.warning("Unauthorized access to unread messages count, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    # Validate the user_id from the query parameter matches the session user_id
    requested_user_id = request.args.get("user_id")
    if not requested_user_id or int(requested_user_id) != user_id:
        logging.warning(f"User ID mismatch in get_unread_messages_count: requested {requested_user_id}, session {user_id}, Session: %s", session)
        return jsonify({"error": "Invalid user ID"}), 400
    
    conn = get_db_connection()
    try:
        # Debug: Log all unread messages
        unread_messages = conn.execute(
            "SELECT id, sender_id, receiver_id, is_read FROM messages WHERE receiver_id = ? AND is_read = 0",
            (user_id,)
        ).fetchall()
        for msg in unread_messages:
            logging.debug(f"Unread message ID {msg['id']}: sender_id={msg['sender_id']}, receiver_id={msg['receiver_id']}, is_read={msg['is_read']}")
        
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0",
            (user_id,)
        ).fetchone()[0]
        logging.info(f"Unread messages count for user ID {user_id}: {count}, Session: %s", session)
        return jsonify({"count": count})
    except sqlite3.Error as e:
        logging.error(f"Database error fetching unread messages count for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@app.route("/get_all_conversations")
def get_all_conversations():
    if "user_id" not in session:
        logging.warning("Unauthorized access to get all conversations, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        conversations = []
        users = conn.execute("SELECT id, email FROM users WHERE id != ?", (user_id,)).fetchall()
        for user in users:
            other_user_id = user["id"]
            other_user_name = user["email"]
            unread_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE sender_id = ? AND receiver_id = ? AND is_read = 0",
                (other_user_id, user_id)
            ).fetchone()[0]
            conversations.append({
                "other_user_id": other_user_id,
                "other_user_name": other_user_name,
                "unread_count": unread_count
            })
        logging.info(f"Fetched {len(conversations)} conversations for user ID {user_id}, Session: %s", session)
        return jsonify({"conversations": conversations})
    except sqlite3.Error as e:
        logging.error(f"Database error fetching conversations for user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@app.route("/get_conversation")
def get_conversation():
    if "user_id" not in session:
        logging.warning("Unauthorized access to get conversation, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    receiver_id = request.args.get("receiver_id")
    if not receiver_id:
        logging.warning("No receiver_id provided for get conversation, Session: %s", session)
        return jsonify({"error": "Receiver ID required"}), 400
    
    # Ensure receiver_id is an integer
    try:
        receiver_id = int(receiver_id)
    except ValueError:
        logging.warning(f"Invalid receiver_id provided: {receiver_id}, Session: %s", session)
        return jsonify({"error": "Invalid receiver ID"}), 400
    
    conn = get_db_connection()
    try:
        # Debug: Check unread messages before update
        unread_before = conn.execute(
            "SELECT id, sender_id, receiver_id, is_read FROM messages WHERE receiver_id = ? AND is_read = 0",
            (user_id,)
        ).fetchall()
        logging.debug(f"Unread messages before update for user ID {user_id}: {[dict(row) for row in unread_before]}")

        # Mark all unread messages for the current user as read (regardless of sender_id)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE messages SET is_read = 1 WHERE receiver_id = ? AND is_read = 0",
            (user_id,)
        )
        updated_rows = cursor.rowcount
        conn.commit()
        logging.debug(f"Marked {updated_rows} messages as read for user ID {user_id}")

        # Debug: Check unread messages after update
        unread_after = conn.execute(
            "SELECT id, sender_id, receiver_id, is_read FROM messages WHERE receiver_id = ? AND is_read = 0",
            (user_id,)
        ).fetchall()
        logging.debug(f"Unread messages after update for user ID {user_id}: {[dict(row) for row in unread_after]}")

        # Fetch the conversation messages between the two users
        messages = conn.execute(
            """
            SELECT * FROM messages
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY timestamp ASC
            """,
            (user_id, receiver_id, receiver_id, user_id)
        ).fetchall()
        messages = [row_to_dict(msg) for msg in messages]
        
        # Debug logging for each message
        for msg in messages:
            logging.debug(f"Message ID {msg['id']}: sender_id={msg['sender_id']}, receiver_id={msg['receiver_id']}, message='{msg['message']}', is_read={msg['is_read']}")

        # Fetch other user's name
        other_user = row_to_dict(conn.execute("SELECT email FROM users WHERE id = ?", (receiver_id,)).fetchone())
        other_user_name = other_user["email"] if other_user else "Unknown User"
        
        # Debug: Verify total unread count after update
        total_unread = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0",
            (user_id,)
        ).fetchone()[0]
        logging.info(f"Total unread messages for user ID {user_id} after fetching conversation: {total_unread}, Session: %s", session)

        logging.info(f"Fetched {len(messages)} messages between user ID {user_id} and receiver ID {receiver_id}, Session: %s", session)
        return jsonify({
            "messages": messages,
            "other_user_name": other_user_name,
            "session_user_id": user_id
        })
    except sqlite3.Error as e:
        logging.error(f"Database error fetching conversation between user ID {user_id} and receiver ID {receiver_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@app.route("/send_message", methods=["POST"])
def send_message():
    if "user_id" not in session:
        logging.warning("Unauthorized access to send message, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    receiver_id = request.form.get("receiver_id")
    message_text = request.form.get("message", "").strip()
    media_file = request.files.get("media_file")
    
    if not receiver_id:
        logging.warning("No receiver_id provided for sending message, Session: %s", session)
        return jsonify({"error": "Receiver ID required"}), 400
    
    # Ensure receiver_id is an integer
    try:
        receiver_id = int(receiver_id)
    except ValueError:
        logging.warning(f"Invalid receiver_id provided: {receiver_id}, Session: %s", session)
        return jsonify({"error": "Invalid receiver ID"}), 400
    
    conn = get_db_connection()
    try:
        # Check if conversation exists, create if it doesn't
        conversation_id = conn.execute(
            "SELECT id FROM conversations WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)",
            (user_id, receiver_id, receiver_id, user_id)
        ).fetchone()
        if not conversation_id:
            conn.execute(
                "INSERT INTO conversations (user1_id, user2_id) VALUES (?, ?)",
                (min(int(user_id), int(receiver_id)), max(int(user_id), int(receiver_id)))
            )
            conn.commit()
            conversation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            conversation_id = conversation_id[0]

        media_path = None
        media_type = None
        if media_file and allowed_file(media_file.filename):
            filename = secure_filename(media_file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{filename}"
            media_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            media_file.save(media_path)
            ext = filename.rsplit('.', 1)[1].lower()
            if ext in {'png', 'jpg', 'jpeg'}:
                media_type = 'image'
            elif ext in {'mp4', 'mov'}:
                media_type = 'video'
            elif ext in {'wav', 'mp3'}:
                media_type = 'audio'
            logging.info(f"Media uploaded: {filename}, Type: {media_type}, Session: %s", session)

        if message_text or media_path:
            sanitized_message = escape(message_text) if message_text else ""
            # Debug logging before sending message
            logging.debug(f"Sending message: sender_id={user_id}, receiver_id={receiver_id}, message='{sanitized_message}', Session: %s", session)
            conn.execute(
                "INSERT INTO messages (sender_id, receiver_id, message, media_type, media_path, conversation_id, is_pinned, is_starred) VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
                (user_id, receiver_id, sanitized_message, media_type, media_path, conversation_id)
            )
            conn.commit()
            message_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            new_message = row_to_dict(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())
            unread_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0",
                (receiver_id,)
            ).fetchone()[0]
            logging.info(f"Message sent from user ID {user_id} to receiver ID {receiver_id}, Message ID: {message_id}, Session: %s", session)
            return jsonify({
                "success": True,
                "receiver_id": receiver_id,
                "message": new_message,
                "unread_count": unread_count,
                "conversation_id": conversation_id
            })
        else:
            logging.warning(f"No message or media to send from user ID {user_id} to receiver ID {receiver_id}, Session: %s", session)
            return jsonify({"error": "Message or media required"}), 400
    except sqlite3.Error as e:
        logging.error(f"Database error sending message from user ID {user_id} to receiver ID {receiver_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@app.route("/delete_message/<int:message_id>", methods=["POST"])
def delete_message(message_id):
    if "user_id" not in session:
        logging.warning("Unauthorized access to delete message, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        message = row_to_dict(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())
        if not message:
            logging.warning(f"Message ID {message_id} not found for deletion, Session: %s", session)
            return jsonify({"error": "Message not found"}), 404
        
        if message["sender_id"] != user_id and message["receiver_id"] != user_id:
            logging.warning(f"User ID {user_id} not authorized to delete message ID {message_id}, Session: %s", session)
            return jsonify({"error": "Unauthorized to delete this message"}), 403
        
        if message["media_path"] and os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], message["media_path"])):
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], message["media_path"]))
            logging.info(f"Media deleted for message ID {message_id}: {message['media_path']}, Session: %s", session)
        
        conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
        logging.info(f"Message ID {message_id} deleted by user ID {user_id}, Session: %s", session)
        return jsonify({"success": True, "receiver_id": message["receiver_id"]})
    except sqlite3.Error as e:
        logging.error(f"Database error deleting message ID {message_id} by user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@app.route("/react_message/<int:message_id>", methods=["POST"])
def react_message(message_id):
    if "user_id" not in session:
        logging.warning("Unauthorized access to react to message, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    reaction = request.form.get("reaction")
    if not reaction:
        logging.warning(f"No reaction provided for message ID {message_id}, Session: %s", session)
        return jsonify({"error": "Reaction required"}), 400
    
    conn = get_db_connection()
    try:
        message = row_to_dict(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())
        if not message:
            logging.warning(f"Message ID {message_id} not found for reaction, Session: %s", session)
            return jsonify({"error": "Message not found"}), 404
        
        if message["sender_id"] != user_id and message["receiver_id"] != user_id:
            logging.warning(f"User ID {user_id} not authorized to react to message ID {message_id}, Session: %s", session)
            return jsonify({"error": "Unauthorized to react to this message"}), 403
        
        conn.execute(
            "UPDATE messages SET reaction = ? WHERE id = ?",
            (reaction, message_id)
        )
        conn.commit()
        logging.info(f"Reaction '{reaction}' added to message ID {message_id} by user ID {user_id}, Session: %s", session)
        return jsonify({"success": True})
    except sqlite3.Error as e:
        logging.error(f"Database error adding reaction to message ID {message_id} by user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@app.route("/pin_message/<int:message_id>", methods=["POST"])
def pin_message(message_id):
    if "user_id" not in session:
        logging.warning("Unauthorized access to pin message, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        message = row_to_dict(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())
        if not message:
            logging.warning(f"Message ID {message_id} not found for pinning, Session: %s", session)
            return jsonify({"error": "Message not found"}), 404
        
        if message["sender_id"] != user_id and message["receiver_id"] != user_id:
            logging.warning(f"User ID {user_id} not authorized to pin message ID {message_id}, Session: %s", session)
            return jsonify({"error": "Unauthorized to pin this message"}), 403
        
        # Toggle pin state (0 or 1)
        current_pinned = message["is_pinned"]
        conn.execute(
            "UPDATE messages SET is_pinned = ? WHERE id = ?",
            (1 - current_pinned, message_id)  # Toggle: 0 -> 1, 1 -> 0
        )
        conn.commit()
        logging.info(f"Message ID {message_id} pin toggled to {1 - current_pinned} by user ID {user_id}, Session: %s", session)
        return jsonify({"success": True, "is_pinned": 1 - current_pinned})
    except sqlite3.Error as e:
        logging.error(f"Database error pinning message ID {message_id} by user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@app.route("/star_message/<int:message_id>", methods=["POST"])
def star_message(message_id):
    if "user_id" not in session:
        logging.warning("Unauthorized access to star message, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        message = row_to_dict(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())
        if not message:
            logging.warning(f"Message ID {message_id} not found for starring, Session: %s", session)
            return jsonify({"error": "Message not found"}), 404
        
        if message["sender_id"] != user_id and message["receiver_id"] != user_id:
            logging.warning(f"User ID {user_id} not authorized to star message ID {message_id}, Session: %s", session)
            return jsonify({"error": "Unauthorized to star this message"}), 403
        
        # Toggle star state (0 or 1)
        current_starred = message["is_starred"]
        conn.execute(
            "UPDATE messages SET is_starred = ? WHERE id = ?",
            (1 - current_starred, message_id)  # Toggle: 0 -> 1, 1 -> 0
        )
        conn.commit()
        logging.info(f"Message ID {message_id} star toggled to {1 - current_starred} by user ID {user_id}, Session: %s", session)
        return jsonify({"success": True, "is_starred": 1 - current_starred})
    except sqlite3.Error as e:
        logging.error(f"Database error starring message ID {message_id} by user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@app.route("/inbox")
def inbox():
    if "user_id" not in session:
        logging.warning("Unauthorized access to inbox, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        # Step 1: Ensure all messages have a conversation_id
        messages_without_conversation = conn.execute(
            "SELECT * FROM messages WHERE conversation_id IS NULL"
        ).fetchall()
        
        for msg in messages_without_conversation:
            sender_id = msg["sender_id"]
            receiver_id = msg["receiver_id"]
            conversation = conn.execute(
                """
                SELECT id FROM conversations 
                WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)
                """,
                (sender_id, receiver_id, receiver_id, sender_id)
            ).fetchone()
            
            if not conversation:
                conn.execute(
                    "INSERT INTO conversations (user1_id, user2_id) VALUES (?, ?)",
                    (min(sender_id, receiver_id), max(sender_id, receiver_id))
                )
                conn.commit()
                conversation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                conversation_id = conversation[0]
            
            conn.execute(
                "UPDATE messages SET conversation_id = ? WHERE id = ?",
                (conversation_id, msg["id"])
            )
        conn.commit()

        # Step 2: Fetch conversations with messages, linking to providers
        conversations = conn.execute(
            """
            SELECT DISTINCT c.id AS conversation_id, c.user1_id, c.user2_id,
                   u1.email AS user1_name, u2.email AS user2_name,
                   p.id AS provider_id, p.name AS provider_name,
                   (SELECT COUNT(*) FROM messages m 
                    WHERE m.receiver_id = ? AND m.is_read = 0 
                    AND m.conversation_id = c.id) AS unread_count
            FROM conversations c
            JOIN users u1 ON c.user1_id = u1.id
            JOIN users u2 ON c.user2_id = u2.id
            LEFT JOIN providers p ON (c.user1_id = p.user_id AND c.user2_id = ?) 
                               OR (c.user2_id = p.user_id AND c.user1_id = ?)
            JOIN messages m ON m.conversation_id = c.id
            WHERE c.user1_id = ? OR c.user2_id = ?
            """,
            (user_id, user_id, user_id, user_id, user_id)
        ).fetchall()

        # Step 3: Format conversations and determine the other user's info
        formatted_conversations = []
        for conv in conversations:
            conv_dict = row_to_dict(conv)
            other_user_id = conv_dict["user2_id"] if conv_dict["user1_id"] == user_id else conv_dict["user1_id"]
            other_user_name = conv_dict["user2_name"] if conv_dict["user1_id"] == user_id else conv_dict["user1_name"]
            provider_id = conv_dict["provider_id"]
            provider_name = conv_dict["provider_name"] if provider_id else "Unknown Provider"

            formatted_conversations.append({
                "conversation_id": conv_dict["conversation_id"],
                "other_user_id": other_user_id,
                "other_user_name": other_user_name,
                "provider_id": provider_id,
                "provider_name": provider_name,
                "unread_count": conv_dict["unread_count"]
            })

        # Step 4: Calculate total unread count
        total_unread = sum(conv["unread_count"] for conv in formatted_conversations)

        logging.info(f"Inbox fetched for user ID {user_id}: {len(formatted_conversations)} conversations, Total unread: {total_unread}, Session: %s", session)
        return jsonify({
            "conversations": formatted_conversations,
            "unread_count": total_unread,
            "session_user_id": user_id
        })
    except sqlite3.Error as e:
        logging.error(f"Database error fetching inbox for user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        conn.close()

@app.route("/get_unread_count")
def get_unread_count():
    if "user_id" not in session:
        logging.warning("Unauthorized access to unread count, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0",
            (user_id,)
        ).fetchone()[0]
        logging.info(f"Unread count fetched for user ID {user_id}: {count}, Session: %s", session)
        return jsonify({"count": count})
    except sqlite3.Error as e:
        logging.error(f"Database error fetching unread count for user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()


@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)


@app.route('/sitemap.xml')
def sitemap():
    return send_file('sitemap.xml')

# Existing homepage route (probably already there)
@app.route('/')
def home():
    return render_template('home.html')  # Or whatever your homepage template is

# New route for login
@app.route('/login')
def login():
    return render_template('login.html')

# Add these for other key pages (repeat the pattern)
@app.route('/signup')
def signup():
    return render_template('signup.html')

@app.route('/provider-dashboard')
def provider_dashboard():
    return render_template('provider_dashboard.html')

@app.route('/customer-dashboard')
def customer_dashboard():
    return render_template('customer_dashboard.html')

@app.route('/provider-profile')
def provider_profile():
    return render_template('provider_profile.html')

@app.route('/inbox')
def inbox():
    return render_template('inbox.html')

# If you want to support .html extensions (optional, for direct access)
@app.route('/login.html')
def login_html():
    return render_template('login.html')


if __name__ == "__main__":
    try:
        app.run(debug=True, host="0.0.0.0", port=5000)
    except Exception as e:
        logging.critical(f"Application startup failed: {e}")
        raise