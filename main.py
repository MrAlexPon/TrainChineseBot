import logging
import sqlite3
import random
import os
import re

from dotenv import load_dotenv
from pypinyin import pinyin, Style
import translators as ts
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN") or "8394634711:AAHkV5UModE3zeP02B5PU4qmNXdXzqCsdKs"
logging.basicConfig(level=logging.INFO)

def contains_chinese(text):
    return bool(re.search(r'[\u4e00-\u9fff]', text))

def get_chinese_from_russian(text):
    try:
        hanzi = ts.translate_text(text, translator="google", from_language="ru", to_language="zh")
        return hanzi
    except Exception as e:
        logging.error(f"Russian to Chinese translation error: {e}")
        return None

def init_db():
    conn = sqlite3.connect('vocabulary.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            first_name TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            word TEXT NOT NULL,
            pinyin TEXT,
            translation TEXT NOT NULL,
            added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()

def word_exists(user_id, word):
    conn = sqlite3.connect('vocabulary.db')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM user_words WHERE user_id = ? AND word = ?', (user_id, word))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def translate_word(word):
    try:
        return ts.translate_text(word, translator='google', from_language='zh', to_language='ru')
    except Exception as e:
        logging.error(f"Google Translate fail: {e}")
        return "Ошибка перевода"

def get_pinyin(hanzi):
    try:
        result = []
        for sylls in pinyin(hanzi, style=Style.TONE, heteronym=False):
            result.append(sylls[0])
        return " ".join(result)
    except Exception as e:
        logging.error(f"pypinyin fail: {e}")
        return ""

def get_user_id(telegram_id):
    conn = sqlite3.connect('vocabulary.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def ensure_user_exists(telegram_id, username, first_name):
    try:
        conn = sqlite3.connect('vocabulary.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)',
            (telegram_id, username, first_name)
        )
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка регистрации пользователя: {e}")
    finally:
        conn.close()

def add_word_to_db(user_id, word, pinyin, translation):
    if not user_id:
        logging.error('add_word_to_db: user_id is None!')
        return
    if word_exists(user_id, word):  # Проверка на существование слова в словаре
        logging.info(f"Слово '{word}' уже есть в словаре пользователя {user_id}, добавление пропущено")
        return
    try:
        conn = sqlite3.connect('vocabulary.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO user_words (user_id, word, pinyin, translation) VALUES (?, ?, ?, ?)',
            (user_id, word, pinyin, translation)
        )
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка добавления слова: {e}")
    finally:
        conn.close()

def get_user_words(user_id):
    conn = sqlite3.connect('vocabulary.db')
    cursor = conn.cursor()
    cursor.execute('SELECT word, pinyin, translation FROM user_words WHERE user_id = ?', (user_id,))
    words = cursor.fetchall()
    conn.close()
    return words

def delete_word(user_id, word):
    try:
        conn = sqlite3.connect('vocabulary.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_words WHERE user_id = ? AND word = ?', (user_id, word))
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка удаления слова: {e}")
    finally:
        conn.close()

common_word_pairs = [
    ("你好", "привет"), ("谢谢", "спасибо"), ("再见", "до свидания"), ("是", "да"), ("不", "нет"),
    ("好", "хорошо"), ("爱", "любовь"), ("朋友", "друг"), ("家庭", "семья"), ("学校", "школа"),
    ("工作", "работа"), ("吃饭", "кушать"), ("水", "вода"), ("茶", "чай"), ("咖啡", "кофе"),
    ("书", "книга"), ("电影", "фильм"), ("音乐", "музыка"), ("城市", "город"),
    ("国家", "страна"), ("时间", "время"), ("今天", "сегодня"), ("明天", "завтра")
]

def get_smart_distractors(correct_translation, count=3):
    freq_translations = [pair[1] for pair in common_word_pairs if pair[1] != correct_translation]
    random.shuffle(freq_translations)
    return freq_translations[:count]

MAIN_MENU = [
    [KeyboardButton("➕ Добавить слово"), KeyboardButton("🎯 Тренировка")],
    [KeyboardButton("📚 Мои слова"), KeyboardButton("🗑️ Удалить слово")],
    [KeyboardButton("ℹ️ Помощь")]
]
MAIN_MENU_MARKUP = ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)

START_TEXT = (
    "🤖 Добро пожаловать в бот для изучения китайских иероглифов!\n\n"
    "📝 Как пользоваться:\n"
    "1. Добавляйте иероглифы для изучения.\n"
    "2. Практикуйте слова в тренировке.\n"
    "3. Улучшайте свой словарный запас.\n\n"
    "Просто отправьте китайский иероглиф, слово или фразу — бот покажет пиньинь и перевод!\n"
    "Например: 很酷 или 很酷 очень круто\n"
    "Можно и на русском — бот сам найдёт иероглиф! Например: телефон"
)

HELP_TEXT = (
    "ℹ️ Помощь\n\n"
    "— Вы можете отправить китайский иероглиф (или слово), а можете просто слово по-русски — бот всё обработает.\n"
    "— 'Мои слова' — просмотр вашего словаря.\n"
    "— 'Удалить слово' — стереть запись по иероглифу.\n"
    "— 'Тренировка' — выбирайте правильный перевод из 4 вариантов!"
)

right_emoji = "✅"
wrong_emoji = "❌"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    ensure_user_exists(user.id, user.username, user.first_name)
    await update.message.reply_text(START_TEXT, reply_markup=MAIN_MENU_MARKUP)

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    ensure_user_exists(user.id, user.username, user.first_name)
    user_id = get_user_id(user.id)
    text = update.message.text.strip()

    if context.user_data.get('training_words'):
        await handle_training_response(update, context)
        return

    if text == "➕ Добавить слово":
        await update.message.reply_text(
            "Просто отправьте китайский иероглиф, слово или фразу — или по-русски!\nБот сам найдёт перевод — иероглиф, пиньинь, русское объяснение.",
            reply_markup=MAIN_MENU_MARKUP
        )
    elif text == "🎯 Тренировка":
        words = get_user_words(user_id)
        if not words:
            await update.message.reply_text("Нет слов для тренировки.", reply_markup=MAIN_MENU_MARKUP)
            return
        context.user_data['training_words'] = random.sample(words, len(words))
        context.user_data['current_training_index'] = 0
        await start_training(update, context)
    elif text == "📚 Мои слова":
        words = get_user_words(user_id)
        if not words:
            await update.message.reply_text("Ваш словарь пуст.", reply_markup=MAIN_MENU_MARKUP)
        else:
            word_list = "\n".join([f"{w} ({p})\n{t}" if p else f"{w}\n{t}" for w, p, t in words])
            await update.message.reply_text(f"📚 Ваши слова:\n\n{word_list}", reply_markup=MAIN_MENU_MARKUP)
    elif text == "🗑️ Удалить слово":
        words = get_user_words(user_id)
        if not words:
            await update.message.reply_text("В словаре пока ничего нет.", reply_markup=MAIN_MENU_MARKUP)
        else:
            word_list = "\n".join([f"{w}" for w, p, t in words])
            await update.message.reply_text(
                f"Введите иероглиф для удаления:\n{word_list}",
                reply_markup=MAIN_MENU_MARKUP
            )
            context.user_data['awaiting_deletion'] = True
    elif text == "ℹ️ Помощь":
        await update.message.reply_text(HELP_TEXT, reply_markup=MAIN_MENU_MARKUP)
    elif context.user_data.get('awaiting_deletion'):
        to_delete = text.strip()
        if not word_exists(user_id, to_delete):
            await update.message.reply_text(f"Слово {to_delete} не найдено.", reply_markup=MAIN_MENU_MARKUP)
        else:
            delete_word(user_id, to_delete)
            await update.message.reply_text(f"✅ Удалено: {to_delete}", reply_markup=MAIN_MENU_MARKUP)
        context.user_data['awaiting_deletion'] = False
    else:
        # если вначале есть китайский — стандартный ввод
        parts = text.split(maxsplit=1)
        if contains_chinese(parts[0]):
            hanzi = parts[0]
            user_translation = parts[1] if len(parts) == 2 else None
            pinyin_text = get_pinyin(hanzi)
            translation = user_translation if user_translation else translate_word(hanzi)
            msg = f"{hanzi}"
            if pinyin_text:
                msg += f" ({pinyin_text})"
            msg += f"\n{translation}"
            add_word_to_db(user_id, hanzi, pinyin_text, translation)
            await update.message.reply_text(msg, reply_markup=MAIN_MENU_MARKUP)
        else:
            # Иначе переводим всю фразу целиком с русского на китайский
            hanzi = get_chinese_from_russian(text)
            if not hanzi or not contains_chinese(hanzi):
                await update.message.reply_text(
                    "Не удалось найти подходящий китайский перевод для этого слова или фразы.",
                    reply_markup=MAIN_MENU_MARKUP
                )
                return
            pinyin_text = get_pinyin(hanzi)
            translation = text
            msg = f"{hanzi}"
            if pinyin_text:
                msg += f" ({pinyin_text})"
            msg += f"\n{translation}"
            add_word_to_db(user_id, hanzi, pinyin_text, translation)
            await update.message.reply_text(msg, reply_markup=MAIN_MENU_MARKUP)

async def start_training(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = get_user_id(user.id)
    words = context.user_data['training_words']
    index = context.user_data['current_training_index']
    if index >= len(words):
        context.user_data.pop('training_words', None)
        context.user_data.pop('current_training_index', None)
        context.user_data.pop('correct_answer', None)
        await update.message.reply_text(
            "🎉 Тренировка завершена! Всё хорошо!",
            reply_markup=MAIN_MENU_MARKUP)
        return

    current_word, pinyin_text, correct_translation = words[index]
    all_trans = [t for w, p, t in words if t != correct_translation and t not in ("None", "")]
    random.shuffle(all_trans)
    distractors = get_smart_distractors(correct_translation, count=3-len(all_trans)) if len(all_trans) < 3 else []
    pool = all_trans[:3] + distractors
    options = pool[:3] if len(pool) >= 3 else pool + get_smart_distractors(correct_translation, 3-len(pool))
    options.append(correct_translation)
    random.shuffle(options)

    context.user_data['correct_answer'] = correct_translation
    context.user_data['current_training_index'] = index

    display = f"{current_word}" + (f" ({pinyin_text})" if pinyin_text else "")
    keyboard = [[KeyboardButton(opt)] for opt in options]
    keyboard.append([KeyboardButton("⏹️ Стоп тренировка")])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        f"Что означает?\n\n{display}",
        reply_markup=reply_markup
    )

async def handle_training_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⏹️ Стоп тренировка":
        context.user_data.pop('training_words', None)
        context.user_data.pop('current_training_index', None)
        context.user_data.pop('correct_answer', None)
        await update.message.reply_text("Тренировка остановлена.", reply_markup=MAIN_MENU_MARKUP)
        return

    correct_answer = context.user_data.get('correct_answer')
    if not correct_answer:
        context.user_data['current_training_index'] += 1
        await start_training(update, context)
        return
    if text == correct_answer:
        await update.message.reply_text(f"{right_emoji} Верно!", reply_markup=MAIN_MENU_MARKUP)
    else:
        await update.message.reply_text(f"{wrong_emoji} Нет. Верно: {correct_answer}", reply_markup=MAIN_MENU_MARKUP)
    context.user_data['current_training_index'] += 1
    await start_training(update, context)

def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    application.run_polling()
    print("Бот запущен!")

if __name__ == '__main__':
    main()
