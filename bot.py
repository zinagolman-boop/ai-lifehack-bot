import os
import json
import asyncio
import logging
from datetime import datetime, time
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
SEND_HOUR = int(os.environ.get("SEND_HOUR", "9"))

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash-latest")

DATA_FILE = "users.json"

def load_users():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def get_user(user_id: str):
    users = load_users()
    return users.get(user_id)

def save_user(user_id: str, data: dict):
    users = load_users()
    users[user_id] = data
    save_users(users)

def ask_gemini(prompt: str) -> str:
    response = model.generate_content(prompt)
    return response.text

ASSESSMENT_QUESTIONS = [
    {
        "q": "Что такое «температура» (temperature) в настройках ИИ?",
        "options": [
            "Не знаю такого параметра",
            "Что-то про скорость работы модели",
            "Параметр, влияющий на случайность и креативность ответов",
            "Знаю и регулярно меняю его под разные задачи"
        ]
    },
    {
        "q": "Как лучше всего получить от ИИ точный и полезный ответ?",
        "options": [
            "Просто написать вопрос как есть",
            "Добавить «пожалуйста» и «спасибо»",
            "Дать контекст, роль и конкретную задачу",
            "Использую системные промпты, few-shot примеры и цепочки рассуждений"
        ]
    },
    {
        "q": "Что такое «контекстное окно» у языковой модели?",
        "options": [
            "Окно интерфейса чата",
            "Слышал(а), но не уверен(а) что это",
            "Максимальный объём текста, который модель может обработать за раз",
            "Знаю и учитываю это при работе с длинными документами"
        ]
    },
    {
        "q": "Пробовал(а) ли ты использовать ИИ для автоматизации или создания рабочих процессов?",
        "options": [
            "Нет, использую только для простых вопросов",
            "Иногда прошу помочь с текстами или кодом",
            "Да, строю промпты для конкретных рабочих задач",
            "Да, использую API, агентов или интеграции с другими инструментами"
        ]
    },
    {
        "q": "Чем отличаются разные модели ИИ (GPT-4, Claude, Gemini)?",
        "options": [
            "Не знаю, использую что попало",
            "Знаю названия, но не понимаю разницы",
            "Понимаю общие различия в возможностях и стоимости",
            "Осознанно выбираю модель под конкретную задачу"
        ]
    }
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)

    if user and user.get("level"):
        await update.message.reply_text(
            f"С возвращением! Твой уровень: *{user['level']}* 🎯\n\n"
            f"/lifehack — получить лайфхак прямо сейчас\n"
            f"/check — проверить знания\n"
            f"/progress — посмотреть прогресс\n"
            f"/reset — начать заново",
            parse_mode="Markdown"
        )
    else:
        save_user(user_id, {"level": None, "topics_covered": [], "score": 0, "day": 0})
        await update.message.reply_text(
            "👋 Привет! Я буду каждый день присылать тебе лайфхак по работе с ИИ — "
            "персонально подобранный под твой уровень.\n\n"
            "Сначала пройди короткий тест — 5 вопросов на реальное понимание ИИ.\n\n"
            "Готов(а)?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚀 Начать тест", callback_data="start_test")
            ]])
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)

    if query.data == "start_test":
        await run_assessment(query, user_id, context)
    elif query.data.startswith("answer_"):
        await handle_answer(query, user_id, context)
    elif query.data == "get_lifehack_now":
        await get_lifehack_now_callback(update, context)

async def run_assessment(query, user_id: str, context):
    user = get_user(user_id) or {}
    user["assessment_step"] = 0
    user["assessment_answers"] = []
    save_user(user_id, user)
    await send_assessment_question(query, user_id, 0)

async def send_assessment_question(query_or_message, user_id: str, step: int):
    if step >= len(ASSESSMENT_QUESTIONS):
        await finalize_assessment(query_or_message, user_id)
        return

    q = ASSESSMENT_QUESTIONS[step]
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"answer_{step}_{i}")]
                for i, opt in enumerate(q["options"])]

    text = f"*Вопрос {step+1}/{len(ASSESSMENT_QUESTIONS)}*\n\n{q['q']}"

    if hasattr(query_or_message, 'edit_message_text'):
        await query_or_message.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query_or_message.reply_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_answer(query, user_id: str, context):
    parts = query.data.split("_")
    step = int(parts[1])
    answer = int(parts[2])

    user = get_user(user_id) or {}
    answers = user.get("assessment_answers", [])
    answers.append(answer)
    user["assessment_answers"] = answers
    save_user(user_id, user)

    await send_assessment_question(query, user_id, step + 1)

async def finalize_assessment(query, user_id: str):
    user = get_user(user_id) or {}
    answers = user.get("assessment_answers", [])
    total = sum(answers)
    max_score = (len(ASSESSMENT_QUESTIONS) - 1) * len(ASSESSMENT_QUESTIONS)

    if total <= 4:
        level = "новичок"
        desc = "Ты только начинаешь погружаться в мир ИИ — отличное время чтобы заложить крепкую базу!"
    elif total <= 8:
        level = "любопытный"
        desc = "У тебя есть базовое понимание, но много интересного ещё впереди."
    elif total <= 12:
        level = "практик"
        desc = "Ты неплохо разбираешься в ИИ. Будем шлифовать навыки и открывать продвинутые техники."
    else:
        level = "продвинутый"
        desc = "Ты глубоко погружен(а) в тему. Сосредоточимся на тонкостях и нестандартных подходах."

    user["level"] = level
    user["score"] = total
    user["day"] = 0
    user["topics_covered"] = []
    save_user(user_id, user)

    await query.edit_message_text(
        f"✅ *Оценка завершена!*\n\n"
        f"Твой уровень: *{level}* 🎯\n\n"
        f"{desc}\n\n"
        f"Каждое утро в 9:00 буду присылать персональный лайфхак.\n"
        f"Или получи первый прямо сейчас 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⚡ Получить первый лайфхак!", callback_data="get_lifehack_now")
        ]])
    )

