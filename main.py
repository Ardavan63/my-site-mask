import os
import asyncio
import sqlite3
from io import BytesIO
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import bale
from bale import InputFile, Message

# ==================== متغیرها ====================
api_id = int(os.getenv('TG_API_ID'))
api_hash = os.getenv('TG_API_HASH')
session_string = os.getenv('TG_SESSION')
bale_token = os.getenv('BALE_TOKEN')

client = TelegramClient(StringSession(session_string), api_id, api_hash)
bale_bot = bale.Bot(token=bale_token)

# ==================== دیتابیس ====================
conn = sqlite3.connect('subscribers.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS subscribers (chat_id INTEGER PRIMARY KEY)''')
conn.commit()

def get_subs():
    c.execute("SELECT chat_id FROM subscribers")
    return [row[0] for row in c.fetchall()]

def add_sub(chat_id):
    c.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))
    conn.commit()

def remove_sub(chat_id):
    c.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
    conn.commit()

# ==================== هندلر تلگرام (همه پیام‌ها + لاگ سنگین) ====================
@client.on(events.NewMessage(incoming=True))
async def forward_handler(event):
    msg = event.message
    print(f"📥 پیام جدید از تلگرام دریافت شد | Chat ID: {event.chat_id} | خصوصی: {event.is_private}")

    # عنوان هوشمند
    if event.is_private:
        sender = event.sender or event.chat
        title = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or sender.username or "کاربر ناشناس"
        source = f"📨 پیام خصوصی از: {title}"
    else:
        title = event.chat.title or "گروه/کانال"
        source = f"📌 از: {title}"

    base_caption = f"{msg.message or ''}\n\n{source} (تلگرام)"

    subs = get_subs()
    print(f"👥 تعداد مشترکین: {len(subs)}")

    if not subs:
        print("⚠️ هیچ مشترکی وجود ندارد")
        return

    try:
        if msg.media:
            if msg.file and msg.file.size > 15 * 1024 * 1024:
                print("❌ فایل بزرگتر از ۱۵ مگ — رد شد")
                for uid in subs:
                    await bale_bot.send_message(uid, f"⚠️ فایل بزرگ (>۱۵ مگ) رد شد\n{base_caption}")
                return

            buffer = BytesIO()
            await msg.download_media(file=buffer)
            buffer.seek(0)
            file_bytes = buffer.read()
            ifile = InputFile(file_bytes)

            for uid in subs:
                try:
                    if msg.photo:
                        await bale_bot.send_photo(uid, ifile, caption=base_caption)
                    elif msg.video:
                        await bale_bot.send_video(uid, ifile, caption=base_caption)
                    elif msg.voice:
                        await bale_bot.send_voice(uid, ifile)
                    elif msg.audio:
                        await bale_bot.send_audio(uid, ifile, caption=base_caption)
                    else:
                        await bale_bot.send_document(uid, ifile, caption=base_caption)
                    print(f"✅ رسانه به {uid} ارسال شد")
                except Exception as e:
                    print(f"❌ خطا ارسال به {uid}: {e}")
        else:
            for uid in subs:
                await bale_bot.send_message(uid, base_caption)
                print(f"✅ متن به {uid} ارسال شد")
    except Exception as e:
        print(f"❌ خطای کلی فوروارد: {e}")

# ==================== هندلر بله (با لاگ + on_ready + on_before_ready) ====================
@bale_bot.event
async def on_before_ready():
    await bale_bot.delete_webhook()
    print("✅ Webhook پاک شد — حالا polling فعال است")

@bale_bot.event
async def on_ready():
    print(f"✅ ربات بله کاملاً آنلاین شد | Username: {bale_bot.user.username if bale_bot.user else 'N/A'}")

@bale_bot.event
async def on_message(message: Message):
    print(f"📨 پیام از بله دریافت شد | Chat ID: {message.chat.id} | متن: {message.text}")
    if not message.text:
        return
    text = message.text.strip().lower()
    chat_id = message.chat.id

    if text == "/start":
        add_sub(chat_id)
        await message.reply("✅ ثبت شد!\nاز این به بعد **همه** پیام‌های تلگرامت (حتی خصوصی) مستقیم اینجا میاد.")
        print(f"✅ کاربر {chat_id} ثبت شد")
    elif text == "/stop":
        remove_sub(chat_id)
        await message.reply("❌ ثبت لغو شد.")
        print(f"❌ کاربر {chat_id} حذف شد")
    elif text == "/count":
        await message.reply(f"تعداد مشترکین فعال: {len(get_subs())} نفر")
        print(f"📊 تعداد مشترکین: {len(get_subs())}")
    else:
        await message.reply("دستورات:\n/start → ثبت\n/stop → لغو\n/count → تعداد")

# ==================== اجرای همزمان (درست و بدون ترد) ====================
async def main():
    print("🚀 فورواردر تلگرام → بله (نسخه نهایی) شروع شد")

    await client.start()
    print("✅ تلگرام متصل شد")

    await asyncio.gather(
        client.run_until_disconnected(),
        bale_bot.run(),          # ← این خط کلیدی بود! حالا await می‌شه
        return_exceptions=True
    )

if __name__ == "__main__":
    asyncio.run(main())