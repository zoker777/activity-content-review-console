#!/usr/bin/env python3
import argparse
import json
import mimetypes
import os
import sqlite3
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_ROOT = BASE_DIR / "data" / "raw"
DEFAULT_DB_PATH = BASE_DIR / "data" / "db" / "app.sqlite3"
DEFAULT_MANIFEST_PATH = BASE_DIR / "data" / "manifest.json"
STATIC_DIR = BASE_DIR / "static"

VALID_REVIEW_STATUS = {"unmarked", "approved", "rejected"}
VALID_SUBMIT_STATUS = {"pending", "success", "failed"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v", ".avi"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_inside(root, target):
    root = root.resolve()
    target = target.resolve()
    if root == target or root in target.parents:
        return target
    raise ValueError("path escapes raw root")


def parse_json_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid json: {exc}") from exc


def pick_first(data, keys, default=""):
    for key in keys:
        value = data
        ok = True
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                ok = False
                break
        if ok and value not in (None, ""):
            return value
    return default


def normalize_note(raw, platform, category, activity, source_file):
    note_id = str(
        pick_first(
            raw,
            [
                "note_id",
                "noteId",
                "id",
                "aweme_id",
                "awemeId",
                "item_id",
                "itemId",
                "video_id",
                "videoId",
            ],
        )
    ).strip()
    if not note_id:
        return None

    return {
        "platform": platform,
        "category_name": category,
        "activity_name": activity,
        "note_id": note_id,
        "title": str(pick_first(raw, ["title", "display_title", "desc", "description"], "")),
        "content": str(pick_first(raw, ["content", "desc", "description", "text"], "")),
        "author": pick_first(raw, ["author", "nickname", "user.nickname", "user.name"], ""),
        "source_url": pick_first(raw, ["source_url", "url", "share_url", "shareUrl"], ""),
        "publish_time": pick_first(raw, ["publish_time", "publishTime", "time", "create_time", "createTime"], ""),
        "crawl_time": pick_first(raw, ["crawl_time", "crawlTime", "collected_at", "collectedAt"], ""),
        "source_file": source_file,
        "raw": raw,
    }


class App:
    def __init__(self, raw_root, db_path, manifest_path):
        self.raw_root = Path(raw_root).resolve()
        self.db_path = Path(db_path).resolve()
        self.manifest_path = Path(manifest_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists collected_notes (
                  id integer primary key autoincrement,
                  platform text not null,
                  note_id text not null,
                  category_name text not null,
                  activity_name text not null,
                  first_seen_at text,
                  last_seen_at text,
                  source_file text,
                  created_at text not null,
                  updated_at text not null,
                  unique(platform, category_name, activity_name, note_id)
                );

                create index if not exists idx_collected_notes_lookup
                  on collected_notes(platform, category_name, activity_name, note_id);

                create table if not exists note_review (
                  id integer primary key autoincrement,
                  platform text not null,
                  note_id text not null,
                  category_name text not null,
                  activity_name text not null,
                  status text not null default 'unmarked',
                  reviewer text,
                  created_at text not null,
                  updated_at text not null,
                  unique(platform, category_name, activity_name, note_id)
                );

                create index if not exists idx_note_review_lookup
                  on note_review(platform, category_name, activity_name, note_id);

                create table if not exists note_submit_record (
                  id integer primary key autoincrement,
                  platform text not null,
                  note_id text not null,
                  category_name text not null,
                  activity_name text not null,
                  submit_status text not null,
                  target_record_id text,
                  error_message text,
                  submitted_at text,
                  unique(platform, category_name, activity_name, note_id)
                );

                create index if not exists idx_note_submit_record_lookup
                  on note_submit_record(platform, category_name, activity_name, note_id);
                """
            )

    def load_manifest(self):
        if not self.manifest_path.exists():
            return {"platforms": [], "categories": []}
        with self.manifest_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return {
            "platforms": data.get("platforms", []),
            "categories": data.get("categories", []),
        }

    def manifest_category_names(self):
        return [item.get("name", "") for item in self.load_manifest()["categories"] if item.get("name")]

    def manifest_activities(self, category):
        for item in self.load_manifest()["categories"]:
            if item.get("name") == category:
                return [
                    {
                        "name": activity.get("name", ""),
                        "keywords": activity.get("keywords", []),
                    }
                    for activity in item.get("activities", [])
                    if activity.get("name")
                ]
        return []

    def list_platforms(self):
        platforms = set(self.load_manifest()["platforms"])
        if not self.raw_root.exists():
            return sorted(platforms)
        platforms.update(p.name for p in self.raw_root.iterdir() if p.is_dir() and not p.name.startswith("."))
        return sorted(platforms)

    def list_categories(self, platform):
        categories = self.manifest_category_names()
        seen = set(categories)
        platform_dir = ensure_inside(self.raw_root, self.raw_root / platform)
        if not platform_dir.exists():
            return categories
        extras = sorted(
            p.name
            for p in platform_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name not in seen
        )
        return categories + extras

    def list_activities(self, platform, category):
        activities = self.manifest_activities(category)
        seen = {item["name"] for item in activities}
        category_dir = ensure_inside(self.raw_root, self.raw_root / platform / category)
        if category_dir.exists():
            extras = [
                {"name": item.name, "keywords": []}
                for item in sorted(category_dir.iterdir(), key=lambda path: path.name)
                if item.is_dir() and not item.name.startswith(".") and item.name not in seen
            ]
            activities = activities + extras
        return activities

    def activity_keywords(self, category, activity):
        for item in self.manifest_activities(category):
            if item["name"] == activity:
                return item.get("keywords", [])
        return []

    def activity_dir(self, platform, category, activity):
        return ensure_inside(self.raw_root, self.raw_root / platform / category / activity)

    def read_activity_notes(self, platform, category, activity):
        base = self.activity_dir(platform, category, activity)
        jsonl_dir = ensure_inside(self.raw_root, base / "jsonl")
        if not jsonl_dir.exists():
            return []

        notes = {}
        for file_path in sorted(jsonl_dir.glob("*.jsonl")):
            source_file = str(file_path.relative_to(self.raw_root))
            with file_path.open("r", encoding="utf-8") as file:
                for line_no, line in enumerate(file, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    note = normalize_note(raw, platform, category, activity, source_file)
                    if not note:
                        continue
                    note["line_no"] = line_no
                    notes[note["note_id"]] = note
        return list(notes.values())

    def media_files(self, platform, category, activity, note_id, kind):
        base = self.activity_dir(platform, category, activity)
        media_dir = ensure_inside(self.raw_root, base / kind / note_id)
        if not media_dir.exists() or not media_dir.is_dir():
            return []
        allowed = IMAGE_EXTENSIONS if kind == "images" else VIDEO_EXTENSIONS
        files = []
        for item in sorted(media_dir.iterdir()):
            if item.is_file() and item.suffix.lower() in allowed:
                files.append(item.name)
        return files

    def review_map(self, platform, category, activity):
        with self.connect() as conn:
            rows = conn.execute(
                """
                select note_id, status, reviewer, updated_at
                from note_review
                where platform = ? and category_name = ? and activity_name = ?
                """,
                (platform, category, activity),
            ).fetchall()
        return {row["note_id"]: dict(row) for row in rows}

    def submit_map(self, platform, category, activity):
        with self.connect() as conn:
            rows = conn.execute(
                """
                select note_id, submit_status, target_record_id, error_message, submitted_at
                from note_submit_record
                where platform = ? and category_name = ? and activity_name = ?
                """,
                (platform, category, activity),
            ).fetchall()
        return {row["note_id"]: dict(row) for row in rows}

    def list_notes(self, platform, category, activity, status="visible"):
        notes = self.read_activity_notes(platform, category, activity)
        reviews = self.review_map(platform, category, activity)
        submits = self.submit_map(platform, category, activity)
        result = []

        for note in notes:
            review = reviews.get(note["note_id"], {"status": "unmarked", "reviewer": "", "updated_at": ""})
            submit = submits.get(note["note_id"])
            review_status = review["status"]
            if status == "visible" and review_status == "rejected":
                continue
            if status in VALID_REVIEW_STATUS and review_status != status:
                continue
            images = self.media_files(platform, category, activity, note["note_id"], "images")
            videos = self.media_files(platform, category, activity, note["note_id"], "videos")
            result.append(
                {
                    **{key: note[key] for key in [
                        "platform",
                        "category_name",
                        "activity_name",
                        "note_id",
                        "title",
                        "content",
                        "author",
                        "source_url",
                        "publish_time",
                        "crawl_time",
                        "source_file",
                    ]},
                    "keywords": self.activity_keywords(category, activity),
                    "review": review,
                    "submit": submit,
                    "image_count": len(images),
                    "video_count": len(videos),
                }
            )
        return result

    def get_note(self, platform, category, activity, note_id):
        notes = self.read_activity_notes(platform, category, activity)
        note = next((item for item in notes if item["note_id"] == note_id), None)
        if not note:
            return None
        reviews = self.review_map(platform, category, activity)
        submits = self.submit_map(platform, category, activity)
        images = self.media_files(platform, category, activity, note_id, "images")
        videos = self.media_files(platform, category, activity, note_id, "videos")
        return {
            **note,
            "keywords": self.activity_keywords(category, activity),
            "review": reviews.get(note_id, {"status": "unmarked", "reviewer": "", "updated_at": ""}),
            "submit": submits.get(note_id),
            "images": [
                {
                    "name": name,
                    "url": "/api/media/images?"
                    + urlencode(
                        {
                            "platform": platform,
                            "category": category,
                            "activity": activity,
                            "noteId": note_id,
                            "file": name,
                        }
                    ),
                }
                for name in images
            ],
            "videos": [
                {
                    "name": name,
                    "url": "/api/media/videos?"
                    + urlencode(
                        {
                            "platform": platform,
                            "category": category,
                            "activity": activity,
                            "noteId": note_id,
                            "file": name,
                        }
                    ),
                }
                for name in videos
            ],
        }

    def upsert_review(self, platform, category, activity, note_id, status, reviewer=""):
        if status not in VALID_REVIEW_STATUS:
            raise ValueError("invalid review status")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                insert into note_review (
                  platform, note_id, category_name, activity_name, status, reviewer, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(platform, category_name, activity_name, note_id)
                do update set status = excluded.status, reviewer = excluded.reviewer, updated_at = excluded.updated_at
                """,
                (platform, note_id, category, activity, status, reviewer, now, now),
            )
        return {"status": status, "reviewer": reviewer, "updated_at": now}

    def upsert_submit(self, platform, category, activity, note_id, submit_status, target_record_id="", error_message=""):
        if submit_status not in VALID_SUBMIT_STATUS:
            raise ValueError("invalid submit status")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                insert into note_submit_record (
                  platform, note_id, category_name, activity_name, submit_status,
                  target_record_id, error_message, submitted_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(platform, category_name, activity_name, note_id)
                do update set
                  submit_status = excluded.submit_status,
                  target_record_id = excluded.target_record_id,
                  error_message = excluded.error_message,
                  submitted_at = excluded.submitted_at
                """,
                (platform, note_id, category, activity, submit_status, target_record_id, error_message, now),
            )
        return {
            "submit_status": submit_status,
            "target_record_id": target_record_id,
            "error_message": error_message,
            "submitted_at": now,
        }

    def is_collected(self, platform, category, activity, note_id):
        with self.connect() as conn:
            row = conn.execute(
                """
                select id, platform, note_id, category_name, activity_name, first_seen_at, last_seen_at, source_file
                from collected_notes
                where platform = ? and category_name = ? and activity_name = ? and note_id = ?
                """,
                (platform, category, activity, note_id),
            ).fetchone()
        return dict(row) if row else None

    def mark_collected(self, platform, category, activity, note_id, source_file="", first_seen_at="", last_seen_at=""):
        now = utc_now()
        first_seen_at = first_seen_at or now
        last_seen_at = last_seen_at or now
        with self.connect() as conn:
            conn.execute(
                """
                insert into collected_notes (
                  platform, note_id, category_name, activity_name,
                  first_seen_at, last_seen_at, source_file, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(platform, category_name, activity_name, note_id)
                do update set
                  last_seen_at = excluded.last_seen_at,
                  source_file = coalesce(nullif(excluded.source_file, ''), collected_notes.source_file),
                  updated_at = excluded.updated_at
                """,
                (platform, note_id, category, activity, first_seen_at, last_seen_at, source_file, now, now),
            )
        return self.is_collected(platform, category, activity, note_id)

    def sync_collected_from_raw(self):
        count = 0
        for platform in self.list_platforms():
            for category in self.list_categories(platform):
                for activity in self.list_activities(platform, category):
                    for note in self.read_activity_notes(platform, category, activity):
                        self.mark_collected(
                            platform,
                            category,
                            activity,
                            note["note_id"],
                            note.get("source_file", ""),
                            note.get("crawl_time", "") or utc_now(),
                            note.get("crawl_time", "") or utc_now(),
                        )
                        count += 1
        return {"synced": count}

    def media_path(self, platform, category, activity, note_id, kind, filename):
        if kind not in {"images", "videos"}:
            raise ValueError("invalid media kind")
        allowed = IMAGE_EXTENSIONS if kind == "images" else VIDEO_EXTENSIONS
        if Path(filename).name != filename or Path(filename).suffix.lower() not in allowed:
            raise ValueError("invalid media file")
        base = self.activity_dir(platform, category, activity)
        target = ensure_inside(self.raw_root, base / kind / note_id / filename)
        if not target.exists() or not target.is_file():
            return None
        return target


class Handler(BaseHTTPRequestHandler):
    app = None

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=HTTPStatus.BAD_REQUEST):
        self.send_json({"error": message}, status)

    def do_GET(self):
        try:
            self.handle_get()
        except ValueError as exc:
            self.send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
        except FileNotFoundError:
            self.send_error_json("not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        try:
            self.handle_post()
        except ValueError as exc:
            self.send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

        if path == "/":
            return self.serve_static("index.html")
        if path.startswith("/static/"):
            return self.serve_static(path.removeprefix("/static/"))

        if path == "/api/health":
            return self.send_json(
                {
                    "ok": True,
                    "raw_root": str(self.app.raw_root),
                    "db_path": str(self.app.db_path),
                    "manifest_path": str(self.app.manifest_path),
                }
            )
        if path == "/api/manifest":
            return self.send_json(self.app.load_manifest())
        if path == "/api/platforms":
            return self.send_json({"platforms": self.app.list_platforms()})
        if path == "/api/categories":
            return self.send_json({"categories": self.app.list_categories(query["platform"])})
        if path == "/api/activities":
            return self.send_json({"activities": self.app.list_activities(query["platform"], query["category"])})
        if path == "/api/notes":
            notes = self.app.list_notes(
                query["platform"],
                query["category"],
                query["activity"],
                query.get("status", "visible"),
            )
            return self.send_json({"notes": notes})
        if path == "/api/note":
            note = self.app.get_note(query["platform"], query["category"], query["activity"], query["noteId"])
            if not note:
                return self.send_error_json("note not found", HTTPStatus.NOT_FOUND)
            return self.send_json({"note": note})
        if path == "/api/collected/exists":
            item = self.app.is_collected(query["platform"], query["category"], query["activity"], query["noteId"])
            return self.send_json({"exists": bool(item), "record": item})
        if path in {"/api/media/images", "/api/media/videos"}:
            kind = path.rsplit("/", 1)[-1]
            media = self.app.media_path(
                query["platform"],
                query["category"],
                query["activity"],
                query["noteId"],
                kind,
                query["file"],
            )
            if not media:
                return self.send_error_json("media not found", HTTPStatus.NOT_FOUND)
            return self.serve_file(media)

        return self.send_error_json("not found", HTTPStatus.NOT_FOUND)

    def handle_post(self):
        parsed = urlparse(self.path)
        body = parse_json_body(self)

        if parsed.path == "/api/notes/review":
            review = self.app.upsert_review(
                body["platform"],
                body["category"],
                body["activity"],
                body["noteId"],
                body["status"],
                body.get("reviewer", ""),
            )
            return self.send_json({"review": review})
        if parsed.path == "/api/notes/submit":
            submit = self.app.upsert_submit(
                body["platform"],
                body["category"],
                body["activity"],
                body["noteId"],
                body.get("submitStatus", "success"),
                body.get("targetRecordId", ""),
                body.get("errorMessage", ""),
            )
            return self.send_json({"submit": submit})
        if parsed.path == "/api/collected/mark":
            record = self.app.mark_collected(
                body["platform"],
                body["category"],
                body["activity"],
                body["noteId"],
                body.get("sourceFile", ""),
                body.get("firstSeenAt", ""),
                body.get("lastSeenAt", ""),
            )
            return self.send_json({"record": record})
        if parsed.path == "/api/sync-collected":
            return self.send_json(self.app.sync_collected_from_raw())

        return self.send_error_json("not found", HTTPStatus.NOT_FOUND)

    def serve_static(self, relative):
        relative = unquote(relative)
        if relative == "":
            relative = "index.html"
        target = ensure_inside(STATIC_DIR, STATIC_DIR / relative)
        if not target.exists() or not target.is_file():
            return self.send_error_json("not found", HTTPStatus.NOT_FOUND)
        return self.serve_file(target)

    def serve_file(self, path):
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        file_size = path.stat().st_size
        range_header = self.headers.get("Range")

        if range_header and range_header.startswith("bytes="):
            start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
            start = int(start_text or "0")
            end = int(end_text) if end_text else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Type", mime_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            with path.open("rb") as file:
                file.seek(start)
                self.wfile.write(file.read(length))
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with path.open("rb") as file:
            while True:
                chunk = file.read(1024 * 256)
                if not chunk:
                    break
                self.wfile.write(chunk)


def main():
    parser = argparse.ArgumentParser(description="活动内容审核控制台")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--raw-root", default=os.environ.get("RAW_DATA_ROOT", str(DEFAULT_RAW_ROOT)))
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", str(DEFAULT_DB_PATH)))
    parser.add_argument("--manifest-path", default=os.environ.get("MANIFEST_PATH", str(DEFAULT_MANIFEST_PATH)))
    args = parser.parse_args()

    Handler.app = App(args.raw_root, args.db_path, args.manifest_path)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"服务已启动：http://{args.host}:{args.port}")
    print(f"原始数据目录：{Handler.app.raw_root}")
    print(f"SQLite 数据库：{Handler.app.db_path}")
    print(f"活动清单：{Handler.app.manifest_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
