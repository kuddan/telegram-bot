import sqlite3
import os
import logging
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update, User
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ChatMemberHandler,
    filters,
    ContextTypes
)

# --- 1. خادم الويب لإبقاء البوت حياً ---
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# --- 2. إعدادات البوت وقاعدة البيانات ---
TOKEN = "8821264603:AAF8vCfrMBBznVzqrk7EI781ecyJRDcqXF4"
DB_FILE = "pending_members.db"
LOCK = asyncio.Lock()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending (
            user_id INTEGER PRIMARY KEY,
            mention_html TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_user_to_db(user_id: int, mention_html: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO pending (user_id, mention_html) VALUES (?, ?)", (user_id, mention_html))
    conn.commit()
    cursor.execute("SELECT user_id, mention_html FROM pending ORDER BY rowid ASC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def clear_db_users(user_ids):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    for uid in user_ids:
        cursor.execute("DELETE FROM pending WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()

def get_all_db_users():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, mention_html FROM pending ORDER BY rowid ASC")
    rows = cursor.fetchall()
    conn.close()
    return rows

async def process_welcome_send(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    async with LOCK:
        rows = get_all_db_users()
        if not rows:
            return False
            
        members_list = "\n".join([f"• {row[1]}" for row in rows])
        
        welcome_text = (
            f"مرحبا بكل الاعضاء الجدد المنضمين للساحات 🌺\n\n"
            f"{members_list}\n\n"
            f"نرحب بجميع استفساراتكم وطلباتكم، وسيتم الرد عليها في أقرب فرصة بإذن الله.\n\n"
            f"ساحات المعلمين للجميع، فحيّاكم الله جميعًا. 🌹"
        )
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            parse_mode="HTML"
        )
        
        user_ids = [row[0] for row in rows]
        clear_db_users(user_ids)
        return True

async def process_new_user(user: User, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    if user.is_bot:
        return
        
    async with LOCK:
        mention = user.mention_html()
        rows = add_user_to_db(user.id, mention)
        count = len(rows)
        print(f"==> عضو جديد: {user.full_name} | المسجلين بالعداد: {count}/5")
        
        if count >= 5:
            top_5 = rows[:5]
            members_list = "\n".join([f"• {row[1]}" for row in top_5])
            
            welcome_text = (
                f"مرحبا بكل الاعضاء الجدد المنضمين للساحات 🌺\n\n"
                f"{members_list}\n\n"
                f"نرحب بجميع استفساراتكم وطلباتكم، وسيتم الرد عليها في أقرب فرصة بإذن الله.\n\n"
                f"ساحات المعلمين للجميع، فحيّاكم الله جميعًا. 🌹"
            )
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_text,
                parse_mode="HTML"
            )
            
            user_ids_to_remove = [row[0] for row in top_5]
            clear_db_users(user_ids_to_remove)

async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.new_chat_members:
        for member in update.message.new_chat_members:
            await process_new_user(member, update.effective_chat.id, context)

async def handle_chat_member_updated(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return
    
    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    
    if old_status != new_status and new_status in ["member", "administrator"]:
        await process_new_user(result.new_chat_member.user, update.effective_chat.id, context)

async def force_flush_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sent = await process_welcome_send(update.effective_chat.id, context)
    if not sent:
        await update.message.reply_text("لا يوجد أعضاء بانتظار الترحيب حالياً.")

if __name__ == '__main__':
    keep_alive()
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("flush", force_flush_welcome))
    app.add_handler(MessageHandler(filters.Regex(r'^(رحب|/رحب)$'), force_flush_welcome))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    app.add_handler(ChatMemberHandler(handle_chat_member_updated, ChatMemberHandler.CHAT_MEMBER))
    
    print("=== البوت يعمل الآن بقاعدة بيانات SQLite وخادم ويب ===")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