async def send_lifehack_to_user(user_id: str, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(user_id)
    if not user or not user.get("level"):
        return

    level = user["level"]
    day = user.get("day", 0) + 1
    topics = user.get("topics_covered", [])
    topics_str = ", ".join(topics[-5:]) if topics else "ещё не было"

    prompt = f"""Ты — эксперт по работе с ИИ. Напиши практичный лайфхак для пользователя.

Уровень пользователя: {level}
День обучения: {day}
Недавно пройденные темы: {topics_str}

Требования:
- Лайфхак должен быть НОВЫМ (не повторять пройденные темы)
- Подходить по сложности для уровня "{level}"
- Конкретный и применимый сразу на практике
- Касаться работы с ChatGPT, Claude или ИИ в целом

Формат ответа (строго):
ТЕМА: [одно слово или короткая фраза]
ЛАЙФХАК: [название лайфхака, 5-8 слов]
СУТЬ: [2-3 предложения что это и зачем]
КАК ИСПОЛЬЗОВАТЬ: [конкретный пример или шаги]
ПОПРОБУЙ СЕЙЧАС: [простое задание которое можно сделать за 2 минуты]"""

    try:
        response = ask_gemini(prompt)
        lines = response.strip().split("\n")
        topic = ""
        for line in lines:
            if line.startswith("ТЕМА:"):
                topic = line.replace("ТЕМА:", "").strip()
                break

        if topic:
            topics.append(topic)
            user["topics_covered"] = topics
        user["day"] = day
        save_user(user_id, user)

        message = f"🌅 *День {day} — Лайфхак дня*\n\n{response}\n\n---\n💬 Есть вопросы? Просто напиши мне!"

        await context.bot.send_message(
            chat_id=int(user_id),
            text=message,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error sending lifehack to {user_id}: {e}")
        await context.bot.send_message(
            chat_id=int(user_id),
            text=f"⚠️ Не удалось получить лайфхак. Попробуй /lifehack чуть позже."
        )

async def lifehack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)

    if not user or not user.get("level"):
        await update.message.reply_text("Сначала пройди тест! Напиши /start")
        return

    await update.message.reply_text("⏳ Генерирую лайфхак специально для тебя...")
    await send_lifehack_to_user(user_id, context)

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)

    if not user or not user.get("level"):
        await update.message.reply_text("Сначала пройди тест! Напиши /start")
        return

    topics = user.get("topics_covered", [])
    if not topics:
        await update.message.reply_text("Сначала получи хотя бы один лайфхак! Напиши /lifehack")
        return

    topics_str = ", ".join(topics[-3:])
    prompt = f"""Создай короткую проверку знаний (1 вопрос) по теме: {topics_str}.

Уровень пользователя: {user['level']}

Формат:
ВОПРОС: [вопрос]
А) [вариант]
Б) [вариант]
В) [вариант]
ПРАВИЛЬНЫЙ: [А/Б/В]
ОБЪЯСНЕНИЕ: [почему именно этот ответ, 1-2 предложения]"""

    await update.message.reply_text("🧠 Проверяю твои знания...")
    response = ask_gemini(prompt)
    await update.message.reply_text(
        f"*Мини-тест*\n\n{response}",
        parse_mode="Markdown"
    )

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)

    if not user or not user.get("level"):
        await update.message.reply_text("Сначала пройди тест! Напиши /start")
        return

    day = user.get("day", 0)
    level = user.get("level", "—")
    topics = user.get("topics_covered", [])

    topics_text = "\n".join([f"• {t}" for t in topics]) if topics else "Ещё нет пройденных тем"

    await update.message.reply_text(
        f"📊 *Твой прогресс*\n\n"
        f"🎯 Уровень: *{level}*\n"
        f"📅 Дней обучения: *{day}*\n"
        f"📚 Изученные темы ({len(topics)}):\n{topics_text}",
        parse_mode="Markdown"
    )

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    save_user(user_id, {"level": None, "topics_covered": [], "score": 0, "day": 0})
    await update.message.reply_text("🔄 Прогресс сброшен. Напиши /start чтобы начать заново.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)

    if not user or not user.get("level"):
        await update.message.reply_text("Напиши /start чтобы начать!")
        return

    user_text = update.message.text
    topics = user.get("topics_covered", [])

    prompt = f"""Пользователь изучает работу с ИИ (уровень: {user['level']}).
Изученные темы: {', '.join(topics) if topics else 'нет'}.
Вопрос пользователя: {user_text}

Ответь коротко и по делу, как дружелюбный эксперт. Максимум 3-4 предложения."""

    response = ask_gemini(prompt)
    await update.message.reply_text(response)

async def get_lifehack_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(chat_id=int(user_id), text="⏳ Генерирую первый лайфхак...")
    await send_lifehack_to_user(user_id, context)

async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    for user_id, user in users.items():
        if user.get("level"):
            await send_lifehack_to_user(user_id, context)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lifehack", lifehack_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    job_queue = app.job_queue
    job_queue.run_daily(daily_job, time=time(hour=SEND_HOUR, minute=0))

    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
