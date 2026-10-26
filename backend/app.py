from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

from werkzeug.security import generate_password_hash, check_password_hash

import sqlite3
import sys
import secrets
import uuid
from pathlib import Path
from werkzeug.utils import secure_filename


# ============================================================
# PATH CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_DIR = BASE_DIR / "database"
DATABASE_PATH = DATABASE_DIR / "census.db"

FRONTEND_DIR = BASE_DIR / "frontend"
TEMPLATE_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

# ============================================================
# DOCUMENT UPLOAD CONFIGURATION
# ============================================================

UPLOAD_DIR = BASE_DIR / "uploads" / "documents"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_DOCUMENT_EXTENSIONS = {
    "pdf", "doc", "docx", "txt",
    "jpg", "jpeg", "png",
    "xls", "xlsx", "csv"
}

MAX_DOCUMENT_SIZE = 5 * 1024 * 1024  # 5 MB per file

BLOCKCHAIN_DIR = BASE_DIR / "blockchain"

sys.path.append(str(BLOCKCHAIN_DIR))


# ============================================================
# BLOCKCHAIN SERVICE
# ============================================================

from blockchain_service import (
    log_record,
    verify_record,
    get_latest_record,
    get_record_history,
    get_blockchain_info
)


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR)
)

app.secret_key = "smart-census-system-development-key"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():
    connection = sqlite3.connect(DATABASE_PATH)

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    return connection


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_database():

    DATABASE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = get_db_connection()

    cursor = connection.cursor()

    # --------------------------------------------------------
    # IMPORTANT:
    # Existing users table uses `name`, not `full_name`.
    #
    # Therefore we DO NOT recreate or modify users table.
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS census_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            date_of_birth TEXT NOT NULL,
            mobile_number TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT NOT NULL,
            occupation TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # DELETED RECORD AUDIT TABLE
    #
    # This table keeps ownership information even after the
    # original census record is deleted from census_records.
    #
    # This allows blockchain history to remain accessible.
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deleted_record_audit (
            record_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # PASSWORD RESET TABLE
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # --------------------------------------------------------
    # CENSUS DOCUMENTS TABLE
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS census_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL UNIQUE,
            file_path TEXT NOT NULL,
            mime_type TEXT,
            file_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (record_id) REFERENCES census_records(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    connection.commit()

    connection.close()


# ============================================================
# BUILD RECORD DATA FOR BLOCKCHAIN
# ============================================================

def build_record_data(row):

    return {
        "full_name": row["full_name"],
        "age": int(row["age"]),
        "gender": row["gender"],
        "date_of_birth": row["date_of_birth"],
        "mobile_number": row["mobile_number"],
        "address": row["address"],
        "city": row["city"],
        "occupation": row["occupation"]
    }


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def allowed_document(filename):
    if not filename or "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_DOCUMENT_EXTENSIONS


def save_uploaded_documents(files, record_id, user_id, connection):
    """Save multiple uploaded documents for a census record."""
    saved_count = 0
    errors = []

    for uploaded_file in files:
        if not uploaded_file or not uploaded_file.filename:
            continue

        original_name = secure_filename(uploaded_file.filename)

        if not original_name:
            errors.append("One file had an invalid filename.")
            continue

        if not allowed_document(original_name):
            errors.append(
                f"{original_name}: file type is not allowed."
            )
            continue

        file_content = uploaded_file.read()
        file_size = len(file_content)

        if file_size > MAX_DOCUMENT_SIZE:
            errors.append(
                f"{original_name}: maximum file size is 5 MB."
            )
            continue

        extension = original_name.rsplit(".", 1)[1].lower()
        stored_name = f"{uuid.uuid4().hex}.{extension}"
        destination = UPLOAD_DIR / stored_name

        try:
            destination.write_bytes(file_content)

            connection.execute(
                """
                INSERT INTO census_documents
                (
                    record_id,
                    user_id,
                    original_name,
                    stored_name,
                    file_path,
                    mime_type,
                    file_size
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    user_id,
                    original_name,
                    stored_name,
                    str(destination.relative_to(BASE_DIR)),
                    uploaded_file.mimetype,
                    file_size
                )
            )
            saved_count += 1

        except Exception as error:
            if destination.exists():
                destination.unlink()
            errors.append(f"{original_name}: could not be saved.")
            print("Document Save Error:", error)

    return saved_count, errors


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    if "user_id" in session:
        return redirect(
            url_for("dashboard")
        )

    return redirect(
        url_for("login")
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        # Support existing form if it uses full_name
        if not name:

            name = request.form.get(
                "full_name",
                ""
            ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not name or not email or not password:

            flash(
                "Please fill all required fields.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        hashed_password = generate_password_hash(
            password
        )

        connection = get_db_connection()

        try:

            connection.execute(
                """
                INSERT INTO users
                (name, email, password)
                VALUES (?, ?, ?)
                """,
                (
                    name,
                    email,
                    hashed_password
                )
            )

            connection.commit()

            flash(
                "Registration successful. Please login.",
                "success"
            )

            return redirect(
                url_for("login")
            )

        except sqlite3.IntegrityError:

            flash(
                "Email already registered.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        finally:

            connection.close()

    return render_template(
        "register.html"
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        connection = get_db_connection()

        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        connection.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            session["user_email"] = user["email"]

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid email or password.",
            "error"
        )

    return render_template(
        "login.html"
    )


# ============================================================
# FORGOT PASSWORD
# ============================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not email:
            flash("Please enter your registered email.", "error")
            return redirect(url_for("forgot_password"))

        connection = get_db_connection()
        user = connection.execute(
            "SELECT id, email FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if not user:
            connection.close()
            flash("No account found with this email address.", "error")
            return redirect(url_for("forgot_password"))

        # Remove old reset sessions for this user.
        connection.execute(
            "DELETE FROM password_reset_sessions WHERE user_id = ?",
            (user["id"],)
        )

        token = secrets.token_urlsafe(32)

        connection.execute(
            """
            INSERT INTO password_reset_sessions (user_id, token)
            VALUES (?, ?)
            """,
            (user["id"], token)
        )
        connection.commit()
        connection.close()

        session["password_reset_token"] = token
        return redirect(url_for("reset_password"))

    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():

    token = session.get("password_reset_token")

    if not token:
        flash("Please start the password reset process again.", "error")
        return redirect(url_for("forgot_password"))

    connection = get_db_connection()
    reset_session = connection.execute(
        """
        SELECT prs.id, prs.user_id, u.email
        FROM password_reset_sessions prs
        JOIN users u ON u.id = prs.user_id
        WHERE prs.token = ?
        """,
        (token,)
    ).fetchone()

    if not reset_session:
        connection.close()
        session.pop("password_reset_token", None)
        flash("This password reset session is no longer valid.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < 6:
            connection.close()
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for("reset_password"))

        if new_password != confirm_password:
            connection.close()
            flash("Passwords do not match.", "error")
            return redirect(url_for("reset_password"))

        hashed_password = generate_password_hash(new_password)

        connection.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (hashed_password, reset_session["user_id"])
        )

        connection.execute(
            "DELETE FROM password_reset_sessions WHERE id = ?",
            (reset_session["id"],)
        )
        connection.commit()
        connection.close()

        session.pop("password_reset_token", None)
        flash("Password changed successfully. Please login.", "success")
        return redirect(url_for("login"))

    connection.close()
    return render_template("reset_password.html", email=reset_session["email"])


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    connection = get_db_connection()

    total_records = connection.execute(
        """
        SELECT COUNT(*)
        FROM census_records
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()[0]

    recent_records = connection.execute(
        """
        SELECT *
        FROM census_records
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (user_id,)
    ).fetchall()

    connection.close()

    try:

        blockchain_info = get_blockchain_info()

    except Exception as error:

        print(
            "Blockchain Info Error:",
            error
        )

        blockchain_info = {
            "connected": False,
            "account": "",
            "contract_address": "",
            "chain_id": "",
            "latest_block": ""
        }

    return render_template(
        "dashboard.html",
        total_records=total_records,
        recent_records=recent_records,
        blockchain_info=blockchain_info
    )


# ============================================================
# ADD CENSUS RECORD
# ============================================================

@app.route(
    "/add-record",
    methods=["GET", "POST"]
)
def add_record():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        age = request.form.get(
            "age",
            ""
        ).strip()

        gender = request.form.get(
            "gender",
            ""
        ).strip()

        date_of_birth = request.form.get(
            "date_of_birth",
            ""
        ).strip()

        mobile_number = request.form.get(
            "mobile_number",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        city = request.form.get(
            "city",
            ""
        ).strip()

        occupation = request.form.get(
            "occupation",
            ""
        ).strip()

        if not all([
            full_name,
            age,
            gender,
            date_of_birth,
            mobile_number,
            address,
            city,
            occupation
        ]):

            flash(
                "Please fill all fields.",
                "error"
            )

            return redirect(
                url_for("add_record")
            )

        try:

            age = int(age)

        except ValueError:

            flash(
                "Age must be a valid number.",
                "error"
            )

            return redirect(
                url_for("add_record")
            )

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO census_records
            (
                user_id,
                full_name,
                age,
                gender,
                date_of_birth,
                mobile_number,
                address,
                city,
                occupation
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                full_name,
                age,
                gender,
                date_of_birth,
                mobile_number,
                address,
                city,
                occupation
            )
        )

        record_id = cursor.lastrowid

        # ----------------------------------------------------
        # DOCUMENT UPLOADS
        # ----------------------------------------------------
        uploaded_files = request.files.getlist("documents")
        document_count, document_errors = save_uploaded_documents(
            uploaded_files,
            record_id,
            session["user_id"],
            connection
        )

        connection.commit()

        record = connection.execute(
            """
            SELECT *
            FROM census_records
            WHERE id = ?
            """,
            (record_id,)
        ).fetchone()

        connection.close()

        # ----------------------------------------------------
        # BLOCKCHAIN CREATE
        # ----------------------------------------------------

        try:

            record_data = build_record_data(
                record
            )

            result = log_record(
                record_id,
                record_data,
                "CREATE"
            )

            print(
                "Blockchain CREATE:",
                result
            )

            flash(
                "Census record added and secured on blockchain.",
                "success"
            )

        except Exception as error:

            print(
                "Blockchain CREATE Error:",
                error
            )

            flash(
                "Census record added, but blockchain logging failed.",
                "error"
            )

        if document_count:
            flash(
                f"{document_count} document(s) uploaded successfully.",
                "success"
            )
        for document_error in document_errors:
            flash(document_error, "error")

        return redirect(
            url_for("records")
        )

    return render_template(
        "add_record.html"
    )


# ============================================================
# VIEW RECORDS
# ============================================================

@app.route("/records")
def records():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    connection = get_db_connection()

    records_data = connection.execute(
        """
        SELECT *
        FROM census_records
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()

    documents = {}
    for row in records_data:
        documents[row["id"]] = connection.execute(
            """
            SELECT * FROM census_documents
            WHERE record_id = ? AND user_id = ?
            ORDER BY id DESC
            """,
            (row["id"], session["user_id"])
        ).fetchall()

    connection.close()

    return render_template(
        "records.html",
        records=records_data,
        documents=documents
    )


# ============================================================
# EDIT RECORD
# ============================================================

@app.route(
    "/edit-record/<int:record_id>",
    methods=["GET", "POST"]
)
def edit_record(record_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    connection = get_db_connection()

    record = connection.execute(
        """
        SELECT *
        FROM census_records
        WHERE id = ?
        AND user_id = ?
        """,
        (
            record_id,
            session["user_id"]
        )
    ).fetchone()

    if not record:

        connection.close()

        flash(
            "Record not found.",
            "error"
        )

        return redirect(
            url_for("records")
        )

    if request.method == "POST":

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        age = request.form.get(
            "age",
            ""
        ).strip()

        gender = request.form.get(
            "gender",
            ""
        ).strip()

        date_of_birth = request.form.get(
            "date_of_birth",
            ""
        ).strip()

        mobile_number = request.form.get(
            "mobile_number",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        city = request.form.get(
            "city",
            ""
        ).strip()

        occupation = request.form.get(
            "occupation",
            ""
        ).strip()

        if not all([
            full_name,
            age,
            gender,
            date_of_birth,
            mobile_number,
            address,
            city,
            occupation
        ]):

            connection.close()

            flash(
                "Please fill all fields.",
                "error"
            )

            return redirect(
                url_for(
                    "edit_record",
                    record_id=record_id
                )
            )

        try:

            age = int(age)

        except ValueError:

            connection.close()

            flash(
                "Age must be a valid number.",
                "error"
            )

            return redirect(
                url_for(
                    "edit_record",
                    record_id=record_id
                )
            )

        connection.execute(
            """
            UPDATE census_records

            SET
                full_name = ?,
                age = ?,
                gender = ?,
                date_of_birth = ?,
                mobile_number = ?,
                address = ?,
                city = ?,
                occupation = ?

            WHERE id = ?
            AND user_id = ?
            """,
            (
                full_name,
                age,
                gender,
                date_of_birth,
                mobile_number,
                address,
                city,
                occupation,
                record_id,
                session["user_id"]
            )
        )

        connection.commit()

        updated_record = connection.execute(
            """
            SELECT *
            FROM census_records
            WHERE id = ?
            """,
            (record_id,)
        ).fetchone()

        # ----------------------------------------------------
        # DOCUMENT UPLOADS DURING EDIT
        # ----------------------------------------------------
        uploaded_files = request.files.getlist("documents")
        document_count, document_errors = save_uploaded_documents(
            uploaded_files,
            record_id,
            session["user_id"],
            connection
        )
        connection.commit()

        connection.close()

        # ----------------------------------------------------
        # BLOCKCHAIN UPDATE
        # ----------------------------------------------------

        try:

            updated_data = build_record_data(
                updated_record
            )

            result = log_record(
                record_id,
                updated_data,
                "UPDATE"
            )

            print(
                "Blockchain UPDATE:",
                result
            )

            flash(
                "Record updated and blockchain history created.",
                "success"
            )

        except Exception as error:

            print(
                "Blockchain UPDATE Error:",
                error
            )

            flash(
                "Record updated, but blockchain logging failed.",
                "error"
            )

        if document_count:
            flash(
                f"{document_count} document(s) uploaded successfully.",
                "success"
            )
        for document_error in document_errors:
            flash(document_error, "error")

        return redirect(
            url_for("records")
        )

    # Load existing documents for the edit page.
    existing_documents = connection.execute(
        """
        SELECT * FROM census_documents
        WHERE record_id = ? AND user_id = ?
        ORDER BY id DESC
        """,
        (record_id, session["user_id"])
    ).fetchall()

    connection.close()

    return render_template(
        "edit_record.html",
        record=record,
        documents=existing_documents
    )


# ============================================================
# DELETE RECORD
# ============================================================

@app.route(
    "/delete-record/<int:record_id>",
    methods=["POST"]
)
def delete_record(record_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    connection = get_db_connection()

    record = connection.execute(
        """
        SELECT *
        FROM census_records
        WHERE id = ?
        AND user_id = ?
        """,
        (
            record_id,
            session["user_id"]
        )
    ).fetchone()

    if not record:

        connection.close()

        flash(
            "Record not found.",
            "error"
        )

        return redirect(
            url_for("records")
        )

    # Save data BEFORE deletion because blockchain needs it.
    record_data = build_record_data(
        record
    )

    # Save document file paths so physical files can also be removed.
    document_rows = connection.execute(
        """
        SELECT file_path FROM census_documents
        WHERE record_id = ? AND user_id = ?
        """,
        (record_id, session["user_id"])
    ).fetchall()

    # --------------------------------------------------------
    # SAVE DELETION OWNERSHIP
    #
    # This allows the History page to know which user owned
    # the deleted record.
    # --------------------------------------------------------

    connection.execute(
        """
        INSERT OR REPLACE INTO deleted_record_audit
        (
            record_id,
            user_id
        )
        VALUES (?, ?)
        """,
        (
            record_id,
            session["user_id"]
        )
    )

    # --------------------------------------------------------
    # DELETE FROM MAIN CENSUS TABLE
    # --------------------------------------------------------

    connection.execute(
        """
        DELETE FROM census_records
        WHERE id = ?
        AND user_id = ?
        """,
        (
            record_id,
            session["user_id"]
        )
    )

    connection.commit()

    connection.close()

    for document_row in document_rows:
        try:
            document_path = BASE_DIR / document_row["file_path"]
            if document_path.exists():
                document_path.unlink()
        except Exception as error:
            print("Deleted Record Document Cleanup Error:", error)

    # --------------------------------------------------------
    # BLOCKCHAIN DELETE
    # --------------------------------------------------------

    try:

        result = log_record(
            record_id,
            record_data,
            "DELETE"
        )

        print(
            "Blockchain DELETE:",
            result
        )

        flash(
            "Record deleted and deletion logged on blockchain.",
            "success"
        )

    except Exception as error:

        print(
            "Blockchain DELETE Error:",
            error
        )

        flash(
            "Record deleted, but blockchain logging failed.",
            "error"
        )

    return redirect(
        url_for("records")
    )


# ============================================================
# DOCUMENTS - DOWNLOAD
# ============================================================

@app.route("/document/<int:document_id>/download")
def download_document(document_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    document = connection.execute(
        """
        SELECT * FROM census_documents
        WHERE id = ? AND user_id = ?
        """,
        (document_id, session["user_id"])
    ).fetchone()
    connection.close()

    if not document:
        flash("Document not found or access denied.", "error")
        return redirect(url_for("records"))

    file_path = BASE_DIR / document["file_path"]

    if not file_path.exists():
        flash("The document file is missing from the server.", "error")
        return redirect(url_for("records"))

    from flask import send_file
    return send_file(
        file_path,
        as_attachment=True,
        download_name=document["original_name"]
    )


# ============================================================
# DOCUMENTS - DELETE
# ============================================================

@app.route("/document/<int:document_id>/delete", methods=["POST"])
def delete_document(document_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    document = connection.execute(
        """
        SELECT * FROM census_documents
        WHERE id = ? AND user_id = ?
        """,
        (document_id, session["user_id"])
    ).fetchone()

    if not document:
        connection.close()
        flash("Document not found or access denied.", "error")
        return redirect(url_for("records"))

    file_path = BASE_DIR / document["file_path"]

    connection.execute(
        "DELETE FROM census_documents WHERE id = ? AND user_id = ?",
        (document_id, session["user_id"])
    )
    connection.commit()
    connection.close()

    try:
        if file_path.exists():
            file_path.unlink()
    except Exception as error:
        print("Document File Delete Error:", error)

    flash("Document deleted successfully.", "success")
    return redirect(url_for("records"))


# ============================================================
# VERIFY RECORD
# ============================================================

@app.route(
    "/verify-record/<int:record_id>"
)
def verify_record_route(record_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    connection = get_db_connection()

    record = connection.execute(
        """
        SELECT *
        FROM census_records
        WHERE id = ?
        AND user_id = ?
        """,
        (
            record_id,
            session["user_id"]
        )
    ).fetchone()

    connection.close()

    if not record:

        flash(
            "Record not found.",
            "error"
        )

        return redirect(
            url_for("records")
        )

    record_data = build_record_data(
        record
    )

    result = verify_record(
        record_id,
        record_data
    )

    if result.get("verified"):

        flash(
            "Blockchain verification successful. "
            "Record integrity is intact.",
            "success"
        )

    else:

        flash(
            "Blockchain verification failed. "
            "Record integrity could not be confirmed.",
            "error"
        )

    return redirect(
        url_for("records")
    )


# ============================================================
# BLOCKCHAIN HISTORY
# ============================================================

@app.route(
    "/blockchain-history/<int:record_id>"
)
def blockchain_history(record_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    connection = get_db_connection()

    # --------------------------------------------------------
    # FIRST:
    # Check whether record still exists.
    # --------------------------------------------------------

    record = connection.execute(
        """
        SELECT *
        FROM census_records
        WHERE id = ?
        AND user_id = ?
        """,
        (
            record_id,
            session["user_id"]
        )
    ).fetchone()

    # --------------------------------------------------------
    # IF RECORD DOES NOT EXIST:
    #
    # Check deleted_record_audit table.
    # --------------------------------------------------------

    deleted_record = None

    if not record:

        deleted_record = connection.execute(
            """
            SELECT *
            FROM deleted_record_audit
            WHERE record_id = ?
            AND user_id = ?
            """,
            (
                record_id,
                session["user_id"]
            )
        ).fetchone()

    connection.close()

    # --------------------------------------------------------
    # USER DOES NOT OWN THIS RECORD
    # --------------------------------------------------------

    if not record and not deleted_record:

        flash(
            "Record history not found or access denied.",
            "error"
        )

        return redirect(
            url_for("records")
        )

    # --------------------------------------------------------
    # GET BLOCKCHAIN HISTORY
    # --------------------------------------------------------

    try:

        history = get_record_history(
            record_id
        )

        blockchain_info = get_blockchain_info()

    except Exception as error:

        print(
            "Blockchain History Error:",
            error
        )

        history = []

        blockchain_info = {
            "connected": False,
            "account": "",
            "contract_address": "",
            "chain_id": "",
            "latest_block": ""
        }

        flash(
            "Unable to load blockchain history.",
            "error"
        )

    # --------------------------------------------------------
    # FOR DELETED RECORD:
    #
    # The original SQLite record no longer exists.
    # Create a small display object so the existing history
    # template can still work.
    # --------------------------------------------------------

    if not record:

        record = {
            "id": record_id,
            "full_name": "Deleted Census Record",
            "age": "-",
            "gender": "-",
            "date_of_birth": "-",
            "mobile_number": "-",
            "address": "-",
            "city": "-",
            "occupation": "-",
            "created_at": deleted_record["deleted_at"]
        }

    return render_template(
        "blockchain_history.html",
        record=record,
        history=history,
        blockchain_info=blockchain_info
    )



# ============================================================
# PROFILE
# ============================================================

@app.route("/profile")
def profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()

    user = connection.execute(
        """
        SELECT id, name, email, created_at
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    connection.close()

    if not user:

        session.clear()

        flash(
            "User profile could not be found.",
            "error"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "account.html",
        page="profile",
        user=user
    )


# ============================================================
# SETTINGS
# ============================================================

@app.route("/settings")
def settings():

    if "user_id" not in session:
        return redirect(
            url_for("login")
        )

    return render_template(
        "account.html",
        page="settings",
        user_name=session.get(
            "user_name",
            "User"
        ),
        user_email=session.get(
            "user_email",
            ""
        )
    )


# ============================================================
# HELP / SUPPORT
# ============================================================

@app.route("/help")
def help_page():

    if "user_id" not in session:
        return redirect(
            url_for("login")
        )

    return render_template(
        "account.html",
        page="help",
        user_name=session.get(
            "user_name",
            "User"
        ),
        user_email=session.get(
            "user_email",
            ""
        )
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    initialize_database()

    print("\n========================================")
    print("       SMART CENSUS SYSTEM")
    print("========================================")
    print("Server running at:")
    print("http://127.0.0.1:5000")
    print("========================================\n")

    app.run(
        debug=True
    )
    