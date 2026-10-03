#!/usr/bin/env python3
"""Минимальная панель управления ботом.

Что умеет:
  - вход по паролю панели (PANEL_PASSWORD из .env);
  - хранит доступ к ВК (логин, пароль, токен сообщества) и API-ключ (DeepSeek) в .env;
  - одной кнопкой «Сохранить и пополнить» сохраняет настройки и добавляет
    загруженный файл (.md/.txt) в базу знаний knowledge.md.

Запуск:
  python panel.py
Затем откройте http://127.0.0.1:8080

Панель слушает только localhost. Не выставляйте её в интернет без пароля и HTTPS.
"""

import html
import hmac
import os
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
KB_PATH = os.path.join(BASE_DIR, "knowledge.md")

MAX_UPLOAD = 2 * 1024 * 1024  # 2 МБ
COOKIE_NAME = "panel_session"
ALLOWED_EXT = (".md", ".txt", ".markdown")
SESSIONS = set()


def read_env():
    data = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
    return data


def write_env(updates):
    """Обновляет только непустые ключи, сохраняя остальные значения."""
    data = read_env()
    for key, value in updates.items():
        if value:
            data[key] = value
    with open(ENV_PATH, "w", encoding="utf-8") as fh:
        for key, value in data.items():
            fh.write(f"{key}={value}\n")


