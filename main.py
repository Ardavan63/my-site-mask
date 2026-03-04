import os
import asyncio
import sqlite3
from io import BytesIO
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import bale
from bale import InputFile, Message

# متغیرهای Railway
api_id = int(os.getenv('TG_API_ID'))
api_hash = os.getenv('TG_API_HASH')
session_string = os.getenv('TG_SESSION')
bale_token = os.getenv('BALE_TOKEN')

client = TelegramClient(StringSession(session_string), api_id, api_hash)
bale_bot = bale.Bot(token=bale_token)

# دیتابیس subscribers
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

# هندلر تلگرام - فقط کانال و گروه
@client.on(events.NewMessage(incoming=True))
async def forward_handler(event):
    if event.is_private:
        return

    msg = event.message
    title = event.chat.title or "گروه/کانال"
    base_caption = f"{msg.message or ''}\n\n📌 از: {title} (تلگرام)"

    subs = get_subs()
    if not subs:
        return

    try:
        if msg.media:
            if msg.file and msg.file.size > 15 * 1024 * 1024:
                for uid in subs:
                    await bale_bot.send_message(uid, f"⚠️ فایل بزرگ (>۱۵ مگ) رد شد\n{base_caption}")
                return

            buffer = BytesIO()
            await msg.download_media(file=buffer)
            buffer.seek(0)
            ifile = InputFile(buffer.read())

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
                except:
                    pass
            print(f"✅ رسانه فوروارد شد به {len(subs)} نفر | از {title}")
        else:
            for uid in subs:
                await bale_bot.send_message(uid, base_caption)
            print(f"✅ متن فوروارد شد به {len(subs)} نفر | از {title}")
    except Exception as e:
        print(f"خطای فوروارد: {e}")

# هندلر بله (فیکس شده)
@bale_bot.event
async def on_message(message: Message):
    if not message.text:
        return
    text = message.text.strip().lower()
    chat_id = message.chat.id

    if text == "/start":
        add_sub(chat_id)
        await message.reply("✅ ثبت شد!\nاز این به بعد همه پیام‌های کانال و گروه تلگرامت مستقیم اینجا میاد.")
    elif text == "/stop":
        remove_sub(chat_id)
        await message.reply("❌ ثبت لغو شد.")
    elif text == "/count":
        await message.reply(f"تعداد مشترکین فعال: {len(get_subs())} نفر")
    else:
        await message.reply("دستورات:\n/start → ثبت\n/stop → لغو\n/count → تعداد مشترکین")

async def main():
    print("🚀 فورواردر چند کاربره تلگرام → بله شروع شد")
    await client.start()
    print("✅ تلگرام متصل")
    print("✅ ربات بله آماده — کاربران با /start ثبت شوند")

    await asyncio.gather(
        client.run_until_disconnected(),
        bale_bot.run()
    )

if __name__ == "__main__":
    asyncio.run(main())