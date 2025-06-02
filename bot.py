import requests
import sqlite3
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

BOT_TOKEN = '7806164979:AAGABF7cvKVov0ijek6tVJGfAf9lyaHRHcs'

# --- база данных ---
conn = sqlite3.connect('topics.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS topics (user_id INTEGER, topic TEXT)')
cursor.execute('CREATE TABLE IF NOT EXISTS sent_links (user_id INTEGER, link TEXT)')
conn.commit()

# --- парсинг arXiv через BeautifulSoup ---
def search_arxiv(topic):
    base_url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{topic}",
        "start": 0,
        "max_results": 5,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }
    response = requests.get(base_url, params=params)
    soup = BeautifulSoup(response.content, 'xml')
    
    results = []
    for entry in soup.find_all('entry'):
        title = entry.title.text.strip().replace('\n', ' ')
        link = entry.id.text.strip()
        results.append((title, link))
    return results

# --- уведомление пользователей ---
async def notify_users(app):
    cursor.execute("SELECT DISTINCT user_id FROM topics")
    for (user_id,) in cursor.fetchall():
        cursor.execute("SELECT topic FROM topics WHERE user_id = ?", (user_id,))
        topics = [row[0] for row in cursor.fetchall()]
        for topic in topics:
            articles = search_arxiv(topic)
            for title, link in articles:
                cursor.execute("SELECT 1 FROM sent_links WHERE user_id = ? AND link = ?", (user_id, link))
                if not cursor.fetchone():
                    await app.bot.send_message(chat_id=user_id, text=f"📄 *{title}*\n{link}", parse_mode="Markdown")
                    cursor.execute("INSERT INTO sent_links (user_id, link) VALUES (?, ?)", (user_id, link))
    conn.commit()

# --- команды Telegram-бота ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь /add <тема>, чтобы следить за новыми статьями на arXiv.")

async def add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи тему: /add elliptic curves")
        return

    topic = " ".join(context.args)
    user_id = update.effective_chat.id

    cursor.execute("INSERT INTO topics (user_id, topic) VALUES (?, ?)", (user_id, topic))
    conn.commit()

    await update.message.reply_text(f"Тема '{topic}' добавлена! 🔍 Сейчас ищу свежие статьи...")

    articles = search_arxiv(topic)
    if not articles:
        await update.message.reply_text("Ничего не найдено 😕")
        return

    response = f"📚 Топ-5 статей по теме *{topic}*:\n\n"
    for title, link in articles:
        response += f"• [{title}]({link})\n"
    
    await update.message.reply_text(response, parse_mode="Markdown")


async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT topic FROM topics WHERE user_id = ?", (update.effective_chat.id,))
    topics = [row[0] for row in cursor.fetchall()]
    if topics:
        await update.message.reply_text("Ты следишь за темами:\n" + "\n".join(f"- {t}" for t in topics))
    else:
        await update.message.reply_text("Ты ещё не добавил ни одной темы.")

async def remove_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи тему, которую хочешь удалить: /remove elliptic curves")
        return

    topic = " ".join(context.args)
    user_id = update.effective_chat.id

    cursor.execute("SELECT 1 FROM topics WHERE user_id = ? AND topic = ?", (user_id, topic))
    if not cursor.fetchone():
        await update.message.reply_text(f"Тема '{topic}' не найдена в твоём списке.")
        return

    cursor.execute("DELETE FROM topics WHERE user_id = ? AND topic = ?", (user_id, topic))
    conn.commit()
    await update.message.reply_text(f"Тема '{topic}' удалена.")


# --- запуск приложения ---
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add", add_topic))
app.add_handler(CommandHandler("list", list_topics))
app.add_handler(CommandHandler("remove", remove_topic))

# --- планировщик на 6 часов ---
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: app.create_task(notify_users(app)), 'interval', hours=6)
scheduler.start()

app.run_polling()
