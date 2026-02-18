import os
import asyncio
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, ForceReply
from pyrogram.errors import FloodWait
from shazamio import Shazam
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TDRC, APIC, USLT, ID3NoHeaderError
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

async def download_image(url: str) -> bytes:
    if not url:
        return b""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception:
        pass
    return b""

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
    video_id = track.get('videoId')
    title = track.get('title', 'Unknown')
    artists_list = track.get('artists', [])
    artist = artists_list[0].get('name', 'Unknown') if artists_list else 'Unknown'
    album_dict = track.get('album')
    album = album_dict.get('name', '') if album_dict else ''
    year = track.get('year', '')
    
    thumbnails = track.get('thumbnails', [])
    cover_url = thumbnails[-1].get('url') if thumbnails else ""
    
    # ------------------------------------------------------------
    # HQ Cover Resolution Patch: Overriding Google's compression
    # ------------------------------------------------------------
    if cover_url:
        if "=" in cover_url and ("lh3.googleusercontent.com" in cover_url or "yt3.ggpht.com" in cover_url):
            cover_url = cover_url.split("=")[0] + "=w1200-h1200-l90-rj"
        elif "i.ytimg.com" in cover_url:
            cover_url = cover_url.replace("hqdefault.jpg", "maxresdefault.jpg").replace("sddefault.jpg", "maxresdefault.jpg")
    
    lyrics_text = ""
    if video_id:
        try:
            watch_playlist = ytmusic.get_watch_playlist(videoId=video_id)
            lyrics_id = watch_playlist.get('lyrics')
            if lyrics_id:
                lyrics_data = ytmusic.get_lyrics(lyrics_id)
                lyrics_text = lyrics_data.get('lyrics', '')
        except Exception:
            pass
            
    return {
        "title": title,
        "artist": artist,
        "album": album,
        "year": year,
        "cover_url": cover_url,
        "lyrics": lyrics_text,
        "genre": ""
    }

def inject_metadata(file_path: str, meta: dict):
    try:
        audio = ID3(file_path)
    except ID3NoHeaderError:
        audio = ID3()

    audio.add(TIT2(encoding=3, text=meta.get('title', 'Unknown')))
    audio.add(TPE1(encoding=3, text=meta.get('artist', 'Unknown')))
    
    if meta.get('album'):
        audio.add(TALB(encoding=3, text=meta.get('album')))
    if meta.get('genre'):
        audio.add(TCON(encoding=3, text=meta.get('genre')))
    if meta.get('year'):
        audio.add(TDRC(encoding=3, text=str(meta.get('year'))))
    if meta.get('lyrics'):
        audio.add(USLT(encoding=3, lang='eng', desc='', text=meta.get('lyrics')))
    if meta.get('cover_bytes'):
        audio.add(APIC(
            encoding=3,
            mime='image/jpeg',
            type=3,
            desc='Cover',
            data=meta.get('cover_bytes')
        ))

    audio.save(file_path, v2_version=3)

@app.on_message((filters.audio | filters.document) & filters.private)
async def process_audio(client: Client, message: Message):
    if not message.audio and not (message.document and message.document.file_name.endswith(".mp3")):
        return

    status_msg = await message.reply_text("[~] Downloading audio stream...")
    raw_file_path = await message.download()

    await status_msg.edit_text("[*] Transcoding audio to pure MP3 format...")
    file_path = f"{raw_file_path}_pure.mp3"
    
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", raw_file_path, "-codec:a", "libmp3lame", "-q:a", "2", file_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await process.communicate()
    
    if process.returncode == 0 and os.path.exists(file_path):
        os.remove(raw_file_path)
    else:
        await status_msg.edit_text("[-] Critical: FFmpeg transcode failed.")
        if os.path.exists(raw_file_path):
            os.remove(raw_file_path)
        return

    await status_msg.edit_text("[*] Computing acoustic fingerprint (Shazam Engine)...")
    
    metadata = {}
    engine_used = ""
    
    try:
        out = await shazam.recognize(file_path)
        
        if out and 'track' in out:
            engine_used = "Shazam"
            track_data = out['track']
            metadata['title'] = track_data.get('title', 'Unknown')
            metadata['artist'] = track_data.get('subtitle', 'Unknown')
            metadata['genre'] = track_data.get('genres', {}).get('primary', '')
            metadata['cover_url'] = track_data.get('images', {}).get('coverarthq', '')
            
            for section in track_data.get('sections', []):
                if section.get('type') == 'SONG':
                    for meta in section.get('metadata', []):
                        if meta.get('title') == 'Album':
                            metadata['album'] = meta.get('text')
                        if meta.get('title') == 'Released':
                            metadata['year'] = meta.get('text')
                elif section.get('type') == 'LYRICS':
                    metadata['lyrics'] = "\n".join(section.get('text', []))
        else:
            await status_msg.edit_text("[-] Shazam DB Miss. Engaging YouTube Music Engine...")
            await asyncio.sleep(1) 
            
            search_query = extract_heuristic_query(message)
            if search_query:
                yt_data = await asyncio.to_thread(fetch_ytmusic_metadata, search_query)
                if yt_data:
                    engine_used = "YouTube Music"
                    metadata = yt_data

        if not metadata:
            pending_tasks[message.from_user.id] = file_path
            await status_msg.delete()
            await message.reply_text(
                "[-] All engines failed. Track unrecognized.\n\n[?] Please reply to this message with the exact metadata in this format:\n`Artist - Title`",
                reply_markup=ForceReply(selective=True)
            )
            return

        await status_msg.edit_text(f"[+] Injecting full metadata payload ({engine_used})...")
        
        if metadata.get('cover_url'):
            metadata['cover_bytes'] = await download_image(metadata['cover_url'])

        inject_metadata(file_path, metadata)

        title_str = metadata.get('title', 'Unknown')
        artist_str = metadata.get('artist', 'Unknown')
        safe_name = f"{artist_str} - {title_str}".replace('/', '_').replace('\\', '_') + ".mp3"
        new_file_path = os.path.join(os.path.dirname(file_path), safe_name)
        os.rename(file_path, new_file_path)

        await status_msg.edit_text("[^] Uploading modified payload...")
        
        await asyncio.sleep(1)
        
        caption_text = (
            f"**Title:** {title_str}\n"
            f"**Artist:** {artist_str}\n"
            f"**Album:** {metadata.get('album', 'Unknown')}\n"
            f"**Year:** {metadata.get('year', 'Unknown')}\n"
            f"**Genre:** {metadata.get('genre', 'Unknown')}\n"
            f"**Engine:** {engine_used}"
        )
        
        await message.reply_audio(
            audio=new_file_path,
            title=title_str,
            performer=artist_str,
            caption=caption_text
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
        inject_metadata(file_path, {"title": title, "artist": artist})

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