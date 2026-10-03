# VK AI Bot — автоответчик для сообщества ВКонтакте

Бот отвечает на входящие сообщения в сообществе ВК с помощью ИИ (DeepSeek или любой OpenAI-совместимый API) и опирается на базу знаний (RAG на BM25).

## Возможности

- Приём сообщений через Bots Long Poll API — публичный сервер и SSL не нужны.
- Ответы через DeepSeek или другой OpenAI-совместимый API.
- База знаний: `knowledge.md`, поиск релевантных фрагментов (BM25), без внешних сервисов.
- История диалога по каждому собеседнику, защита от дублей, индикатор «печатает».
- Автопереподключение Long Poll.

## Быстрый старт

```bash
git clone https://github.com/drogalin/vk-bot.git
cd vk-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполните токены
python vk_bot.py
```

## Настройка

Все параметры — в `.env` (см. `.env.example`). Токен сообщества ВК выдаётся в настройках сообщества с правом «Сообщения сообщества»; включите Long Poll API и событие «Входящие сообщения».

## Структура проекта

```plaintext
vk-bot/
├── vk_bot.py          # Long Poll + логика ответа
├── knowledge_base.py  # RAG-поиск по базе знаний (BM25)
├── knowledge.md       # база знаний (прайс, FAQ)
├── requirements.txt
├── .env.example
└── .gitignore
```

## Лицензия

MIT
