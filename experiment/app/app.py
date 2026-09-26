"""The service every stack deploys: a small item store over Postgres, with
Redis as a read cache when REDIS_URL is set. Each response names the replica
that served it.

Environment: DATABASE_URL (required), REDIS_URL (optional), PORT (8000).
It exits 1 when a store it was given does not answer within a few seconds,
so a stack that starts it before its database is ready never comes up."""
import json
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
import redis

REPLICA = socket.gethostname()
CONNECT_S = 5


def connect_db(url):
    deadline = time.time() + CONNECT_S
    while True:
        try:
            conn = psycopg.connect(url, autocommit=True, connect_timeout=2)
            # replicas start together; CREATE TABLE IF NOT EXISTS races without the lock
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(1)")
                conn.execute("CREATE TABLE IF NOT EXISTS items "
                             "(id SERIAL PRIMARY KEY, name TEXT NOT NULL)")
            return conn
        except psycopg.OperationalError as e:
            if time.time() > deadline:
                sys.exit(f"database unreachable: {e}")
            time.sleep(0.5)


def connect_cache(url):
    if not url:
        return None
    r = redis.Redis.from_url(url, socket_timeout=2)
    deadline = time.time() + CONNECT_S
    while True:
        try:
            r.ping()
            return r
        except redis.RedisError as e:
            if time.time() > deadline:
                sys.exit(f"redis unreachable: {e}")
            time.sleep(0.5)


DB = None
CACHE = None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps({**body, "replica": REPLICA}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            DB.execute("SELECT 1")
            return self._send(200, {"ok": True, "cache": CACHE is not None})
        if self.path.startswith("/items/"):
            key = self.path.rsplit("/", 1)[1]
            if CACHE is not None:
                hit = CACHE.get(f"item:{key}")
                if hit is not None:
                    return self._send(200, {"id": int(key), "name": hit.decode(), "cached": True})
            row = DB.execute("SELECT name FROM items WHERE id = %s", (int(key),)).fetchone()
            if row is None:
                return self._send(404, {"error": "no such item"})
            if CACHE is not None:
                CACHE.set(f"item:{key}", row[0])
            return self._send(200, {"id": int(key), "name": row[0], "cached": False})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/items":
            return self._send(404, {"error": "not found"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        row = DB.execute("INSERT INTO items (name) VALUES (%s) RETURNING id", (body["name"],)).fetchone()
        return self._send(201, {"id": row[0], "name": body["name"]})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    DB = connect_db(os.environ["DATABASE_URL"])
    CACHE = connect_cache(os.environ.get("REDIS_URL", ""))
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()
