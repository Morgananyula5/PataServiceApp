from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import psycopg2
from psycopg2.extras import DictCursor
import json
import re
from datetime import datetime, timedelta, timezone
import logging
import time
import random
from html import escape
import socket
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from time import sleep
import threading
from queue import Queue
from flask import send_file
from flask import send_from_directory
from dotenv import load_dotenv
from flask import request, jsonify
import requests

load_dotenv()

username = os.getenv("AT_USERNAME")
api_key = os.getenv("AT_API_KEY")

otp_store = {}

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session'
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True

Session(app)

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'mp4', 'mov', 'wav', 'mp3', 'webm'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, mode=0o755)

if not os.path.exists(app.config['SESSION_FILE_DIR']):
    os.makedirs(app.config['SESSION_FILE_DIR'], mode=0o755)

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS", "findserviceapp@gmail.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "dixqtgsfqnsscmgv")
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    try:
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is not set.")
        # Append sslmode=require if not present
        if 'sslmode' not in database_url:
            database_url += "?sslmode=require"
        conn = psycopg2.connect(database_url, cursor_factory=DictCursor)
        logging.info(f"Connected to PostgreSQL database at {conn.dsn}")
        return conn
    except (psycopg2.Error, ValueError) as e:
        logging.error(f"Database connection failed: {str(e)}")
        raise Exception(f"Unable to connect to the database: {str(e)}")

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)

email_result_queue = Queue()

def send_verification_email(email, verification_code):
    try:
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            logging.error(f"Invalid email format: {email}")
            return False

        msg = MIMEMultipart('alternative')
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = email
        msg['Subject'] = 'Password Reset Verification Code'

        plain_body = f"""
You requested to reset your password.

Verification Code: {verification_code}

This code will expire in 15 minutes.
If you did not request this, ignore this email.
"""
        html_body = f"""
<html>
<body>
    <h2>Password Reset Request</h2>
    <p>Use the code below to reset your password:</p>
    <h3>{verification_code}</h3>
    <p>This code expires in 15 minutes.</p>
</body>
</html>
"""

        msg.attach(MIMEText(plain_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, email, msg.as_string())

        logging.info(f"Password reset email sent to {email}")
        return True

    except Exception as e:
        logging.error(f"Password reset email FAILED for {email}: {str(e)}")
        return False


def send_email(recipient, subject, plain_body, html_body):
    try:
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, recipient):
            logging.error(f"Invalid email format: {recipient}")
            return False

        msg = MIMEMultipart('alternative')
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = recipient
        msg['Subject'] = subject

        msg.attach(MIMEText(plain_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, recipient, msg.as_string())

        logging.info(f"Email sent to {recipient}: {subject}")
        return True

    except Exception as e:
        logging.error(f"Email FAILED for {recipient}: {str(e)}")
        return False



def get_admin_user_id():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        admin = cursor.fetchone()
        return admin['id'] if admin else None
    finally:
        cursor.close()
        conn.close()

def send_booking_request_to_provider(provider_email, customer_name, customer_email, customer_phone, booking_id, service_date):
    subject = "New Booking Request"
    service_date_str = service_date if service_date else "Not specified"
    plain_body = f"""
Dear Provider,

A new booking request has been submitted by {customer_name}.

Booking ID: {booking_id}
Service Date: {service_date_str}
Customer Email: {customer_email}
Customer Phone: {customer_phone}

Please log in to your dashboard to respond to this booking.

Best regards,
Your Service Platform

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>New Booking Request</h2>
    <p>Dear Provider,</p>
    <p>A new booking request has been submitted.</p>
    <p><strong>Name:</strong> {customer_name}</p>
    <p><strong>Booking ID:</strong> {booking_id}</p>
    <p><strong>Service Date:</strong> {service_date_str}</p>
    <p><strong>Customer Email:</strong> {customer_email}</p>
    <p><strong>Customer Phone:</strong> {customer_phone}</p>
    <p>Please log in to your dashboard to respond to this booking.</p>
    <p>Best regards,<br>Your Service Platform</p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(provider_email, subject, plain_body, html_body)

def send_booking_request_confirmation_to_customer(customer_email, provider_name, booking_id, service_date):
    subject = "Booking Request Sent Successfully"
    service_date_str = service_date if service_date else "Not specified"
    plain_body = f"""
Dear Customer,

Your booking request to {provider_name} has been sent successfully.

Booking ID: {booking_id}
Service Date: {service_date_str}

You will be notified once the provider responds.

Best regards,
Your Service Platform

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>Booking Request Sent Successfully</h2>
    <p>Dear Customer,</p>
    <p>Your booking request has been sent successfully.</p>
    <p><strong>Name:</strong> {provider_name}</p>
    <p><strong>Booking ID:</strong> {booking_id}</p>
    <p><strong>Service Date:</strong> {service_date_str}</p>
    <p>You will be notified once the provider responds.</p>
    <p>Best regards,<br>Your Service Platform</p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(customer_email, subject, plain_body, html_body)

def send_booking_confirmed_to_customer(customer_email, provider_name, provider_email, provider_phone, booking_id, service_date):
    subject = "Booking Confirmed"
    service_date_str = service_date if service_date else "Not specified"
    plain_body = f"""
Dear Customer,

Your booking with {provider_name} has been confirmed.

Booking ID: {booking_id}
Service Date: {service_date_str}
Provider Email: {provider_email}
Provider Phone: {provider_phone}

Please contact the provider if you have any questions.

Best regards,
Your Service Platform

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>Booking Confirmed</h2>
    <p>Dear Customer,</p>
    <p>Your booking has been confirmed.</p>
    <p><strong>Name:</strong> {provider_name}</p>
    <p><strong>Booking ID:</strong> {booking_id}</p>
    <p><strong>Service Date:</strong> {service_date_str}</p>
    <p><strong>Provider Email:</strong> {provider_email}</p>
    <p><strong>Provider Phone:</strong> {provider_phone}</p>
    <p>Please contact the provider if you have any questions.</p>
    <p>Best regards,<br>Your Service Platform</p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(customer_email, subject, plain_body, html_body)

def send_booking_confirmed_to_provider(provider_email, customer_name, booking_id, service_date):
    subject = "Booking Confirmed Successfully"
    service_date_str = service_date if service_date else "Not specified"
    plain_body = f"""
Dear Provider,

You have successfully confirmed the booking from {customer_name}.

Booking ID: {booking_id}
Service Date: {service_date_str}

Best regards,
Your Service Platform

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>Booking Confirmed Successfully</h2>
    <p>Dear Provider,</p>
    <p>You have successfully confirmed the booking.</p>
    <p><strong>Name:</strong> {customer_name}</p>
    <p><strong>Booking ID:</strong> {booking_id}</p>
    <p><strong>Service Date:</strong> {service_date_str}</p>
    <p>Best regards,<br>Your Service Platform</p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(provider_email, subject, plain_body, html_body)

def send_booking_rejected_to_customer(customer_email, provider_name, provider_email, provider_phone, booking_id):
    subject = "Booking Rejected"
    plain_body = f"""
Dear Customer,

Your booking with {provider_name} has been rejected.

Booking ID: {booking_id}
Provider Email: {provider_email}
Provider Phone: {provider_phone}

Please contact the provider for more details or try booking another provider.

Best regards,
Your Service Platform

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>Booking Rejected</h2>
    <p>Dear Customer,</p>
    <p>Your booking has been rejected.</p>
    <p><strong>Name:</strong> {provider_name}</p>
    <p><strong>Booking ID:</strong> {booking_id}</p>
    <p><strong>Provider Email:</strong> {provider_email}</p>
    <p><strong>Provider Phone:</strong> {provider_phone}</p>
    <p>Please contact the provider for more details or try booking another provider.</p>
    <p>Best regards,<br>Your Service Platform</p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(customer_email, subject, plain_body, html_body)

def send_booking_rejected_to_provider(provider_email, customer_name, booking_id):
    subject = "Booking Rejected Successfully"
    plain_body = f"""
Dear Provider,

You have successfully rejected the booking from {customer_name}.

Booking ID: {booking_id}

Best regards,
Your Service Platform

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>Booking Rejected Successfully</h2>
    <p>Dear Provider,</p>
    <p>You have successfully rejected the booking.</p>
    <p><strong>Name:</strong> {customer_name}</p>
    <p><strong>Booking ID:</strong> {booking_id}</p>
    <p>Best regards,<br>Your Service Platform</p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(provider_email, subject, plain_body, html_body)

def send_booking_rescheduled_to_customer(customer_email, provider_name, provider_email, provider_phone, booking_id, original_date, new_date):
    subject = "Booking Rescheduled"
    original_date_str = original_date if original_date else "Not specified"
    new_date_str = new_date if new_date else "Not specified"
    plain_body = f"""
Dear Customer,

Your booking with {provider_name} has been rescheduled.

Booking ID: {booking_id}
Original Service Date: {original_date_str}
New Service Date: {new_date_str}
Provider Email: {provider_email}
Provider Phone: {provider_phone}

Please contact the provider if you have any questions.

Best regards,
Your Service Platform

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>Booking Rescheduled</h2>
    <p>Dear Customer,</p>
    <p>Your booking has been rescheduled.</p>
    <p><strong>Name:</strong> {provider_name}</p>
    <p><strong>Booking ID:</strong> {booking_id}</p>
    <p><strong>Original Service Date:</strong> {original_date_str}</p>
    <p><strong>New Service Date:</strong> {new_date_str}</p>
    <p><strong>Provider Email:</strong> {provider_email}</p>
    <p><strong>Provider Phone:</strong> {provider_phone}</p>
    <p>Please contact the provider if you have any questions.</p>
    <p>Best regards,<br>Your Service Platform</p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(customer_email, subject, plain_body, html_body)

def send_booking_rescheduled_to_provider(provider_email, customer_name, booking_id, original_date, new_date):
    subject = "Booking Rescheduled Successfully"
    original_date_str = original_date if original_date else "Not specified"
    new_date_str = new_date if new_date else "Not specified"
    plain_body = f"""
Dear Provider,

You have successfully rescheduled the booking from {customer_name}.

Booking ID: {booking_id}
Original Service Date: {original_date_str}
New Service Date: {new_date_str}

Best regards,
Your Service Platform

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>Booking Rescheduled Successfully</h2>
    <p>Dear Provider,</p>
    <p>You have successfully rescheduled the booking.</p>
    <p><strong>Name:</strong> {customer_name}</p>
    <p><strong>Booking ID:</strong> {booking_id}</p>
    <p><strong>Original Service Date:</strong> {original_date_str}</p>
    <p><strong>New Service Date:</strong> {new_date_str}</p>
    <p>Best regards,<br>Your Service Platform</p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(provider_email, subject, plain_body, html_body)

def cleanup_expired_codes(conn):
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM verification_codes WHERE expires_at < %s",
            (datetime.now(),)
        )
        conn.commit()
        logging.info("Expired verification codes cleaned up")
    except psycopg2.Error as e:
        logging.error(f"Error cleaning up expired verification codes: {e}")

def is_rate_limited(email):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT created_at FROM verification_codes WHERE email = %s ORDER BY created_at DESC LIMIT 1",
            (email,)
        )
        last_sent = row_to_dict(cursor.fetchone())
        if last_sent:
            last_sent_time = last_sent["created_at"]  # Already a datetime object
            if (datetime.now() - last_sent_time).total_seconds() < 120:
                logging.warning(f"Rate limit hit for resending verification code to {email}, Session: {session}")
                return True
        return False
    except psycopg2.Error as e:
        logging.error(f"Error checking rate limit for {email}: {e}, Session: {session}")
        return False
    finally:
        cursor.close()
        conn.close()