# Пароль панели: сначала из окружения, иначе из .env
os.environ.setdefault("PANEL_PASSWORD", read_env().get("PANEL_PASSWORD", ""))
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "")
HOST = os.environ.get("PANEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("PANEL_PORT", "8080"))


def parse_multipart(body, content_type):
    """Минимальный разбор multipart/form-data (модуль cgi устарел)."""
    marker = "boundary="
    pos = content_type.find(marker)
    if pos == -1:
        return {}
    boundary = content_type[pos + len(marker):].strip().strip('"').encode()
    fields = {}
    for chunk in body.split(b"--" + boundary):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--" or b"\r\n\r\n" not in chunk:
            continue
        raw_headers, content = chunk.split(b"\r\n\r\n", 1)
        content = content.rstrip(b"\r\n")
        name = filename = None
        for line in raw_headers.decode("utf-8", "replace").split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                for token in line.split(";"):
                    token = token.strip()
                    if token.startswith("name="):
                        name = token[5:].strip().strip('"')
                    elif token.startswith("filename="):
                        filename = token[9:].strip().strip('"')
        if name:
            fields[name] = (filename, content)
    return fields


STYLE = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0f1115; color: #e8eaed; display: grid; place-items: center;
         min-height: 100vh; padding: 24px; }
  .card { width: 100%; max-width: 380px; background: #171a21; border: 1px solid #262b36;
          border-radius: 16px; padding: 22px; }
  h1 { margin: 0 0 4px; font-size: 18px; }
  .hint { margin: 0 0 18px; min-height: 20px; font-size: 13px; color: #8b93a7; }
  label { display: block; margin: 0 0 12px; font-size: 13px; color: #b6bdcc; }
  input { width: 100%; margin-top: 6px; padding: 10px 12px; font: inherit;
          color: #e8eaed; background: #0f1115; border: 1px solid #2c3341; border-radius: 10px; }
  input:focus { outline: none; border-color: #5b8def; }
  input[type=file] { padding: 8px; }
  .row { display: flex; gap: 12px; margin-top: 4px; align-items: center; }
  button { flex: 1; padding: 11px 12px; font: inherit; font-weight: 600; cursor: pointer;
           background: #5b8def; border: 1px solid #5b8def; color: #fff; border-radius: 10px; }
  .logout { color: #8b93a7; font-size: 13px; text-decoration: none; white-space: nowrap; }
"""

LOGIN_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вход в панель</title>
<style>{style}</style>
</head>
<body>
  <main class="card">
    <h1>Панель бота</h1>
    <p class="hint">{status}</p>
    <form method="post" action="/login">
      <label>Пароль панели
        <input name="password" type="password" autocomplete="current-password" autofocus>
      </label>
      <div class="row">
        <button>Войти</button>
      </div>
    </form>
  </main>
</body>
</html>
"""

MAIN_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Панель бота</title>
<style>{style}</style>
</head>
<body>
  <main class="card">
    <h1>Панель бота</h1>
    <p class="hint">{status}</p>
    <form method="post" action="/submit" enctype="multipart/form-data">
      <label>Логин (ВК)
        <input name="login" type="text" autocomplete="off" placeholder="оставьте пустым, чтобы не менять">
      </label>
      <label>Пароль (ВК)
        <input name="password" type="password" autocomplete="off" placeholder="оставьте пустым, чтобы не менять">
      </label>
      <label>Токен сообщества
        <input name="token" type="text" autocomplete="off" placeholder="оставьте пустым, чтобы не менять">
      </label>
      <label>API-ключ (DeepSeek)
        <input name="api" type="text" autocomplete="off" placeholder="оставьте пустым, чтобы не менять">
      </label>
      <label>Файл базы знаний (.md или .txt)
        <input name="knowledge" type="file" accept=".md,.txt,.markdown">
      </label>
      <div class="row">
        <button>Сохранить и пополнить</button>
        <a class="logout" href="/logout">Выйти</a>
      </div>
    </form>
  </main>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _redirect(self, location, cookie=None):
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _page(self, template, status=""):
        body = template.format(style=STYLE, status=html.escape(status)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if not PANEL_PASSWORD:
            return True
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                if key == COOKIE_NAME and value in SESSIONS:
                    return True
        return False

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        status = urllib.parse.parse_qs(parsed.query).get("msg", [""])[0]

        if parsed.path == "/login":
            self._page(LOGIN_PAGE, status)
        elif parsed.path == "/logout":
            self._redirect("/login?msg=" + urllib.parse.quote("Вы вышли из панели"))
        elif parsed.path in ("/", "/index.html"):
            if not self._authed():
                self._redirect("/login")
                return
            if not PANEL_PASSWORD:
                status = ("Пароль панели не задан — добавьте PANEL_PASSWORD в .env. " + status).strip()
            self._page(MAIN_PAGE, status)
        else:
            self.send_error(404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        ctype = self.headers.get("Content-Type", "")

        if path == "/login":
            given = urllib.parse.parse_qs(raw.decode("utf-8", "replace")).get("password", [""])[0]
            if not PANEL_PASSWORD:
                self._redirect("/")
            elif hmac.compare_digest(given, PANEL_PASSWORD):
                token = secrets.token_urlsafe(24)
                SESSIONS.add(token)
                self._redirect("/", f"{COOKIE_NAME}={token}; HttpOnly; Path=/; SameSite=Strict")
            else:
                self._redirect("/login?msg=" + urllib.parse.quote("Неверный пароль"))
            return

        if path == "/submit":
            if not self._authed():
                self._redirect("/login")
                return
            if ctype.startswith("multipart/form-data"):
                fields = parse_multipart(raw, ctype)
            else:
                fields = {k: (None, v[0].encode()) for k, v in
                          urllib.parse.parse_qs(raw.decode("utf-8", "replace")).items()}

            def value(name):
                item = fields.get(name)
                return item[1].decode("utf-8", "replace").strip() if item else ""

            write_env({
                "VK_LOGIN": value("login"),
                "VK_PASSWORD": value("password"),
                "VK_GROUP_TOKEN": value("token"),
                "LLM_API_KEY": value("api"),
            })
            message = "Настройки сохранены"

            item = fields.get("knowledge")
            if item and item[0]:
                name, data = item[0], item[1]
                if not name.lower().endswith(ALLOWED_EXT):
                    message += ". Файл базы знаний не добавлен: нужен .md или .txt"
                elif len(data) > MAX_UPLOAD:
                    message += ". Файл базы знаний не добавлен: слишком большой"
                else:
                    text = data.decode("utf-8", "replace").strip()
                    if text:
                        with open(KB_PATH, "a", encoding="utf-8") as fh:
                            fh.write("\n\n" + text + "\n")
                        message += ". База знаний пополнена из файла"
                    else:
                        message += ". Файл базы знаний пуст"

            self._redirect("/?msg=" + urllib.parse.quote(message))
            return

        self.send_error(404)

    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Панель бота: http://{HOST}:{PORT}  (Ctrl+C — остановить)")
    if not PANEL_PASSWORD:
        print("Внимание: PANEL_PASSWORD не задан — панель открыта без пароля.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
