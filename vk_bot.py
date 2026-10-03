import os
import time
import logging
from collections import defaultdict, deque

import requests
from dotenv import load_dotenv

from knowledge_base import KnowledgeBase

load_dotenv()

VK_API_VERSION = "5.199"
VK_API_URL = "https://api.vk.com/method/"

GROUP_TOKEN = os.environ["VK_GROUP_TOKEN"]
GROUP_ID = int(os.environ["VK_GROUP_ID"])

# DeepSeek (OpenAI-совместимый API)
LLM_API_KEY = os.environ["LLM_API_KEY"]
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# База знаний
KB_PATH = os.environ.get("KB_PATH", "knowledge.md")
KB_TOP_K = int(os.environ.get("KB_TOP_K", "3"))

# Максимум пар «вопрос-ответ» в памяти на одного собеседника
HISTORY_SIZE = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vk-bot")

session = requests.Session()

# Здесь задаётся характер бота — правьте под свой бизнес
SYSTEM_PROMPT = (
    "Ты — вежливый ассистент студии, которая делает дорогие презентации "
    "(инвестдеки, тендерные и коммерческие материалы) для компаний в Москве. "
    "Отвечай кратко и по делу, дружелюбно, на русском. "
    "Если человек интересуется услугами — уточни задачу, сроки и бюджет, "
    "и предложи созвон или оставить контакт. Не выдумывай цены и факты, "
    "которых не знаешь; лучше переспроси."
)

# История диалогов по каждому собеседнику
history = defaultdict(lambda: deque(maxlen=HISTORY_SIZE * 2))

# База знаний (если файла нет — бот работает без неё)
kb = KnowledgeBase(KB_PATH) if os.path.exists(KB_PATH) else None

# Защита от повторов: id уже обработанных сообщений
seen_messages = deque(maxlen=2000)
seen_set = set()


def vk(method, **params):
    params = {**params, "access_token": GROUP_TOKEN, "v": VK_API_VERSION}
    resp = session.post(VK_API_URL + method, data=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"VK error in {method}: {data['error']}")
    return data["response"]


def build_system_prompt(text):
    prompt = SYSTEM_PROMPT
    if kb is not None:
        fragments = kb.search(text, k=KB_TOP_K)
        if fragments:
            context = "\n---\n".join(fragments)
            prompt += (
                "\n\nНиже — выдержки из базы знаний. Используй их, если релевантно, "
                "и не выдумывай того, чего там нет.\n\n" + context
            )
    return prompt


def llm_reply(peer_id, text):
    messages = [{"role": "system", "content": build_system_prompt(text)}]
    messages += list(history[peer_id])
    messages.append({"role": "user", "content": text})

    resp = session.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        json={
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 600,
        },
        timeout=60,
    )
    resp.raise_for_status()
    answer = resp.json()["choices"][0]["message"]["content"].strip()

    history[peer_id].append({"role": "user", "content": text})
    history[peer_id].append({"role": "assistant", "content": answer})
    return answer


def send_message(peer_id, text):
    vk(
        "messages.send",
        peer_id=peer_id,
        message=text,
        random_id=int(time.time() * 1000),
    )


def set_typing(peer_id):
    try:
        vk("messages.setActivity", peer_id=peer_id, type="typing")
    except Exception:
        pass  # индикатор набора — необязательная косметика


def get_long_poll():
    lp = vk("groups.getLongPollServer", group_id=GROUP_ID)
    return lp["server"], lp["key"], lp["ts"]


def already_seen(message_id):
    if message_id in seen_set:
        return True
    if len(seen_messages) == seen_messages.maxlen:
        seen_set.discard(seen_messages[0])
    seen_messages.append(message_id)
    seen_set.add(message_id)
    return False


def handle_update(update):
    if update.get("type") != "message_new":
        return

    msg = update["object"]["message"]
    peer_id = msg["peer_id"]
    from_id = msg["from_id"]
    text = (msg.get("text") or "").strip()

    # Игнорируем сообщения без текста и сообщения от самого сообщества
    if not text or from_id < 0:
        return

    if already_seen(msg["id"]):
        return

    log.info("Входящее от %s: %s", from_id, text)
    set_typing(peer_id)

    try:
        answer = llm_reply(peer_id, text)
    except Exception as exc:
        log.error("Ошибка ИИ: %s", exc)
        answer = "Извините, я задумался. Напишите, пожалуйста, ещё раз чуть позже."

    try:
        send_message(peer_id, answer)
        log.info("Ответ отправлен %s", from_id)
    except Exception as exc:
        log.error("Не удалось отправить: %s", exc)


def run():
    server, key, ts = get_long_poll()
    log.info("Бот запущен. Слушаю Long Poll…")

    while True:
        try:
            resp = session.get(
                server,
                params={"act": "a_check", "key": key, "ts": ts, "wait": 25},
                timeout=40,
            )
            resp.raise_for_status()
            data = resp.json()

            if "failed" in data:
                log.warning("Long Poll: failed=%s, переподключаюсь", data["failed"])
                server, key, ts = get_long_poll()
                continue

            ts = data["ts"]
            for update in data.get("updates", []):
                handle_update(update)

        except requests.RequestException as exc:
            log.warning("Сеть: %s — пауза 3 сек", exc)
            time.sleep(3)
            try:
                server, key, ts = get_long_poll()
            except Exception as exc2:
                log.error("Переподключение не удалось: %s", exc2)
                time.sleep(5)


if __name__ == "__main__":
    run()
