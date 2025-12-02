import random
import traceback

import discord
import validators
import yt_dlp
from bilibili_api import HEADERS
from bilibili_api import video
from bilibili_api.video import *
from discord import Intents
from discord.ext import commands
from dotenv import load_dotenv
import ctypes.util
from discord import opus

from db import *
from util import get_bv_and_p


def load_opus_lib():
    if opus.is_loaded():
        return

    # 1. Try auto-discovery (Works on Linux/Docker usually)
    opus_path = ctypes.util.find_library('opus')

    # 2. If not found, check specific paths for Mac/Linux
    if not opus_path:
        candidate_paths = [
            '/opt/homebrew/lib/libopus.dylib',  # Mac Apple Silicon
            '/usr/local/lib/libopus.dylib',  # Mac Intel
            '/usr/lib/x86_64-linux-gnu/libopus.so.0',  # Linux/Docker
        ]
        for path in candidate_paths:
            if os.path.exists(path):
                opus_path = path
                break

    # 3. Load it
    if opus_path:
        try:
            opus.load_opus(opus_path)
            print(f"✅ Loaded Opus from: {opus_path}")
        except Exception as e:
            print(f"⚠️ Found {opus_path} but failed to load: {e}")
    else:
        # On some Linux distros, it might be implicitly loaded, so we just warn
        print("⚠️ Could not find Opus library path explicitly. Voice might fail.")


load_opus_lib()

load_dotenv()
TOKEN = os.getenv('TOKEN')
intent = Intents.default()
intent.reactions = True
intent.voice_states = True
intent.messages = True
queue = None
bot = commands.Bot(command_prefix='!', intents=intent)


@bot.tree.command(description="摸摸")
async def pat(interaction: discord.Interaction):
    r = random.random()
    if r < 0.95:
        await interaction.response.send_message("喵~")
    else:
        await interaction.response.send_message("摸摸你的")


@bot.tree.command(description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect(force=False)
        await interaction.response.send_message("Disconnected")
        while not queue.empty():
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                break
    else:
        await interaction.response.send_message("Not in any voice channel")


@bot.tree.command(description="Add a music to the queue")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    if not await ensure_voice(interaction):
        return
    try:
        if validators.url(query) is True:
            if 'bilibili' in query:
                bv, pid = get_bv_and_p(query)
                await enqueue_bilibili(interaction, bv, pid)
            elif 'youtube' in query:
                await interaction.followup.send("Unsupported URL")
                # await enqueue_ytb(interaction, query, False)
            else:
                await interaction.followup.send("Unsupported")
        else:
            # search on ytb
            # await enqueue_ytb(interaction, query, True)
            await interaction.followup.send("Unsupported")
    except Exception as e:
        traceback.print_exc()
        await interaction.followup.send("出问题了")


async def enqueue_one(interaction: discord.Interaction, data):
    detector = video.VideoDownloadURLDataDetecter(data.url)
    stream = detector.detect_best_streams(
        audio_accepted_qualities=[AudioQuality._64K, AudioQuality._132K, AudioQuality._192K])
    stream: List[AudioStreamDownloadURL] = [s for s in stream if isinstance(s, AudioStreamDownloadURL)]
    if not stream:
        await interaction.followup.send("找不到啊")
        return

    data.url = stream[0].url
    await queue.put((interaction, data))
    await interaction.followup.send(f"Added **{data.title}** to queue")


async def enqueue_bilibili(interaction: discord.Interaction, bv, pid=None) -> None:
    v = video.Video(bvid=bv)
    info = await v.get_info()
    if pid is not None:
        url = await v.get_download_url(page_index=pid)
        await enqueue_one(interaction, Data.from_bili(info, url, False))
    else:
        pages = await v.get_pages()
        if len(pages) > 1:
            for page in await v.get_pages():
                cid = page['cid']
                url = await v.get_download_url(cid=cid)
                await enqueue_one(interaction, Data.from_bili(page, url, True, info['pic']))
        else:
            url = await v.get_download_url(page_index=0)
            await enqueue_one(interaction, Data.from_bili(info, url, False))


async def enqueue_ytb(interaction: discord.Interaction, url, search) -> None:
    ytdl_format_options = {
        'format': 'bestaudio/best',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
    }
    ytdl = yt_dlp.YoutubeDL(ytdl_format_options)
    if search:
        result = ytdl.extract_info(url=f"ytsearch:{url}, original mv, ost, high quality", download=False)['entries']
        result = [r for r in result if r['duration'] < 60 * 60 * 3]
        if not result:
            await interaction.followup.send("找不到啊")
            return
        i = result[0]
    else:
        i = ytdl.extract_info(url=url, download=False)
    data = Data.from_yt(i, i['url'])
    await queue.put((interaction, data))
    await interaction.followup.send(f"Added **{data.title}** to queue")


def create_embed(interaction: discord.Interaction, data):
    embed = discord.Embed(title="Now Playing", color=0xf1ebc0)
    embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon)
    embed.set_thumbnail(url=data.image)
    title = data.title
    if len(title) > 20:
        title = title[:20] + "..."
    embed.add_field(name="Title", value=title, inline=False)
    duration = str(datetime.timedelta(seconds=data.duration))
    embed.add_field(name="Duration", value=f'`{duration}`', inline=True)
    embed.add_field(name="Requested by", value=interaction.user.mention, inline=True)
    return embed


