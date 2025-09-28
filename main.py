import random
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from googletrans import Translator

import asyncio

API_TOKEN = "8145653514:AAGrpQHKkcvMWFKEOjlJ2r0j8BnsXYACznI"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

translator = Translator()

# ---- БАЗА ДАННЫХ ----
conn = sqlite3.connect("words.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    word TEXT,
    translation TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS stats (
    user_id INTEGER PRIMARY KEY,
    total_added INTEGER DEFAULT 0,
    total_correct INTEGER DEFAULT 0,
    total_wrong INTEGER DEFAULT 0
)
""")
conn.commit()


# ---- ФУНКЦИИ ----
def add_word(user_id, word, translation):
    cursor.execute("INSERT INTO words (user_id, word, translation) VALUES (?, ?, ?)", (user_id, word, translation))
    cursor.execute("INSERT OR IGNORE INTO stats (user_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE stats SET total_added = total_added + 1 WHERE user_id = ?", (user_id,))
    conn.commit()


def get_words(user_id):
    cursor.execute("SELECT word, translation FROM words WHERE user_id = ?", (user_id,))
    return cursor.fetchall()


def update_stats(user_id, correct):
    cursor.execute("INSERT OR IGNORE INTO stats (user_id) VALUES (?)", (user_id,))
    if correct:
        cursor.execute("UPDATE stats SET total_correct = total_correct + 1 WHERE user_id = ?", (user_id,))
    else:
        cursor.execute("UPDATE stats SET total_wrong = total_wrong + 1 WHERE user_id = ?", (user_id,))
    conn.commit()


def get_stats(user_id):
    cursor.execute("SELECT total_added, total_correct, total_wrong FROM stats WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row if row else (0, 0, 0)


# ---- ХЕНДЛЕРЫ ----
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот для изучения слов.\n\n"
        "📌 Команды:\n"
        "➕ Добавить слово: `/add слово перевод`\n"
        "   (можно и без перевода: `/add 苹果`)\n"
        "🎯 Тренировка (случайные режимы): `/train`\n"
        "🃏 Флешкарты: `/flashcards`\n"
        "📊 Статистика: `/stats`",
        parse_mode="Markdown"
    )


@dp.message(Command("add"))
async def add(message: types.Message):
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Напиши слово или слово + перевод.\nПример:\n`/add 苹果 яблоко`\nили `/add 苹果`",
                             parse_mode="Markdown")
        return

    text = parts[1]

    if " " in text:
        word, translation = text.split(maxsplit=1)
    else:
        word = text
        try:
            result = translator.translate(word, src="zh-cn", dest="ru")
            translation = result.text
        except Exception:
            await message.answer("⚠️ Не удалось перевести автоматически. Укажи перевод вручную.")
            return

    add_word(user_id, word, translation)
    await message.answer(f"✅ Добавлено: {word} → {translation}")


@dp.message(Command("train"))
async def train(message: types.Message):
    user_id = message.from_user.id
    words = get_words(user_id)
    if not words:
        await message.answer("Ты ещё не добавил слова. Используй `/add слово перевод`")
        return

    mode = random.choice(["choice", "reverse", "input", "flash", "odd"])
    word, right = random.choice(words)

    if mode == "choice":
        all_translations = [t for _, t in words]
        options = random.sample(all_translations, min(3, len(all_translations)))
        if right not in options:
            options.append(right)
        random.shuffle(options)

        builder = InlineKeyboardBuilder()
        for opt in options:
            builder.button(text=opt, callback_data=f"ans:{word}:{right}:{opt}")
        builder.adjust(1)
        await message.answer(f"❓ Что значит слово: *{word}* ?", parse_mode="Markdown", reply_markup=builder.as_markup())

    elif mode == "reverse":
        await message.answer(f"🔄 Переведи на китайский: *{right}* (введи ответ)")
        dp.message.register(lambda msg: check_input(msg, right, word), lambda msg: True, once=True)

    elif mode == "input":
        await message.answer(f"⌨️ Введи перевод слова: *{word}*")
        dp.message.register(lambda msg: check_input(msg, right, word), lambda msg: True, once=True)

    elif mode == "flash":
        builder = InlineKeyboardBuilder()
        builder.button(text="Показать перевод", callback_data=f"flash:{word}:{right}")
        builder.adjust(1)
        await message.answer(f"🃏 Вспомни перевод слова: *{word}*", parse_mode="Markdown",
                             reply_markup=builder.as_markup())

    elif mode == "odd":
        if len(words) < 4:
            await train(message)
            return
        all_words = random.sample(words, 4)
        translations = [t for _, t in all_words]
        odd = random.choice(translations)
        builder = InlineKeyboardBuilder()
        for opt in translations:
            builder.button(text=opt, callback_data=f"odd:{right}:{opt}:{odd}")
        builder.adjust(1)
        await message.answer("🧐 Найди лишний перевод среди этих вариантов:", reply_markup=builder.as_markup())


async def check_input(message: types.Message, right, word):
    user_id = message.from_user.id
    answer = message.text.strip()
    if answer == word or answer == right:
        update_stats(user_id, True)
        await message.answer(f"✅ Верно! {word} → {right}")
    else:
        update_stats(user_id, False)
        await message.answer(f"❌ Неверно! {word} → {right}")


@dp.callback_query(lambda c: c.data.startswith("ans:"))
async def check_answer(callback: types.CallbackQuery):
    _, word, right, chosen = callback.data.split(":")
    user_id = callback.from_user.id
    if chosen == right:
        update_stats(user_id, True)
        await callback.message.answer(f"✅ Верно! {word} → {right}")
    else:
        update_stats(user_id, False)
        await callback.message.answer(f"❌ Неверно! {word} → {right}, а не {chosen}")


@dp.callback_query(lambda c: c.data.startswith("flash:"))
async def flash_answer(callback: types.CallbackQuery):
    _, word, right = callback.data.split(":")
    await callback.message.answer(f"👉 {word} → {right}")


@dp.callback_query(lambda c: c.data.startswith("odd:"))
async def check_odd(callback: types.CallbackQuery):
    _, right, chosen, odd = callback.data.split(":")
    if chosen == odd:
        await callback.message.answer(f"✅ Верно! Лишнее: {odd}")
    else:
        await callback.message.answer(f"❌ Неверно! Лишнее было: {odd}")


@dp.message(Command("flashcards"))
async def flashcards(message: types.Message):
    user_id = message.from_user.id
    words = get_words(user_id)
    if not words:
        await message.answer("Ты ещё не добавил слова. Используй `/add слово перевод`")
        return

    word, right = random.choice(words)
    builder = InlineKeyboardBuilder()
    builder.button(text="Показать перевод", callback_data=f"flash:{word}:{right}")
    builder.adjust(1)
    await message.answer(f"🃏 Вспомни перевод слова: *{word}*", parse_mode="Markdown", reply_markup=builder.as_markup())


@dp.message(Command("stats"))
async def stats(message: types.Message):
    user_id = message.from_user.id
    total_added, total_correct, total_wrong = get_stats(user_id)
    await message.answer(
        f"📊 Твоя статистика:\n"
        f"➕ Добавлено слов: {total_added}\n"
        f"✅ Правильных ответов: {total_correct}\n"
        f"❌ Ошибок: {total_wrong}"
    )


# ---- ЗАПУСК ----
if __name__ == "__main__":
    import asyncio

    asyncio.run(dp.start_polling(bot))