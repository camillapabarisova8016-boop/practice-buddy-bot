import os
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from openai import OpenAI

# Настройки
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TEACHER_USERNAME = "pabarisova"  # твой username без @
TEACHER_CHAT_ID = None  # заполнится автоматически при первом /start от тебя

# Клиент DeepSeek (OpenAI-совместимый)
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# Простое хранилище (в реальной версии можно заменить на файл/базу)
students = {}  # user_id: {"character": prompt, "name": str, "history": [], "activity": []}
assignments = {}  # простые задания, которые ученик может отметить

logging.basicConfig(level=logging.INFO)

def load_data():
    global students
    if os.path.exists("students.json"):
        with open("students.json", "r", encoding="utf-8") as f:
            students = json.load(f)

def save_data():
    with open("students.json", "w", encoding="utf-8") as f:
        json.dump(students, f, ensure_ascii=False, indent=2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    global TEACHER_CHAT_ID
    if user.username == TEACHER_USERNAME:
        TEACHER_CHAT_ID = user.id
        await update.message.reply_text(
            "Привет, учитель. Я готов. Используй /add_student <id> <имя> чтобы добавить ученика, "
            "потом /set_character <id> <промпт персонажа>."
        )
    else:
        await update.message.reply_text("Привет. Напиши учителю, чтобы тебя добавили.")

async def add_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != TEACHER_USERNAME:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /add_student <telegram_id> <имя>")
        return
    sid = context.args[0]
    name = " ".join(context.args[1:])
    students[sid] = {
        "name": name,
        "character": "Ты дружелюбный учитель английского. Говори просто и поддерживай.",
        "history": [],
        "activity": [],
        "last_report": None
    }
    save_data()
    await update.message.reply_text(f"Ученик {name} (ID {sid}) добавлен.")

async def set_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != TEACHER_USERNAME:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /set_character <telegram_id> <текст промпта>")
        return
    sid = context.args[0]
    prompt = " ".join(context.args[1:])
    if sid in students:
        students[sid]["character"] = prompt
        save_data()
        await update.message.reply_text(f"Персонаж для {students[sid]['name']} обновлён.")
    else:
        await update.message.reply_text("Сначала добавь ученика через /add_student")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != TEACHER_USERNAME:
        return
    text = "📊 Отчёт по ученикам:\n\n"
    for sid, data in students.items():
        last = data["activity"][-1] if data["activity"] else "никогда"
        suspicious = "да" if any(a.get("suspicious") for a in data["activity"][-5:]) else "нет"
        text += f"• {data['name']} (ID {sid})\n  Последняя активность: {last}\n  Подозрение на ИИ/переводчик: {suspicious}\n\n"
    await update.message.reply_text(text or "Пока нет данных.")

def check_suspicious(text: str, history: list) -> bool:
    # Простая эвристика для теста
    if len(text) > 200 and text.count(".") > 5 and "I think" not in text.lower():
        return True
    # Можно расширить позже
    return False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sid = str(user.id)
    if sid not in students:
        await update.message.reply_text("Тебя ещё не добавили. Напиши учителю.")
        return

    student = students[sid]
    user_text = update.message.text

    # Добавляем в историю
    student["history"].append({"role": "user", "content": user_text})
    if len(student["history"]) > 20:
        student["history"] = student["history"][-20:]

    suspicious = check_suspicious(user_text, student["history"])
    student["activity"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "length": len(user_text),
        "suspicious": suspicious
    })
    save_data()

    # Формируем сообщения для модели
    messages = [{"role": "system", "content": student["character"]}]
    messages.extend(student["history"][-10:])

    try:
        response = client.chat.completions.create(
            model="deepseek-flash",
            messages=messages,
            max_tokens=500,
            extra_body={"thinking": {"type": "disabled"}}
        )
        reply = response.choices[0].message.content
        if not reply or not str(reply).strip():
            reply = "Hmm... try saying that again."
        student["history"].append({"role": "assistant", "content": reply})
        save_data()
        await update.message.reply_text(reply)

        if suspicious and TEACHER_CHAT_ID:
            await context.bot.send_message(
                TEACHER_CHAT_ID,
                f"⚠️ Подозрительный ответ от {student['name']}: слишком гладкий текст."
            )
    except Exception as e:
        await update.message.reply_text("Ошибка при ответе. Попробуй позже.")
        logging.error(e)

def main():
    load_data()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_student", add_student))
    app.add_handler(CommandHandler("set_character", set_character))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
