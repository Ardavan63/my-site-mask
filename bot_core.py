import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from shazamio import Shazam
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

# واکشی توکن از Environment Variables جهت امنیت (Security Protocol)
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("[-] Critical: BOT_TOKEN environment variable is strictly required.")

app = Client(
    "nexus_metadata_bot",
    api_id=6,
    api_hash="eb06d4abfb49dc3eeb1aeb98ae0f581e",
    bot_token=BOT_TOKEN,
    in_memory=True
)

shazam = Shazam()

@app.on_message(filters.audio | filters.document)
async def process_audio(client: Client, message: Message):
    if not message.audio and not (message.document and message.document.file_name.endswith(".mp3")):
        return

    status_msg = await message.reply_text("[~] Downloading audio stream...")
    file_path = await message.download()

    await status_msg.edit_text("[*] Computing acoustic fingerprint...")
    
    try:
        out = await shazam.recognize(file_path)
        if not out or 'track' not in out:
            await status_msg.edit_text("[-] Error: Acoustic signature unrecognized.")
            os.remove(file_path)
            return

        track_data = out['track']
        title = track_data.get('title', 'Unknown')
        artist = track_data.get('subtitle', 'Unknown')
        
        album = ""
        for section in track_data.get('sections', []):
            if section.get('type') == 'SONG':
                for meta in section.get('metadata', []):
                    if meta.get('title') == 'Album':
                        album = meta.get('text')

        await status_msg.edit_text(f"[+] Match: {artist} - {title}\n[*] Injecting metadata binary...")

        try:
            audio = EasyID3(file_path)
        except Exception:
            audio = MP3(file_path)
            if audio.tags is None:
                audio.add_tags()
            audio = EasyID3(file_path)

        audio['title'] = title
        audio['artist'] = artist
        if album:
            audio['album'] = album
        audio.save()

        safe_name = f"{artist} - {title}".replace('/', '_').replace('\\', '_') + ".mp3"
        new_file_path = os.path.join(os.path.dirname(file_path), safe_name)
        os.rename(file_path, new_file_path)

        await status_msg.edit_text("[^] Uploading modified payload...")
        
        await asyncio.sleep(1)
        await message.reply_audio(
            audio=new_file_path,
            title=title,
            performer=artist,
            caption=f"**Title:** {title}\n**Artist:** {artist}\n**Album:** {album}"
        )
        await status_msg.delete()

    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception as e:
        await status_msg.edit_text(f"[-] Fault Exception: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        if 'new_file_path' in locals() and os.path.exists(new_file_path):
            os.remove(new_file_path)

if __name__ == "__main__":
    app.run()