async def _play():
    while True:
        interaction: discord.Interaction
        interaction, data = await queue.get()
        try:
            await interaction.channel.send(embed=create_embed(interaction, data))
            music = get_bilibili(data) if data.type == 0 else get_youtube(data)
            interaction.guild.voice_client.play(music)
            while interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
                await asyncio.sleep(2)
            if queue.empty() and interaction.guild.voice_client:
                await interaction.guild.voice_client.disconnect(force=False)
            queue.task_done()
        except:
            traceback.print_exc()
            await interaction.followup.send("出问题了")


def get_bilibili(data):
    header = f'User-Agent: {HEADERS["User-Agent"]}\r\nReferer: {HEADERS["Referer"]}\r\n'
    ffmpeg_options = {
        'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -headers "{header}"',
        'options': '-vn -loglevel quiet'
    }
    return discord.FFmpegPCMAudio(data.url, **ffmpeg_options)


def get_youtube(data):
    ffmpeg_options = {
        'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn -loglevel quiet'
    }
    return discord.FFmpegPCMAudio(data.url, **ffmpeg_options)


async def ensure_voice(interaction: discord.Interaction):
    try:
        if interaction.user.voice:
            if interaction.guild.voice_client and interaction.guild.voice_client.channel != interaction.user.voice.channel:
                await interaction.guild.voice_client.disconnect(force=False)
            if not interaction.guild.voice_client:
                await interaction.user.voice.channel.connect(self_mute=True, self_deaf=True)
            return True
        else:
            await interaction.followup.send("You must be in a voice channel to use this command")
            return False
    except Exception as e:
        traceback.print_exc()
        await interaction.followup.send("出问题了")
        return False


@bot.tree.command(description="Skip the current next song")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        if queue.empty():
            await interaction.guild.voice_client.disconnect(force=False)
        await interaction.response.send_message("Skipped")
    else:
        await interaction.response.send_message("Not playing anything")


@bot.tree.command(description="Modify the playlist")
async def list(interaction: discord.Interaction, action: str, url: str):
    await interaction.response.defer()
    pid = None
    if 'bilibili' in url:
        processed_url, pid = get_bv_and_p(url)
        type = "0"
    elif 'youtube' in url and url.startswith("http"):
        processed_url = url
        type = "1"
    else:
        await interaction.followup.send("不要")
        return

    if action == "add":
        insert(processed_url, type, pid)
        await interaction.followup.send(f"Added {processed_url} to playlist")
    elif action == "delete":
        delete(processed_url, pid)
        await interaction.followup.send(f"Removed {processed_url} from playlist")
    elif action == "list":
        music_lst = list_all()
        await interaction.followup.send("\n".join([f"{m.url}{(' p=' + m.pid) if m.pid else ''}" for m in music_lst]))
    else:
        await interaction.followup.send("Invalid action")


@bot.tree.command(description="Play from playlist")
async def fav(interaction: discord.Interaction, count: int = None):
    await interaction.response.defer()
    if not await ensure_voice(interaction):
        return
    music_lst = random_music(count)
    for music in music_lst:
        if music.type == "0":
            await enqueue_bilibili(interaction, music.url, music.pid)
        elif music.type == "1":
            await enqueue_ytb(interaction, music.url, False)


@bot.event
async def on_ready():
    global queue
    # Initialize the queue here, ensuring it attaches to the CURRENT loop
    queue = asyncio.Queue()

    await bot.tree.sync()
    print("ready", flush=True)

    if not hasattr(bot, "play_task"):
        bot.play_task = asyncio.create_task(_play())


class Data:
    def __init__(self, type, title, duration, image, url):
        """
        :param type: 0 for bilibili, 1 for youtube
        """
        self.type = type
        self.title = title
        self.duration = duration
        self.image = image
        self.url = url

    def __str__(self):
        return self.title + " " + str(self.duration) + " " + self.image

    @classmethod
    def from_bili(cls, info, url, p, first=None):
        if p:
            if 'first_frame' in info:
                return cls(0, info['part'], info['duration'], info['first_frame'], url)
            else:
                return cls(0, info['part'], info['duration'], first, url)
        else:
            return cls(0, info['title'], info['duration'], info['pic'], url)

    @classmethod
    def from_yt(cls, info, url):
        return cls(1, info['title'], info['duration'], info['thumbnail'], url)


if __name__ == '__main__':
    bot.run(TOKEN, )
