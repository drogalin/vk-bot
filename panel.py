#!/usr/bin/env python3
"""Минимальная панель управления ботом.

Что умеет:
  - хранит доступ к ВК (логин, пароль, токен сообщества) и API-ключ (DeepSeek) в .env;
  - кнопкой «Пополнить базу знаний» добавляет текст в knowledge.md.

Запуск:
  python panel.py
Затем откройте http://127.0.0.1:8080

Панель слушает только localhost. Не выставляйте её в интернет без пароля и HTTPS.
"""

import html
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
KB_PATH = os.path.join(BASE_DIR, "knowledge.md")

HOST = os.environ.get("PANEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("PANEL_PORT", "8080"))


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


PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Панель бота</title>
<style>
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
  input, textarea { width: 100%; margin-top: 6px; padding: 10px 12px; font: inherit;
         color: #e8eaed; background: #0f1115; border: 1px solid #2c3341; border-radius: 10px; }
  input:focus, textarea:focus { outline: none; border-color: #5b8def; }
  textarea { resize: vertical; }
  .row { display: flex; gap: 10px; margin-top: 4px; }
  button { flex: 1; padding: 11px 12px; font: inherit; font-weight: 600;
           border: 1px solid #2c3341; border-radius: 10px; cursor: pointer; }
  .primary { background: #5b8def; border-color: #5b8def; color: #fff; }
  .ghost { background: transparent; color: #c7cddb; }
</style>
</head>
<body>
  <main class="card">
    <h1>Панель бота</h1>
    <p class="hint">{status}</p>
    <form method="post" action="/submit">
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
      <label>Новое знание
        <textarea name="knowledge" rows="3" placeholder="Текст, который добавится в базу знаний"></textarea>
      </label>
      <div class="row">
        <button class="ghost" name="action" value="save">Сохранить</button>
        <button class="primary" name="action" value="knowledge">Пополнить базу знаний</button>
      </div>
    </form>
  </main>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        query = urllib.parse.parse_qs(parsed.query)
        status = html.escape(query.get("msg", [""])[0])
        body = PAGE.replace("{status}", status).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/submit":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        fields = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        action = fields.get("action", "")

        if action == "save":
            write_env({
                "VK_LOGIN": fields.get("login", ""),
                "VK_PASSWORD": fields.get("password", ""),
                "VK_GROUP_TOKEN": fields.get("token", ""),
                "LLM_API_KEY": fields.get("api", ""),
            })
            message = "Настройки сохранены"
        elif action == "knowledge":
            text = (fields.get("knowledge") or "").strip()
            if text:
                with open(KB_PATH, "a", encoding="utf-8") as fh:
                    fh.write("\n\n" + text + "\n")
                message = "База знаний пополнена"
            else:
                message = "Пустое знание — нечего добавлять"
        else:
            message = "Неизвестное действие"

        self._redirect("/?msg=" + urllib.parse.quote(message))

    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Панель бота: http://{HOST}:{PORT}  (Ctrl+C — остановить)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
