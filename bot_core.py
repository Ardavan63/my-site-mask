import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, ForceReply
from pyrogram.errors import FloodWait
from shazamio import Shazam
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from ytmusicapi import YTMusic

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
ytmusic = YTMusic()
pending_tasks = {}

def extract_heuristic_query(message: Message) -> str:
    query = ""
    if message.audio:
        title = message.audio.title or ""
        artist = message.audio.performer or ""
        query = f"{artist} {title}".strip()
        
    if not query and message.document and message.document.file_name:
        base_name = os.path.splitext(message.document.file_name)[0]
        query = base_name.replace('-', ' ').replace('_', ' ')
        
    return query.strip()

def fetch_ytmusic_metadata(query: str):
    results = ytmusic.search(query=query, filter="songs", limit=1)
    if not results:
        return None
    
    track = results[0]
    title = track.get('title', 'Unknown')
    artists_list = track.get('artists', [])
    artist = artists_list[0].get('name', 'Unknown') if artists_list else 'Unknown'
    album_dict = track.get('album')
    album = album_dict.get('name', '') if album_dict else ''
    
    return {"title": title, "artist": artist, "album": album}

@app.on_message((filters.audio | filters.document) & filters.private)
async def process_audio(client: Client, message: Message):
    if not message.audio and not (message.document and message.document.file_name.endswith(".mp3")):
        return

    status_msg = await message.reply_text("[~] Downloading audio stream...")
    file_path = await message.download()

    await status_msg.edit_text("[*] Computing acoustic fingerprint (Shazam Engine)...")
    
    try:
        out = await shazam.recognize(file_path)
        title = "Unknown"
        artist = "Unknown"
        album = ""
        engine_used = "Shazam"
        metadata_found = False

        if out and 'track' in out:
            metadata_found = True
            track_data = out['track']
            title = track_data.get('title', 'Unknown')
            artist = track_data.get('subtitle', 'Unknown')
            for section in track_data.get('sections', []):
                if section.get('type') == 'SONG':
                    for meta in section.get('metadata', []):
                        if meta.get('title') == 'Album':
                            album = meta.get('text')
        else:
            await status_msg.edit_text("[-] Shazam DB Miss. Engaging YouTube Music Engine...")
            await asyncio.sleep(1) 
            
            search_query = extract_heuristic_query(message)
            if search_query:
                yt_data = await asyncio.to_thread(fetch_ytmusic_metadata, search_query)
                if yt_data:
                    metadata_found = True
                    engine_used = "YouTube Music"
                    title = yt_data['title']
                    artist = yt_data['artist']
                    album = yt_data['album']

        if not metadata_found:
            pending_tasks[message.from_user.id] = file_path
            await status_msg.delete()
            await message.reply_text(
                "[-] All engines failed. Track unrecognized.\n\n[?] Please reply to this message with the exact metadata in this format:\n`Artist - Title`",
                reply_markup=ForceReply(selective=True)
            )
            return

        await status_msg.edit_text(f"[+] Injecting metadata binary ({engine_used}):\nArtist: {artist}\nTitle: {title}")

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
            caption=f"**Title:** {title}\n**Artist:** {artist}\n**Album:** {album if album else 'Unknown'}\n**Engine:** {engine_used}"
        )
        await status_msg.delete()

        if os.path.exists(new_file_path):
            os.remove(new_file_path)

    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception as e:
        await status_msg.edit_text(f"[-] Fault Exception: {str(e)}")
        if os.path.exists(file_path):
            os.remove(file_path)

@app.on_message(filters.reply & filters.text & filters.private)
async def manual_metadata_injection(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in pending_tasks:
        return

    file_path = pending_tasks[user_id]
    input_data = message.text.strip()
    
    if "-" not in input_data:
        await message.reply_text("[-] Invalid Syntax. Strict format required: `Artist - Title`.")
        return

    artist, title = [part.strip() for part in input_data.split("-", 1)]
    status_msg = await message.reply_text(f"[*] Executing manual injection:\nArtist: {artist}\nTitle: {title}")

    try:
        try:
            audio = EasyID3(file_path)
        except Exception:
            audio = MP3(file_path)
            if audio.tags is None:
                audio.add_tags()
            audio = EasyID3(file_path)

        audio['title'] = title
        audio['artist'] = artist
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
            caption=f"**Title:** {title}\n**Artist:** {artist}\n**Engine:** Manual Override"
        )
        
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception as e:
        await status_msg.edit_text(f"[-] Fault Exception: {str(e)}")
    finally:
        del pending_tasks[user_id]
        await status_msg.delete()
        if 'new_file_path' in locals() and os.path.exists(new_file_path):
            os.remove(new_file_path)
        elif os.path.exists(file_path):
            os.remove(file_path)

if __name__ == "__main__":
    app.run()