def send_status_update_message(provider_id, customer_email, booking_id, status, original_date, new_date=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
       
        # Fetch provider's user_id
        cursor.execute("SELECT user_id FROM providers WHERE id = %s", (provider_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.error(f"Provider ID {provider_id} not found for notification")
            return {"success": False, "error": "Provider not found"}
        provider_user_id = provider["user_id"]
       
        # Fetch customer's user_id with email or phone
        cursor.execute("SELECT id FROM users WHERE email = %s OR phone = %s", (customer_email, customer_email))
        customer = row_to_dict(cursor.fetchone())
        if not customer:
            logging.error(f"Customer email/phone {customer_email} not found for notification")
            return {"success": False, "error": "Customer not found"}
        customer_user_id = customer["id"]
       
        # Find or create conversation atomically
        min_id = min(provider_user_id, customer_user_id)
        max_id = max(provider_user_id, customer_user_id)
        cursor.execute("""
            SELECT id FROM conversations
            WHERE user1_id = %s AND user2_id = %s
            FOR UPDATE
        """, (min_id, max_id))
        conversation = cursor.fetchone()
        if not conversation:
            cursor.execute("""
                INSERT INTO conversations (user1_id, user2_id)
                VALUES (%s, %s)
                ON CONFLICT (user1_id, user2_id) DO NOTHING
                RETURNING id
            """, (min_id, max_id))
            row = cursor.fetchone()
            if row:
                conversation_id = row['id']
            else:
                # Fallback SELECT in case of conflict
                cursor.execute("""
                    SELECT id FROM conversations
                    WHERE user1_id = %s AND user2_id = %s
                """, (min_id, max_id))
                conversation_id = cursor.fetchone()['id']
            logging.info(f"Created or retrieved conversation ID {conversation_id} for provider_user_id {provider_user_id} and customer_user_id {customer_user_id}")
        else:
            conversation_id = conversation['id']
       
        # Construct message based on status
        if status == "Pending":
            message = f"Your booking (ID: {booking_id}) with provider is pending for {original_date}."
        elif status == "Confirmed":
            message = f"Your booking (ID: {booking_id}) has been confirmed for {original_date}."
        elif status == "Rejected":
            message = f"Your booking (ID: {booking_id}) has been rejected."
        elif status == "Rescheduled":
            message = f"Your booking (ID: {booking_id}) has been rescheduled from {original_date} to {new_date}."
        else:
            message = f"Booking (ID: {booking_id}) status updated to {status}."
       
        # Insert message with conversation_id
        cursor.execute(
            """
            INSERT INTO messages (sender_id, receiver_id, message, timestamp, is_read, conversation_id)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (provider_user_id, customer_user_id, message, datetime.now(), False, conversation_id)
        )
        message_id = cursor.fetchone()['id']
        conn.commit()
       
        logging.info(f"Status update message sent: Booking ID {booking_id}, Status: {status}, Message ID: {message_id}, Conversation ID: {conversation_id}")
        return {"success": True, "message_id": message_id, "conversation_id": conversation_id}
   
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        logging.error(f"Database error sending status update for booking ID {booking_id}: {str(e)}")
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            cursor.close()
            conn.close()

def update_messages_schema(conn):
    cursor = conn.cursor()
    try:
        # Add conversation_id column if missing
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'messages' AND column_name = 'conversation_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE messages ADD COLUMN conversation_id INTEGER")
            logging.info("Added conversation_id column to messages table")
       
        # Add reaction column if missing
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'messages' AND column_name = 'reaction'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE messages ADD COLUMN reaction VARCHAR(50) DEFAULT NULL")
            logging.info("Added reaction column to messages table")
       
        # Update existing messages with NULL conversation_id
        cursor.execute("""
            UPDATE messages m
            SET conversation_id = c.id
            FROM conversations c
            WHERE m.conversation_id IS NULL
            AND (
                (m.sender_id = c.user1_id AND m.receiver_id = c.user2_id)
                OR (m.sender_id = c.user2_id AND m.receiver_id = c.user1_id)
            )
        """)
        updated_rows = cursor.rowcount
        logging.info(f"Updated {updated_rows} messages with conversation_id")

        # Handle messages still without conversation_id (create new conversations)
        cursor.execute("""
            INSERT INTO conversations (user1_id, user2_id)
            SELECT DISTINCT LEAST(m.sender_id, m.receiver_id), GREATEST(m.sender_id, m.receiver_id)
            FROM messages m
            LEFT JOIN conversations c ON
                (m.sender_id = c.user1_id AND m.receiver_id = c.user2_id) OR
                (m.sender_id = c.user2_id AND m.receiver_id = c.user1_id)
            WHERE m.conversation_id IS NULL AND c.id IS NULL
            RETURNING id, user1_id, user2_id
        """)
        new_conversations = cursor.fetchall()
        for conv in new_conversations:
            cursor.execute("""
                UPDATE messages
                SET conversation_id = %s
                WHERE conversation_id IS NULL
                AND ((sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s))
            """, (conv['id'], conv['user1_id'], conv['user2_id'], conv['user2_id'], conv['user1_id']))
        logging.info(f"Created {len(new_conversations)} new conversations and assigned to messages")

        conn.commit()
    except psycopg2.Error as e:
        logging.error(f"Error updating messages table schema: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()

def check_and_fix_bookings_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'bookings' AND column_name = 'status'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE bookings ADD COLUMN status TEXT DEFAULT 'Pending'")
            logging.info("Added status column to bookings table")
       
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'bookings' AND column_name = 'provider_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE bookings ADD COLUMN provider_id INTEGER")
            logging.info("Added provider_id column to bookings table")
       
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'bookings' AND column_name = 'customer_email'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE bookings ADD COLUMN customer_email TEXT")
            logging.info("Added customer_email column to bookings table")
       
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'bookings' AND column_name = 'updated_at'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE bookings ADD COLUMN updated_at TIMESTAMP")
            cursor.execute("UPDATE bookings SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
            logging.info("Added and populated updated_at column in bookings table")
       
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'bookings' AND column_name = 'rescheduled_date'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE bookings ADD COLUMN rescheduled_date TIMESTAMP")
            logging.info("Added rescheduled_date column to bookings table")

        # === NEW: rejected_reason column (only for reject flow) ===
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'bookings' AND column_name = 'rejected_reason'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE bookings ADD COLUMN rejected_reason TEXT")
            logging.info("Added rejected_reason column to bookings table")
       
        conn.commit()
    except psycopg2.Error as e:
        logging.error(f"Error checking or fixing bookings table schema: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()

def update_users_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'phone'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(255)")
            logging.info("Added phone column to users table")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'last_login'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN last_login TIMESTAMP")
            logging.info("Added last_login column to users table")
       
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'status'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")
            logging.info("Added status column to users table")
       
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'is_verified'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT FALSE")
            logging.info("Added is_verified column to users table")
       
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'created_at'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP")
            cursor.execute("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
            logging.info("Added created_at column to users table and set for existing users")
       
        # Add county and sub_county columns if missing (new for customer location)
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'county'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN county VARCHAR(255)")
            logging.info("Added county column to users table")
       
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'sub_county'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN sub_county VARCHAR(255)")
            logging.info("Added sub_county column to users table")
       
        conn.commit()
    except psycopg2.Error as e:
        logging.error(f"Error updating users table schema: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()

def create_admin_user(conn):
    new_admin_email = 'kemuntoaristotle@gmail.com'
    new_admin_password = 'Muhangani2001$'
    hashed_password = generate_password_hash(new_admin_password, method="pbkdf2:sha256")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE role = 'admin'")
        existing_admin = row_to_dict(cursor.fetchone())
        if existing_admin:
            cursor.execute(
                "UPDATE users SET email = %s, password = %s WHERE id = %s",
                (new_admin_email, hashed_password, existing_admin['id'])
            )
            conn.commit()
            logging.info(f"Admin user email updated to {new_admin_email}")
        else:
            cursor.execute(
                "INSERT INTO users (email, password, role, status, is_verified, created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (new_admin_email, hashed_password, 'admin', 'active', True, datetime.now())
            )
            conn.commit()
            logging.info(f"Admin user {new_admin_email} created successfully")
    except psycopg2.Error as e:
        logging.error(f"Error updating/creating admin user: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()

def update_providers_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'providers' AND column_name = 'service_category'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE providers ADD COLUMN service_category TEXT")
            logging.info("Added service_category column to providers table")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'providers' AND column_name = 'local_area'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE providers ADD COLUMN local_area VARCHAR(255) DEFAULT ''")
            logging.info("Added local_area column to providers table")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'providers' AND column_name = 'last_viewed_ratings_count'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE providers ADD COLUMN last_viewed_ratings_count INTEGER DEFAULT 0")
            logging.info("Added last_viewed_ratings_count column to providers table")
        # NEW: real-time location columns
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'providers' AND column_name = 'latitude'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE providers ADD COLUMN latitude DOUBLE PRECISION DEFAULT NULL")
            logging.info("Added latitude column to providers table")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'providers' AND column_name = 'longitude'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE providers ADD COLUMN longitude DOUBLE PRECISION DEFAULT NULL")
            logging.info("Added longitude column to providers table")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'providers' AND column_name = 'location_updated_at'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE providers ADD COLUMN location_updated_at TIMESTAMP DEFAULT NULL")
            logging.info("Added location_updated_at column to providers table")
        conn.commit()
    except psycopg2.Error as e:
        logging.error(f"Error updating providers table schema: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()

def update_feedback_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'feedback' AND column_name = 'is_viewed'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE feedback ADD COLUMN is_viewed BOOLEAN DEFAULT FALSE")
            logging.info("Added is_viewed column to feedback table")
       
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'feedback' AND column_name = 'user_type'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE feedback ADD COLUMN user_type TEXT DEFAULT 'customer'")
            logging.info("Added user_type column to feedback table")
       
        conn.commit()
    except psycopg2.Error as e:
        logging.error(f"Error updating feedback table schema: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()

def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        update_messages_schema(conn)  # Ensure this runs first
        check_and_fix_bookings_schema(conn)
        update_users_schema(conn)
        update_providers_schema(conn)
        update_feedback_schema(conn)
        create_admin_user(conn)
        # Add sender_id column if it doesn't exist
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'notifications' AND column_name = 'sender_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE notifications ADD COLUMN sender_id INTEGER")
        # Add activity_status column to providers if it doesn't exist
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'providers' AND column_name = 'activity_status'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE providers ADD COLUMN activity_status TEXT DEFAULT 'Active'")
            logging.info("Added activity_status column to providers table")
       
        # Add unique constraint to conversations if missing
        cursor.execute("""
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_name = 'conversations' AND constraint_type = 'UNIQUE' AND constraint_name = 'unique_conversation'
        """)
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE conversations ADD CONSTRAINT unique_conversation UNIQUE (user1_id, user2_id)")
            logging.info("Added unique constraint to conversations table")
       
        conn.commit()
        logging.info("Database schema verified or updated successfully")
    except psycopg2.Error as e:
        logging.error(f"Database error creating/updating tables: {e}")
        raise
    finally:
        cursor.close()
        conn.close()




def create_portfolios_table(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id SERIAL PRIMARY KEY,
                provider_id INTEGER NOT NULL UNIQUE,
                skills TEXT NOT NULL,
                certifications TEXT,
                experience TEXT NOT NULL,
                work_samples TEXT,
                github_links TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (provider_id) REFERENCES providers (id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_portfolios_provider_id ON portfolios(provider_id);")
        conn.commit()
        logging.info("Portfolios table created or verified successfully")
    except psycopg2.Error as e:
        logging.error(f"Error creating portfolios table: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()

def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        update_messages_schema(conn)  # Ensure this runs first
        check_and_fix_bookings_schema(conn)
        update_users_schema(conn)
        update_providers_schema(conn)
        update_feedback_schema(conn)
        create_portfolios_table(conn)  # Added: Ensure portfolios table exists
        create_admin_user(conn)
        # Add sender_id column if it doesn't exist
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'notifications' AND column_name = 'sender_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE notifications ADD COLUMN sender_id INTEGER")
        # Add activity_status column to providers if it doesn't exist
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'providers' AND column_name = 'activity_status'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE providers ADD COLUMN activity_status TEXT DEFAULT 'Active'")
            logging.info("Added activity_status column to providers table")
       
        # Add unique constraint to conversations if missing
        cursor.execute("""
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_name = 'conversations' AND constraint_type = 'UNIQUE' AND constraint_name = 'unique_conversation'
        """)
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE conversations ADD CONSTRAINT unique_conversation UNIQUE (user1_id, user2_id)")
            logging.info("Added unique constraint to conversations table")
       
        conn.commit()
        logging.info("Database schema verified or updated successfully")
    except psycopg2.Error as e:
        logging.error(f"Database error creating/updating tables: {e}")
        raise
    finally:
        cursor.close()
        conn.close()



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


def time_ago(dt):
    if not dt:
        return "Never"
    now = datetime.now()
    delta = now - dt
    if delta.days > 365:
        return f"{delta.days // 365} years ago"
    elif delta.days > 30:
        return f"{delta.days // 30} months ago"
    elif delta.days > 0:
        return f"{delta.days} days ago"
    elif delta.seconds > 3600:
        return f"{delta.seconds // 3600} hours ago"
    elif delta.seconds > 60:
        return f"{delta.seconds // 60} minutes ago"
    else:
        return "Just now"


def send_chat_notification_email(recipient_email, sender_name, message_preview):
    subject = f"New Message from {sender_name}"
    plain_body = f"""
Dear User,

You have a new message from {sender_name}:

"{message_preview}"

Log in using this link to view: www.findservice.live

Best regards,
Your Service Platform

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>New Message</h2>
    <p>Dear User,</p>
    <p>You have a new message from <strong>{sender_name}</strong>:</p>
    <blockquote>"{escape(message_preview)}"</blockquote>
    <p>Log in using this link to view: <a href="https://www.findservice.live">www.findservice.live</a></p>
    <p>Best regards,<br>Your Service Platform</p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(recipient_email, subject, plain_body, html_body)


def send_welcome_email(email, county, sub_county):
    subject = "Welcome to Our Service Platform!"
    plain_body = f"""
Dear User,

Thank you for signing up! We're excited to have you on board and help you connect with reliable service providers.

How the platform works:
1. Log in to your dashboard at [your platform URL].
2. To access service providers in your location ({county}, {sub_county}), check the "Local Providers" section on your dashboard—it shows nearby options based on your area.
3. To browse providers in all other locations available, use the "All Providers" section to explore nationwide services.
4. Select a provider, click "Book Now," fill in your details (name, phone, date, etc.), and submit.
5. You'll receive a confirmation email and can chat with the provider for updates.

If you have questions or need assistance, reply to this email or contact support.

Best regards,
The Service Platform Team

If you don't see this email in your inbox, please check your spam or junk folder.
"""
    html_body = f"""
<html>
<body>
    <h2>Welcome to Our Service Platform!</h2>
    <p>Dear User,</p>
    <p>Thank you for signing up! We're excited to help you find and book top service providers.</p>
    <h3>How the Platform Works:</h3>
    <ol>
        <li><strong>Log In:</strong> Access your dashboard at <a href="{{ url_for('customer_dashboard', _external=True) }}">your dashboard</a>.</li>
        <li><strong>Local Providers:</strong> View services in your area ({county}, {sub_county}) in the "Local Providers" section—tailored to your location for convenience.</li>
        <li><strong>All Locations:</strong> Explore providers across all available areas in the "All Providers" section to find experts anywhere.</li>
        <li><strong>Book a Service:</strong> Select a provider, click "Book Now," enter your details (name, phone, preferred date), and submit your request.</li>
        <li><strong>Track & Communicate:</strong> Get email confirmations and use in-app chat for real-time updates with your provider.</li>
    </ol>
    <p>If you need help or have questions, reply to this email or contact our support team.</p>
    <p>Best regards,<br><strong>The Service Platform Team</strong></p>
    <p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p>
</body>
</html>
"""
    send_email(email, subject, plain_body, html_body)

@app.before_request
def check_authentication():
    if "user_id" in session:
        session.modified = True
   
    # Skip authentication checks for these endpoints
    if request.endpoint in [
        'static',
        'login',
        'signup',
        'verify_email',
        'resend_verification',
        'logout',
        'home',
        'admin_console',
        'send_otp',              # ✅ ADD THIS
        'verify_phone_page',     # ✅ ADD THIS
        'verify_otp'             # ✅ ADD THIS
    ]:
        return

   
    # Define API request prefixes (added '/upload_portfolio' to treat it as API for JSON error responses)
    is_api_request = request.path.startswith('/book_provider') or \
                     request.path.startswith('/get_') or \
                     request.path.startswith('/confirm_') or \
                     request.path.startswith('/reject_') or \
                     request.path.startswith('/reschedule_') or \
                     request.path.startswith('/send_') or \
                     request.path.startswith('/delete_') or \
                     request.path.startswith('/react_') or \
                     request.path.startswith('/remove_') or \
                     request.path.startswith('/pin_') or \
                     request.path.startswith('/star_') or \
                     request.path.startswith('/inbox') or \
                     request.path.startswith('/admin_remove_') or \
                     request.path.startswith('/admin_ban_') or \
                     request.path.startswith('/admin_unban_') or \
                     request.path.startswith('/admin_return_') or \
                     request.path.startswith('/admin_message_') or \
                     request.path.startswith('/api/admin/') or \
                     request.path.startswith('/submit_rating') or \
                     request.path.startswith('/upload_portfolio')
   
    # If user is not logged in and it’s an API request, return JSON error
    if "user_id" not in session and is_api_request:
        logging.warning("Unauthorized API request to %s, Session: %s", request.path, session)
        return jsonify({"error": "Unauthorized, please log in."}), 401

    # If user is logged in, check verification status
    if "user_id" in session and request.endpoint not in ['verify_email', 'resend_verification', 'logout']:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_verified FROM users WHERE id = %s", (session["user_id"],))
            user = row_to_dict(cursor.fetchone())
            if not user or not user["is_verified"]:
                # For API requests, return JSON error instead of redirecting
                if is_api_request:
                    logging.warning(f"Unverified user ID {session['user_id']} attempted API access to {request.path}, Session: {session}")
                    return jsonify({"error": "Email not verified. Please verify your email address."}), 403
                # For non-API requests, redirect to verification page
                else:
                    logging.warning(f"Unverified user ID {session['user_id']} attempted to access {request.path}, Session: {session}")
                    flash("Please verify your email address to access this page.", "error")
                    return redirect(url_for("verify_email"))
        finally:
            cursor.close()
            conn.close()

@app.errorhandler(500)
def internal_server_error(e):
    api_prefixes = (
        '/book_provider', '/get_', '/confirm_', '/reject_', '/reschedule_',
        '/send_', '/delete_', '/react_', '/remove_', '/pin_', '/star_',
        '/inbox', '/admin_remove_', '/admin_ban_', '/admin_unban_',
        '/admin_return_', '/admin_message_', '/api/admin/', '/submit_rating'
    )
    if any(request.path.startswith(prefix) for prefix in api_prefixes):
        logging.error(f"Internal server error on API route {request.path}: {str(e)}, Session: %s", session)
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    return render_template("500.html"), 500


def normalize_ke_phone(phone):
    phone = phone.strip().replace(" ", "")

    if phone.startswith("+254"):
        return phone
    if phone.startswith("254"):
        return "+" + phone
    if phone.startswith("07") or phone.startswith("01"):
        return "+254" + phone[1:]

    return phone


def generate_otp():
    return str(random.randint(100000, 999999))


def save_otp(phone, otp):
    otp_store[phone] = {
        "otp": otp,
        "expires": time.time() + 300
    }

def check_otp(phone, user_otp):
    record = otp_store.get(phone)

    if not record:
        return False, "No OTP found"

    if time.time() > record["expires"]:
        return False, "OTP expired"

    if record["otp"] != user_otp:
        return False, "Invalid OTP"

    return True, "Verified"

def send_sms(phone, message):
    phone = normalize_ke_phone(phone)

    ENV = os.getenv("AT_ENV", "sandbox").lower()

    if ENV == "sandbox":
        url = "https://api.sandbox.africastalking.com/version1/messaging"
    else:
        url = "https://api.africastalking.com/version1/messaging"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "apiKey": api_key
    }

    # ✅ NO sender ID
    payload = {
        "username": username,
        "to": phone,
        "message": message
    }

    try:
        response = requests.post(
            url,
            data=payload,
            headers=headers,
            timeout=15,
            verify=True,
            proxies={"http": None, "https": None}
        )

        logging.info(f"AT RAW RESPONSE: {response.status_code} - {response.text}")

        if response.status_code not in [200, 201]:
            return False, f"HTTP error: {response.text}"

        data = response.json()

        sms_data = data.get("SMSMessageData", {})
        message_text = sms_data.get("Message")
        recipients = sms_data.get("Recipients", [])

        if not recipients:
            return False, message_text or "No recipient response"

        recipient = recipients[0]
        status = recipient.get("status")
        status_code = recipient.get("statusCode")

        if status == "Success":
            return True, data

        return False, f"{status} ({status_code})"

    except Exception as e:
        logging.error(f"SMS EXCEPTION: {str(e)}")
        return False, str(e)



def format_phone(phone):
    if phone.startswith("07"):
        return "+254" + phone[1:]
    return phone


@app.route("/")
def home():
    logging.info("Home route accessed, Session: %s", session)
    return render_template("home.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        password = request.form["password"]
        role = request.form["role"]
        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            county = request.form.get("county")
            sub_county = request.form.get("sub_county")
            if role == "customer" and (not county or not sub_county):
                flash("County and sub-county are required for customers.", "error")
                return redirect(url_for("signup"))

            if "email" in request.form:
                email = request.form["email"]
                phone = None
                # Check for existing user by email
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                existing_user = row_to_dict(cursor.fetchone())
                if existing_user:
                    if existing_user["status"] == "banned":
                        logging.warning(f"Signup attempt by banned email: {email}, Session: %s", session)
                        flash("This email has been banned. Please contact support.", "error")
                        return redirect(url_for("signup"))
                    else:
                        logging.warning(f"Signup failed: Email already registered - {email}, Session: %s", session)
                        flash("Email already registered.", "error")
                        return redirect(url_for("signup"))

                # Insert user directly as verified — no email code verification required
                cursor.execute(
                    "INSERT INTO users (email, phone, password, role, is_verified, created_at, county, sub_county) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (email, phone, hashed_password, role, True, datetime.now(),
                     county if role == "customer" else None,
                     sub_county if role == "customer" else None)
                )
                user_id = cursor.fetchone()['id']

                # Notify admin of new user
                admin_id = get_admin_user_id()
                if admin_id:
                    cursor.execute(
                        "INSERT INTO notifications (user_id, type, content) VALUES (%s, %s, %s)",
                        (admin_id, "new_user", f"New user registered: {email}")
                    )

                conn.commit()

                logging.info(f"Signup completed directly for email: {email}, role: {role}, Session: %s", session)
                flash("Account created successfully! You can now log in.", "success")
                return redirect(url_for("login"))

            elif "phone" in request.form:
                if role != "provider":
                    flash("Customers must sign up using email for now.", "error")
                    return redirect(url_for("signup"))

                phone = normalize_ke_phone(request.form["phone"])
                email = None

                cursor.execute("SELECT * FROM users WHERE phone = %s", (phone,))
                existing_user = row_to_dict(cursor.fetchone())

                if existing_user:
                    if existing_user["status"] == "banned":
                        flash("This phone has been banned. Please contact support.", "error")
                        return redirect(url_for("signup"))
                    else:
                        flash("Phone already registered.", "error")
                        return redirect(url_for("signup"))

                # Store session
                session.permanent = True
                session["pending_phone"] = phone
                session["pending_password"] = hashed_password
                session["pending_role"] = role
                session["pending_county"] = county
                session["pending_sub_county"] = sub_county
                session.modified = True

                logging.info(f"OTP process started for phone: {phone}, role: {role}, Session AFTER SET: %s", session)

                # Generate OTP
                otp = generate_otp()
                save_otp(phone, otp)

                message = f"Your FindService OTP is {otp}. Expires in 5 minutes."

                success, response = send_sms(phone, message)

                if not success:
                    logging.error(f"SMS failed during signup: {response}")
                    flash("SMS delivery failed. Use the OTP shown in console for testing.", "warning")
                    logging.info(f"TEST OTP for {phone}: {otp}")
                else:
                    logging.info(f"OTP sent successfully to {phone}")

                return redirect(url_for("verify_phone_page"))

            else:
                flash("Invalid signup method.", "error")
                return redirect(url_for("signup"))

        except psycopg2.Error as e:
            conn.rollback()
            logging.error(f"Database error during signup: {e}, Session: %s", session)
            flash("Database error. Please try again.", "error")
        finally:
            cursor.close()
            conn.close()
    return render_template("signup.html")


@app.route("/send_otp", methods=["POST"])
def send_otp():
    try:
        logging.info(f"/send_otp called, Session BEFORE: {dict(session)}")

        # Accept JSON or form
        if request.is_json:
            data = request.get_json()
            phone = data.get("phone")
        else:
            phone = request.form.get("phone")

        if not phone:
            return jsonify({
                "success": False,
                "message": "Phone required"
            }), 400

        phone = normalize_ke_phone(phone)

        # Ensure session exists
        if "pending_phone" not in session:
            logging.warning(f"Session missing pending_phone. Restoring with {phone}")
            session["pending_phone"] = phone
            session["pending_role"] = session.get("pending_role", "provider")
            session.permanent = True
            session.modified = True

        # Sync phone
        if session.get("pending_phone") != phone:
            session["pending_phone"] = phone
            session.modified = True

        # Generate OTP
        otp = generate_otp()
        save_otp(phone, otp)

        message = f"Your FindService OTP is {otp}. Expires in 5 minutes."

        success, response = send_sms(phone, message)

        if not success:
            logging.error(f"SMS failed: {response}")

            # ✅ DO NOT BLOCK USER FLOW
            logging.info(f"TEST OTP for {phone}: {otp}")

            return jsonify({
                "success": True,
                "message": "SMS failed. Use test OTP from console.",
                "debug": response  # optional for dev
            })

        logging.info(f"OTP sent successfully to {phone}")

        return jsonify({
            "success": True,
            "message": "OTP sent successfully"
        })

    except Exception as e:
        logging.error(f"Error in /send_otp: {str(e)}")
        return jsonify({
            "success": False,
            "message": "Server error",
            "error": str(e)
        }), 500




@app.route("/verify-phone")
def verify_phone_page():
    phone = session.get("pending_phone")
    return render_template("verify_phone.html", phone=phone)



@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    phone = request.form.get("phone")
    otp = request.form.get("otp")

    phone = format_phone(phone)

    valid, message = check_otp(phone, otp)

    if not valid:
        return message, 400

    # ✅ Retrieve stored data from session
    hashed_password = session.get("pending_password")
    role = session.get("pending_role")
    county = session.get("pending_county")
    sub_county = session.get("pending_sub_county")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO users (phone, password, role, is_verified, created_at, county, sub_county)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (phone, hashed_password, role, True, datetime.now(), county, sub_county)
        )

        user_id = cursor.fetchone()["id"]
        conn.commit()

        # ✅ Clear session temp data
        session.pop("pending_phone", None)
        session.pop("pending_password", None)
        session.pop("pending_role", None)
        session.pop("pending_county", None)
        session.pop("pending_sub_county", None)

        # ✅ Log user in
        session["user_id"] = user_id

        return redirect(url_for("login"))

    except Exception as e:
        conn.rollback()
        logging.error(f"OTP signup error: {str(e)}")
        return "Signup failed", 500

    finally:
        cursor.close()
        conn.close()


@app.route("/verify_email", methods=["GET", "POST"])
def verify_email():
    if request.method == "POST":
        code = request.form.get("code")
        if not code:
            flash("Verification code is required.", "error")
            return render_template("verify_email.html")

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM verification_codes WHERE code = %s AND email = %s",
                (code, session.get("pending_user_email"))
            )
            verification = row_to_dict(cursor.fetchone())

            if not verification:
                logging.warning(f"Invalid verification code {code} for email {session.get('pending_user_email')}, Session: {session}")
                flash("Invalid or expired verification code. Please request a new one.", "error")
                return render_template("verify_email.html")

            current_time = datetime.now()
            expires_at = verification["expires_at"]  # Already a datetime object
            if current_time > expires_at:
                logging.warning(f"Expired verification code {code} for email {session.get('pending_user_email')}, Session: {session}")
                flash("Verification code has expired. Please request a new one.", "error")
                return render_template("verify_email.html")

            cursor.execute(
                "UPDATE users SET is_verified = TRUE WHERE id = %s AND email = %s",
                (session.get("pending_user_id"), session.get("pending_user_email"))
            )
            cursor.execute("DELETE FROM verification_codes WHERE email = %s", (session.get("pending_user_email"),))
            conn.commit()

            # Fetch user details for welcome email
            cursor.execute(
                "SELECT role, county, sub_county FROM users WHERE id = %s",
                (session.get("pending_user_id"),)
            )
            user = row_to_dict(cursor.fetchone())
            if user and user["role"] == "customer" and user["county"] and user["sub_county"]:
                send_welcome_email(
                    session.get("pending_user_email"),
                    user["county"],
                    user["sub_county"]
                )
                logging.info(f"Welcome email sent to {session.get('pending_user_email')} after verification, Session: {session}")

            logging.info(f"Email verified for user ID {session.get('pending_user_id')}, email: {session.get('pending_user_email')}, Session: {session}")
            flash("Email verified successfully! You can now log in.", "success")
            session.pop("pending_user_id", None)
            session.pop("pending_user_email", None)
            return redirect(url_for("login"))

        except psycopg2.Error as e:
            conn.rollback()
            logging.error(f"Database error during email verification: {e}, Session: {session}")
            flash("Database error. Please try again.", "error")
        finally:
            cursor.close()
            conn.close()
       
        return render_template("verify_email.html")

    if "pending_user_email" not in session:
        logging.warning("Access to verify_email without pending email, Session: %s", session)
        flash("No email verification in progress.", "error")
        return redirect(url_for("signup"))

    flash("If you haven't received the email, please check your spam or junk folder.", "info")
    return render_template("verify_email.html")

@app.route("/resend_verification", methods=["POST"])
def resend_verification():
    if "pending_user_email" not in session:
        logging.warning("Attempt to resend verification without pending email, Session: %s", session)
        return jsonify({"error": "No email verification in progress"}), 400

    email = session["pending_user_email"]
   
    if is_rate_limited(email):
        return jsonify({"error": "Please wait 2 minutes before requesting a new code."}), 429

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        verification_code = str(random.randint(100000, 999999))
        expires_at = datetime.now() + timedelta(minutes=15)

        send_verification_email(email, verification_code)

        cleanup_expired_codes(conn)

        cursor.execute("DELETE FROM verification_codes WHERE email = %s", (email,))
        cursor.execute(
            "INSERT INTO verification_codes (email, code, expires_at) VALUES (%s, %s, %s)",
            (email, verification_code, expires_at)
        )
        conn.commit()

        logging.info(f"Verification code resent to {email}, code: {verification_code}, Session: {session}")
        return jsonify({"success": True, "message": "A new verification code has been sent to your email. Please check your inbox or spam folder."})

    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error resending verification for {email}: {e}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_input = request.form["email"]
        password = request.form["password"]
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if '@' in login_input:
                cursor.execute(
                    "SELECT * FROM users WHERE LOWER(email) = LOWER(%s)",
                    (login_input,)
                )
            else:
                cursor.execute(
                    "SELECT * FROM users WHERE phone = %s",
                    (login_input,)
                )
            user = row_to_dict(cursor.fetchone())
            if not user:
                logging.warning(f"Login failed: Input not found - {login_input}, Session: %s", session)
                flash("Invalid email/phone or password", "error")
            elif not user["is_verified"]:
                logging.warning(f"Login failed: Input not verified - {login_input}, Session: %s", session)
                flash("Please verify your email address before logging in.", "error")
                session["pending_user_email"] = user["email"] if user["email"] else None
                session["pending_user_id"] = user["id"]
                return redirect(url_for("verify_email"))
            elif user["status"] == "banned":
                logging.warning(f"Login failed: User banned - {login_input}, Session: %s", session)
                flash("You have been banned", "error")
            elif user["status"] == "removed":
                logging.warning(f"Login failed: User removed - {login_input}, Session: %s", session)
                flash("Your account has been removed. Please sign up again.", "error")
            elif check_password_hash(user["password"], password):
                cursor.execute("UPDATE users SET last_login = %s WHERE id = %s",
                               (datetime.now(), user["id"]))
                conn.commit()
                session["user_id"] = user["id"]
                session["user_role"] = user["role"]
                session["user_email"] = user["email"] or user["phone"]  # Use email or phone as identifier
                session.permanent = True
                logging.info(f"User logged in: {login_input}, Role: {user['role']}, Session: %s", session)
                if user["role"] == "admin":
                    return redirect(url_for("admin_console"))
                elif user["role"] == "customer":
                    return redirect(url_for("customer_dashboard"))
                elif user["role"] == "provider":
                    return redirect(url_for("provider_dashboard"))
                else:
                    flash("Invalid user role", "error")
            else:
                logging.warning(f"Login failed: Incorrect password for input - {login_input}, Session: %s", session)
                flash("Invalid email/phone or password", "error")
        except psycopg2.Error as e:
            logging.error(f"Database error during login for input {login_input}: {e}, Session: %s", session)
            flash("Database error. Please try again.", "error")
        finally:
            cursor.close()
            conn.close()
    return render_template("login.html")

@app.route("/admin_console")
def admin_console():
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to admin console, Session: %s", session)
        flash("Access denied. Admins only.", "error")
        return redirect(url_for("login"))
   
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, email, role, status, last_login, is_verified
            FROM users
            WHERE role = 'provider'
        """)
        providers = [row_to_dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT id, email, role, status, last_login, is_verified
            FROM users
            WHERE role = 'customer'
        """)
        customers = [row_to_dict(row) for row in cursor.fetchall()]
       
        logging.info(f"Admin console accessed: {len(providers)} providers, {len(customers)} customers, Session: %s", session)
        return render_template("admin_console.html", providers=providers, customers=customers)
    except psycopg2.Error as e:
        logging.error(f"Database error in admin console: {e}, Session: %s", session)
        flash("Error loading admin console. Please try again.", "error")
        return redirect(url_for("login"))
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_remove_provider/<int:user_id>")
def admin_remove_provider(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to remove provider, Session: %s", session)
        flash("Access denied", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET status = 'removed' WHERE id = %s AND role = 'provider'", (user_id,))
        if cursor.rowcount == 0:
            logging.warning(f"No provider found with ID {user_id} for removal, Session: %s", session)
            flash("Provider not found or already removed", "error")
        else:
            conn.commit()
            logging.info(f"Provider ID {user_id} marked as removed by admin, Session: %s", session)
            flash("Provider removed successfully", "success")
        return redirect(url_for("admin_console"))
    except psycopg2.Error as e:
        logging.error(f"Database error removing provider ID {user_id}: {e}, Session: %s", session)
        flash("Error removing provider. Please try again.", "error")
        return redirect(url_for("admin_console"))
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_ban_customer/<int:user_id>")
def admin_ban_customer(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to ban customer, Session: %s", session)
        flash("Access denied", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET status = 'banned' WHERE id = %s AND role = 'customer'", (user_id,))
        if cursor.rowcount == 0:
            logging.warning(f"No customer found with ID {user_id} for banning, Session: %s", session)
            flash("Customer not found", "error")
        else:
            conn.commit()
            logging.info(f"Customer ID {user_id} banned by admin, Session: %s", session)
            flash("Customer banned successfully", "success")
        return redirect(url_for("admin_console"))
    except psycopg2.Error as e:
        logging.error(f"Database error banning customer ID {user_id}: {e}, Session: %s", session)
        flash("Error banning customer. Please try again.", "error")
        return redirect(url_for("admin_console"))
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_ban_provider/<int:user_id>")
def admin_ban_provider(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to ban provider, Session: %s", session)
        flash("Access denied", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET status = 'banned' WHERE id = %s AND role = 'provider'", (user_id,))
        conn.commit()
        logging.info(f"Provider ID {user_id} banned by admin, Session: %s", session)
        flash("Provider banned successfully", "success")
        return redirect(url_for("admin_console"))
    except psycopg2.Error as e:
        logging.error(f"Database error banning provider ID {user_id}: {e}, Session: %s", session)
        flash("Error banning provider. Please try again.", "error")
        return redirect(url_for("admin_console"))
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_remove_customer/<int:user_id>")
def admin_remove_customer(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to remove customer, Session: %s", session)
        flash("Access denied", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Delete the customer from the users table
        cursor.execute("DELETE FROM users WHERE id = %s AND role = 'customer'", (user_id,))
        if cursor.rowcount == 0:
            logging.warning(f"No customer found with ID {user_id} for removal, Session: %s", session)
            flash("Customer not found or already removed", "error")
        else:
            conn.commit()
            logging.info(f"Customer ID {user_id} deleted by admin, Session: %s", session)
            flash("Customer removed successfully", "success")
        return redirect(url_for("admin_console"))
    except psycopg2.Error as e:
        logging.error(f"Database error removing customer ID {user_id}: {e}, Session: %s", session)
        flash("Error removing customer. Please try again.", "error")
        return redirect(url_for("admin_console"))
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_unban_provider/<int:user_id>")
def admin_unban_provider(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Access denied", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT email FROM users WHERE id = %s AND role = 'provider'", (user_id,))
        user = row_to_dict(cursor.fetchone())
        if not user:
            flash("Provider not found", "error")
            return redirect(url_for("admin_console"))

        cursor.execute("UPDATE users SET status = 'active' WHERE id = %s AND role = 'provider' AND status = 'banned'", (user_id,))
        if cursor.rowcount == 0:
            flash("Provider not banned or already active", "error")
        else:
            conn.commit()
            send_email(
                recipient=user["email"],
                subject="Your Account Has Been Unbanned",
                plain_body="Dear Provider,\n\nWe are pleased to inform you that your account has been unbanned and you can now access our platform again.\n\nIf you have any questions, please contact support.\n\nBest regards,\nYour Service Platform",
                html_body="<html><body><h2>Your Account Has Been Unbanned</h2><p>Dear Provider,</p><p>We are pleased to inform you that your account has been unbanned and you can now access our platform again.</p><p>If you have any questions, please contact support.</p><p>Best regards,<br>Your Service Platform</p></body></html>"
            )
            flash("Provider unbanned successfully and notification email sent", "success")
        return redirect(url_for("admin_console"))
    except psycopg2.Error as e:
        flash("Error unbanning provider. Please try again.", "error")
        return redirect(url_for("admin_console"))
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_unban_customer/<int:user_id>")
def admin_unban_customer(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Access denied", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT email FROM users WHERE id = %s AND role = 'customer'", (user_id,))
        user = row_to_dict(cursor.fetchone())
        if not user:
            flash("Customer not found", "error")
            return redirect(url_for("admin_console"))

        cursor.execute("UPDATE users SET status = 'active' WHERE id = %s AND role = 'customer' AND status = 'banned'", (user_id,))
        if cursor.rowcount == 0:
            flash("Customer not banned or already active", "error")
        else:
            conn.commit()
            send_email(
                recipient=user["email"],
                subject="Your Account Has Been Unbanned",
                plain_body="Dear Customer,\n\nWe are pleased to inform you that your account has been unbanned and you can now access our platform again.\n\nIf you have any questions, please contact support.\n\nBest regards,\nYour Service Platform",
                html_body="<html><body><h2>Your Account Has Been Unbanned</h2><p>Dear Customer,</p><p>We are pleased to inform you that your account has been unbanned and you can now access our platform again.</p><p>If you have any questions, please contact support.</p><p>Best regards,<br>Your Service Platform</p></body></html>"
            )
            flash("Customer unbanned successfully and notification email sent", "success")
        return redirect(url_for("admin_console"))
    except psycopg2.Error as e:
        flash("Error unbanning customer. Please try again.", "error")
        return redirect(url_for("admin_console"))
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_return_provider/<int:user_id>")
def admin_return_provider(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Access denied", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT email FROM users WHERE id = %s AND role = 'provider'", (user_id,))
        user = row_to_dict(cursor.fetchone())
        if not user:
            flash("Provider not found", "error")
            return redirect(url_for("admin_console"))

        cursor.execute("UPDATE users SET status = 'active' WHERE id = %s AND role = 'provider' AND status = 'removed'", (user_id,))
        if cursor.rowcount == 0:
            flash("Provider not removed or already active", "error")
        else:
            conn.commit()
            send_email(
                recipient=user["email"],
                subject="Your Account Has Been Returned",
                plain_body="Dear Provider,\n\nYour account has been returned to the platform, and you can now access it again.\n\nIf you have any questions, please contact support.\n\nBest regards,\nYour Service Platform",
                html_body="<html><body><h2>Your Account Has Been Returned</h2><p>Dear Provider,</p><p>Your account has been returned to the platform, and you can now access it again.</p><p>If you have any questions, please contact support.</p><p>Best regards,<br>Your Service Platform</p></body></html>"
            )
            flash("Provider returned successfully and notification email sent", "success")
        return redirect(url_for("admin_console"))
    except psycopg2.Error as e:
        flash("Error returning provider. Please try again.", "error")
        return redirect(url_for("admin_console"))
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_return_customer/<int:user_id>")
def admin_return_customer(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Access denied", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT email FROM users WHERE id = %s AND role = 'customer'", (user_id,))
        user = row_to_dict(cursor.fetchone())
        if not user:
            flash("Customer not found", "error")
            return redirect(url_for("admin_console"))

        cursor.execute("UPDATE users SET status = 'active' WHERE id = %s AND role = 'customer' AND status = 'removed'", (user_id,))
        if cursor.rowcount == 0:
            flash("Customer not removed or already active", "error")
        else:
            conn.commit()
            send_email(
                recipient=user["email"],
                subject="Your Account Has Been Returned",
                plain_body="Dear Customer,\n\nYour account has been returned to the platform, and you can now access it again.\n\nIf you have any questions, please contact support.\n\nBest regards,\nYour Service Platform",
                html_body="<html><body><h2>Your Account Has Been Returned</h2><p>Dear Customer,</p><p>Your account has been returned to the platform, and you can now access it again.</p><p>If you have any questions, please contact support.</p><p>Best regards,<br>Your Service Platform</p></body></html>"
            )
            flash("Customer returned successfully and notification email sent", "success")
        return redirect(url_for("admin_console"))
    except psycopg2.Error as e:
        flash("Error returning customer. Please try again.", "error")
        return redirect(url_for("admin_console"))
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_remove_provider_with_reason", methods=["POST"])
def admin_remove_provider_with_reason():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    user_id = data.get("user_id")
    reason = data.get("reason")

    if not user_id or not reason:
        return jsonify({"error": "User ID and reason are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET status = 'removed' WHERE id = %s AND role = 'provider'", (user_id,))
        if cursor.rowcount == 0:
            return jsonify({"error": "Provider not found or already removed"}), 404

        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if provider:
            send_email(
                recipient=provider["email"],
                subject="Account Removed",
                plain_body=f"Dear Provider,\n\nYour account has been removed from our platform.\nReason: {reason}\n\nIf you have any questions, please contact support.\n\nBest regards,\nYour Service Platform",
                html_body=f"<html><body><h2>Account Removed</h2><p>Dear Provider,</p><p>Your account has been removed from our platform.</p><p><strong>Reason:</strong> {reason}</p><p>If you have any questions, please contact support.</p><p>Best regards,<br>Your Service Platform</p></body></html>"
            )
        conn.commit()
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_ban_provider_with_reason", methods=["POST"])
def admin_ban_provider_with_reason():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    user_id = data.get("user_id")
    reason = data.get("reason")

    if not user_id or not reason:
        return jsonify({"error": "User ID and reason are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET status = 'banned' WHERE id = %s AND role = 'provider'", (user_id,))
        if cursor.rowcount == 0:
            return jsonify({"error": "Provider not found or already banned"}), 404

        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if provider:
            send_email(
                recipient=provider["email"],
                subject="Account Banned",
                plain_body=f"Dear Provider,\n\nYour account has been banned from our platform.\nReason: {reason}\n\nIf you have any questions, please contact support.\n\nBest regards,\nYour Service Platform",
                html_body=f"<html><body><h2>Account Banned</h2><p>Dear Provider,</p><p>Your account has been banned from our platform.</p><p><strong>Reason:</strong> {reason}</p><p>If you have any questions, please contact support.</p><p>Best regards,<br>Your Service Platform</p></body></html>"
            )
        conn.commit()
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_remove_customer_with_reason", methods=["POST"])
def admin_remove_customer_with_reason():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    user_id = data.get("user_id")
    reason = data.get("reason")

    if not user_id or not reason:
        return jsonify({"error": "User ID and reason are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET status = 'removed' WHERE id = %s AND role = 'customer'", (user_id,))
        if cursor.rowcount == 0:
            return jsonify({"error": "Customer not found or already removed"}), 404

        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        customer = row_to_dict(cursor.fetchone())
        if customer:
            send_email(
                recipient=customer["email"],
                subject="Account Removed",
                plain_body=f"Dear Customer,\n\nYour account has been removed from our platform.\nReason: {reason}\n\nIf you have any questions, please contact support.\n\nBest regards,\nYour Service Platform",
                html_body=f"<html><body><h2>Account Removed</h2><p>Dear Customer,</p><p>Your account has been removed from our platform.</p><p><strong>Reason:</strong> {reason}</p><p>If you have any questions, please contact support.</p><p>Best regards,<br>Your Service Platform</p></body></html>"
            )
        conn.commit()
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_ban_customer_with_reason", methods=["POST"])
def admin_ban_customer_with_reason():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    user_id = data.get("user_id")
    reason = data.get("reason")

    if not user_id or not reason:
        return jsonify({"error": "User ID and reason are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET status = 'banned' WHERE id = %s AND role = 'customer'", (user_id,))
        if cursor.rowcount == 0:
            return jsonify({"error": "Customer not found or already banned"}), 404

        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        customer = row_to_dict(cursor.fetchone())
        if customer:
            send_email(
                recipient=customer["email"],
                subject="Account Banned",
                plain_body=f"Dear Customer,\n\nYour account has been banned from our platform.\nReason: {reason}\n\nIf you have any questions, please contact support.\n\nBest regards,\nYour Service Platform",
                html_body=f"<html><body><h2>Account Banned</h2><p>Dear Customer,</p><p>Your account has been banned from our platform.</p><p><strong>Reason:</strong> {reason}</p><p>If you have any questions, please contact support.</p><p>Best regards,<br>Your Service Platform</p></body></html>"
            )
        conn.commit()
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/admin_message_provider/<int:user_id>", methods=["GET", "POST"])
def admin_message_provider(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to admin_message_provider, Session: %s", session)
        flash("Access denied", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        message_text = request.form.get("message", "").strip()
        if not message_text:
            flash("Message content is required.", "error")
            return redirect(url_for("admin_console"))

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            admin_id = session["user_id"]
            # Find or create conversation
            cursor.execute(
                """
                SELECT id FROM conversations
                WHERE (user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s)
                """,
                (admin_id, user_id, user_id, admin_id)
            )
            conversation = cursor.fetchone()
            if not conversation:
                cursor.execute(
                    """
                    INSERT INTO conversations (user1_id, user2_id)
                    VALUES (%s, %s) RETURNING id
                    """,
                    (min(admin_id, user_id), max(admin_id, user_id))
                )
                conversation_id = cursor.fetchone()['id']
            else:
                conversation_id = conversation['id']

            # Insert message with conversation_id
            cursor.execute(
                """
                INSERT INTO messages (sender_id, receiver_id, message, timestamp, is_read, conversation_id)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (admin_id, user_id, escape(message_text), datetime.now(), False, conversation_id)
            )
            conn.commit()
            logging.info(f"Message sent from admin ID {admin_id} to provider ID {user_id}, Conversation ID: {conversation_id}, Session: %s", session)
            flash("Message sent successfully to provider.", "success")
        except psycopg2.Error as e:
            conn.rollback()
            logging.error(f"Database error sending message to provider ID {user_id}: {e}, Session: %s", session)
            flash("Error sending message. Please try again.", "error")
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for("admin_console"))
    return redirect(url_for("admin_console"))

@app.route("/admin_message_customer/<int:user_id>", methods=["GET", "POST"])
def admin_message_customer(user_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to admin_message_customer, Session: %s", session)
        flash("Access denied", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        message_text = request.form.get("message", "").strip()
        if not message_text:
            flash("Message content is required.", "error")
            return redirect(url_for("admin_console"))

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            admin_id = session["user_id"]
            # Find or create conversation
            cursor.execute(
                """
                SELECT id FROM conversations
                WHERE (user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s)
                """,
                (admin_id, user_id, user_id, admin_id)
            )
            conversation = cursor.fetchone()
            if not conversation:
                cursor.execute(
                    """
                    INSERT INTO conversations (user1_id, user2_id)
                    VALUES (%s, %s) RETURNING id
                    """,
                    (min(admin_id, user_id), max(admin_id, user_id))
                )
                conversation_id = cursor.fetchone()['id']
            else:
                conversation_id = conversation['id']

            # Insert message with conversation_id
            cursor.execute(
                """
                INSERT INTO messages (sender_id, receiver_id, message, timestamp, is_read, conversation_id)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (admin_id, user_id, escape(message_text), datetime.now(), False, conversation_id)
            )
            conn.commit()
            logging.info(f"Message sent from admin ID {admin_id} to customer ID {user_id}, Conversation ID: {conversation_id}, Session: %s", session)
            flash("Message sent successfully to customer.", "success")
        except psycopg2.Error as e:
            conn.rollback()
            logging.error(f"Database error sending message to customer ID {user_id}: {e}, Session: %s", session)
            flash("Error sending message. Please try again.", "error")
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for("admin_console"))
    return redirect(url_for("admin_console"))

@app.route("/api/admin/dashboard-metrics")
def dashboard_metrics():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Active Users (unchanged)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE status = 'active' AND last_login >= %s",
            (thirty_days_ago,)
        )
        active_users = cursor.fetchone()[0]

        # Pending Bookings (unchanged)
        cursor.execute(
            "SELECT COUNT(*) FROM bookings b "
            "JOIN providers p ON b.provider_id = p.id "
            "JOIN users u ON p.user_id = u.id "
            "WHERE b.status = 'Pending' AND u.status = 'active'"
        )
        pending_bookings = cursor.fetchone()[0]

        # Avg Provider Rating (updated for active providers)
        cursor.execute("""
            SELECT AVG(r.overall_rating)
            FROM ratings r
            JOIN providers p ON r.provider_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE u.status = 'active'
        """)
        avg_rating = cursor.fetchone()[0]
        avg_rating = round(float(avg_rating), 1) if avg_rating is not None else None

        # Customer Satisfaction (new calculation)
        # High Rating Percentage
        cursor.execute("""
            SELECT COUNT(*)
            FROM ratings r
            JOIN providers p ON r.provider_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE u.status = 'active' AND r.overall_rating >= 4
        """)
        high_rating_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM ratings r
            JOIN providers p ON r.provider_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE u.status = 'active'
        """)
        total_rating_count = cursor.fetchone()[0]

        high_rating_percentage = (high_rating_count / total_rating_count * 100) if total_rating_count > 0 else 0

        # Repeat Booking Percentage
        cursor.execute("""
            SELECT COUNT(DISTINCT b1.id)
            FROM bookings b1
            JOIN providers p1 ON b1.provider_id = p1.id
            JOIN users u1 ON p1.user_id = u1.id
            WHERE u1.status = 'active'
            AND EXISTS (
                SELECT 1
                FROM bookings b2
                JOIN providers p2 ON b2.provider_id = p2.id
                JOIN users u2 ON p2.user_id = u2.id
                WHERE b2.customer_email = b1.customer_email
                  AND b2.provider_id = b1.provider_id
                  AND b2.created_at < b1.created_at
                  AND u2.status = 'active'
            )
        """)
        repeat_booking_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM bookings b
            JOIN providers p ON b.provider_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE u.status = 'active'
        """)
        total_booking_count = cursor.fetchone()[0]

        repeat_booking_percentage = (repeat_booking_count / total_booking_count * 100) if total_booking_count > 0 else 0

        # Combine for Customer Satisfaction
        customer_satisfaction = (high_rating_percentage + repeat_booking_percentage) / 2
        customer_satisfaction = round(customer_satisfaction, 1)

        metrics = {
            "activeUsers": active_users,
            "pendingBookings": pending_bookings,
            "avgProviderRating": avg_rating,
            "customerSatisfaction": customer_satisfaction
        }
        logging.info(f"Dashboard metrics fetched: {metrics}, Session: %s", session)
        return jsonify(metrics)
    except psycopg2.Error as e:
        logging.error(f"Database error in dashboard metrics: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/admin/users")
def admin_users():
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to admin users, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT u.id, u.email, u.role, u.status, COALESCE(p.name, u.email) as name
            FROM users u
            LEFT JOIN providers p ON u.id = p.user_id
            """
        )
        users_list = [row_to_dict(user) for user in cursor.fetchall()]
        logging.info(f"Fetched {len(users_list)} users for admin, Session: %s", session)
        return jsonify(users_list)
    except psycopg2.Error as e:
        logging.error(f"Database error in admin users: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/admin/services")
def admin_services():
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to admin services, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT u.email, p.service_category as category,
                   (SELECT COUNT(*) FROM bookings b WHERE b.provider_id = p.id) as bookings,
                   (SELECT COUNT(*) FROM bookings b WHERE b.provider_id = p.id AND b.status = 'Rejected') as issues
            FROM providers p
            JOIN users u ON p.user_id = u.id
            """
        )
        services_list = [row_to_dict(service) for service in cursor.fetchall()]
        logging.info(f"Fetched {len(services_list)} services for admin, Session: %s", session)
        return jsonify(services_list)
    except psycopg2.Error as e:
        logging.error(f"Database error in admin services: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/admin/alerts")
def admin_alerts():
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to admin alerts, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        alerts = []

        # Pending bookings from active providers
        cursor.execute(
            "SELECT COUNT(*) as count, MAX(updated_at) as latest "
            "FROM bookings b "
            "JOIN providers p ON b.provider_id = p.id "
            "JOIN users u ON p.user_id = u.id "
            "WHERE b.status = 'Pending' AND u.status = 'active'"
        )
        pending_bookings = row_to_dict(cursor.fetchone())
        if pending_bookings["count"] > 0:
            alerts.append({
                "message": f"There are {pending_bookings['count']} pending bookings.",
                "timestamp": pending_bookings["latest"]
            })

        # New users, using UTC time
        twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        cursor.execute(
            "SELECT COUNT(*) as count, MAX(created_at) as latest FROM users WHERE created_at >= %s AND status = 'active' AND is_verified = TRUE",
            (twenty_four_hours_ago,)
        )
        new_users = row_to_dict(cursor.fetchone())
        if new_users["count"] > 0:
            alerts.append({
                "message": f"{new_users['count']} new users registered in the last 24 hours.",
                "timestamp": new_users["latest"]
            })

        # Rejected bookings from active providers, using UTC time
        one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        cursor.execute(
            "SELECT COUNT(*) as count, MAX(updated_at) as latest "
            "FROM bookings b "
            "JOIN providers p ON b.provider_id = p.id "
            "JOIN users u ON p.user_id = u.id "
            "WHERE b.status = 'Rejected' AND u.status = 'active' AND b.updated_at >= %s",
            (one_week_ago,)
        )
        rejected_bookings = row_to_dict(cursor.fetchone())
        if rejected_bookings["count"] > 0:
            alerts.append({
                "message": f"{rejected_bookings['count']} bookings were rejected in the last week.",
                "timestamp": rejected_bookings["latest"]
            })

        logging.info(f"Fetched {len(alerts)} alerts for admin, Session: %s", session)
        return jsonify(alerts)
    except psycopg2.Error as e:
        logging.error(f"Database error in admin alerts: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/admin/notifications")
def admin_notifications():
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to admin notifications, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, content AS message, is_read FROM notifications WHERE user_id = %s AND type IN ('new_user', 'new_message') ORDER BY timestamp DESC",
            (user_id,)
        )
        notifications_list = [row_to_dict(notif) for notif in cursor.fetchall()]
        for notif in notifications_list:
            notif["unread"] = not notif["is_read"]  # Convert BOOLEAN to Python bool
        logging.info(f"Fetched {len(notifications_list)} notifications for admin user ID {user_id}, Session: %s", session)
        return jsonify(notifications_list)
    except psycopg2.Error as e:
        logging.error(f"Database error in admin notifications: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/admin/unread_notifications_count", methods=["GET"])
def unread_notifications_count():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = FALSE AND type IN ('new_user', 'new_message')",
            (user_id,)
        )
        count = cursor.fetchone()[0]
        logging.info(f"Fetched unread notifications count: {count} for admin, Session: %s", session)
        return jsonify({"count": count})
    except psycopg2.Error as e:
        logging.error(f"Database error fetching unread notifications count: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/admin/delete_read_notifications", methods=["POST"])
def delete_read_notifications():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM notifications WHERE user_id = %s AND is_read = TRUE AND type IN ('new_user', 'new_message')",
            (user_id,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        logging.info(f"Deleted {deleted_count} read notifications for admin user ID {user_id}, Session: %s", session)
        return jsonify({"success": True, "deleted_count": deleted_count})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting read notifications for user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/admin/active-users")
def active_users():
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to active users, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        thirty_days_ago = datetime.now() - timedelta(days=30)
        cursor.execute(
            "SELECT id, email, role, last_login FROM users WHERE last_login >= %s",
            (thirty_days_ago,)
        )
        users_list = [row_to_dict(user) for user in cursor.fetchall()]
        logging.info(f"Fetched {len(users_list)} active users for admin, Session: %s", session)
        return jsonify(users_list)
    except psycopg2.Error as e:
        logging.error(f"Database error in active users: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/admin/pending-bookings")
def pending_bookings():
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized access to pending bookings, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT b.id, b.provider_id, b.customer_email, b.service_date, p.name as provider_name, u.email as customer_email
            FROM bookings b
            JOIN providers p ON b.provider_id = p.id
            JOIN users u ON b.customer_email = u.email
            WHERE b.status = 'Pending'
            """
        )
        bookings_list = [row_to_dict(booking) for booking in cursor.fetchall()]
        logging.info(f"Fetched {len(bookings_list)} pending bookings for admin, Session: %s", session)
        return jsonify(bookings_list)
    except psycopg2.Error as e:
        logging.error(f"Database error in pending bookings: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

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
    customer_email = session.get("user_email")
    if not customer_email:
        logging.warning(f"No customer email in session for user_id {user_id}, Session: %s", session)
        flash("Session error. Please log in again.", "error")
        return redirect(url_for("login"))
   
    conn = get_db_connection()
    cursor = conn.cursor()
    local_providers = []
    all_providers = []
    unread_messages = 0
    bookings = []
    admin_user_id = None
    conversations_data = {}
   
    try:
        # Fetch customer's county and sub_county
        cursor.execute("SELECT county, sub_county FROM users WHERE id = %s", (user_id,))
        customer_loc = row_to_dict(cursor.fetchone())
        customer_county = customer_loc.get("county")
        customer_subcounty = customer_loc.get("sub_county")
       
        # Base query for providers - now includes u.email AS provider_email
        base_query = """
            SELECT
                p.*,
                u.last_login,
                u.id AS user_id,
                u.email AS provider_email,
                (SELECT COUNT(*)
                 FROM stories s
                 LEFT JOIN stories_views sv ON s.id = sv.story_id AND sv.customer_id = %s
                 WHERE s.provider_id = p.id
                   AND sv.story_id IS NULL
                   AND s.expires_at > CURRENT_TIMESTAMP) AS unviewed_story_count,
                (SELECT COUNT(*)
                 FROM stories s
                 WHERE s.provider_id = p.id
                   AND s.expires_at > CURRENT_TIMESTAMP) AS total_active_story_count
            FROM providers p
            JOIN users u ON p.user_id = u.id
            WHERE p.activity_status = 'Active'
        """
       
        # Fetch all providers first
        cursor.execute(base_query, (user_id,))
        all_providers_raw = [dict(row) for row in cursor.fetchall()]
       
        # If customer location exists, filter local providers
        if customer_county and customer_subcounty:
            local_query = base_query + " AND p.areas_served = %s AND p.sub_county = %s"
            cursor.execute(local_query, (user_id, customer_county, customer_subcounty))
            local_providers = [dict(row) for row in cursor.fetchall()]
           
            # Exclude local providers from all_providers
            local_ids = {p['id'] for p in local_providers}
            all_providers = [p for p in all_providers_raw if p['id'] not in local_ids]
        else:
            # No location: all providers in all_providers, local empty
            all_providers = all_providers_raw
       
        # Format last_active for both lists and ensure email is N/A if None
        for provider in local_providers + all_providers:
            provider['last_active'] = time_ago(provider['last_login'])
            if provider.get('provider_email') is None:
                provider['provider_email'] = 'N/A'
       
        logging.info(f"Fetched {len(local_providers)} local providers and {len(all_providers)} other providers for customer_id {user_id}, Session: %s", session)

        # Rest of the code unchanged...
        cursor.execute(
            "SELECT COUNT(*) FROM messages WHERE receiver_id = %s AND is_read = FALSE",
            (user_id,)
        )
        unread_messages = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT b.id, b.provider_id, b.customer_name, b.customer_phone, b.customer_email,
                   b.location, b.service_date, b.rescheduled_date, b.status, b.created_at, b.updated_at, p.name AS provider_name
            FROM bookings b LEFT JOIN providers p ON b.provider_id = p.id
            WHERE b.customer_email = %s ORDER BY b.updated_at DESC
            """,
            (customer_email,)
        )
        bookings = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT id FROM users WHERE role = 'admin'")
        admin_user = row_to_dict(cursor.fetchone())
        admin_user_id = admin_user['id'] if admin_user else None

        # Fetch conversations with latest message timestamp for sorting
        cursor.execute("""
            SELECT
                c.id AS conversation_id,
                CASE
                    WHEN c.user1_id = %s THEN u2.email
                    ELSE u1.email
                END AS other_user_name,
                CASE
                    WHEN c.user1_id = %s THEN c.user2_id
                    ELSE c.user1_id
                END AS other_user_id,
                MAX(m.timestamp) AS latest_timestamp
            FROM conversations c
            JOIN users u1 ON c.user1_id = u1.id
            JOIN users u2 ON c.user2_id = u2.id
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.user1_id = %s OR c.user2_id = %s
            GROUP BY c.id, u1.email, u2.email, c.user1_id, c.user2_id
            ORDER BY latest_timestamp DESC NULLS LAST
        """, (user_id, user_id, user_id, user_id))
        conversations = [dict(row) for row in cursor.fetchall()]

        for conv in conversations:
            # Primary fetch using conversation_id with deleted_for filter
            cursor.execute("""
                SELECT m.*, u.email AS sender_email, u.role AS sender_role
                FROM messages m
                JOIN users u ON m.sender_id = u.id
                WHERE m.conversation_id = %s
                AND (m.deleted_for IS NULL OR NOT (',' || m.deleted_for || ',') LIKE %s)
                ORDER BY m.timestamp ASC
            """, (conv['conversation_id'], f'%,{user_id},%'))
            messages = [dict(row) for row in cursor.fetchall()]
           
            # Fallback: If no messages found (e.g., conversation_id null or all filtered), fetch using sender/receiver
            if len(messages) == 0:
                cursor.execute("""
                    SELECT m.*, u.email AS sender_email, u.role AS sender_role
                    FROM messages m
                    JOIN users u ON m.sender_id = u.id
                    WHERE (m.sender_id = %s AND m.receiver_id = %s OR m.sender_id = %s AND m.receiver_id = %s)
                    AND (m.deleted_for IS NULL OR NOT (',' || m.deleted_for || ',') LIKE %s)
                    ORDER BY m.timestamp ASC
                """, (user_id, conv['other_user_id'], conv['other_user_id'], user_id, f'%,{user_id},%'))
                messages = [dict(row) for row in cursor.fetchall()]
                logging.info(f"Fallback fetch used for conversation {conv['conversation_id']} with other_user_id {conv['other_user_id']}, found {len(messages)} messages")
           
            conv['messages'] = messages
            conversations_data[conv['other_user_id']] = conv

    except psycopg2.Error as e:
        logging.error(f"Database error fetching dashboard data: {e}, Session: %s", session)
        flash("Unable to load dashboard data at this time.", "warning")
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "customer_dashboard.html",
        local_providers=local_providers,
        all_providers=all_providers,
        unread_messages=unread_messages,
        bookings=bookings,
        admin_user_id=admin_user_id,
        conversations_data=conversations_data
    )

@app.route("/book_provider/<int:provider_id>", methods=["GET", "POST"])
def book_provider(provider_id):
    logging.info(f"book_provider route hit for provider_id {provider_id}, method {request.method}, Session: {session}")
   
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning(f"Unauthorized access to book provider for provider_id {provider_id}, Session: {session}")
        return jsonify({"error": "Please log in as a customer to book a provider."}), 401
   
    if request.method != "POST":
        logging.warning(f"Invalid method {request.method} for provider_id {provider_id}, Session: {session}")
        return jsonify({"error": "Method not allowed"}), 405
   
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
       
        cursor.execute("""
            SELECT p.*, u.email AS provider_email
            FROM providers p
            JOIN users u ON p.user_id = u.id
            WHERE p.id = %s
        """, (provider_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider ID {provider_id} not found, Session: {session}")
            return jsonify({"error": "Provider not found."}), 404
       
        logging.info(f"Received form data for provider_id {provider_id}: {dict(request.form)}, Session: {session}")
       
        customer_name = request.form.get("customer_name", "").strip()
        customer_phone = request.form.get("customer_phone", "").strip()
        customer_email = request.form.get("customer_email", "").strip()
        location = request.form.get("location", "").strip()
        service_date = request.form.get("service_date", "").strip() or None
       
        if not all([customer_name, customer_phone, customer_email, location]):
            missing = [k for k, v in {"name": customer_name, "phone": customer_phone, "email": customer_email, "location": location}.items() if not v]
            logging.warning(f"Missing required fields for provider_id {provider_id}: {missing}, Session: {session}")
            return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
       
        cursor.execute(
            """
            INSERT INTO bookings (provider_id, customer_name, customer_phone, customer_email, location, service_date, status, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (provider_id, customer_name, customer_phone, customer_email, location, service_date, "Pending", datetime.now())
        )
        booking_id = cursor.fetchone()['id']
       
        provider_user_id = provider["user_id"]
        cursor.execute(
            "INSERT INTO notifications (user_id, type, content) VALUES (%s, %s, %s)",
            (provider_user_id, "booking", f"New booking from {customer_name}")
        )

        conn.commit()
       
        logging.info(f"Booking ID {booking_id} created for provider_id {provider_id}, customer_email {customer_email}, Session: {session}")
       
        notification_result = send_status_update_message(provider["id"], customer_email, booking_id, "Pending", service_date)
        if isinstance(notification_result, dict) and notification_result.get("success"):
            logging.info(f"Notification sent for booking ID {booking_id}, message_id: {notification_result.get('message_id', 'unknown')}, Session: {session}")
            response = {
                "success": True,
                "booking_id": booking_id,
                "notification_sent": True,
                "message_id": notification_result.get("message_id")
            }
        else:
            error_msg = notification_result.get("error", "Unknown error") if isinstance(notification_result, dict) else str(notification_result)
            logging.warning(f"Notification failed for booking ID {booking_id}: {error_msg}, Session: {session}")
            response = {
                "success": True,
                "booking_id": booking_id,
                "notification_sent": False,
                "warning": f"Booking created but notification failed: {error_msg}"
            }
       
        provider_email = provider["provider_email"]
        send_booking_request_to_provider(provider_email, customer_name, customer_email, customer_phone, booking_id, service_date)
        send_booking_request_confirmation_to_customer(customer_email, provider["name"], booking_id, service_date)
       
        return jsonify(response), 200
   
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        logging.error(f"Database error in book_provider for provider_id {provider_id}: {str(e)}, Form: {dict(request.form)}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Unexpected error in book_provider for provider_id {provider_id}: {str(e)}, Form: {dict(request.form)}, Session: {session}")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    finally:
        if conn:
            cursor.close()
            conn.close()


@app.route("/provider_dashboard", methods=["GET", "POST"])
def provider_dashboard():
    if "user_id" not in session or session.get("user_role") != "provider":
        flash("Please log in as a provider to access this page.", "error")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch provider with joined users.email – this now correctly includes the provider's email
        cursor.execute("""
            SELECT p.*, u.email
            FROM providers p
            JOIN users u ON p.user_id = u.id
            WHERE p.user_id = %s
        """, (user_id,))
        provider = row_to_dict(cursor.fetchone())
        bookings = []
        unread_count = 0
        pending_bookings_count = 0
        has_unviewed_story = False
        portfolio = None  # Added: Initialize portfolio

        if provider:
            cursor.execute(
                "SELECT * FROM bookings WHERE provider_id = %s ORDER BY updated_at DESC",
                (provider["id"],)
            )
            bookings = [row_to_dict(booking) for booking in cursor.fetchall()]
            pending_bookings_count = sum(1 for b in bookings if b.get("status") == "Pending")
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE receiver_id = %s AND is_read = FALSE",
                (user_id,)
            )
            unread_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) > 0
                FROM stories
                WHERE provider_id = %s
                  AND expires_at > CURRENT_TIMESTAMP
                  AND viewed = FALSE
            """, (provider["id"],))
            has_unviewed_story = cursor.fetchone()[0]

            # Added: Fetch portfolio details
            cursor.execute("""
                SELECT skills, experience, github_links
                FROM portfolios
                WHERE provider_id = %s
            """, (provider["id"],))
            portfolio = row_to_dict(cursor.fetchone())

        cursor.execute("SELECT id FROM users WHERE role = 'admin'")
        admin_user = row_to_dict(cursor.fetchone())
        admin_user_id = admin_user['id'] if admin_user else None

        if request.method == "POST":
            action = request.form.get("action")
            if action in ["create", "edit"]:
                name = request.form["name"]
                phone = request.form["phone"]
                email = request.form.get("email", "").strip()  # Email from form (can be empty on create)
                service_description = request.form["service_description"]
                areas_served = request.form["areas_served"]
                sub_county = request.form["sub_county"]
                local_area = request.form.get("local_area", "")
                availability = request.form["availability"]
                custom_availability = None
                if availability == "Set Time":
                    start_time = request.form.get("start_time")
                    end_time = request.form.get("end_time")
                    if start_time and end_time:
                        custom_availability = f"{start_time} - {end_time}"
                pricing = request.form["pricing"]
                currency = request.form["currency"]
                service_category = request.form["service_category"]
                key_skills = request.form.get("key_skills", "").strip()

                # === EMAIL HANDLING FIX ===
                # Always update the users table with the email from the form
                if email:
                    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                    if not re.match(email_regex, email):
                        flash("Invalid email format.", "error")
                        return redirect(url_for("provider_dashboard"))

                    # Check uniqueness only against other users
                    cursor.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(%s) AND id != %s", (email, user_id))
                    if cursor.fetchone():
                        flash("Email already in use by another account.", "error")
                        return redirect(url_for("provider_dashboard"))

                    cursor.execute("UPDATE users SET email = %s WHERE id = %s", (email, user_id))
                else:
                    # If email field is empty, clear the email in users table
                    cursor.execute("UPDATE users SET email = NULL WHERE id = %s", (user_id,))

                # === END EMAIL FIX ===

                profile_picture = request.files.get("profile_picture")
                new_picture_filename = None
                if profile_picture and allowed_file(profile_picture.filename):
                    if provider and provider.get("profile_picture"):
                        old_path = os.path.join(app.config["UPLOAD_FOLDER"], provider["profile_picture"])
                        if os.path.exists(old_path):
                            try:
                                os.remove(old_path)
                            except OSError:
                                pass
                    new_picture_filename = secure_filename(profile_picture.filename)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    new_picture_filename = f"{timestamp}_{new_picture_filename}"
                    profile_picture.save(os.path.join(app.config["UPLOAD_FOLDER"], new_picture_filename))

                picture_to_save = new_picture_filename or provider.get("profile_picture") if provider else None

                if action == "create":
                    cursor.execute(
                        """
                        INSERT INTO providers
                        (user_id, name, profile_picture, phone, service_description, areas_served, sub_county,
                         local_area, availability, custom_availability, pricing, currency, service_category, key_skills)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (user_id, name, picture_to_save, phone, service_description, areas_served, sub_county,
                         local_area, availability, custom_availability, pricing, currency, service_category, key_skills)
                    )
                    provider_id = cursor.fetchone()['id']
                    conn.commit()
                    flash("Profile created successfully!", "success")
                    return redirect(url_for("provider_dashboard"))

                elif action == "edit":
                    cursor.execute(
                        """
                        UPDATE providers
                        SET name = %s, profile_picture = %s, phone = %s, service_description = %s,
                            areas_served = %s, sub_county = %s, local_area = %s, availability = %s,
                            custom_availability = %s, pricing = %s, currency = %s, service_category = %s,
                            key_skills = %s
                        WHERE id = %s
                        """,
                        (name, picture_to_save, phone, service_description, areas_served, sub_county, local_area,
                         availability, custom_availability, pricing, currency, service_category, key_skills, provider["id"])
                    )
                    conn.commit()
                    flash("Profile updated successfully!", "success")

                    # Refresh provider data after edit
                    cursor.execute("""
                        SELECT p.*, u.email
                        FROM providers p
                        JOIN users u ON p.user_id = u.id
                        WHERE p.id = %s
                    """, (provider["id"],))
                    provider = row_to_dict(cursor.fetchone())

            # Added: Handle portfolio upload
            elif action == "upload_portfolio":
                skills = request.form.get("skills", "").strip()
                experience = request.form.get("experience", "").strip()
                github_links_list = request.form.getlist("github_links[]")  # Handle dynamic GitHub links
                github_links = ','.join(filter(None, github_links_list)).strip()  # Join non-empty links with comma

                if not skills or not experience or not github_links:
                    logging.warning("Missing required portfolio fields in upload, Session: %s", session)
                    flash("Skills, Experience, and at least one GitHub link are required.", "error")
                    return redirect(url_for("provider_dashboard"))

                # Insert or update portfolio (UPSERT) - Added certifications and work_samples as empty strings for table completeness
                cursor.execute(
                    """
                    INSERT INTO portfolios (provider_id, skills, certifications, experience, work_samples, github_links, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (provider_id) DO UPDATE
                    SET skills = EXCLUDED.skills,
                        certifications = EXCLUDED.certifications,
                        experience = EXCLUDED.experience,
                        work_samples = EXCLUDED.work_samples,
                        github_links = EXCLUDED.github_links,
                        created_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (provider["id"], skills, '', experience, '', github_links)
                )
                portfolio_id = cursor.fetchone()['id']
                conn.commit()
                logging.info(f"Portfolio uploaded/updated with ID {portfolio_id} for provider_id {provider['id']}, Session: %s", session)
                flash("Portfolio uploaded successfully!", "success")
                # Refresh portfolio after upload
                cursor.execute("""
                    SELECT skills, experience, github_links
                    FROM portfolios
                    WHERE provider_id = %s
                """, (provider["id"],))
                portfolio = row_to_dict(cursor.fetchone())

        return render_template(
            "provider_dashboard.html",
            provider=provider,
            bookings=bookings,
            session_user_id=user_id,
            unread_messages=unread_count,
            admin_user_id=admin_user_id,
            pending_bookings_count=pending_bookings_count,
            has_unviewed_story=has_unviewed_story,
            portfolio=portfolio  # Added: Pass portfolio to template
        )
    except Exception as e:
        conn.rollback()
        logging.error(f"Error in provider_dashboard for user ID {user_id}: {str(e)}")
        flash("Error processing request.", "error")
        return redirect(url_for("provider_dashboard"))
    finally:
        cursor.close()
        conn.close()


@app.route("/submit_reply", methods=["POST"])
def submit_reply():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to submit reply, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    rating_id = data.get("rating_id")
    reply = data.get("reply")
    if not rating_id or not reply:
        logging.warning("Missing rating_id or reply in submit_reply, Session: %s", session)
        return jsonify({"error": "Rating ID and reply text are required"}), 400

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404

        cursor.execute("SELECT provider_id FROM ratings WHERE id = %s", (rating_id,))
        rating = row_to_dict(cursor.fetchone())
        if not rating or rating["provider_id"] != provider["id"]:
            logging.warning(f"Rating ID {rating_id} not found or not owned by provider_id {provider['id']}, Session: %s", session)
            return jsonify({"error": "Rating not found"}), 404

        cursor.execute(
            """
            INSERT INTO rating_replies (rating_id, reply, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (rating_id, reply)
        )
        reply_id = cursor.fetchone()['id']
        conn.commit()
        logging.info(f"Reply submitted for rating ID {rating_id} by provider ID {provider['id']}, Reply ID: {reply_id}, Session: %s", session)
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error submitting reply for rating ID {rating_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/delete_provider", methods=["POST"])
def delete_provider():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to delete provider, Session: %s", session)
        flash("Please log in as a provider to delete your profile.", "error")
        return redirect(url_for("login"))
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if provider and provider["profile_picture"] and os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], provider["profile_picture"])):
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], provider["profile_picture"]))
            logging.info(f"Profile picture deleted: {provider['profile_picture']}, Session: %s", session)
       
        cursor.execute("DELETE FROM providers WHERE user_id = %s", (user_id,))
        conn.commit()
        logging.info(f"Provider profile deleted for user ID {user_id}, Session: %s", session)
        flash("Profile deleted successfully!", "success")
        return redirect(url_for("provider_dashboard"))
    except psycopg2.Error as e:
        logging.error(f"Database error deleting provider for user ID {user_id}: {e}, Session: %s", session)
        flash("Error deleting profile. Please try again.", "error")
        return redirect(url_for("provider_dashboard"))
    finally:
        cursor.close()
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
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT * FROM providers
            WHERE name ILIKE %s OR service_description ILIKE %s OR areas_served ILIKE %s
            """,
            (f"%{query}%", f"%{query}%", f"%{query}%")
        )
        providers = [row_to_dict(provider) for provider in cursor.fetchall()]
        logging.info(f"Search query '{query}' returned {len(providers)} providers, Session: %s", session)
    except psycopg2.Error as e:
        logging.error(f"Database error during search for query '{query}': {e}, Session: %s", session)
        flash("Error searching for providers. Please try again.", "error")
        providers = []
    finally:
        cursor.close()
        conn.close()
   
    return render_template("search_results.html", query=query, providers=providers, web_results=web_results)

@app.route("/get_unread_messages_count")
def get_unread_messages_count():
    if "user_id" not in session:
        logging.warning("Unauthorized access to unread messages count, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    requested_user_id = request.args.get("user_id")
    if not requested_user_id or int(requested_user_id) != user_id:
        logging.warning(f"User ID mismatch: requested {requested_user_id}, session {user_id}")
        return jsonify({"error": "Invalid user ID"}), 400
   
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE receiver_id = %s AND is_read = FALSE
            AND (deleted_for IS NULL OR NOT deleted_for LIKE %s)
            """,
            (user_id, f"%{user_id}%")
        )
        count = cursor.fetchone()[0]
        logging.info(f"Unread messages count for user ID {user_id}: {count}")
        return jsonify({"count": count})
    except psycopg2.Error as e:
        logging.error(f"Database error fetching unread count for user_id {user_id}: {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/get_bookings")
def get_bookings():
    if "user_id" not in session:
        logging.warning("Unauthorized access to get bookings, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    user_role = session.get("user_role")
    provider_id = request.args.get("provider_id")
    customer_id = request.args.get("customer_id")
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)

    if limit <= 0:
        limit = 20
    elif limit > 100:
        limit = 100
    offset = max(0, offset)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if user_role == "provider":
            cursor.execute("SELECT * FROM providers WHERE user_id = %s", (user_id,))
            provider = row_to_dict(cursor.fetchone())
            if not provider:
                logging.warning(f"Provider not found for user ID {user_id}, Session: %s", session)
                return jsonify({"error": "Provider profile not found"}), 404
            cursor.execute(
                "SELECT * FROM bookings WHERE provider_id = %s ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                (provider["id"], limit, offset)
            )
            bookings = cursor.fetchall()
            cursor.execute(
                "SELECT COUNT(*) FROM bookings WHERE provider_id = %s",
                (provider["id"],)
            )
            total = cursor.fetchone()[0]
        elif user_role == "customer":
            if not provider_id or not customer_id:
                logging.warning(f"Missing provider_id or customer_id for customer bookings, Session: %s", session)
                return jsonify({"error": "Provider ID and customer ID required"}), 400
            if int(customer_id) != user_id:
                logging.warning(f"Customer ID mismatch: requested {customer_id}, session {user_id}, Session: %s", session)
                return jsonify({"error": "Unauthorized"}), 403
            customer_email = session.get("user_email")
            if not customer_email:
                logging.warning(f"No customer email in session for user ID {user_id}, Session: %s", session)
                return jsonify({"error": "Customer email not found"}), 400
            cursor.execute(
                "SELECT * FROM bookings WHERE provider_id = %s AND customer_email = %s ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                (provider_id, customer_email, limit, offset)
            )
            bookings = cursor.fetchall()
            cursor.execute(
                "SELECT COUNT(*) FROM bookings WHERE provider_id = %s AND customer_email = %s",
                (provider_id, customer_email)
            )
            total = cursor.fetchone()[0]
        else:
            logging.warning(f"Invalid user role: {user_role}, Session: %s", session)
            return jsonify({"error": "Invalid user role"}), 400
       
        bookings = [row_to_dict(booking) for booking in bookings]
        logging.info(f"Fetched {len(bookings)} of {total} bookings for user ID {user_id}, role {user_role}, provider_id {provider_id}, customer_id {customer_id}, limit {limit}, offset {offset}, Session: %s", session)
        return jsonify({
            "bookings": bookings,
            "total": total,
            "limit": limit,
            "offset": offset
        })
    except psycopg2.Error as e:
        logging.error(f"Database error fetching bookings for user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/confirm_booking/<int:booking_id>", methods=["POST"])
def confirm_booking(booking_id):
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning(f"Unauthorized access to confirm booking_id {booking_id}, Session: {session}")
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: {session}")
            return jsonify({"error": "Provider profile not found"}), 404
       
        cursor.execute("SELECT * FROM bookings WHERE id = %s AND provider_id = %s", (booking_id, provider["id"]))
        booking = row_to_dict(cursor.fetchone())
        if not booking:
            logging.warning(f"Booking ID {booking_id} not found for provider_id {provider['id']}, Session: {session}")
            return jsonify({"error": "Booking not found"}), 404
       
        if booking["status"] != "Pending":
            logging.warning(f"Booking ID {booking_id} not Pending, current status: {booking['status']}, Session: {session}")
            return jsonify({"error": "Booking cannot be confirmed"}), 400
       
        updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "UPDATE bookings SET status = %s, updated_at = %s WHERE id = %s",
            ("Confirmed", updated_at, booking_id)
        )
       
        # Fetch customer user_id for notification
        cursor.execute("SELECT id FROM users WHERE email = %s", (booking["customer_email"],))
        customer = cursor.fetchone()
        if customer:
            customer_user_id = customer['id']
            cursor.execute(
                "INSERT INTO notifications (user_id, type, content, timestamp, is_read) "
                "VALUES (%s, %s, %s, %s, %s)",
                (customer_user_id, "booking_update", f"Your booking (ID: {booking_id}) has been confirmed.", datetime.now(), False)
            )
       
        conn.commit()
       
        notification_result = send_status_update_message(provider["id"], booking["customer_email"], booking_id, "Confirmed", booking["service_date"])
        success = isinstance(notification_result, dict) and notification_result.get("success", False)
        response = {
            "success": True,
            "status": "Confirmed",
            "notification_sent": success,
            "updated_at": updated_at,
            "customer_id": customer_user_id  # Added this line
        }
        if success:
            response["message_id"] = notification_result.get("message_id")
            logging.info(f"Booking ID {booking_id} confirmed, notification sent, message_id: {response['message_id']}, Session: {session}")
        else:
            error_msg = notification_result.get("error", "Unknown error") if isinstance(notification_result, dict) else str(notification_result)
            response["warning"] = f"Failed to notify customer: {error_msg}"
            logging.warning(f"Booking ID {booking_id} confirmed, notification failed: {error_msg}, Session: {session}")
       
        customer_email = booking["customer_email"]
        provider_email = session["user_email"]
        send_booking_confirmed_to_customer(customer_email, provider["name"], provider_email, provider["phone"], booking_id, booking["service_date"])
        send_booking_confirmed_to_provider(provider_email, booking["customer_name"], booking_id, booking["service_date"])
       
        return jsonify(response), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error confirming booking_id {booking_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    except Exception as e:
        conn.rollback()
        logging.error(f"Unexpected error confirming booking_id {booking_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/reject_booking/<int:booking_id>", methods=["POST"])
def reject_booking(booking_id):
    logging.info(f"reject_booking route hit for booking_id {booking_id}, Session: {session}")
   
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning(f"Unauthorized access to reject booking_id {booking_id}, Session: {session}")
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: {session}")
            return jsonify({"error": "Provider profile not found"}), 404
       
        cursor.execute("SELECT * FROM bookings WHERE id = %s AND provider_id = %s", (booking_id, provider["id"]))
        booking = row_to_dict(cursor.fetchone())
        if not booking:
            logging.warning(f"Booking ID {booking_id} not found for provider_id {provider['id']}, Session: {session}")
            return jsonify({"error": "Booking not found"}), 404
       
        if booking["status"] != "Pending":
            logging.warning(f"Booking ID {booking_id} not Pending, current status: {booking['status']}, Session: {session}")
            return jsonify({"error": "Booking cannot be rejected"}), 400

        if not request.is_json:
            return jsonify({"error": "JSON body required"}), 400

        data = request.json
        # FIXED: Accept both key names for robustness
        rejected_reason = (
            data.get("rejected_reason") or
            data.get("rejection_reason") or
            ""
        ).strip() or None
       
        updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "UPDATE bookings SET status = %s, updated_at = %s, rejected_reason = %s WHERE id = %s",
            ("Rejected", updated_at, rejected_reason, booking_id)
        )
       
        # Fetch customer user_id for notification and response
        customer_user_id = None
        cursor.execute("SELECT id FROM users WHERE email = %s", (booking["customer_email"],))
        customer = cursor.fetchone()
        if customer:
            customer_user_id = customer['id']
            cursor.execute(
                "INSERT INTO notifications (user_id, type, content, timestamp, is_read) "
                "VALUES (%s, %s, %s, %s, %s)",
                (customer_user_id, "booking_update", f"Your booking (ID: {booking_id}) has been rejected.", datetime.now(), False)
            )
       
        conn.commit()
       
        notification_result = send_status_update_message(provider["id"], booking["customer_email"], booking_id, "Rejected", booking["service_date"])
        success = isinstance(notification_result, dict) and notification_result.get("success", False)
        response = {
            "success": True,
            "status": "Rejected",
            "notification_sent": success,
            "updated_at": updated_at,
            "customer_id": customer_user_id   # FIXED: include customer_id so frontend chat works
        }
        if success:
            response["message_id"] = notification_result.get("message_id")
            logging.info(f"Booking ID {booking_id} rejected, reason: {rejected_reason}, notification sent, Session: {session}")
        else:
            error_msg = notification_result.get("error", "Unknown error") if isinstance(notification_result, dict) else str(notification_result)
            response["warning"] = f"Failed to notify customer: {error_msg}"
            logging.warning(f"Booking ID {booking_id} rejected, notification failed: {error_msg}, Session: {session}")
       
        customer_email = booking["customer_email"]
        provider_email = session["user_email"]
        send_booking_rejected_to_customer(customer_email, provider["name"], provider_email, provider["phone"], booking_id)
        send_booking_rejected_to_provider(provider_email, booking["customer_name"], booking_id)
       
        return jsonify(response), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error rejecting booking_id {booking_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    except Exception as e:
        conn.rollback()
        logging.error(f"Unexpected error rejecting booking_id {booking_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_recent_rejected_decisions")
def get_recent_rejected_decisions():
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to get_recent_rejected_decisions, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT email, phone FROM users WHERE id = %s", (user_id,))
        user = row_to_dict(cursor.fetchone())
        if not user:
            return jsonify({"error": "User not found"}), 404

        email = user.get('email')
        phone = user.get('phone')
        identifiers = [id for id in [email, phone] if id]
        if not identifiers:
            return jsonify({"success": True, "decisions": []})

        placeholders = ','.join(['%s'] * len(identifiers))
        cursor.execute(
            f"""
            SELECT 
                b.id, 
                b.provider_id, 
                b.customer_name, 
                b.service_date, 
                b.status, 
                b.updated_at,
                COALESCE(b.rejected_reason, 'No reason provided') AS rejected_reason,
                p.name AS provider_name
            FROM bookings b
            JOIN providers p ON b.provider_id = p.id
            WHERE (b.customer_email IN ({placeholders}) OR b.customer_phone IN ({placeholders}))
              AND b.status = 'Rejected'
            ORDER BY b.updated_at DESC
            LIMIT 10
            """,
            identifiers * 2
        )
        decisions = [row_to_dict(row) for row in cursor.fetchall()]
        logging.info(f"Recent Rejected decisions returned for user_id {user_id}: {len(decisions)} decisions")
        return jsonify({"success": True, "decisions": decisions})
    except psycopg2.Error as e:
        logging.error(f"Database error in get_recent_rejected_decisions for user_id {user_id}: {e}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/reschedule_booking/<int:booking_id>", methods=["POST"])
def reschedule_booking(booking_id):
    logging.info(f"reschedule_booking route hit for booking_id {booking_id}, Session: {session}")
   
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning(f"Unauthorized access to reschedule booking_id {booking_id}, Session: {session}")
        return jsonify({"error": "Unauthorized"}), 401
   
    new_service_date = request.json.get("new_service_date")
    if not new_service_date:
        logging.warning(f"No new_service_date provided for booking_id {booking_id}, Session: {session}")
        return jsonify({"error": "New service date required"}), 400
   
    try:
        datetime.strptime(new_service_date, "%Y-%m-%d %H:%M")
    except ValueError:
        logging.warning(f"Invalid new_service_date format: {new_service_date} for booking_id {booking_id}, Session: {session}")
        return jsonify({"error": "Invalid date format, use YYYY-MM-DD HH:MM"}), 400
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: {session}")
            return jsonify({"error": "Provider profile not found"}), 404
       
        cursor.execute("SELECT * FROM bookings WHERE id = %s AND provider_id = %s", (booking_id, provider["id"]))
        booking = row_to_dict(cursor.fetchone())
        if not booking:
            logging.warning(f"Booking ID {booking_id} not found for provider_id {provider['id']}, Session: {session}")
            return jsonify({"error": "Booking not found"}), 404
       
        if booking["status"] not in ["Pending", "Confirmed"]:
            logging.warning(f"Booking ID {booking_id} not in Pending or Confirmed status, current status: {booking['status']}, Session: {session}")
            return jsonify({"error": "Booking cannot be rescheduled"}), 400
       
        updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "UPDATE bookings SET service_date = %s, rescheduled_date = %s, status = %s, updated_at = %s WHERE id = %s",
            (new_service_date, new_service_date, "Rescheduled", updated_at, booking_id)
        )
       
        # Insert notification for customer
        cursor.execute("SELECT id FROM users WHERE email = %s", (booking["customer_email"],))
        customer = cursor.fetchone()
        if customer:
            customer_user_id = customer['id']
            cursor.execute(
                "INSERT INTO notifications (user_id, type, content, timestamp, is_read) "
                "VALUES (%s, %s, %s, %s, %s)",
                (customer_user_id, "booking_update", f"Your booking (ID: {booking_id}) has been rescheduled to {new_service_date}.", datetime.now(), False)
            )
       
        conn.commit()
       
        notification_result = send_status_update_message(provider["id"], booking["customer_email"], booking_id, "Rescheduled", booking["service_date"], new_service_date)
        success = isinstance(notification_result, dict) and notification_result.get("success", False)
        response = {
            "success": True,
            "status": "Rescheduled",
            "new_service_date": new_service_date,
            "notification_sent": success,
            "updated_at": updated_at
        }
        if success:
            response["message_id"] = notification_result.get("message_id")
            logging.info(f"Booking ID {booking_id} rescheduled, notification sent, message_id: {response['message_id']}, Session: {session}")
        else:
            error_msg = notification_result.get("error", "Unknown error") if isinstance(notification_result, dict) else str(notification_result)
            response["warning"] = f"Failed to notify customer: {error_msg}"
            logging.warning(f"Booking ID {booking_id} rescheduled, notification failed: {error_msg}, Session: {session}")
       
        # Fetch customer_id for chat
        cursor.execute("SELECT customer_email FROM bookings WHERE id = %s", (booking_id,))
        customer_email = cursor.fetchone()['customer_email']
        cursor.execute("SELECT id FROM users WHERE email = %s", (customer_email,))
        customer = cursor.fetchone()
        response["customer_id"] = customer['id'] if customer else None

        customer_email = booking["customer_email"]
        provider_email = session["user_email"]
        send_booking_rescheduled_to_customer(customer_email, provider["name"], provider_email, provider["phone"], booking_id, booking["service_date"], new_service_date)
        send_booking_rescheduled_to_provider(provider_email, booking["customer_name"], booking_id, booking["service_date"], new_service_date)
       
        return jsonify(response), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error rescheduling booking_id {booking_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    except Exception as e:
        conn.rollback()
        logging.error(f"Unexpected error rescheduling booking_id {booking_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/get_customer_bookings")
def get_customer_bookings():
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to get customer bookings, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    customer_email = session.get("user_email")
    if not customer_email:
        logging.warning(f"No customer email in session for user ID {user_id}, Session: %s", session)
        return jsonify({"error": "Customer email not found"}), 400
   
    conn = get_db_connection()
    try:
        check_and_fix_bookings_schema(conn)
       
        bookings = conn.execute(
            """
            SELECT b.id, b.provider_id, b.customer_name, b.customer_phone, b.customer_email,
                   b.location, b.service_date, b.rescheduled_date, b.status, b.created_at, b.updated_at, p.name AS provider_name
            FROM bookings b
            LEFT JOIN providers p ON b.provider_id = p.id
            WHERE b.customer_email = ?
            ORDER BY b.updated_at DESC
            """,
            (customer_email,)
        ).fetchall()
       
        if not bookings:
            logging.info(f"No bookings found for customer email {customer_email}, Session: %s", session)
            return jsonify({"bookings": [], "message": "No bookings found for this customer"})
       
        bookings_list = []
        for booking in bookings:
            booking_dict = row_to_dict(booking)
            if 'status' not in booking_dict or booking_dict['status'] is None:
                booking_dict['status'] = 'Pending'
                logging.warning(f"Booking ID {booking_dict['id']} had missing/null status, defaulted to 'Pending', Session: %s", session)
            bookings_list.append(booking_dict)
       
        logging.info(f"Fetched {len(bookings_list)} bookings for customer email {customer_email}, Session: %s", session)
        return jsonify({"bookings": bookings_list, "success": True})
    except sqlite3.Error as e:
        logging.error(f"Database error fetching bookings for customer email {customer_email}: {e}, Session: %s", session)
        return jsonify({"error": "Error loading booking status", "details": str(e)}), 500
    finally:
        conn.close()

@app.route("/get_booking_customer/<int:booking_id>")
def get_booking_customer(booking_id):
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning(f"Unauthorized access to get_booking_customer for booking_id {booking_id}, Session: {session}")
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch provider to verify ownership
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: {session}")
            return jsonify({"error": "Provider profile not found"}), 404

        # Fetch booking details
        cursor.execute(
            "SELECT customer_email, customer_phone FROM bookings WHERE id = %s AND provider_id = %s",
            (booking_id, provider["id"])
        )
        booking = row_to_dict(cursor.fetchone())
        if not booking:
            logging.warning(f"Booking ID {booking_id} not found for provider_id {provider['id']}, Session: {session}")
            return jsonify({"error": "Booking not found"}), 404

        # Fetch customer user_id using email or phone
        cursor.execute(
            "SELECT id FROM users WHERE email = %s OR phone = %s",
            (booking["customer_email"], booking["customer_phone"])
        )
        customer = row_to_dict(cursor.fetchone())

        # If no customer user exists, create one for chat purposes
        if not customer:
            # Use email as primary if available, else phone
            new_email = booking["customer_email"] if booking["customer_email"] else f"{booking['customer_phone']}@temp.example.com"
            new_phone = booking["customer_phone"] if booking["customer_phone"] else None
            dummy_password_hash = generate_password_hash('')  # Dummy hash for chat-only user
            cursor.execute(
                """
                INSERT INTO users (email, phone, password, role, is_verified, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (new_email, new_phone, dummy_password_hash, 'customer', True, 'active', datetime.now())
            )
            new_customer = row_to_dict(cursor.fetchone())
            if new_customer:
                customer = new_customer
                logging.info(f"Created temp user for customer in booking {booking_id}: ID {customer['id']}, email {new_email}, Session: {session}")
            else:
                logging.error(f"Failed to create temp user for booking {booking_id}, Session: {session}")
                return jsonify({"error": "Failed to create customer record"}), 500
        else:
            logging.info(f"Found existing customer for booking {booking_id}: ID {customer['id']}, Session: {session}")

        logging.info(f"Customer ID {customer['id']} fetched/created for booking_id {booking_id}, Session: {session}")
        return jsonify({"success": True, "customer_id": customer["id"]}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error in get_booking_customer for booking_id {booking_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/get_booking_status")
def get_booking_status():
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to get_booking_status, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    customer_email = session.get("user_email")
    if not customer_email:
        logging.warning(f"No customer email in session for user ID {user_id}, Session: %s", session)
        return jsonify({"error": "Customer email not found"}), 400
   
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT b.id, b.provider_id, b.customer_name, b.customer_phone, b.customer_email,
                   b.location, b.service_date, b.rescheduled_date, b.status, b.created_at, b.updated_at,
                   p.name AS provider_name, p.service_description AS service
            FROM bookings b
            LEFT JOIN providers p ON b.provider_id = p.id
            WHERE b.customer_email = %s
            AND b.status IN ('Confirmed', 'Rescheduled')
            ORDER BY b.updated_at DESC
            """,
            (customer_email,)
        )
        bookings = [dict(row) for row in cursor.fetchall()]
        if not bookings:
            logging.info(f"No bookings found for customer email {customer_email} in get_booking_status, Session: %s", session)
            return jsonify({"bookings": [], "success": True})
       
        logging.info(f"Fetched {len(bookings)} bookings for customer email {customer_email} in get_booking_status, Session: %s", session)
       
        for booking in bookings:
            if 'status' not in booking or booking['status'] is None:
                booking['status'] = 'Pending'
                logging.warning(f"Booking ID {booking['id']} had missing/null status, defaulted to 'Pending', Session: %s", session)
        return jsonify({"bookings": bookings, "success": True})
    except psycopg2.Error as e:
        logging.error(f"Database error fetching bookings for customer email {customer_email} in get_booking_status: {e}, Session: %s", session)
        return jsonify({"error": "Error loading booking status", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/delete_booking/<int:booking_id>", methods=["POST"])
def delete_booking(booking_id):
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to delete booking, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    customer_email = session.get("user_email")
    if not customer_email:
        logging.warning(f"No customer email found in session for user ID {user_id}, Session: %s", session)
        return jsonify({"error": "Customer email not found"}), 400
   
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        conn.execute("BEGIN")  # Explicit transaction for atomicity
       
        # Verify booking belongs to customer (uses index on customer_email)
        cursor.execute(
            "SELECT id FROM bookings WHERE id = %s AND customer_email = %s FOR UPDATE",
            (booking_id, customer_email)
        )
        booking = row_to_dict(cursor.fetchone())
        if not booking:
            logging.warning(f"Booking ID {booking_id} not found for customer email {customer_email}, Session: %s", session)
            return jsonify({"error": "Booking not found"}), 404
       
        # Delete the booking (fast DELETE with index on id)
        cursor.execute(
            "DELETE FROM bookings WHERE id = %s AND customer_email = %s",
            (booking_id, customer_email)
        )
        if cursor.rowcount == 0:
            logging.warning(f"No rows deleted for booking ID {booking_id} and customer email {customer_email}, Session: %s", session)
            return jsonify({"error": "Failed to delete booking"}), 500
       
        conn.commit()
        logging.info(f"Booking ID {booking_id} deleted by customer email {customer_email}, Session: %s", session)
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting booking ID {booking_id} for customer email {customer_email}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/provider_delete_booking/<int:booking_id>", methods=["POST"])
def provider_delete_booking(booking_id):
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to provider delete booking, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify provider exists
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider["id"]
       
        # Check if booking exists and belongs to provider
        cursor.execute(
            "SELECT * FROM bookings WHERE id = %s AND provider_id = %s",
            (booking_id, provider_id)
        )
        booking = row_to_dict(cursor.fetchone())
        if not booking:
            logging.warning(f"Booking ID {booking_id} not found for provider_id {provider_id}, Session: %s", session)
            return jsonify({"error": "Booking not found"}), 404
       
        # Delete the booking
        cursor.execute("DELETE FROM bookings WHERE id = %s AND provider_id = %s", (booking_id, provider_id))
        if cursor.rowcount == 0:
            logging.warning(f"No rows deleted for booking ID {booking_id}, provider_id {provider_id}, Session: %s", session)
            return jsonify({"error": "Failed to delete booking"}), 500
       
        conn.commit()
        logging.info(f"Booking ID {booking_id} deleted by provider_id {provider_id}, Session: %s", session)
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting booking ID {booking_id} for provider_id {provider_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/provider_delete_all_bookings", methods=["POST"])
def provider_delete_all_bookings():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to provider delete all bookings, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify provider exists
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider["id"]
       
        # Delete all bookings for this provider
        cursor.execute("DELETE FROM bookings WHERE provider_id = %s", (provider_id,))
        deleted_count = cursor.rowcount
       
        conn.commit()
        logging.info(f"All bookings ({deleted_count}) deleted for provider_id {provider_id}, Session: %s", session)
        return jsonify({"success": True, "deleted_count": deleted_count})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting all bookings for provider_id {provider_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
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
        users = conn.execute("SELECT id, email, role FROM users WHERE id != ?", (user_id,)).fetchall()
        for user in users:
            other_user_id = user["id"]
            # Set other_user_name based on role
            if user["role"] == "admin":
                other_user_name = "ADMINISTRATOR"
            else:
                other_user_name = user["email"]
            other_user_role = user["role"]

            message_count = conn.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
                """,
                (user_id, other_user_id, other_user_id, user_id)
            ).fetchone()[0]

            if message_count > 0:
                unread_count = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE sender_id = ? AND receiver_id = ? AND is_read = 0",
                    (other_user_id, user_id)
                ).fetchone()[0]
                conversations.append({
                    "other_user_id": other_user_id,
                    "other_user_name": other_user_name,
                    "other_user_role": other_user_role,
                    "unread_count": unread_count
                })
        logging.info(f"Fetched {len(conversations)} conversations for user ID {user_id}, Session: %s", session)
        return jsonify({"conversations": conversations})
    except sqlite3.Error as e:
        logging.error(f"Database error fetching conversations for user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@app.route("/get_conversation", defaults={"receiver_id": None})
@app.route("/get_conversation/<int:receiver_id>")
def get_conversation(receiver_id):
    # Accept receiver_id from EITHER path param (/get_conversation/5)
    # OR query param (/get_conversation?receiver_id=5)
    # The frontend sends query params, so this dual-route fix is the core of the bug fix.
    if receiver_id is None:
        receiver_id = request.args.get("receiver_id", type=int)
    if not receiver_id:
        return jsonify({"error": "Receiver ID required"}), 400

    if "user_id" not in session:
        logging.warning("Unauthorized access to get_conversation, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Verify receiver exists
        cursor.execute(
            "SELECT email FROM users WHERE id = %s",
            (receiver_id,)
        )
        other_user = row_to_dict(cursor.fetchone())

        if not other_user:
            return jsonify({"error": "Conversation user not found"}), 404

        other_user_name = other_user["email"]

        # Always use canonical conversation order (min/max)
        canonical_min = min(user_id, receiver_id)
        canonical_max = max(user_id, receiver_id)

        # Fetch the canonical conversation
        cursor.execute("""
            SELECT id
            FROM conversations
            WHERE user1_id = %s AND user2_id = %s
        """, (canonical_min, canonical_max))

        conversation_row = row_to_dict(cursor.fetchone())

        # If no conversation exists yet, return empty state (no error)
        if not conversation_row:
            return jsonify({
                "messages": [],
                "other_user_name": other_user_name,
                "session_user_id": user_id,
                "user_role": session.get("user_role"),
                "is_empty": True,
                "conversation_id": None,
                "unread_count": 0,
                "marked_read_count": 0
            })

        conversation_id = conversation_row["id"]

        # SECURITY CHECK: ensure the current user is actually a participant
        cursor.execute("""
            SELECT id
            FROM conversations
            WHERE id = %s
              AND (user1_id = %s OR user2_id = %s)
        """, (conversation_id, user_id, user_id))

        ownership_check = cursor.fetchone()

        if not ownership_check:
            logging.warning(
                f"Blocked unauthorized conversation access. user_id={user_id}, conversation_id={conversation_id}"
            )
            return jsonify({"error": "Unauthorized conversation access"}), 403

        # ── CORE FIX: Mark all unread messages sent TO the current user as read ──
        cursor.execute("""
            UPDATE messages
            SET is_read = TRUE
            WHERE receiver_id = %s
              AND sender_id = %s
              AND conversation_id = %s
              AND is_read = FALSE
        """, (user_id, receiver_id, conversation_id))

        affected_rows = cursor.rowcount

        # Also mark related new_message notifications as read for this user
        cursor.execute("""
            UPDATE notifications
            SET is_read = TRUE
            WHERE user_id = %s
              AND sender_id = %s
              AND type = 'new_message'
              AND is_read = FALSE
        """, (user_id, receiver_id))

        # Commit the read-status updates to the database immediately
        conn.commit()

        # Fetch messages for this conversation, filtering out ones deleted for this user
        cursor.execute("""
            SELECT m.*, u.email AS sender_email, u.role AS sender_role
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.conversation_id = %s
              AND (
                    m.deleted_for IS NULL
                    OR m.deleted_for = ''
                    OR NOT (',' || m.deleted_for || ',') LIKE %s
                  )
            ORDER BY m.timestamp ASC
        """, (conversation_id, f'%,{user_id},%'))

        messages = [row_to_dict(row) for row in cursor.fetchall()]

        # Fetch remaining unread count AFTER the update (should be 0 for this conversation)
        cursor.execute("""
            SELECT COUNT(*)
            FROM messages
            WHERE receiver_id = %s
              AND is_read = FALSE
              AND conversation_id = %s
        """, (user_id, conversation_id))

        unread_count = cursor.fetchone()[0]

        logging.info(
            f"get_conversation: user_id={user_id} opened conversation_id={conversation_id} "
            f"with receiver_id={receiver_id}. Marked {affected_rows} messages as read. "
            f"Remaining unread: {unread_count}"
        )

        return jsonify({
            "messages": messages,
            "other_user_name": other_user_name,
            "session_user_id": user_id,
            "user_role": session.get("user_role"),
            "is_empty": len(messages) == 0,
            "conversation_id": conversation_id,
            "unread_count": unread_count,
            "marked_read_count": affected_rows
        })

    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error in get_conversation for user_id={user_id}, receiver_id={receiver_id}: {str(e)}")
        return jsonify({
            "error": "Database error",
            "details": str(e)
        }), 500

    finally:
        cursor.close()
        conn.close()

@app.route("/send_message", methods=["POST"])
def send_message():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    receiver_id = request.form.get("receiver_id")
    provider_id = request.form.get("provider_id")  # Optional from customer dashboard
    message_text = request.form.get("message", "").strip()
    media_file = request.files.get("media_file")

    if not receiver_id and not provider_id:
        return jsonify({"error": "Receiver ID or Provider ID required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Determine receiver_id
        if provider_id and not receiver_id:
            provider_id = int(provider_id)
            cursor.execute("SELECT user_id FROM providers WHERE id = %s", (provider_id,))
            provider = cursor.fetchone()
            if not provider:
                return jsonify({"error": "Provider not found"}), 404
            receiver_id = provider['user_id']
        else:
            receiver_id = int(receiver_id)

        cursor.execute("SELECT id FROM users WHERE id = %s", (receiver_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Receiver not found"}), 404

        # === CANONICAL CONVERSATION (min/max) + LEGACY SWAP MERGE ===
        canonical_min = min(user_id, receiver_id)
        canonical_max = max(user_id, receiver_id)

        # Get or create canonical conversation
        cursor.execute("""
            SELECT id FROM conversations
            WHERE user1_id = %s AND user2_id = %s
            LIMIT 1
        """, (canonical_min, canonical_max))
        conversation = cursor.fetchone()
        if conversation:
            conversation_id = conversation['id']
        else:
            # Check for swapped legacy conversation
            cursor.execute("""
                SELECT id FROM conversations
                WHERE user1_id = %s AND user2_id = %s
                LIMIT 1
            """, (canonical_max, canonical_min))
            swapped = cursor.fetchone()
            if swapped:
                swapped_id = swapped['id']
                # Move all messages from swapped to canonical (after creating it)
                cursor.execute("""
                    INSERT INTO conversations (user1_id, user2_id)
                    VALUES (%s, %s) RETURNING id
                """, (canonical_min, canonical_max))
                conversation_id = cursor.fetchone()['id']
                # Merge messages
                cursor.execute("""
                    UPDATE messages
                    SET conversation_id = %s
                    WHERE conversation_id = %s
                """, (conversation_id, swapped_id))
                # Delete swapped conversation
                cursor.execute("DELETE FROM conversations WHERE id = %s", (swapped_id,))
                logging.info(f"Merged swapped conversation {swapped_id} → canonical {conversation_id}")
            else:
                # No swapped → just create canonical
                cursor.execute("""
                    INSERT INTO conversations (user1_id, user2_id)
                    VALUES (%s, %s) RETURNING id
                """, (canonical_min, canonical_max))
                conversation_id = cursor.fetchone()['id']

        # === MEDIA HANDLING (unchanged) ===
        media_path = None
        media_type = None
        if media_file and allowed_file(media_file.filename):
            filename = secure_filename(media_file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{filename}"
            media_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            media_path = filename
            ext = filename.rsplit('.', 1)[1].lower()
            media_type = {'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'mp4': 'video', 'mov': 'video', 'wav': 'audio', 'mp3': 'audio', 'webm': 'audio'}.get(ext)

        if not message_text and not media_path:
            return jsonify({"error": "Message or media required"}), 400

        # Insert message with canonical conversation_id
        cursor.execute("""
            INSERT INTO messages (sender_id, receiver_id, message, media_type, media_path, conversation_id, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING *
        """, (user_id, receiver_id, escape(message_text), media_type, media_path, conversation_id))
        inserted_message = row_to_dict(cursor.fetchone())

        conn.commit()
        logging.info(f"Message sent: ID {inserted_message['id']}, Sender {user_id}, Receiver {receiver_id}, Conversation {conversation_id}")

        # Email notification (unchanged)
        cursor.execute("SELECT email, role FROM users WHERE id = %s", (user_id,))
        sender = row_to_dict(cursor.fetchone())
        cursor.execute("SELECT email, role FROM users WHERE id = %s", (receiver_id,))
        receiver = row_to_dict(cursor.fetchone())

        if receiver and receiver['email']:
            sender_name = sender['email'] if sender['role'] != 'admin' else 'Administrator'
            receiver_name = receiver['email'] if receiver['role'] != 'admin' else 'Administrator'
            subject = f"New Message from {sender_name}"
            plain_body = f"""
Dear {receiver_name},

You have a new message from {sender_name}:

"{message_text[:100]}{'...' if len(message_text) > 100 else ''}"

Log in to your dashboard using this link to view the full conversation: www.findservice.live

Best regards,
Your Service Platform
"""
            html_body = f"""
<html>
<body>
    <h2>New Message</h2>
    <p>Dear {receiver_name},</p>
    <p>You have a new message from <strong>{sender_name}</strong>:</p>
    <blockquote>"{escape(message_text)}"</blockquote>
    <p>Log in to your dashboard using this link to view the full conversation: <a href="https://www.findservice.live">www.findservice.live</a></p>
    <p>Best regards,<br>Your Service Platform</p>
</body>
</html>
"""
            send_email(receiver['email'], subject, plain_body, html_body)

        return jsonify({"success": True, "message": inserted_message})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error in send_message: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/delete_message/<int:message_id>", methods=["POST"])
def delete_message(message_id):
    if "user_id" not in session:
        logging.warning("Unauthorized access to delete message, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    retries = 3
    delay = 1
    attempt = 0
    while attempt < retries:
        conn = get_db_connection()
        conn.execute("BEGIN TRANSACTION")
        try:
            message = row_to_dict(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())
            if not message:
                logging.warning(f"Message ID {message_id} not found for deletion, Session: %s", session)
                return jsonify({"error": "Message not found"}), 404
           
            if message["sender_id"] != user_id and message["receiver_id"] != user_id:
                logging.warning(f"User ID {user_id} not authorized to delete message ID {message_id}, Session: %s", session)
                return jsonify({"error": "Unauthorized to delete this message"}), 403
           
            if message["media_path"]:
                media_file_path = os.path.join(app.config["UPLOAD_FOLDER"], message["media_path"])
                if os.path.exists(media_file_path):
                    try:
                        os.remove(media_file_path)
                        logging.info(f"Media file deleted for message ID {message_id}: {message['media_path']}, Session: %s", session)
                    except OSError as e:
                        logging.error(f"Failed to delete media file for message ID {message_id}: {message['media_path']}, Error: {str(e)}, Session: %s", session)
                        return jsonify({"error": "Failed to delete media file", "details": str(e)}), 500
           
            conversation_id = message["conversation_id"]
            conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
           
            remaining_messages = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,)
            ).fetchone()[0]

            is_conversation_empty = remaining_messages == 0
            if is_conversation_empty:
                conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
                logging.info(f"Conversation ID {conversation_id} deleted as it has no remaining messages, Session: %s", session)

            conn.commit()
            logging.info(f"Message ID {message_id} deleted by user ID {user_id}, Conversation empty: {is_conversation_empty}, Session: %s", session)
            return jsonify({
                "success": True,
                "receiver_id": message["receiver_id"],
                "is_conversation_empty": is_conversation_empty
            })

        except sqlite3.OperationalError as e:
            conn.rollback()
            if "database is locked" in str(e) and attempt < retries - 1:
                logging.warning(f"Database locked deleting message ID {message_id}, attempt {attempt + 1}. Retrying in {delay} seconds..., Session: %s", session)
                time.sleep(delay * (2 ** attempt) + random.uniform(0, 0.1))
                attempt += 1
                continue
            logging.error(f"Database error deleting message ID {message_id}, attempt {attempt + 1}: {e}, Session: %s", session)
            return jsonify({"error": "Database error", "details": str(e)}), 500

        except sqlite3.Error as e:
            conn.rollback()
            logging.error(f"Database error deleting message ID {message_id}, attempt {attempt + 1}: {e}, Session: %s", session)
            return jsonify({"error": "Database error", "details": str(e)}), 500

        finally:
            conn.close()

    logging.error(f"Failed to delete message ID {message_id} after {retries} attempts, Session: %s", session)
    return jsonify({"error": f"Failed after {retries} attempts"}), 500

@app.route("/react_message/<int:message_id>", methods=["POST"])
def react_message(message_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    reaction = request.form.get("reaction")
    if not reaction:
        return jsonify({"error": "Reaction required"}), 400
   
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check message existence and get details in one query
        cursor.execute(
            """
            SELECT sender_id, receiver_id, message
            FROM messages
            WHERE id = %s AND (sender_id = %s OR receiver_id = %s)
            """,
            (message_id, user_id, user_id)
        )
        message = cursor.fetchone()
        if not message:
            return jsonify({"error": "Message not found or unauthorized"}), 404
       
        # Update reaction
        cursor.execute(
            "UPDATE messages SET reaction = %s WHERE id = %s RETURNING id",
            (reaction, message_id)
        )
        if cursor.fetchone() is None:
            return jsonify({"error": "Failed to update reaction"}), 500
       
        # Fetch sender's email for notification content
        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        sender = cursor.fetchone()
        sender_name = sender['email'] if sender else 'Unknown'
       
        # Create detailed notification content with message snippet
        snippet = message['message'][:20] + '...' if len(message['message']) > 20 else message['message']
        notification_content = f"{sender_name} reacted with {reaction} to '{snippet}'"
       
        # Determine the recipient (other user in the conversation)
        other_user_id = message['sender_id'] if message['receiver_id'] == user_id else message['receiver_id']
       
        # Insert notification with sender_id for frontend navigation
        cursor.execute(
            """
            INSERT INTO notifications (user_id, type, content, sender_id, timestamp, is_read)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (other_user_id, "reaction", notification_content, user_id, datetime.now(), False)
        )
       
        conn.commit()
        logging.info(f"Reaction added to message ID {message_id} and notification sent to user ID {other_user_id}")
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error reacting to message ID {message_id}: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
   
    logging.error(f"Failed to react to message ID {message_id} after {retries} attempts, Session: %s", session)
    return jsonify({"error": f"Failed after {retries} attempts"}), 500

@app.route("/remove_reaction/<int:message_id>", methods=["POST"])
def remove_reaction(message_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check message existence and authorization
        cursor.execute(
            """
            SELECT sender_id, receiver_id, reaction
            FROM messages
            WHERE id = %s AND (sender_id = %s OR receiver_id = %s)
            """,
            (message_id, user_id, user_id)
        )
        message = cursor.fetchone()
        if not message:
            return jsonify({"error": "Message not found or unauthorized"}), 404
        if not message['reaction']:
            return jsonify({"success": True, "message": "No reaction to remove"})
       
        # Remove reaction
        cursor.execute(
            "UPDATE messages SET reaction = NULL WHERE id = %s RETURNING id",
            (message_id,)
        )
        if cursor.fetchone() is None:
            return jsonify({"error": "Failed to remove reaction"}), 500
       
        conn.commit()
       
        # Send notification to the other user
        other_user_id = message['sender_id'] if message['receiver_id'] == user_id else message['receiver_id']
        cursor.execute(
            "INSERT INTO notifications (user_id, type, content, timestamp, is_read) "
            "VALUES (%s, %s, %s, %s, %s)",
            (other_user_id, "reaction", f"Reaction Removed from your message", datetime.now(), False)
        )
        conn.commit()
       
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error removing reaction from message ID {message_id}: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()



    logging.error(f"Failed to remove reaction from message ID {message_id} after {retries} attempts, Session: %s", session)
    return jsonify({"error": f"Failed after {retries} attempts"}), 500

@app.route("/pin_message/<int:message_id>", methods=["POST"])
def pin_message(message_id):
    if "user_id" not in session:
        logging.warning("Unauthorized access to pin message, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    retries = 3
    delay = 1
    attempt = 0
    while attempt < retries:
        conn = get_db_connection()
        conn.execute("BEGIN TRANSACTION")
        try:
            message = row_to_dict(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())
            if not message:
                logging.warning(f"Message ID {message_id} not found for pinning, Session: %s", session)
                return jsonify({"error": "Message not found"}), 404
           
            if message["sender_id"] != user_id and message["receiver_id"] != user_id:
                logging.warning(f"User ID {user_id} not authorized to pin message ID {message_id}, Session: %s", session)
                return jsonify({"error": "Unauthorized to pin this message"}), 403
           
            current_pinned = message["is_pinned"]
            new_pinned_state = 1 - current_pinned
            conn.execute(
                "UPDATE messages SET is_pinned = ? WHERE id = ?",
                (new_pinned_state, message_id)
            )
            conn.commit()
            logging.info(f"Message ID {message_id} pin toggled to {new_pinned_state} by user ID {user_id}, Session: %s", session)
            return jsonify({"success": True, "is_pinned": new_pinned_state})

        except sqlite3.OperationalError as e:
            conn.rollback()
            if "database is locked" in str(e) and attempt < retries - 1:
                logging.warning(f"Database locked pinning message ID {message_id}, attempt {attempt + 1}. Retrying in {delay} seconds..., Session: %s", session)
                time.sleep(delay * (2 ** attempt) + random.uniform(0, 0.1))
                attempt += 1
                continue
            logging.error(f"Database error pinning message ID {message_id}, attempt {attempt + 1}: {e}, Session: %s", session)
            return jsonify({"error": "Database error", "details": str(e)}), 500

        except sqlite3.Error as e:
            conn.rollback()
            logging.error(f"Database error pinning message ID {message_id}, attempt {attempt + 1}: {e}, Session: %s", session)
            return jsonify({"error": "Database error", "details": str(e)}), 500

        finally:
            conn.close()

    logging.error(f"Failed to pin message ID {message_id} after {retries} attempts, Session: %s", session)
    return jsonify({"error": f"Failed after {retries} attempts"}), 500

@app.route("/star_message/<int:message_id>", methods=["POST"])
def star_message(message_id):
    if "user_id" not in session:
        logging.warning("Unauthorized access to star message, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    retries = 3
    delay = 1
    attempt = 0
    while attempt < retries:
        conn = get_db_connection()
        conn.execute("BEGIN TRANSACTION")
        try:
            message = row_to_dict(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())
            if not message:
                logging.warning(f"Message ID {message_id} not found for starring, Session: %s", session)
                return jsonify({"error": "Message not found"}), 404
           
            if message["sender_id"] != user_id and message["receiver_id"] != user_id:
                logging.warning(f"User ID {user_id} not authorized to star message ID {message_id}, Session: %s", session)
                return jsonify({"error": "Unauthorized to star this message"}), 403
           
            current_starred = message["is_starred"]
            new_starred_state = 1 - current_starred
            conn.execute(
                "UPDATE messages SET is_starred = ? WHERE id = ?",
                (new_starred_state, message_id)
            )
            conn.commit()
            logging.info(f"Message ID {message_id} star toggled to {new_starred_state} by user ID {user_id}, Session: %s", session)
            return jsonify({"success": True, "is_starred": new_starred_state})

        except sqlite3.OperationalError as e:
            conn.rollback()
            if "database is locked" in str(e) and attempt < retries - 1:
                logging.warning(f"Database locked starring message ID {message_id}, attempt {attempt + 1}. Retrying in {delay} seconds..., Session: %s", session)
                time.sleep(delay * (2 ** attempt) + random.uniform(0, 0.1))
                attempt += 1
                continue
            logging.error(f"Database error starring message ID {message_id}, attempt {attempt + 1}: {e}, Session: %s", session)
            return jsonify({"error": "Database error", "details": str(e)}), 500

        except sqlite3.Error as e:
            conn.rollback()
            logging.error(f"Database error starring message ID {message_id}, attempt {attempt + 1}: {e}, Session: %s", session)
            return jsonify({"error": "Database error", "details": str(e)}), 500

        finally:
            conn.close()

    logging.error(f"Failed to star message ID {message_id} after {retries} attempts, Session: %s", session)
    return jsonify({"error": f"Failed after {retries} attempts"}), 500

@app.route("/inbox")
def inbox():
    if "user_id" not in session:
        logging.warning("Unauthorized access to inbox, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
   
    try:
        # FIX: Include user1_id and user2_id explicitly (for integrity)
        cursor.execute("""
            SELECT
                c.id AS conversation_id,
                c.user1_id,
                c.user2_id,
                CASE
                    WHEN c.user1_id = %s THEN u2.email
                    ELSE u1.email
                END AS other_user_name,
                CASE
                    WHEN c.user1_id = %s THEN u2.role
                    ELSE u1.role
                END AS other_user_role,
                CASE
                    WHEN c.user1_id = %s THEN c.user2_id
                    ELSE c.user1_id
                END AS other_user_id
            FROM conversations c
            JOIN users u1 ON c.user1_id = u1.id
            JOIN users u2 ON c.user2_id = u2.id
            WHERE (c.user1_id = %s OR c.user2_id = %s)
            ORDER BY c.id
        """, (user_id, user_id, user_id, user_id, user_id))

        conversations = [dict(row) for row in cursor.fetchall()]

        formatted_conversations = []
        total_unread = 0

        for conv in conversations:

            # Latest message
            cursor.execute("""
                SELECT message, timestamp
                FROM messages m
                WHERE m.conversation_id = %s
                AND (m.deleted_for IS NULL OR NOT (',' || m.deleted_for || ',') LIKE %s)
                ORDER BY m.timestamp DESC
                LIMIT 1
            """, (conv['conversation_id'], f'%,{user_id},%'))

            lm = dict(cursor.fetchone() or {'message': None, 'timestamp': None})

            # Unread count
            cursor.execute("""
                SELECT COUNT(*)
                FROM messages
                WHERE conversation_id = %s
                AND receiver_id = %s
                AND is_read = FALSE
                AND (deleted_for IS NULL OR NOT (',' || deleted_for || ',') LIKE %s)
            """, (conv['conversation_id'], user_id, f'%,{user_id},%'))

            unread_count = cursor.fetchone()[0]
            total_unread += unread_count

            # FIX: Use already computed values — DO NOT recompute
            other_user_id = conv["other_user_id"]
            other_user_name = "ADMINISTRATOR" if conv["other_user_role"] == "admin" else conv["other_user_name"]

            formatted_conversations.append({
                "conversation_id": conv["conversation_id"],
                "other_user_id": other_user_id,
                "other_user_name": other_user_name,
                "unread_count": unread_count,
                "latest_message": lm["message"] or "No messages yet"
            })

        logging.info(f"Inbox fetched for user ID {user_id}: {len(formatted_conversations)} conversations")

        return jsonify({
            "conversations": formatted_conversations,
            "unread_count": total_unread
        })

    except Exception as e:
        logging.error(f"Inbox error: {str(e)}")
        return jsonify({"error": "Failed to fetch inbox"}), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/get_unread_count")
def get_unread_count():
    if "user_id" not in session:
        logging.warning("Unauthorized access to unread count, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    retries = 3
    delay = 1
    attempt = 0
    while attempt < retries:
        conn = get_db_connection()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0",
                (user_id,)
            ).fetchone()[0]
            logging.info(f"Unread count fetched for user ID {user_id}: {count}, Session: %s", session)
            return jsonify({"count": count})
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                logging.warning(f"Database locked fetching unread count for user ID {user_id}, attempt {attempt + 1}. Retrying in {delay} seconds..., Session: %s", session)
                time.sleep(delay * (2 ** attempt) + random.uniform(0, 0.1))
                attempt += 1
                continue
            logging.error(f"Database error fetching unread count for user ID {user_id}, attempt {attempt + 1}: {e}, Session: %s", session)
            return jsonify({"error": "Database error", "details": str(e)}), 500
        except sqlite3.Error as e:
            logging.error(f"Database error fetching unread count for user ID {user_id}, attempt {attempt + 1}: {e}, Session: %s", session)
            return jsonify({"error": "Database error", "details": str(e)}), 500
        finally:
            conn.close()

    logging.error(f"Failed to fetch unread count for user ID {user_id} after {retries} attempts, Session: %s", session)
    return jsonify({"error": f"Failed after {retries} attempts"}), 500

@app.route("/provider_profile/<int:provider_id>")
def provider_profile(provider_id):
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to provider profile, Session: %s", session)
        flash("Please log in as a customer to view provider profiles.", "error")
        return redirect(url_for("login"))
   
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM providers WHERE id = %s", (provider_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider ID {provider_id} not found, Session: %s", session)
            flash("Provider not found.", "error")
            return redirect(url_for("customer_dashboard"))
       
        cursor.execute("SELECT * FROM portfolios WHERE provider_id = %s", (provider_id,))
        portfolio = row_to_dict(cursor.fetchone())
        provider["portfolio"] = portfolio if portfolio else None
       
        # Fetch all payment details
        cursor.execute("SELECT * FROM payment_details WHERE provider_id = %s", (provider_id,))
        payment_details = [row_to_dict(detail) for detail in cursor.fetchall()]
       
        if not payment_details:
            logging.info(f"No payment details found for provider_id {provider_id}, Session: %s", session)
        else:
            logging.info(f"Fetched {len(payment_details)} payment details for provider_id {provider_id}: {payment_details}, Session: %s", session)
       
        logging.info(f"Provider profile accessed for provider ID {provider_id} by user ID {session['user_id']}, Session: %s", session)
        return render_template("provider_profile.html", provider=provider, payment_details=payment_details)
    except psycopg2.Error as e:
        logging.error(f"Database error fetching provider profile for provider_id {provider_id}: {e}, Session: %s", session)
        flash("Error fetching provider profile. Please try again.", "error")
        return redirect(url_for("customer_dashboard"))
    finally:
        cursor.close()
        conn.close()

@app.route("/provider_portfolio/<int:provider_id>")
def provider_portfolio(provider_id):
    if "user_id" not in session or session.get("user_role") not in ["customer", "provider"]:
        logging.warning("Unauthorized access to provider portfolio, Session: %s", session)
        flash("Please log in to view provider portfolio.", "error")
        return redirect(url_for("login"))
   
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM providers WHERE id = %s", (provider_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider ID {provider_id} not found, Session: %s", session)
            flash("Provider not found.", "error")
            return redirect(url_for("customer_dashboard" if session.get("user_role") == "customer" else "provider_dashboard"))
       
        cursor.execute("SELECT * FROM portfolios WHERE provider_id = %s", (provider_id,))
        portfolio = row_to_dict(cursor.fetchone())
        if not portfolio:
            portfolio = {
                "skills": "",
                "certifications": "",
                "experience": "",
                "work_samples": "",
                "github_links": ""
            }
       
        cursor.execute("SELECT * FROM payment_details WHERE provider_id = %s", (provider_id,))
        payment_details = [row_to_dict(detail) for detail in cursor.fetchall()]
       
        logging.info(f"Provider portfolio accessed for provider ID {provider_id} by user ID {session['user_id']}, Session: %s", session)
        return render_template("provider_portfolio.html", provider=provider, portfolio=portfolio, payment_details=payment_details)
    except psycopg2.Error as e:
        logging.error(f"Database error fetching provider portfolio for provider_id {provider_id}: {e}, Session: %s", session)
        flash("Error fetching provider portfolio. Please try again.", "error")
        return redirect(url_for("customer_dashboard" if session.get("user_role") == "customer" else "provider_dashboard"))
    except Exception as e:
        logging.error(f"Unexpected error in provider_portfolio for provider_id {provider_id}: {e}, Session: %s", session)
        flash("An unexpected error occurred. Please try again later.", "error")
        return redirect(url_for("customer_dashboard" if session.get("user_role") == "customer" else "provider_dashboard"))
    finally:
        cursor.close()
        conn.close()

@app.route("/get_portfolio", methods=["GET"])
def get_portfolio():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to get portfolio, Session: %s", session)
        return jsonify({"error": "Unauthorized, please log in as a provider."}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider["id"]
       
        cursor.execute(
            "SELECT skills, certifications, experience, work_samples, github_links, created_at FROM portfolios WHERE provider_id = %s ORDER BY created_at DESC LIMIT 1",
            (provider_id,)
        )
        portfolio = row_to_dict(cursor.fetchone())
       
        if portfolio:
            portfolio_data = {
                "skills": portfolio["skills"],
                "certifications": portfolio["certifications"] or "",
                "experience": portfolio["experience"],
                "work_samples": portfolio["work_samples"] or "",
                "github_links": portfolio["github_links"].split(",") if portfolio["github_links"] else [],
                "created_at": portfolio["created_at"].isoformat() if portfolio["created_at"] else None
            }
            logging.info(f"Portfolio fetched for provider_id {provider_id}, Session: %s", session)
            return jsonify({"portfolio": portfolio_data}), 200
        else:
            logging.info(f"No portfolio found for provider_id {provider_id}, Session: %s", session)
            return jsonify({"portfolio": None}), 200
    except psycopg2.Error as e:
        logging.error(f"Database error in get_portfolio for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/submit_rating", methods=["POST"])
def submit_rating():
    try:
        if "user_id" not in session or session.get("user_role") != "customer":
            logging.warning("Unauthorized access to submit rating, Session: %s", session)
            return jsonify({"error": "Unauthorized, please log in as a customer."}), 401
       
        user_id = session["user_id"]
        customer_email = session.get("user_email")
        if not customer_email:
            logging.warning(f"No customer email found in session for user ID {user_id}, Session: %s", session)
            return jsonify({"error": "Customer email not found"}), 400

        booking_id = request.form.get("booking_id")
        provider_id = request.form.get("provider_id")
        overall_rating = request.form.get("overall_rating")
        quality = request.form.get("quality")
        punctuality = request.form.get("punctuality")
        communication = request.form.get("communication")
        feedback = request.form.get("feedback", "").strip()

        if not all([provider_id, overall_rating]):
            logging.warning(f"Missing required fields: provider_id={provider_id}, overall_rating={overall_rating}, Session: %s", session)
            return jsonify({"error": "Provider ID and overall rating are required"}), 400

        try:
            provider_id = int(provider_id)
            overall_rating = int(overall_rating)
            quality = int(quality) if quality else None
            punctuality = int(punctuality) if punctuality else None
            communication = int(communication) if communication else None
            booking_id = int(booking_id) if booking_id else None
        except (ValueError, TypeError):
            logging.warning(f"Invalid input values: booking_id={booking_id}, provider_id={provider_id}, overall_rating={overall_rating}, quality={quality}, punctuality={punctuality}, communication={communication}, Session: %s", session)
            return jsonify({"error": "Invalid input values"}), 400

        for rating in [overall_rating, quality, punctuality, communication]:
            if rating is not None and (rating < 1 or rating > 5):
                logging.warning(f"Rating out of range: overall_rating={overall_rating}, quality={quality}, punctuality={punctuality}, communication={communication}, Session: %s", session)
                return jsonify({"error": "Ratings must be between 1 and 5"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Check provider exists
            cursor.execute("SELECT id FROM providers WHERE id = %s", (provider_id,))
            provider = cursor.fetchone()
            if not provider:
                logging.warning(f"Provider ID {provider_id} not found, Session: %s", session)
                return jsonify({"error": "Provider not found"}), 404

            if booking_id:
                # Validate booking
                cursor.execute(
                    "SELECT * FROM bookings WHERE id = %s AND customer_email = %s",
                    (booking_id, customer_email)
                )
                booking = cursor.fetchone()
                if not booking:
                    logging.warning(f"Booking ID {booking_id} not found for customer email {customer_email}, Session: %s", session)
                    return jsonify({"error": "Booking not found or does not belong to you"}), 404

                if booking["status"] != "Confirmed":
                    logging.warning(f"Booking ID {booking_id} is not in Confirmed status, current status: {booking['status']}, Session: %s", session)
                    return jsonify({"error": "Can only rate confirmed bookings"}), 400

                if booking["provider_id"] != provider_id:
                    logging.warning(f"Provider ID {provider_id} does not match booking ID {booking_id} provider_id {booking['provider_id']}, Session: %s", session)
                    return jsonify({"error": "Provider does not match booking"}), 400

                # Check for existing rating
                cursor.execute(
                    "SELECT id FROM ratings WHERE booking_id = %s",
                    (booking_id,)
                )
                existing_rating = cursor.fetchone()
                if existing_rating:
                    logging.warning(f"Booking ID {booking_id} has already been rated, Session: %s", session)
                    return jsonify({"error": "This booking has already been rated"}), 400

            # Insert rating
            cursor.execute(
                """
                INSERT INTO ratings (booking_id, provider_id, customer_id, overall_rating, quality, punctuality, communication, feedback, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (
                    booking_id,
                    provider_id,
                    user_id,
                    overall_rating,
                    quality,
                    punctuality,
                    communication,
                    feedback,
                    datetime.now()
                )
            )
            rating_id = cursor.fetchone()['id']

            # Verify insertion
            cursor.execute("SELECT * FROM ratings WHERE id = %s", (rating_id,))
            new_rating = cursor.fetchone()
            if not new_rating:
                logging.error(f"Rating ID {rating_id} insertion failed verification, Session: %s", session)
                return jsonify({"error": "Rating insertion failed"}), 500

            # Insert notification
            cursor.execute("SELECT user_id FROM providers WHERE id = %s", (provider_id,))
            provider_user = cursor.fetchone()
            if provider_user:
                provider_user_id = provider_user['user_id']
                cursor.execute(
                    "INSERT INTO notifications (user_id, type, content) VALUES (%s, %s, %s)",
                    (provider_user_id, "rating", f"New rating: {overall_rating}/5")
                )

            # Fetch provider email and send notification email
            cursor.execute("SELECT u.email FROM users u JOIN providers p ON u.id = p.user_id WHERE p.id = %s", (provider_id,))
            provider_email_row = cursor.fetchone()
            if provider_email_row:
                provider_email = provider_email_row['email']
                customer_name = customer_email  # Use session email as customer identifier

                # Build dynamic email content
                plain_body = f"""
Dear Provider,

You have received a new rating from {customer_name}.

Overall Rating: {overall_rating}/5
"""
                html_body = f"""
<html>
<body>
    <h2>New Rating Received</h2>
    <p>Dear Provider,</p>
    <p>You have received a new rating from <strong>{customer_name}</strong>:</p>
    <p><strong>Overall Rating:</strong> {overall_rating}/5</p>
"""
                if quality:
                    plain_body += f"\nQuality: {quality}/5"
                    html_body += f"<p><strong>Quality:</strong> {quality}/5</p>"
                if punctuality:
                    plain_body += f"\nPunctuality: {punctuality}/5"
                    html_body += f"<p><strong>Punctuality:</strong> {punctuality}/5</p>"
                if communication:
                    plain_body += f"\nCommunication: {communication}/5"
                    html_body += f"<p><strong>Communication:</strong> {communication}/5</p>"
                plain_body += f"\n\nFeedback: {feedback}\n\nPlease log in to your dashboard to view full details.\n\nBest regards,\nYour Service Platform\n\nIf you don't see this email in your inbox, please check your spam or junk folder."
                html_body += f"<p><strong>Feedback:</strong> {escape(feedback)}</p><p><a href=\"{{ url_for('provider_dashboard', _external=True) }}\">Log in to view full details</a></p><p>Best regards,<br>Your Service Platform</p><p><strong>Note:</strong> If you don't see this email in your inbox, please check your spam or junk folder.</p></body></html>"

                send_email(provider_email, "New Rating Received", plain_body, html_body)
                logging.info(f"Rating email sent to provider {provider_email} for rating ID {rating_id}")

            conn.commit()
            logging.info(f"Rating submitted for provider ID {provider_id} by user ID {user_id}, Booking ID: {booking_id}, Rating ID: {rating_id}, Session: %s", session)
            return jsonify({"success": True, "rating_id": rating_id})

        except psycopg2.Error as e:
            conn.rollback()
            logging.error(f"Database error submitting rating for provider ID {provider_id}: {e}, Session: %s", session)
            return jsonify({"error": "Database error", "details": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        logging.error(f"Unexpected error in submit_rating: {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

    logging.error(f"Failed to submit rating for provider ID {provider_id} after {retries} attempts, Session: %s", session)
    return jsonify({"error": f"Failed after {retries} attempts"}), 500


@app.route("/get_provider_ratings")
def get_provider_ratings():
    # Check if user is authenticated and a provider
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning(f"Unauthorized access to /get_provider_ratings, Session: {session}")
        return jsonify({"error": "Unauthorized, please log in as a provider."}), 401
   
    user_id = session["user_id"]
    logging.info(f"Fetching ratings for user_id {user_id}, Session: {session}")
   
    conn = None
    try:
        # Establish database connection
        conn = get_db_connection()
        cursor = conn.cursor()
       
        # Fetch provider_id based on user_id
        cursor.execute(
            "SELECT id FROM providers WHERE user_id = %s",
            (user_id,)
        )
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"No provider profile found for user_id {user_id}, Session: {session}")
            return jsonify({"error": "Provider profile not found"}), 404
       
        provider_id = provider["id"]
        logging.info(f"Provider ID {provider_id} retrieved for user_id {user_id}")
       
        # Fetch last_viewed_ratings_count
        cursor.execute(
            "SELECT last_viewed_ratings_count FROM providers WHERE id = %s",
            (provider_id,)
        )
        last_viewed_row = row_to_dict(cursor.fetchone())
        last_viewed = last_viewed_row["last_viewed_ratings_count"] if last_viewed_row else 0
       
        # Fetch ratings with customer_name from bookings and email from users
        cursor.execute(
            """
            SELECT r.id, r.booking_id, r.overall_rating, r.quality, r.punctuality,
                   r.communication, r.feedback, r.created_at, b.customer_name AS booking_customer_name, u.email AS customer_email
            FROM ratings r
            JOIN users u ON r.customer_id = u.id
            LEFT JOIN bookings b ON r.booking_id = b.id
            WHERE r.provider_id = %s
            ORDER BY r.created_at DESC
            """,
            (provider_id,)
        )
        ratings = [row_to_dict(row) for row in cursor.fetchall()]
        logging.info(f"Fetched {len(ratings)} ratings for provider_id {provider_id}")
       
        # Format ratings data
        ratings_list = []
        for rating in ratings:
            booking_customer_name = rating.get("booking_customer_name")
            customer_email = rating["customer_email"]
            # Use booking_customer_name if available and non-empty, else derive name from email
            if booking_customer_name and booking_customer_name.strip():
                customer_display = f"{booking_customer_name} ({customer_email})"
            else:
                name_from_email = customer_email.split('@')[0]
                customer_display = f"{name_from_email} ({customer_email})"
            ratings_list.append({
                "id": rating["id"],
                "booking_id": rating["booking_id"],
                "customer_name": customer_display,
                "overall_rating": rating["overall_rating"],
                "quality": rating["quality"],
                "punctuality": rating["punctuality"],
                "communication": rating["communication"],
                "feedback": rating["feedback"],
                "created_at": rating["created_at"].isoformat() if rating["created_at"] else None
            })
       
        current_count = len(ratings_list)
        # Successful response
        response = {
            "success": True,
            "ratings": ratings_list,
            "count": current_count,
            "last_viewed_count": last_viewed,
            "current_count": current_count
        }
        logging.info(f"Returning {len(ratings_list)} ratings for provider_id {provider_id} with last_viewed {last_viewed}")
        return jsonify(response), 200
   
    except psycopg2.Error as e:
        logging.error(f"Database error fetching ratings for user_id {user_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    except Exception as e:
        logging.error(f"Unexpected error fetching ratings for user_id {user_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    finally:
        if conn:
            cursor.close()
            conn.close()
            logging.debug(f"Database connection closed for user_id {user_id}")


@app.route("/update_last_viewed_ratings", methods=["POST"])
def update_last_viewed_ratings():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to update last viewed ratings, Session: %s", session)
        return jsonify({"error": "Unauthorized, please log in as a provider."}), 401

    data = request.json
    count = data.get("count")
    if count is None:
        logging.warning("Count missing in update last viewed ratings request, Session: %s", session)
        return jsonify({"error": "Count required"}), 400

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404

        cursor.execute(
            "UPDATE providers SET last_viewed_ratings_count = %s WHERE id = %s",
            (count, provider["id"])
        )
        if cursor.rowcount == 0:
            logging.warning(f"No rows updated for provider_id {provider['id']}, count {count}, Session: %s", session)
            return jsonify({"error": "Failed to update last viewed count"}), 500

        conn.commit()
        logging.info(f"Last viewed ratings count updated to {count} for provider_id {provider['id']}, Session: %s", session)
        return jsonify({"success": True}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error updating last viewed ratings for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_provider_ratings_public")
def get_provider_ratings_public():
    provider_id = request.args.get("provider_id")
    if not provider_id:
        logging.warning("No provider_id provided for get_provider_ratings_public, Session: %s", session)
        return jsonify({"error": "Provider ID required"}), 400

    try:
        provider_id = int(provider_id)
    except ValueError:
        logging.warning(f"Invalid provider_id provided: {provider_id}, Session: %s", session)
        return jsonify({"error": "Invalid provider ID"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if provider exists
        cursor.execute("SELECT id FROM providers WHERE id = %s", (provider_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider ID {provider_id} not found, Session: %s", session)
            return jsonify({"error": "Provider not found"}), 404

        # Fetch ratings with LEFT JOIN on bookings, JOIN on users, and LEFT JOIN on rating_replies
        cursor.execute(
            """
            SELECT r.id, r.booking_id, r.overall_rating, r.quality, r.punctuality,
                   r.communication, r.feedback, r.created_at,
                   COALESCE(b.customer_name, u.email) AS customer_display,
                   rr.reply, rr.created_at AS reply_date
            FROM ratings r
            LEFT JOIN bookings b ON r.booking_id = b.id
            JOIN users u ON r.customer_id = u.id
            LEFT JOIN rating_replies rr ON r.id = rr.rating_id
            WHERE r.provider_id = %s
            ORDER BY r.created_at DESC
            """,
            (provider_id,)
        )
        ratings = [row_to_dict(row) for row in cursor.fetchall()]

        ratings_list = []
        for rating in ratings:
            ratings_list.append({
                "id": rating["id"],
                "booking_id": rating["booking_id"],
                "customer_name": rating["customer_display"],
                "overall_rating": rating["overall_rating"],
                "quality": rating["quality"],
                "punctuality": rating["punctuality"],
                "communication": rating["communication"],
                "feedback": rating["feedback"],
                "created_at": rating["created_at"].isoformat() if rating["created_at"] else None,
                "reply": rating["reply"],
                "reply_date": rating["reply_date"].isoformat() if rating["reply_date"] else None
            })

        logging.info(f"Fetched {len(ratings_list)} ratings for provider ID {provider_id}, Session: %s", session)
        return jsonify({
            "success": True,
            "ratings": ratings_list,
            "count": len(ratings_list)
        })

    except psycopg2.Error as e:
        logging.error(f"Database error in get_provider_ratings_public for provider_id {provider_id}: {e.pgcode} - {e.pgerror}", exc_info=True)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    except Exception as e:
        logging.error(f"Unexpected error in get_provider_ratings_public for provider_id {provider_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/add_payment_details", methods=["POST"])
def add_payment_details():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to add payment details, Session: %s", session)
        return jsonify({"error": "Unauthorized, please log in as a provider."}), 401

    payment_data = request.json
    if not payment_data:
        logging.warning("No payment data provided, Session: %s", session)
        return jsonify({"error": "No payment data provided"}), 400

    method = payment_data.get('method')
    if not method or method not in ['mpesa', 'bank']:
        logging.warning(f"Invalid payment method: {method}, Session: %s", session)
        return jsonify({"error": "Invalid payment method"}), 400

    required_fields = {
        'mpesa': {
            'send_money': ['mpesa_name', 'phone_number'],
            'till_number': ['business_name', 'till_number'],
            'paybill': ['business_name', 'business_number', 'account_number']
        },
        'bank': ['account_name', 'account_number']
    }

    if method == 'mpesa':
        suboption = payment_data.get('suboption')
        if not suboption or suboption not in required_fields['mpesa']:
            logging.warning(f"Invalid M-Pesa suboption: {suboption}, Session: %s", session)
            return jsonify({"error": "Invalid M-Pesa suboption"}), 400
        missing_fields = [field for field in required_fields['mpesa'][suboption] if not payment_data.get(field)]
    else:
        missing_fields = [field for field in required_fields['bank'] if not payment_data.get(field)]

    if missing_fields:
        logging.warning(f"Missing required fields: {missing_fields}, Session: %s", session)
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = cursor.fetchone()
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider['id']

        payment_details = {
            'provider_id': provider_id,
            'method': method,
            'mpesa_suboption': payment_data.get('suboption') if method == 'mpesa' else None,
            'mpesa_name': payment_data.get('mpesa_name') if method == 'mpesa' and payment_data.get('suboption') == 'send_money' else None,
            'phone_number': payment_data.get('phone_number') if method == 'mpesa' and payment_data.get('suboption') == 'send_money' else None,
            'business_name': payment_data.get('business_name') if method == 'mpesa' and payment_data.get('suboption') in ['till_number', 'paybill'] else None,
            'till_number': payment_data.get('till_number') if method == 'mpesa' and payment_data.get('suboption') == 'till_number' else None,
            'business_number': payment_data.get('business_number') if method == 'mpesa' and payment_data.get('suboption') == 'paybill' else None,
            'account_number': payment_data.get('account_number') if (method == 'mpesa' and payment_data.get('suboption') == 'paybill') or method == 'bank' else None,
            'account_name': payment_data.get('account_name') if method == 'bank' else None,
        }

        cursor.execute(
            """
            INSERT INTO payment_details (
                provider_id, method, mpesa_suboption, mpesa_name, phone_number,
                business_name, till_number, business_number, account_number, account_name
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                payment_details['provider_id'],
                payment_details['method'],
                payment_details['mpesa_suboption'],
                payment_details['mpesa_name'],
                payment_details['phone_number'],
                payment_details['business_name'],
                payment_details['till_number'],
                payment_details['business_number'],
                payment_details['account_number'],
                payment_details['account_name']
            )
        )
        payment_id = cursor.fetchone()['id']
        conn.commit()
        logging.info(f"Payment details added with ID {payment_id} for provider ID {provider_id}, method: {method}, Session: %s", session)
        return jsonify({"success": True, "payment_id": payment_id}), 200

    except psycopg2.Error as e:
        conn.rollback()
        error_msg = f"Database error adding payment details: {str(e)}"
        logging.error(f"{error_msg}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# Modified: Return a list of payment methods instead of a single row
@app.route("/get_payment_details_by_user/<int:user_id>")
def get_payment_details_by_user(user_id):
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning(f"Unauthorized access to get_payment_details_by_user for user_id {user_id}, Session: {session}")
        return jsonify({"error": "Unauthorized, please log in as a customer."}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch provider ID from providers table
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: {session}")
            return jsonify({"error": "Provider not found"}), 404
        provider_id = provider["id"]

        # Fetch all payment details for the provider
        cursor.execute(
            "SELECT method, mpesa_suboption, mpesa_name, phone_number, business_name, till_number, business_number, account_number, account_name "
            "FROM payment_details WHERE provider_id = %s",
            (provider_id,)
        )
        payment_details_list = cursor.fetchall()
        payment_details = [row_to_dict(detail) for detail in payment_details_list]

        if not payment_details:
            logging.info(f"No payment details found for provider_id {provider_id} (user_id {user_id}), Session: {session}")
            return jsonify({"success": True, "payment_details": [], "message": "No payment details available"}), 200
        else:
            logging.info(f"Fetched {len(payment_details)} payment details for provider_id {provider_id} (user_id {user_id}): {payment_details}, Session: {session}")
            return jsonify({"success": True, "payment_details": payment_details}), 200

    except psycopg2.Error as e:
        logging.error(f"Database error fetching payment details for user_id {user_id}: {e}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# New: Endpoint for providers to view all their payment methods
@app.route("/get_provider_payment_methods")
def get_provider_payment_methods():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to get_provider_payment_methods, Session: %s", session)
        return jsonify({"error": "Unauthorized, please log in as a provider."}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = cursor.fetchone()
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider['id']

        cursor.execute("SELECT * FROM payment_details WHERE provider_id = %s", (provider_id,))
        payment_methods = cursor.fetchall()

        payment_methods_list = [dict(method) for method in payment_methods]

        if not payment_methods_list:
            logging.info(f"No payment methods found for provider_id {provider_id}, Session: %s", session)
            return jsonify({
                "success": True,
                "payment_methods": [],
                "count": 0,
                "message": "No payment methods added yet"
            }), 200

        logging.info(f"Fetched {len(payment_methods_list)} payment methods for provider_id {provider_id}, Session: %s", session)
        return jsonify({
            "success": True,
            "payment_methods": payment_methods_list,
            "count": len(payment_methods_list)
        }), 200

    except psycopg2.Error as e:
        logging.error(f"Database error fetching payment methods for provider_id {provider_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# New: Endpoint for providers to update a specific payment method
@app.route("/update_payment_method/<int:method_id>", methods=["POST"])
def update_payment_method(method_id):
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to update_payment_method, Session: %s", session)
        return jsonify({"error": "Unauthorized, please log in as a provider."}), 401

    payment_data = request.json
    if not payment_data:
        logging.warning("No payment data provided for update, Session: %s", session)
        return jsonify({"error": "No payment data provided"}), 400

    # Validate payment method
    method = payment_data.get('method')
    if not method or method not in ['mpesa', 'bank']:
        logging.warning(f"Invalid payment method: {method}, Session: %s", session)
        return jsonify({"error": "Invalid payment method"}), 400

    # Define required fields based on method and sub-option
    required_fields = {
        'mpesa': {
            'send_money': ['mpesa_name', 'phone_number'],
            'till_number': ['business_name', 'till_number'],
            'paybill': ['business_name', 'business_number', 'account_number']
        },
        'bank': ['account_name', 'account_number']
    }

    # Validate required fields
    if method == 'mpesa':
        suboption = payment_data.get('suboption')
        if not suboption or suboption not in required_fields['mpesa']:
            logging.warning(f"Invalid M-Pesa suboption: {suboption}, Session: %s", session)
            return jsonify({"error": "Invalid M-Pesa suboption"}), 400
        missing_fields = [field for field in required_fields['mpesa'][suboption] if not payment_data.get(field)]
    else:
        missing_fields = [field for field in required_fields['bank'] if not payment_data.get(field)]

    if missing_fields:
        logging.warning(f"Missing required fields for update: {missing_fields}, Session: %s", session)
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify provider
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = cursor.fetchone()
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider['id']

        # Check if the payment method exists and belongs to the provider
        cursor.execute(
            "SELECT * FROM payment_details WHERE id = %s AND provider_id = %s",
            (method_id, provider_id)
        )
        payment_method = cursor.fetchone()
        if not payment_method:
            logging.warning(f"Payment method ID {method_id} not found for provider_id {provider_id}, Session: %s", session)
            return jsonify({"error": "Payment method not found"}), 404

        # Prepare updated payment details, setting unused fields to None
        updated_details = {
            'method': method,
            'mpesa_suboption': payment_data.get('suboption') if method == 'mpesa' else None,
            'mpesa_name': payment_data.get('mpesa_name') if method == 'mpesa' and payment_data.get('suboption') == 'send_money' else None,
            'phone_number': payment_data.get('phone_number') if method == 'mpesa' and payment_data.get('suboption') == 'send_money' else None,
            'business_name': payment_data.get('business_name') if method == 'mpesa' and payment_data.get('suboption') in ['till_number', 'paybill'] else None,
            'till_number': payment_data.get('till_number') if method == 'mpesa' and payment_data.get('suboption') == 'till_number' else None,
            'business_number': payment_data.get('business_number') if method == 'mpesa' and payment_data.get('suboption') == 'paybill' else None,
            'account_number': payment_data.get('account_number') if (method == 'mpesa' and payment_data.get('suboption') == 'paybill') or method == 'bank' else None,
            'account_name': payment_data.get('account_name') if method == 'bank' else None,
        }

        # Update the payment method in the database
        cursor.execute(
            """
            UPDATE payment_details
            SET method = %s, mpesa_suboption = %s, mpesa_name = %s, phone_number = %s,
                business_name = %s, till_number = %s, business_number = %s, account_number = %s, account_name = %s
            WHERE id = %s AND provider_id = %s
            """,
            (
                updated_details['method'],
                updated_details['mpesa_suboption'],
                updated_details['mpesa_name'],
                updated_details['phone_number'],
                updated_details['business_name'],
                updated_details['till_number'],
                updated_details['business_number'],
                updated_details['account_number'],
                updated_details['account_name'],
                method_id,
                provider_id
            )
        )
        if cursor.rowcount == 0:
            logging.warning(f"No rows updated for payment method ID {method_id}, possibly not found or unchanged, Session: %s", session)
            return jsonify({"error": "Payment method not found or no changes made"}), 404

        conn.commit()
        logging.info(f"Payment method ID {method_id} updated successfully for provider ID {provider_id}, Session: %s", session)
        return jsonify({"success": True}), 200

    except psycopg2.Error as e:
        conn.rollback()
        error_msg = f"Database error updating payment method ID {method_id}: {str(e)}"
        logging.error(f"{error_msg}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    except Exception as e:
        conn.rollback()
        error_msg = f"Unexpected error updating payment method ID {method_id}: {str(e)}"
        logging.error(f"{error_msg}, Session: %s", session)
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# New: Endpoint for providers to delete a specific payment method
@app.route("/delete_payment_method/<int:method_id>", methods=["POST"])
def delete_payment_method(method_id):
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to delete_payment_method, Session: %s", session)
        return jsonify({"error": "Unauthorized, please log in as a provider."}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify provider
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = cursor.fetchone()
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider['id']

        # Check if the payment method exists and belongs to the provider
        cursor.execute(
            "SELECT * FROM payment_details WHERE id = %s AND provider_id = %s",
            (method_id, provider_id)
        )
        payment_method = cursor.fetchone()
        if not payment_method:
            logging.warning(f"Payment method ID {method_id} not found for provider_id {provider_id}, Session: %s", session)
            return jsonify({"error": "Payment method not found"}), 404

        # Delete the payment method
        cursor.execute(
            "DELETE FROM payment_details WHERE id = %s AND provider_id = %s",
            (method_id, provider_id)
        )
        if cursor.rowcount == 0:
            logging.warning(f"No rows deleted for payment method ID {method_id}, possibly already removed, Session: %s", session)
            return jsonify({"error": "Payment method not found"}), 404

        conn.commit()
        logging.info(f"Payment method ID {method_id} deleted successfully for provider ID {provider_id}, Session: %s", session)
        return jsonify({"success": True}), 200

    except psycopg2.Error as e:
        conn.rollback()
        error_msg = f"Database error deleting payment method ID {method_id}: {str(e)}"
        logging.error(f"{error_msg}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    except Exception as e:
        conn.rollback()
        error_msg = f"Unexpected error deleting payment method ID {method_id}: {str(e)}"
        logging.error(f"{error_msg}, Session: %s", session)
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/get_notifications")
def get_notifications():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, type, content, timestamp, sender_id FROM notifications WHERE user_id = %s AND is_read = FALSE ORDER BY timestamp DESC",
            (user_id,)
        )
        notifications = [row_to_dict(row) for row in cursor.fetchall()]
        logging.info(f"Fetched {len(notifications)} unread notifications for user ID {user_id}")
        return jsonify({"success": True, "notifications": notifications})
    except psycopg2.Error as e:
        logging.error(f"Database error fetching notifications for user ID {user_id}: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# New route for provider-specific notifications
@app.route("/get_provider_notifications")
def get_provider_notifications():
    """
    Fetch notifications only for the currently logged-in provider.
    Prevents another provider from seeing someone else's notifications.
    """
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to provider notifications, Session: %s", session)
        return jsonify({"error": "Unauthorized, please log in as a provider."}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT id, type, content, timestamp, is_read, sender_id
            FROM notifications
            WHERE user_id = %s
            ORDER BY timestamp DESC
        """, (user_id,))

        notifications = [row_to_dict(row) for row in cursor.fetchall()]

        logging.info(
            f"Fetched {len(notifications)} notifications for provider user ID {user_id}, Session: %s",
            session
        )

        return jsonify({
            "success": True,
            "notifications": notifications
        })

    except psycopg2.Error as e:
        logging.error(
            f"Database error fetching provider notifications for user ID {user_id}: {str(e)}, Session: %s",
            session
        )
        return jsonify({
            "error": "Database error",
            "details": str(e)
        }), 500

    finally:
        cursor.close()
        conn.close()


@app.route("/mark_notifications_read", methods=["POST"])
def mark_notifications_read():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE",
            (user_id,)
        )
        conn.commit()
        logging.info(f"Marked all unread notifications as read for user ID {user_id}")
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error marking notifications as read for user ID {user_id}: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/mark_notification_read/<int:notification_id>", methods=["POST"])
def mark_notification_read(notification_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT * FROM notifications WHERE id = %s AND user_id = %s",
            (notification_id, user_id)
        )
        notification = row_to_dict(cursor.fetchone())
        if not notification:
            return jsonify({"error": "Notification not found or not yours"}), 404
       
        cursor.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = %s",
            (notification_id,)
        )
        conn.commit()
        logging.info(f"Notification ID {notification_id} marked as read for user ID {user_id}, Session: %s", session)
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error marking notification ID {notification_id} as read for user ID {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()



@app.route("/delete_unread_notifications", methods=["POST"])
def delete_unread_notifications():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM notifications WHERE user_id = %s AND is_read = FALSE",
            (user_id,)
        )
        conn.commit()
        logging.info(f"Deleted unread notifications for user ID {user_id}")
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting unread notifications for user ID {user_id}: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/delete_message_for_me/<int:message_id>", methods=["POST"])
def delete_message_for_me(message_id):
    if "user_id" not in session:
        logging.warning("Unauthorized access to delete message for me, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM messages WHERE id = %s", (message_id,))
        message = row_to_dict(cursor.fetchone())
        if not message:
            logging.warning(f"Message ID {message_id} not found for deletion, Session: %s", session)
            return jsonify({"error": "Message not found"}), 404

        if message["sender_id"] != user_id and message["receiver_id"] != user_id:
            logging.warning(f"User ID {user_id} not authorized to delete message ID {message_id}, Session: %s", session)
            return jsonify({"error": "Unauthorized to delete this message"}), 403

        # Handle media file deletion if it's an audio message
        if message["media_path"]:
            media_file_path = os.path.join(app.config["UPLOAD_FOLDER"], message["media_path"])
            if os.path.exists(media_file_path):
                try:
                    os.remove(media_file_path)
                    logging.info(f"Media file deleted for message ID {message_id}: {message['media_path']}, Session: %s", session)
                except OSError as e:
                    logging.error(f"Failed to delete media file for message ID {message_id}: {message['media_path']}, Error: {str(e)}, Session: %s", session)
                    # Don't fail the deletion if media removal fails; it's non-critical

        # Update deleted_for using set to avoid duplicates
        deleted_for_list = set(filter(None, (message["deleted_for"] or '').split(',')))
        if str(user_id) not in deleted_for_list:
            deleted_for_list.add(str(user_id))
            new_deleted_for = ','.join(deleted_for_list)
            cursor.execute(
                "UPDATE messages SET deleted_for = %s WHERE id = %s",
                (new_deleted_for, message_id)
            )
            conn.commit()
            logging.info(f"Message ID {message_id} marked as deleted for user ID {user_id}, Session: %s", session)
            return jsonify({"success": True})
        else:
            logging.info(f"Message ID {message_id} already deleted for user ID {user_id}, Session: %s", session)
            return jsonify({"success": True, "message": "Message already deleted for this user"})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting message ID {message_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/delete_message_for_all/<int:message_id>", methods=["POST"])
def delete_message_for_all(message_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM messages WHERE id = %s", (message_id,))
        message = row_to_dict(cursor.fetchone())
        if not message:
            return jsonify({"error": "Message not found"}), 404

        # Only the sender can delete for all
        if message["sender_id"] != user_id:
            return jsonify({"error": "Only the sender can delete for all"}), 403

        # Delete associated media file if it exists (especially for audio)
        if message["media_path"]:
            media_file_path = os.path.join(app.config["UPLOAD_FOLDER"], message["media_path"])
            if os.path.exists(media_file_path):
                try:
                    os.remove(media_file_path)
                    logging.info(f"Media file deleted for message ID {message_id}: {message['media_path']}, Session: {session}")
                except OSError as e:
                    logging.error(f"Failed to delete media file for message ID {message_id}: {message['media_path']}, Error: {str(e)}, Session: {session}")
                    # Continue with deletion even if media removal fails

        # Delete the message
        cursor.execute("DELETE FROM messages WHERE id = %s", (message_id,))

        # Check if conversation is empty and delete it if so
        conversation_id = message["conversation_id"]
        cursor.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = %s", (conversation_id,))
        remaining_messages = cursor.fetchone()[0]
        if remaining_messages == 0 and conversation_id:
            cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            logging.info(f"Conversation ID {conversation_id} deleted as it has no remaining messages, Session: {session}")

        conn.commit()
        logging.info(f"Message ID {message_id} deleted for all by user ID {user_id}, Session: {session}")
        return jsonify({"success": True, "is_conversation_empty": remaining_messages == 0})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error in delete_message_for_all for message ID {message_id}: {e}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/get_pending_bookings_count")
def get_pending_bookings_count():
    if "user_id" not in session or session.get("user_role") != "provider":
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    try:
        provider = row_to_dict(conn.execute("SELECT id FROM providers WHERE user_id = ?", (user_id,)).fetchone())
        if not provider:
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider["id"]

        count = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE provider_id = ? AND status = 'Pending'",
            (provider_id,)
        ).fetchone()[0]
        return jsonify({"count": count})
    except sqlite3.Error as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/admin/unread_message_counts")
def unread_message_counts():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    admin_id = session["user_id"]
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Define the pattern for LIKE to match admin_id in deleted_for (e.g., ',1,' or '1,' or ',1')
        pattern = f'%,{admin_id},%'
        cursor.execute("""
            SELECT u.id, COALESCE(COUNT(m.id), 0) AS unread_count
            FROM users u
            LEFT JOIN messages m ON m.sender_id = u.id
                AND m.receiver_id = %s
                AND m.is_read = FALSE
                AND (m.deleted_for IS NULL OR NOT (',' || m.deleted_for || ',') LIKE %s)
            WHERE u.id != %s
            GROUP BY u.id
        """, (admin_id, pattern, admin_id))
        unread_counts = cursor.fetchall()
        result = [{"id": row["id"], "unread_count": row["unread_count"]} for row in unread_counts]
        return jsonify(result)
    except psycopg2.Error as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/get_admin_id")
def get_admin_id():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_db_connection()
    try:
        admin = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()
        if admin:
            admin_dict = dict(admin)  # Adjust based on your row factory
            return jsonify({"admin_id": admin_dict["id"]})
        else:
            return jsonify({"error": "Administrator not found"}), 404
    except sqlite3.Error as e:
        logging.error(f"Database error fetching admin ID: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()


@app.route("/submit_feedback", methods=["POST"])
def submit_feedback():
    # Ensure the user is logged in as a customer
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to submit feedback, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    # Get feedback from the request
    data = request.get_json()
    if not data or "feedback" not in data:
        logging.warning("Invalid feedback data received, Session: %s", session)
        return jsonify({"error": "Feedback text is required"}), 400

    feedback_text = data.get("feedback").strip()
    if not feedback_text:
        logging.warning("Empty feedback text received, Session: %s", session)
        return jsonify({"error": "Feedback text is required"}), 400

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO feedback (customer_id, feedback, timestamp, is_viewed, user_type)
            VALUES (%s, %s, CURRENT_TIMESTAMP, FALSE, 'customer')
            RETURNING id
            """,
            (user_id, feedback_text)
        )
        feedback_id = cursor.fetchone()['id']
        conn.commit()
        logging.info(f"Feedback submitted successfully by customer ID {user_id}, Feedback ID: {feedback_id}, Session: %s", session)
        return jsonify({"success": True, "feedback_id": feedback_id})
    except psycopg2.Error as e:
        conn.rollback()
        error_msg = f"Database error submitting feedback for customer ID {user_id}: {str(e)}"
        logging.error(error_msg + f", Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()




@app.route("/api/admin/new_feedback_count", methods=["GET"])
def new_feedback_count():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM feedback WHERE is_viewed = FALSE")
        count = cursor.fetchone()[0]
        logging.info(f"Fetched unseen feedback count: {count} for admin, Session: {session}")
        return jsonify({"count": count})
    except psycopg2.Error as e:
        logging.error(f"Database error fetching new feedback count: {e}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
       

@app.route("/api/admin/mark_feedback_seen", methods=["POST"])
def mark_feedback_seen():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE feedback SET is_viewed = TRUE WHERE is_viewed = FALSE")
        conn.commit()
        logging.info(f"All feedback marked as viewed by admin, Session: {session}")
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error marking feedback as seen: {e}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/admin/feedback", methods=["GET"])
def get_feedback():
    if "user_id" not in session or session.get("user_role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT f.id, u.email AS customer_name, f.feedback, f.timestamp, f.is_viewed, f.user_type
            FROM feedback f
            JOIN users u ON f.customer_id = u.id
            ORDER BY f.timestamp DESC
        """)
        feedback_list = [dict(row) for row in cursor.fetchall()]
        # Format the customer_name to indicate user type
        for feedback in feedback_list:
            if feedback["user_type"] == "provider":
                feedback["customer_name"] = f"Provider: {feedback['customer_name']}"
            else:
                feedback["customer_name"] = f"Customer: {feedback['customer_name']}"
        logging.info(f"Fetched {len(feedback_list)} feedback entries for admin, Session: {session}")
        return jsonify(feedback_list)
    except sqlite3.Error as e:
        logging.error(f"Database error fetching feedback: {e}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        conn.close()

@app.route("/submit_provider_feedback", methods=["POST"])
def submit_provider_feedback():
    # Ensure the user is logged in as a provider
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to submit provider feedback, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    # Get feedback from the request
    data = request.json
    feedback_text = data.get("feedback")
    if not feedback_text:
        logging.warning("Feedback text missing in provider feedback submission, Session: %s", session)
        return jsonify({"error": "Feedback text is required"}), 400

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO feedback (customer_id, feedback, timestamp, is_viewed, user_type)
            VALUES (%s, %s, CURRENT_TIMESTAMP, FALSE, 'provider')
            RETURNING id
            """,
            (user_id, feedback_text)
        )
        feedback_id = cursor.fetchone()['id']
        conn.commit()
        logging.info(f"Provider feedback submitted successfully by user ID {user_id}, Feedback ID: {feedback_id}, Session: %s", session)
        return jsonify({"success": True, "feedback_id": feedback_id})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error submitting provider feedback for user ID {user_id}: {str(e)}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/admin/delete_feedback", methods=["POST"])
def delete_feedback():
    # Check if the user is logged in and an admin
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized attempt to delete feedback, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    # Get feedback_id from the request
    data = request.json
    feedback_id = data.get("feedback_id")
    if not feedback_id:
        logging.warning("Feedback ID missing in delete request, Session: %s", session)
        return jsonify({"error": "Feedback ID is required"}), 400

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Attempt to delete the feedback
        cursor.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
        if cursor.rowcount == 0:
            logging.warning(f"Feedback ID {feedback_id} not found for deletion, Session: %s", session)
            return jsonify({"error": "Feedback not found"}), 404
        conn.commit()
        logging.info(f"Feedback ID {feedback_id} deleted by admin, Session: %s", session)
        return jsonify({"success": True})
    except sqlite3.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting feedback ID {feedback_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/admin/delete_all_feedback", methods=["POST"])
def delete_all_feedback():
    # Check if the user is logged in and an admin
    if "user_id" not in session or session.get("user_role") != "admin":
        logging.warning("Unauthorized attempt to delete all feedback, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Delete all feedback entries
        cursor.execute("DELETE FROM feedback")
        deleted_count = cursor.rowcount
        conn.commit()
        logging.info(f"All feedback deleted by admin, {deleted_count} entries removed, Session: %s", session)
        return jsonify({"success": True, "deleted_count": deleted_count})
    except sqlite3.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting all feedback: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        conn.close()


@app.route("/mark_all_notifications_read", methods=["POST"])
def mark_all_notifications_read():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE",
            (user_id,)
        )
        affected_rows = cursor.rowcount
        conn.commit()
        logging.info(f"Marked {affected_rows} notifications as read for user ID {user_id}")
        return jsonify({"success": True, "marked_count": affected_rows})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error marking notifications as read for user ID {user_id}: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/get_all_conversations_with_messages', methods=['GET'])
def get_all_conversations_with_messages():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch conversations (may include swapped)
        cursor.execute("""
            SELECT
                c.id AS conversation_id,
                CASE WHEN c.user1_id = %s THEN u2.email ELSE u1.email END AS other_user_name,
                CASE WHEN c.user1_id = %s THEN u2.role ELSE u1.role END AS other_user_role,
                CASE WHEN c.user1_id = %s THEN c.user2_id ELSE c.user1_id END AS other_user_id,
                lm.timestamp AS latest_message_timestamp
            FROM conversations c
            JOIN users u1 ON c.user1_id = u1.id
            JOIN users u2 ON c.user2_id = u2.id
            LEFT JOIN LATERAL (
                SELECT timestamp FROM messages m
                WHERE m.conversation_id = c.id
                AND (m.deleted_for IS NULL OR m.deleted_for = '' OR NOT (',' || m.deleted_for || ',') LIKE %s)
                ORDER BY m.timestamp DESC LIMIT 1
            ) lm ON true
            WHERE c.user1_id = %s OR c.user2_id = %s
            ORDER BY lm.timestamp DESC NULLS LAST
        """, (user_id, user_id, user_id, f'%,{user_id},%', user_id, user_id))
        conversations = [dict(row) for row in cursor.fetchall()]

        all_messages = {}
        for conv in conversations:
            # Force canonical conversation
            canonical_min = min(user_id, conv['other_user_id'])
            canonical_max = max(user_id, conv['other_user_id'])
            cursor.execute("""
                SELECT id FROM conversations WHERE user1_id = %s AND user2_id = %s LIMIT 1
            """, (canonical_min, canonical_max))
            conv_row = cursor.fetchone()
            if not conv_row:
                # Check swapped
                cursor.execute("""
                    SELECT id FROM conversations WHERE user1_id = %s AND user2_id = %s LIMIT 1
                """, (canonical_max, canonical_min))
                swapped = cursor.fetchone()
                if swapped:
                    swapped_id = swapped['id']
                    cursor.execute("""
                        INSERT INTO conversations (user1_id, user2_id) VALUES (%s, %s) RETURNING id
                    """, (canonical_min, canonical_max))
                    conversation_id = cursor.fetchone()['id']
                    cursor.execute("UPDATE messages SET conversation_id = %s WHERE conversation_id = %s", (conversation_id, swapped_id))
                    cursor.execute("DELETE FROM conversations WHERE id = %s", (swapped_id,))
                    logging.info(f"Merged swapped {swapped_id} → canonical {conversation_id}")
                else:
                    cursor.execute("""
                        INSERT INTO conversations (user1_id, user2_id) VALUES (%s, %s) RETURNING id
                    """, (canonical_min, canonical_max))
                    conversation_id = cursor.fetchone()['id']
            else:
                conversation_id = conv_row['id']

            conv['conversation_id'] = conversation_id

            # Strong backfill
            cursor.execute("""
                UPDATE messages SET conversation_id = %s
                WHERE conversation_id IS NULL
                AND ((sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s))
            """, (conversation_id, user_id, conv['other_user_id'], conv['other_user_id'], user_id))

            # Fetch messages
            cursor.execute("""
                SELECT m.*, u.email AS sender_email, u.role AS sender_role
                FROM messages m JOIN users u ON m.sender_id = u.id
                WHERE m.conversation_id = %s
                AND (m.deleted_for IS NULL OR m.deleted_for = '' OR NOT (',' || m.deleted_for || ',') LIKE %s)
                ORDER BY m.timestamp ASC
            """, (conversation_id, f'%,{user_id},%'))
            messages = [dict(row) for row in cursor.fetchall()]

            if len(messages) == 0:
                cursor.execute("""
                    SELECT m.*, u.email AS sender_email, u.role AS sender_role
                    FROM messages m JOIN users u ON m.sender_id = u.id
                    WHERE (m.sender_id = %s AND m.receiver_id = %s OR m.sender_id = %s AND m.receiver_id = %s)
                    AND (m.deleted_for IS NULL OR m.deleted_for = '' OR NOT (',' || m.deleted_for || ',') LIKE %s)
                    ORDER BY m.timestamp ASC
                """, (user_id, conv['other_user_id'], conv['other_user_id'], user_id, f'%,{user_id},%'))
                messages = [dict(row) for row in cursor.fetchall()]

            all_messages[conversation_id] = messages

        # Unread counts
        cursor.execute("""
            SELECT conversation_id, COUNT(*) AS unread_count
            FROM messages
            WHERE receiver_id = %s AND is_read = FALSE
            AND (deleted_for IS NULL OR deleted_for = '' OR NOT (',' || deleted_for || ',') LIKE %s)
            GROUP BY conversation_id
        """, (user_id, f'%,{user_id},%'))
        unread_counts = {row['conversation_id']: row['unread_count'] for row in cursor.fetchall()}

        total_unread = sum(unread_counts.values())

        result = {"conversations": [], "total_unread": total_unread}
        for conv in conversations:
            conv_data = {
                "conversation_id": conv['conversation_id'],
                "other_user_id": conv['other_user_id'],
                "other_user_name": "ADMINISTRATOR" if conv['other_user_role'] == "admin" else conv['other_user_name'],
                "unread_count": unread_counts.get(conv['conversation_id'], 0),
                "messages": all_messages.get(conv['conversation_id'], [])
            }
            result["conversations"].append(conv_data)

        logging.info(f"Fetched all conversations with messages for user ID {user_id}: {len(result['conversations'])} conversations")
        return jsonify(result)
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error fetching all conversations for user ID {user_id}: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/delete_conversation/<int:conversation_id>", methods=["POST"])
def delete_conversation(conversation_id):
    if "user_id" not in session:
        logging.warning("Unauthorized access to delete conversation, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401
   
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify the user is part of the conversation
        cursor.execute(
            """
            SELECT * FROM conversations
            WHERE id = %s AND (user1_id = %s OR user2_id = %s)
            """,
            (conversation_id, user_id, user_id)
        )
        conversation = row_to_dict(cursor.fetchone())
        if not conversation:
            logging.warning(f"Conversation ID {conversation_id} not found or unauthorized for user ID {user_id}, Session: %s", session)
            return jsonify({"error": "Conversation not found or unauthorized"}), 404
       
        # Mark all messages as deleted for this user
        cursor.execute(
            """
            UPDATE messages
            SET deleted_for = COALESCE(deleted_for || ',', '') || %s
            WHERE conversation_id = %s
            """,
            (str(user_id), conversation_id)
        )
       
        # Check if conversation is empty for all participants
        cursor.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE conversation_id = %s
            AND (deleted_for IS NULL OR NOT deleted_for LIKE %s)
            """,
            (conversation_id, f'%{user_id}%')
        )
        remaining_messages = cursor.fetchone()[0]
       
        if remaining_messages == 0:
            cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            logging.info(f"Conversation ID {conversation_id} fully deleted as no messages remain, Session: %s", session)
       
        conn.commit()
        logging.info(f"Conversation ID {conversation_id} marked as deleted for user ID {user_id}, Session: %s", session)
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting conversation ID {conversation_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()



@app.route("/forgot_password", methods=["POST"])
def forgot_password():
    data = request.json
    email = data.get("email")
    if not email:
        return jsonify({"error": "Email required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
        user = row_to_dict(cursor.fetchone())
        if not user:
            return jsonify({"error": "Email not found"}), 404
        if not user["is_verified"]:
            return jsonify({"error": "Email not verified"}), 403

        if is_rate_limited(email):
            return jsonify({"error": "Please wait 2 minutes before requesting a new code."}), 429

        reset_code = str(random.randint(100000, 999999))
        expires_at = datetime.now() + timedelta(minutes=15)

        # Reuse send_verification_email but adapt for reset
        send_verification_email(email, reset_code)  # This sends the code

        cleanup_expired_codes(conn)
        cursor.execute("DELETE FROM verification_codes WHERE email = %s", (email,))
        cursor.execute(
            "INSERT INTO verification_codes (email, code, expires_at) VALUES (%s, %s, %s)",
            (email, reset_code, expires_at)
        )
        conn.commit()
        logging.info(f"Password reset code sent to {email}")
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error in forgot_password for {email}: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/verify_reset_code", methods=["POST"])
def verify_reset_code():
    data = request.json
    email = data.get("email")
    code = data.get("code")
    if not email or not code:
        return jsonify({"error": "Email and code required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT * FROM verification_codes WHERE email = %s AND code = %s",
            (email, code)
        )
        verification = row_to_dict(cursor.fetchone())
        if not verification:
            return jsonify({"error": "Invalid code"}), 400

        if datetime.now() > verification["expires_at"]:
            return jsonify({"error": "Code expired"}), 400

        cursor.execute("DELETE FROM verification_codes WHERE email = %s", (email,))
        conn.commit()
        logging.info(f"Reset code verified for {email}")
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error in verify_reset_code for {email}: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/reset_password", methods=["POST"])
def reset_password():
    data = request.json
    email = data.get("email")
    new_password = data.get("new_password")
    if not email or not new_password:
        return jsonify({"error": "Email and new password required"}), 400

    hashed_password = generate_password_hash(new_password, method="pbkdf2:sha256")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
        user = row_to_dict(cursor.fetchone())
        if not user:
            return jsonify({"error": "Email not found"}), 404

        cursor.execute(
            "UPDATE users SET password = %s WHERE email = %s",
            (hashed_password, email)
        )
        conn.commit()
        logging.info(f"Password reset for {email}")
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error in reset_password for {email}: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/update_activity_status", methods=["POST"])
def update_activity_status():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to update activity status, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    status = data.get("status")
    if not status or status not in ["Active", "Away"]:
        logging.warning(f"Invalid status provided: {status}, Session: %s", session)
        return jsonify({"error": "Invalid status"}), 400

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404

        cursor.execute(
            "UPDATE providers SET activity_status = %s WHERE id = %s",
            (status, provider["id"])
        )
        if cursor.rowcount == 0:
            logging.warning(f"No rows updated for provider_id {provider['id']}, status {status}, Session: %s", session)
            return jsonify({"error": "Failed to update status"}), 500

        conn.commit()
        logging.info(f"Activity status updated to {status} for provider_id {provider['id']}, Session: %s", session)
        return jsonify({"success": True}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error updating activity status for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/sitemap.xml')
def sitemap():
    return send_file('sitemap.xml')


@app.route("/upload_service_media", methods=["POST"])
def upload_service_media():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to upload service media, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider["id"]

        media_files = request.files.getlist("media_files")
        if not media_files:
            logging.warning("No media files provided for upload, Session: %s", session)
            return jsonify({"error": "No media files provided"}), 400

        uploaded_files = []
        for file in media_files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{filename}"
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(file_path)
                ext = filename.rsplit('.', 1)[1].lower()
                media_type = 'image' if ext in ['png', 'jpg', 'jpeg', 'gif'] else 'video'
                cursor.execute(
                    """
                    INSERT INTO service_media (provider_id, media_path, media_type, timestamp)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (provider_id, filename, media_type)
                )
                media_id = cursor.fetchone()['id']
                uploaded_files.append({"id": media_id, "media_path": filename, "media_type": media_type})
            else:
                logging.warning(f"Invalid file uploaded: {file.filename if file else 'None'}, Session: %s", session)

        conn.commit()
        logging.info(f"Uploaded {len(uploaded_files)} media files for provider_id {provider_id}, Session: %s", session)
        return jsonify({"success": True, "uploaded_files": uploaded_files}), 200

    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error uploading service media for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_provider_media/<int:provider_id>", methods=["GET"])
def get_provider_media(provider_id):
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to get provider media, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE id = %s", (provider_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider ID {provider_id} not found, Session: %s", session)
            return jsonify({"error": "Provider not found"}), 404

        cursor.execute(
            "SELECT id, media_path, media_type, timestamp FROM service_media WHERE provider_id = %s ORDER BY timestamp DESC",
            (provider_id,)
        )
        media = [row_to_dict(item) for item in cursor.fetchall()]

        # Ensure media paths are correctly formatted for direct access
        for item in media:
            item['media_path'] = item['media_path'].replace('static/uploads/', '')  # Clean path if needed

        logging.info(f"Fetched {len(media)} media items for provider_id {provider_id}, Session: %s", session)
        return jsonify({"success": True, "media": media}), 200
    except psycopg2.Error as e:
        logging.error(f"Database error fetching media for provider_id {provider_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.errorhandler(404)
def not_found_error(error):
    api_prefixes = (
        '/book_provider', '/get_', '/confirm_', '/reject_', '/reschedule_',
        '/send_', '/delete_', '/react_', '/remove_', '/pin_', '/star_',
        '/inbox', '/admin_remove_', '/admin_ban_', '/admin_unban_',
        '/admin_return', '/admin_message_', '/api/admin/', '/submit_rating'
    )
    if any(request.path.startswith(prefix) for prefix in api_prefixes):
        logging.warning(f"404 Not Found on API route {request.path}, Session: {session}")
        return jsonify({"error": "Not found"}), 404
    return render_template('404.html'), 404


@app.route("/get_latest_confirmed_booking_customer")
def get_latest_confirmed_booking_customer():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning(f"Unauthorized access to get_latest_confirmed_booking_customer, Session: {session}")
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch provider to verify
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: {session}")
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider["id"]

        # Fetch the latest confirmed booking for this provider
        cursor.execute(
            "SELECT customer_email, customer_phone FROM bookings WHERE provider_id = %s AND status = 'Confirmed' ORDER BY updated_at DESC LIMIT 1",
            (provider_id,)
        )
        booking = row_to_dict(cursor.fetchone())
        if not booking:
            logging.warning(f"No confirmed booking found for provider_id {provider_id}, Session: {session}")
            return jsonify({"error": "No confirmed booking found"}), 404

        # Fetch or create customer user_id (same logic as existing route)
        cursor.execute(
            "SELECT id FROM users WHERE email = %s OR phone = %s",
            (booking["customer_email"], booking["customer_phone"])
        )
        customer = row_to_dict(cursor.fetchone())

        # If no customer user exists, create one for chat purposes
        if not customer:
            # Use email as primary if available, else phone
            new_email = booking["customer_email"] if booking["customer_email"] else f"{booking['customer_phone']}@temp.example.com"
            new_phone = booking["customer_phone"] if booking["customer_phone"] else None
            dummy_password_hash = generate_password_hash('')  # Dummy hash for chat-only user
            cursor.execute(
                """
                INSERT INTO users (email, phone, password, role, is_verified, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (new_email, new_phone, dummy_password_hash, 'customer', True, 'active', datetime.now())
            )
            new_customer = row_to_dict(cursor.fetchone())
            if new_customer:
                customer = new_customer
                logging.info(f"Created temp user for customer in latest confirmed booking: ID {customer['id']}, email {new_email}, Session: {session}")
            else:
                logging.error(f"Failed to create temp user for latest confirmed booking, Session: {session}")
                return jsonify({"error": "Failed to create customer record"}), 500
        else:
            logging.info(f"Found existing customer for latest confirmed booking: ID {customer['id']}, Session: {session}")

        logging.info(f"Latest confirmed booking customer fetched for provider_id {provider_id}: customer_id {customer['id']}, Session: {session}")
        return jsonify({"success": True, "customer_id": customer["id"]}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error in get_latest_confirmed_booking_customer for provider_id {provider_id}: {str(e)}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/upload_story", methods=["POST"])
def upload_story():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to upload story, Session: %s", session)
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"success": False, "error": "Provider profile not found"}), 404
        provider_id = provider["id"]

        file = request.files.get("story_file")
        text = request.form.get("text", "")  # Optional text

        if not file or not allowed_file(file.filename):
            logging.warning("Invalid or no file provided for story upload, Session: %s", session)
            return jsonify({"success": False, "error": "Invalid file"}), 400

        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{filename}"
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)
        ext = filename.rsplit('.', 1)[1].lower()
        media_type = 'image' if ext in ['png', 'jpg', 'jpeg', 'gif'] else 'video'

        # Explicitly set viewed = FALSE to ensure new stories start unviewed
        cursor.execute(
            """
            INSERT INTO stories (provider_id, media_path, media_type, text, expires_at, viewed)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (provider_id, filename, media_type, text, datetime.now() + timedelta(hours=24), False)
        )
        story_row = cursor.fetchone()
        if not story_row:
            raise Exception("Failed to insert story")
        story_id = story_row['id']
        conn.commit()
        logging.info(f"Story uploaded with ID {story_id} for provider_id {provider_id}, viewed=False, text length: {len(text)}, Session: %s", session)
        return jsonify({"success": True, "story_id": story_id}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error uploading story for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"success": False, "error": "Database error"}), 500
    except Exception as e:
        logging.error(f"Unexpected error uploading story for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"success": False, "error": "Internal server error"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_stories")
def get_stories():
    if "user_id" not in session or session.get("user_role") != "provider":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            return jsonify({"success": False, "error": "Provider profile not found"}), 404
        provider_id = provider["id"]

        cursor.execute(
            """
            SELECT id, media_path, media_type, text, timestamp, COALESCE(viewed, false) as viewed
            FROM stories
            WHERE provider_id = %s AND expires_at > CURRENT_TIMESTAMP
            ORDER BY timestamp ASC
            """,
            (provider_id,)
        )
        rows = cursor.fetchall()
        stories = [row_to_dict(row) for row in rows]
        unviewed_count = sum(1 for story in stories if not story['viewed'])
        logging.info(f"Fetched {len(stories)} non-expired stories for provider_id {provider_id} (unviewed: {unviewed_count}), viewed statuses: {[s['viewed'] for s in stories]}, Session: {session}")
        return jsonify({"success": True, "stories": stories})
    except psycopg2.Error as e:
        logging.error(f"Database error fetching stories for user_id {user_id}: {e}, Session: {session}")
        return jsonify({"success": False, "error": "Database error"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/delete_story/<int:story_id>", methods=["DELETE", "POST"])
def delete_story(story_id):
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to delete story, Session: %s", session)
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"success": False, "error": "Provider profile not found"}), 404
        provider_id = provider["id"]

        # Fetch story details (media_path and media_type optional now)
        cursor.execute("SELECT media_path, media_type FROM stories WHERE id = %s AND provider_id = %s", (story_id, provider_id))
        story_row = cursor.fetchone()
        if not story_row:
            logging.warning(f"Story ID {story_id} not found for provider_id {provider_id}, Session: %s", session)
            return jsonify({"success": False, "error": "Story not found"}), 404

        story = row_to_dict(story_row)
        # Default media_type if null (prevents undefined/null crashes)
        media_type = story.get('media_type') or 'image'
        logging.info(f"Deleting story ID {story_id} (media_type: {media_type}) for provider_id {provider_id}, Session: %s", session)

        # Delete associated media file if it exists (non-blocking; log warnings only)
        if story["media_path"]:
            media_file_path = os.path.join(app.config["UPLOAD_FOLDER"], story["media_path"])
            if os.path.exists(media_file_path):
                try:
                    os.remove(media_file_path)
                    logging.info(f"Media file deleted for story ID {story_id}: {story['media_path']}, Session: %s", session)
                except OSError as e:
                    logging.warning(f"Failed to delete media file for story ID {story_id}: {e}, Session: %s", session)
                    # Non-fatal; continue with DB deletion

        # Delete the story record
        cursor.execute("DELETE FROM stories WHERE id = %s AND provider_id = %s", (story_id, provider_id))
        if cursor.rowcount == 0:
            logging.warning(f"No rows deleted for story ID {story_id}, provider_id {provider_id}, Session: %s", session)
            return jsonify({"success": False, "error": "Failed to delete story"}), 500

        conn.commit()
        logging.info(f"Story ID {story_id} ({media_type}) deleted by provider_id {provider_id}, Session: %s", session)
        return jsonify({"success": True}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error deleting story ID {story_id}: {e}, Session: %s", session)
        return jsonify({"success": False, "error": "Database error"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/upload_stories", methods=["POST"])
def upload_stories():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to upload stories, Session: %s", session)
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"success": False, "error": "Provider profile not found"}), 404
        provider_id = provider["id"]

        files = request.files.getlist("story_files")
        text = request.form.get("text", "")

        if not files:
            logging.warning("No files provided for stories upload, Session: %s", session)
            return jsonify({"success": False, "error": "No files provided"}), 400

        uploaded_stories = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{filename}"
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(file_path)
                ext = filename.rsplit('.', 1)[1].lower()
                media_type = 'image' if ext in ['png', 'jpg', 'jpeg', 'gif'] else 'video'

                cursor.execute(
                    """
                    INSERT INTO stories (provider_id, media_path, media_type, text, expires_at, viewed)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (provider_id, filename, media_type, text, datetime.now() + timedelta(hours=24), False)
                )
                story_row = cursor.fetchone()
                if not story_row:
                    raise Exception("Failed to insert story")
                story_id = story_row['id']
                uploaded_stories.append({"id": story_id, "media_path": filename, "media_type": media_type})
            else:
                logging.warning(f"Invalid file uploaded: {file.filename if file else 'None'}, Session: %s", session)

        conn.commit()
        logging.info(f"Uploaded {len(uploaded_stories)} stories for provider_id {provider_id}, text length: {len(text)}, Session: %s", session)
        return jsonify({"success": True, "uploaded_stories": uploaded_stories}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error uploading stories for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"success": False, "error": "Database error"}), 500
    except Exception as e:
        logging.error(f"Unexpected error uploading stories for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"success": False, "error": "Internal server error"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/mark_story_viewed/<int:story_id>", methods=["POST"])
def mark_story_viewed(story_id):
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to mark story viewed, Session: %s", session)
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"success": False, "error": "Provider profile not found"}), 404
        provider_id = provider["id"]

        # Mark as viewed instead of deleting
        cursor.execute(
            "UPDATE stories SET viewed = TRUE WHERE id = %s AND provider_id = %s AND viewed = FALSE",
            (story_id, provider_id)
        )
        if cursor.rowcount == 0:
            logging.warning(f"Story ID {story_id} not found or already viewed for provider_id {provider_id}, Session: %s", session)
            return jsonify({"success": False, "error": "Story not found or already viewed"}), 404

        conn.commit()
        logging.info(f"Story ID {story_id} marked as viewed by provider_id {provider_id}, Session: %s", session)
        return jsonify({"success": True}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error marking story viewed for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"success": False, "error": "Database error"}), 500
    finally:
        cursor.close()
        conn.close()




@app.route("/mark_story_viewed_for_customer/<int:story_id>", methods=["POST"])
def mark_story_viewed_for_customer(story_id):
    if "user_id" not in session or session.get("user_role") != "customer":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    customer_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO stories_views (story_id, customer_id)
            VALUES (%s, %s)
            ON CONFLICT (story_id, customer_id) DO NOTHING
            """,
            (story_id, customer_id)
        )
        conn.commit()
        return jsonify({"success": True}), 200
    except psycopg2.Error as e:
        conn.rollback()
        return jsonify({"success": False, "error": "Database error"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_provider_stories/<int:provider_id>")
def get_provider_stories(provider_id):
    if "user_id" not in session or session.get("user_role") != "customer":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    customer_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Mark all stories of this provider as viewed by this customer (idempotent)
        cursor.execute("""
            INSERT INTO stories_views (story_id, customer_id)
            SELECT s.id, %s
            FROM stories s
            WHERE s.provider_id = %s
              AND s.expires_at > CURRENT_TIMESTAMP
            ON CONFLICT (story_id, customer_id) DO NOTHING
        """, (customer_id, provider_id))
        conn.commit()

        # Fetch stories ordered for viewing
        cursor.execute("""
            SELECT id, media_path, media_type, text, timestamp
            FROM stories
            WHERE provider_id = %s AND expires_at > CURRENT_TIMESTAMP
            ORDER BY timestamp ASC
        """, (provider_id,))
        stories = [row_to_dict(row) for row in cursor.fetchall()]

        return jsonify({"success": True, "stories": stories})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Error fetching stories for provider {provider_id}: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_recent_booking_decisions")
def get_recent_booking_decisions():
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to get_recent_booking_decisions, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch customer's identifiers
        cursor.execute("SELECT email, phone FROM users WHERE id = %s", (user_id,))
        user = row_to_dict(cursor.fetchone())
        if not user:
            return jsonify({"error": "User not found"}), 404

        email = user.get('email')
        phone = user.get('phone')
        identifiers = []
        if email:
            identifiers.append(email)
        if phone:
            identifiers.append(phone)

        if not identifiers:
            return jsonify({"success": True, "decisions": []})

        placeholders = ','.join(['%s'] * len(identifiers))

        # ONLY Confirmed/Rescheduled (exactly as per your spec)
        cursor.execute(
            f"""
            SELECT 
                b.id, 
                b.provider_id, 
                b.customer_name, 
                b.service_date, 
                b.rescheduled_date, 
                b.status, 
                b.updated_at,
                p.name AS provider_name
            FROM bookings b
            JOIN providers p ON b.provider_id = p.id
            WHERE (b.customer_email IN ({placeholders}) OR b.customer_phone IN ({placeholders}))
              AND b.status IN ('Confirmed', 'Rescheduled')
            ORDER BY b.updated_at DESC
            LIMIT 10
            """,
            identifiers * 2
        )
        decisions = [row_to_dict(row) for row in cursor.fetchall()]

        # Build clean popup message exactly as you requested
        for decision in decisions:
            if decision['status'] == 'Confirmed':
                decision['message'] = f"Your booking has been confirmed. Warning: Do not pay for the service until it is complete."
            elif decision['status'] == 'Rescheduled':
                decision['message'] = f"Your booking has been Rescheduled. Warning: Do not pay for the service until it is complete."

        logging.info(f"Recent Confirmed/Rescheduled decisions returned for user_id {user_id}: {len(decisions)} decisions, Session: {session}")
        return jsonify({"success": True, "decisions": decisions})

    except psycopg2.Error as e:
        logging.error(f"Database error in get_recent_booking_decisions for user_id {user_id}: {e}, Session: {session}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_recent_rescheduled_booking")
def get_recent_rescheduled_booking():
    if "user_id" not in session or session.get("user_role") != "customer":
        logging.warning("Unauthorized access to get_recent_rescheduled_booking, Session: %s", session)
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch user's email and phone
        cursor.execute("SELECT email, phone FROM users WHERE id = %s", (user_id,))
        user = row_to_dict(cursor.fetchone())
        if not user:
            logging.warning("User not found for user_id %s in get_recent_rescheduled_booking, Session: %s", user_id, session)
            return jsonify({"error": "User not found"}), 404

        email = user.get('email')
        phone = user.get('phone')

        # Collect possible identifiers
        identifiers = []
        if email:
            identifiers.append(email)
        if phone:
            identifiers.append(phone)

        if not identifiers:
            return jsonify({"success": True, "decision": None})

        placeholders = ','.join(['%s'] * len(identifiers))
        cursor.execute(
            f"""
            SELECT b.id, b.provider_id, b.customer_name, b.service_date, b.rescheduled_date, b.status, b.updated_at,
                   p.name AS provider_name
            FROM bookings b
            JOIN providers p ON b.provider_id = p.id
            WHERE (b.customer_email IN ({placeholders}) OR b.customer_phone IN ({placeholders}))
            AND b.status = 'Rescheduled'
            ORDER BY b.updated_at DESC
            LIMIT 1
            """,
            identifiers * 2  # Duplicate for both IN clauses
        )
        decision = row_to_dict(cursor.fetchone())
        if decision:
            # Format message for rescheduled
            decision['message'] = f"The booking you requested with {decision['provider_name']} has been rescheduled."
            if decision['rescheduled_date']:
                decision['message'] += f" to {decision['rescheduled_date'][:10]}."
            else:
                decision['message'] += " to a new date."
            logging.info(f"Recent rescheduled booking fetched for user_id %s: %s, Session: %s", user_id, decision['id'], session)
            return jsonify({"success": True, "decision": decision})
        else:
            logging.info("No recent rescheduled booking found for user_id %s, Session: %s", user_id, session)
            return jsonify({"success": True, "decision": None})
    except psycopg2.Error as e:
        logging.error("Database error in get_recent_rescheduled_booking for user_id %s: %s, Session: %s", user_id, e, session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_story_counts/<int:provider_id>")
def get_story_counts(provider_id):
    if "user_id" not in session or session.get("user_role") != "customer":
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    customer_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Total active stories
        cursor.execute(
            "SELECT COUNT(*) FROM stories WHERE provider_id = %s AND expires_at > CURRENT_TIMESTAMP",
            (provider_id,)
        )
        total_active = cursor.fetchone()[0]

        # Unviewed by this customer
        cursor.execute("""
            SELECT COUNT(*)
            FROM stories s
            LEFT JOIN stories_views sv ON s.id = sv.story_id AND sv.customer_id = %s
            WHERE s.provider_id = %s AND s.expires_at > CURRENT_TIMESTAMP AND sv.story_id IS NULL
        """, (customer_id, provider_id))
        unviewed = cursor.fetchone()[0]

        return jsonify({
            "success": True,
            "total_active": total_active,
            "unviewed": unviewed
        })
    except psycopg2.Error as e:
        logging.error(f"Error in get_story_counts for provider {provider_id}: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_first_story_media/<int:provider_id>")
def get_first_story_media(provider_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT media_path, media_type
            FROM stories
            WHERE provider_id = %s AND expires_at > CURRENT_TIMESTAMP
            ORDER BY timestamp ASC LIMIT 1
        """, (provider_id,))
        story = row_to_dict(cursor.fetchone())
        if story:
            return jsonify({"success": True, "media_path": story["media_path"], "media_type": story["media_type"]})
        return jsonify({"success": False})
    finally:
        cursor.close()
        conn.close()



@app.route("/upload_portfolio", methods=["POST"])
def upload_portfolio():
    skills = request.form.get("skills", "").strip()
    experience = request.form.get("experience", "").strip()
    github_links_list = request.form.getlist("github_links[]")  # Handle dynamic GitHub links
    github_links = ','.join(filter(None, github_links_list)).strip()  # Join non-empty links with comma

    if not skills or not experience or not github_links:
        logging.warning("Missing required portfolio fields, Session: %s", session)
        return jsonify({"error": "Skills, Experience, and at least one GitHub link are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (session["user_id"],))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {session['user_id']}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404
        provider_id = provider["id"]

        # Insert or update portfolio (UPSERT) - Added certifications and work_samples as empty strings for table completeness
        cursor.execute(
            """
            INSERT INTO portfolios (provider_id, skills, certifications, experience, work_samples, github_links, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (provider_id) DO UPDATE
            SET skills = EXCLUDED.skills,
                certifications = EXCLUDED.certifications,
                experience = EXCLUDED.experience,
                work_samples = EXCLUDED.work_samples,
                github_links = EXCLUDED.github_links,
                created_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (provider_id, skills, '', experience, '', github_links)
        )
        portfolio_id = cursor.fetchone()['id']
        conn.commit()
        logging.info(f"Portfolio uploaded/updated with ID {portfolio_id} for provider_id {provider_id}, Session: %s", session)
        return jsonify({"success": True, "portfolio_id": portfolio_id}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error uploading portfolio for user_id {session['user_id']}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    except Exception as e:
        conn.rollback()
        logging.error(f"Unexpected error uploading portfolio for user_id {session['user_id']}: {e}, Session: %s", session)
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/robots.txt")
def robots():
    return send_from_directory(
        directory=app.static_folder,
        path="robots.txt",
        mimetype="text/plain"
    )


@app.route("/sitemap.xml", endpoint="static_sitemap")
def serve_sitemap():
    return send_from_directory(
        directory=app.static_folder,
        path="sitemap.xml",
        mimetype="application/xml"
    )


@app.route("/get_booking_history")
def get_booking_history():
    if "user_id" not in session or session.get("user_role") != "provider":
        logging.warning("Unauthorized access to get_booking_history, Session: %s", session)
        return jsonify({"error": "Unauthorized, please log in as a provider."}), 401

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Get the provider's internal ID
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            logging.warning(f"Provider not found for user_id {user_id}, Session: %s", session)
            return jsonify({"error": "Provider profile not found"}), 404

        provider_id = provider["id"]

        # Fetch EVERY booking the provider has EVER received (no limit, ordered newest first)
        cursor.execute("""
            SELECT 
                b.id,
                b.customer_name,
                b.customer_phone,
                b.customer_email,
                b.location,
                b.service_date,
                b.rescheduled_date,
                b.status,
                b.created_at,
                b.updated_at,
                b.rejected_reason
            FROM bookings b
            WHERE b.provider_id = %s
            ORDER BY b.updated_at DESC
        """, (provider_id,))
        bookings_raw = cursor.fetchall()

        bookings = []
        for row in bookings_raw:
            booking = row_to_dict(row)

            # === EXACT LOGIC FRONTEND EXPECTS ===
            if booking.get("status") == "Pending" or not booking.get("status"):
                booking["provider_response"] = "pending response"
            elif booking.get("status") == "Rejected" and booking.get("rejected_reason"):
                booking["provider_response"] = booking["rejected_reason"]
            else:
                booking["provider_response"] = booking.get("status", "No response")

            # === NEW: Add response_date for "Responded On" display ===
            # Use updated_at as the response timestamp (when provider last acted)
            # For Pending bookings, keep N/A as requested
            if booking.get("status") == "Pending" or not booking.get("status"):
                booking["response_date"] = "N/A"
            else:
                # Use the already-formatted updated_at (ISO format from earlier code)
                booking["response_date"] = booking.get("updated_at") or "N/A"

            # Safe date formatting for frontend (JSON safe)
            if booking.get("created_at"):
                booking["created_at"] = booking["created_at"].isoformat() if hasattr(booking["created_at"], "isoformat") else str(booking["created_at"])
            if booking.get("updated_at"):
                booking["updated_at"] = booking["updated_at"].isoformat() if hasattr(booking["updated_at"], "isoformat") else str(booking["updated_at"])
            if booking.get("service_date"):
                booking["service_date"] = str(booking["service_date"]) if booking["service_date"] else None
            if booking.get("rescheduled_date"):
                booking["rescheduled_date"] = str(booking["rescheduled_date"]) if booking["rescheduled_date"] else None

            bookings.append(booking)

        logging.info(f"Fetched {len(bookings)} bookings in history for provider_id {provider_id}, Session: %s", session)

        return jsonify({
            "success": True,
            "bookings": bookings
        }), 200

    except psycopg2.Error as e:
        logging.error(f"Database error in get_booking_history for user_id {user_id}: {e}, Session: %s", session)
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/update_provider_location", methods=["POST"])
def update_provider_location():
    if "user_id" not in session or session.get("user_role") != "provider":
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    if latitude is None or longitude is None:
        return jsonify({"error": "Latitude and longitude required"}), 400
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM providers WHERE user_id = %s", (user_id,))
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            return jsonify({"error": "Provider not found"}), 404
        cursor.execute(
            "UPDATE providers SET latitude = %s, longitude = %s, location_updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (latitude, longitude, provider["id"])
        )
        conn.commit()
        return jsonify({"success": True})
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Error updating provider location for user_id {user_id}: {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_provider_location/<int:provider_id>")
def get_provider_location(provider_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT latitude, longitude, location_updated_at FROM providers WHERE id = %s",
            (provider_id,)
        )
        provider = row_to_dict(cursor.fetchone())
        if not provider:
            return jsonify({"error": "Provider not found"}), 404
        lat = provider.get("latitude")
        lng = provider.get("longitude")
        updated_at = provider.get("location_updated_at")
        # Consider location stale if older than 5 minutes
        is_live = False
        if lat and lng and updated_at:
            age_seconds = (datetime.now() - updated_at).total_seconds()
            is_live = age_seconds < 300
        return jsonify({
            "success": True,
            "latitude": lat,
            "longitude": lng,
            "is_live": is_live,
            "updated_at": updated_at.isoformat() if updated_at else None
        })
    except psycopg2.Error as e:
        logging.error(f"Error fetching provider location for provider_id {provider_id}: {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/submit_customer_post", methods=["POST"])
def submit_customer_post():
    if "user_id" not in session or session.get("user_role") != "customer":
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    content = request.form.get("content", "").strip()
    media_file = request.files.get("media_file")

    if not content and not media_file:
        return jsonify({"error": "Post content or media is required"}), 400

    media_path = None
    media_type = None

    if media_file and allowed_file(media_file.filename):
        filename = secure_filename(media_file.filename)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"post_{timestamp_str}_{filename}"
        media_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        media_path = filename
        ext = filename.rsplit('.', 1)[1].lower()
        if ext in ['png', 'jpg', 'jpeg', 'gif']:
            media_type = 'image'
        elif ext in ['mp4', 'mov', 'webm']:
            media_type = 'video'

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO customer_posts (customer_id, content, media_path, media_type, created_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (user_id, content, media_path, media_type)
        )
        post_id = cursor.fetchone()['id']
        conn.commit()
        logging.info(f"Customer post created with ID {post_id} by user_id {user_id}")
        return jsonify({"success": True, "post_id": post_id}), 200
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Database error submitting customer post for user_id {user_id}: {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/get_customer_posts", methods=["GET"])
def get_customer_posts():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT cp.id, cp.content, cp.media_path, cp.media_type, cp.created_at,
                   u.email AS customer_email
            FROM customer_posts cp
            JOIN users u ON cp.customer_id = u.id
            ORDER BY cp.created_at DESC
            LIMIT 100
            """,
        )
        posts = [row_to_dict(row) for row in cursor.fetchall()]
        for post in posts:
            if post.get("created_at"):
                post["created_at"] = post["created_at"].isoformat()
        return jsonify({"success": True, "posts": posts}), 200
    except psycopg2.Error as e:
        logging.error(f"Database error fetching customer posts: {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    try:
        logging.basicConfig(level=logging.INFO)
        create_tables()
        app.run(debug=True, host="0.0.0.0", port=5000)
    except Exception as e:
        logging.critical(f"Application startup failed: {e}")
        raise