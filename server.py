import hmac
import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEFAULT_DATABASE = Path(__file__).resolve().parent / "data" / "interests.sqlite3"
DATABASE_PATH = Path(os.environ.get("PNG_HUB_DATABASE_PATH", DEFAULT_DATABASE))
MEDIA_DIR = FRONTEND_DIR / "uploads"
ADMIN_TOKEN = os.environ.get("PNG_HUB_ADMIN_TOKEN", "")
ALLOWED_ORIGIN = os.environ.get("PNG_HUB_ALLOWED_ORIGIN", "").rstrip("/")
ALLOWED_ROLES = {"student", "employer", "sponsor", "other"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_REQUEST_BYTES = 32_768
MAX_MEDIA_BYTES = 25 * 1024 * 1024
MAX_ADMIN_ENTRIES = 500
CONTENT_KINDS = {"article", "announcement", "profile", "media"}
MEDIA_KINDS = {"image", "video"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def initialize_database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS interests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                role TEXT NOT NULL,
                submitted_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(interests)").fetchall()
        }
        if "selected" not in columns:
            connection.execute(
                "ALTER TABLE interests ADD COLUMN selected INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                media_url TEXT NOT NULL DEFAULT '',
                media_kind TEXT NOT NULL DEFAULT '',
                consent INTEGER NOT NULL DEFAULT 0,
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


class HubRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if ALLOWED_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self):
        if not urlsplit(self.path).path.startswith("/api/"):
            self.send_error(404)
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/content":
            self._list_public_content()
            return
        if path == "/api/admin/interests":
            if not self._is_admin():
                self._send_json(401, {"error": "Admin authorization required."})
                return
            self._admin_dashboard()
            return
        if path == "/api/admin/content":
            if not self._is_admin():
                self._send_json(401, {"error": "Admin authorization required."})
                return
            self._list_admin_content()
            return
        if path.startswith("/api/"):
            self._send_json(404, {"error": "Not found."})
            return
        super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/admin/media":
            if not self._is_admin():
                self._send_json(401, {"error": "Admin authorization required."})
                return
            self._upload_media()
            return
        if path == "/api/admin/content":
            if not self._is_admin():
                self._send_json(401, {"error": "Admin authorization required."})
                return
            self._save_content()
            return
        if path != "/api/interests":
            self._send_json(404, {"error": "Not found."})
            return

        if self.headers.get_content_type() != "application/json":
            self._send_json(415, {"error": "Send the form as JSON."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Invalid request size."})
            return
        if content_length < 1 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "The submitted form is too large or empty."})
            return

        try:
            submission = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "The submitted form is not valid JSON."})
            return

        if not isinstance(submission, dict):
            self._send_json(400, {"error": "The submitted form has an invalid format."})
            return

        name = submission.get("name")
        email = submission.get("email")
        role = submission.get("role")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            self._send_json(400, {"error": "Enter a name between 1 and 120 characters."})
            return
        if not isinstance(email, str) or len(email.strip()) > 254 or not EMAIL_PATTERN.fullmatch(email.strip()):
            self._send_json(400, {"error": "Enter a valid email address."})
            return
        if not isinstance(role, str) or role not in ALLOWED_ROLES:
            self._send_json(400, {"error": "Choose a valid interest type."})
            return

        submitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with sqlite3.connect(DATABASE_PATH) as connection:
                cursor = connection.execute(
                    "INSERT INTO interests (name, email, role, submitted_at) VALUES (?, ?, ?, ?)",
                    (name.strip(), email.strip(), role, submitted_at),
                )
                submission_id = cursor.lastrowid
        except sqlite3.Error:
            logging.exception("Could not save an interest submission.")
            self._send_json(500, {"error": "We could not save your details. Please try again later."})
            return

        self._send_json(201, {"id": submission_id, "message": "Your interest has been received."})

    def do_PATCH(self):
        if not self._is_admin():
            self._send_json(401, {"error": "Admin authorization required."})
            return
        match = re.fullmatch(r"/api/admin/interests/(\d+)", urlsplit(self.path).path)
        if match:
            self._update_interest(int(match.group(1)))
            return
        self._send_json(404, {"error": "Not found."})

    def do_DELETE(self):
        if not self._is_admin():
            self._send_json(401, {"error": "Admin authorization required."})
            return
        match = re.fullmatch(r"/api/admin/content/(\d+)", urlsplit(self.path).path)
        if not match:
            self._send_json(404, {"error": "Not found."})
            return
        try:
            with sqlite3.connect(DATABASE_PATH) as connection:
                cursor = connection.execute(
                    "DELETE FROM content WHERE id = ?", (int(match.group(1)),)
                )
            if cursor.rowcount == 0:
                self._send_json(404, {"error": "Content item not found."})
                return
        except sqlite3.Error:
            logging.exception("Could not delete a content item.")
            self._send_json(500, {"error": "We could not delete this item."})
            return
        self._send_json(200, {"message": "Content item deleted."})

    def _is_admin(self):
        authorization = self.headers.get("Authorization", "")
        scheme, separator, supplied_token = authorization.partition(" ")
        return (
            separator == " "
            and scheme.lower() == "bearer"
            and bool(supplied_token)
            and hmac.compare_digest(supplied_token.encode("utf-8"), ADMIN_TOKEN.encode("utf-8"))
        )

    def _read_json(self):
        if self.headers.get_content_type() != "application/json":
            self._send_json(415, {"error": "Send the request as JSON."})
            return None
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Invalid request size."})
            return None
        if content_length < 1 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "The request is too large or empty."})
            return None
        try:
            value = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "The request is not valid JSON."})
            return None
        if not isinstance(value, dict):
            self._send_json(400, {"error": "The request has an invalid format."})
            return None
        return value

    def _upload_media(self):
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data;"):
            self._send_json(415, {"error": "Upload a media file as multipart form data."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Invalid upload size."})
            return
        if content_length < 1 or content_length > MAX_MEDIA_BYTES:
            self._send_json(413, {"error": "Media files must be 25 MB or smaller."})
            return
        try:
            request_body = self.rfile.read(content_length)
            multipart_body = (
                f"Content-Type: {content_type}\r\n"
                "MIME-Version: 1.0\r\n\r\n"
            ).encode("utf-8") + request_body
            form = BytesParser(policy=policy.default).parsebytes(multipart_body)
            uploaded = next(
                (
                    part
                    for part in form.iter_parts()
                    if part.get_param("name", header="content-disposition") == "media"
                ),
                None,
            )
            filename = uploaded.get_filename() if uploaded else None
            if uploaded is None or not filename:
                self._send_json(400, {"error": "Choose an image or video file."})
                return
            filename = Path(filename).name
            extension = Path(filename).suffix.lower()
            uploaded_type = uploaded.get_content_type()
            media_kind = "image" if uploaded_type.startswith("image/") else "video" if uploaded_type.startswith("video/") else ""
            allowed_extensions = {
                "image": {".jpg", ".jpeg", ".png", ".gif", ".webp"},
                "video": {".mp4", ".webm", ".mov"},
            }
            if not media_kind or extension not in allowed_extensions[media_kind]:
                self._send_json(400, {"error": "Use a JPG, PNG, GIF, WEBP, MP4, WEBM or MOV file."})
                return
            media_bytes = uploaded.get_payload(decode=True) or b""
        except (TypeError, ValueError):
            self._send_json(400, {"error": "The media upload could not be read."})
            return
        if len(media_bytes) > MAX_MEDIA_BYTES:
            self._send_json(413, {"error": "Media files must be 25 MB or smaller."})
            return
        stored_name = f"{uuid.uuid4().hex}{extension}"
        try:
            (MEDIA_DIR / stored_name).write_bytes(media_bytes)
        except OSError:
            logging.exception("Could not save uploaded media.")
            self._send_json(500, {"error": "We could not save the media file."})
            return
        self._send_json(201, {"url": f"/uploads/{stored_name}", "media_kind": media_kind})

    def _admin_dashboard(self):
        try:
            with sqlite3.connect(DATABASE_PATH) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT id, name, email, role, submitted_at, selected
                    FROM interests
                    ORDER BY CASE role
                        WHEN 'student' THEN 0
                        WHEN 'sponsor' THEN 1
                        WHEN 'employer' THEN 2
                        ELSE 3
                    END, name COLLATE NOCASE, id DESC
                    LIMIT ?
                    """,
                    (MAX_ADMIN_ENTRIES,),
                ).fetchall()
                total = connection.execute("SELECT COUNT(*) FROM interests").fetchone()[0]
        except sqlite3.Error:
            logging.exception("Could not retrieve admin dashboard data.")
            self._send_json(500, {"error": "We could not load dashboard data."})
            return
        self._send_json(200, {"total": total, "entries": [dict(row) for row in rows]})

    def _list_admin_content(self):
        try:
            with sqlite3.connect(DATABASE_PATH) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT * FROM content ORDER BY updated_at DESC, id DESC"
                ).fetchall()
        except sqlite3.Error:
            logging.exception("Could not retrieve content.")
            self._send_json(500, {"error": "We could not load content."})
            return
        self._send_json(200, {"items": [dict(row) for row in rows]})

    def _list_public_content(self):
        try:
            with sqlite3.connect(DATABASE_PATH) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT id, kind, title, body, author, role, media_url, media_kind, created_at
                    FROM content
                    WHERE published = 1 AND (kind NOT IN ('profile', 'media') OR consent = 1)
                    ORDER BY updated_at DESC, id DESC
                    """
                ).fetchall()
        except sqlite3.Error:
            logging.exception("Could not retrieve public content.")
            self._send_json(500, {"error": "We could not load the latest updates."})
            return
        self._send_json(200, {"items": [dict(row) for row in rows]})

    def _save_content(self):
        data = self._read_json()
        if data is None:
            return
        kind = data.get("kind")
        title = data.get("title")
        body = data.get("body", "")
        author = data.get("author", "")
        role = data.get("role", "")
        media_url = data.get("media_url", "")
        media_kind = data.get("media_kind", "")
        consent = data.get("consent") is True
        published = data.get("published") is True
        item_id = data.get("id")
        if not isinstance(kind, str) or kind not in CONTENT_KINDS:
            self._send_json(400, {"error": "Choose a valid content type."})
            return
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
            self._send_json(400, {"error": "Title must be between 1 and 160 characters."})
            return
        if not isinstance(body, str) or len(body) > 10_000:
            self._send_json(400, {"error": "Text must be 10,000 characters or fewer."})
            return
        if not isinstance(author, str) or len(author.strip()) > 120:
            self._send_json(400, {"error": "Author name must be 120 characters or fewer."})
            return
        if not isinstance(role, str) or (role and role not in ALLOWED_ROLES):
            self._send_json(400, {"error": "Choose a valid profile category."})
            return
        if not isinstance(media_url, str) or len(media_url) > 2048:
            self._send_json(400, {"error": "Media link must be 2,048 characters or fewer."})
            return
        if media_url:
            if media_url.startswith("/uploads/"):
                if not re.fullmatch(r"/uploads/[a-f0-9]{32}\.(?:jpg|jpeg|png|gif|webp|mp4|webm|mov)", media_url):
                    self._send_json(400, {"error": "Invalid uploaded media link."})
                    return
            else:
                try:
                    parsed_media_url = urlsplit(media_url)
                except ValueError:
                    self._send_json(400, {"error": "Enter a valid HTTPS media link."})
                    return
                if parsed_media_url.scheme != "https" or not parsed_media_url.netloc:
                    self._send_json(400, {"error": "Media links must use HTTPS."})
                    return
        if not isinstance(media_kind, str) or media_kind not in MEDIA_KINDS | {""}:
            self._send_json(400, {"error": "Choose image or video for media."})
            return
        if kind == "media" and (not media_url or not media_kind):
            self._send_json(400, {"error": "Add an HTTPS media link and choose image or video."})
            return
        if kind in {"profile", "media"} and published and not consent:
            self._send_json(400, {"error": "Record consent before publishing profiles or media."})
            return
        if not isinstance(data.get("consent", False), bool) or not isinstance(data.get("published", False), bool):
            self._send_json(400, {"error": "Consent and publishing status must be selected explicitly."})
            return
        if item_id is not None and (
            not isinstance(item_id, int) or isinstance(item_id, bool) or item_id < 1
        ):
            self._send_json(400, {"error": "Invalid content item."})
            return
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with sqlite3.connect(DATABASE_PATH) as connection:
                if item_id:
                    cursor = connection.execute(
                        """
                        UPDATE content SET kind=?, title=?, body=?, author=?, role=?,
                            media_url=?, media_kind=?, consent=?, published=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            kind, title.strip(), body.strip(), author.strip(), role,
                            media_url.strip(), media_kind, int(consent), int(published), now, item_id,
                        ),
                    )
                    if cursor.rowcount == 0:
                        self._send_json(404, {"error": "Content item not found."})
                        return
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO content
                            (kind, title, body, author, role, media_url, media_kind,
                             consent, published, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            kind, title.strip(), body.strip(), author.strip(), role,
                            media_url.strip(), media_kind, int(consent), int(published), now, now,
                        ),
                    )
                    item_id = cursor.lastrowid
        except sqlite3.Error:
            logging.exception("Could not save content.")
            self._send_json(500, {"error": "We could not save this content."})
            return
        self._send_json(200, {"id": item_id, "message": "Content saved."})

    def _update_interest(self, interest_id):
        data = self._read_json()
        if data is None:
            return
        name = data.get("name")
        role = data.get("role")
        selected = data.get("selected")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            self._send_json(400, {"error": "Name must be between 1 and 120 characters."})
            return
        if not isinstance(role, str) or role not in ALLOWED_ROLES:
            self._send_json(400, {"error": "Choose a valid category."})
            return
        if not isinstance(selected, bool):
            self._send_json(400, {"error": "Choose whether the student is selected."})
            return
        if selected and role != "student":
            self._send_json(400, {"error": "Only student submissions can be selected for benefits."})
            return
        try:
            with sqlite3.connect(DATABASE_PATH) as connection:
                cursor = connection.execute(
                    "UPDATE interests SET name=?, role=?, selected=? WHERE id=?",
                    (name.strip(), role, int(selected), interest_id),
                )
        except sqlite3.Error:
            logging.exception("Could not update an interest submission.")
            self._send_json(500, {"error": "We could not update this submission."})
            return
        if cursor.rowcount == 0:
            self._send_json(404, {"error": "Submission not found."})
            return
        self._send_json(200, {"message": "Submission updated."})

    def _send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        logging.info("%s - %s", self.address_string(), format_string % args)


def main():
    if len(ADMIN_TOKEN) < 32:
        raise SystemExit(
            "Set PNG_HUB_ADMIN_TOKEN to a private value of at least 32 characters before starting the server."
        )

    initialize_database()
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), HubRequestHandler)
    logging.info("PNG Student Care Hub is available at http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down the hub server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
