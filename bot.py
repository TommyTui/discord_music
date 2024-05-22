import random
import traceback

import discord
import yt_dlp
from bilibili_api import HEADERS
from bilibili_api import video
from bilibili_api.video import *
from discord import Intents
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('TOKEN')
intent = Intents.default()
intent.reactions = True
intent.voice_states = True
intent.messages = True
queue = asyncio.Queue()
bot = commands.Bot(command_prefix='!', intents=intent)


@bot.tree.command(description="摸摸")
async def pat(interaction: discord.Interaction):
    r = random.random()
    if r<0.97:
        await interaction.response.send_message("喵~")
    else:
        await interaction.response.send_message("摸摸你的")


@bot.tree.command(description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect(force=True)
        await interaction.response.send_message("Disconnected")
    else:
        await interaction.response.send_message("Not in any voice channel")


def is_url(query) -> bool:
    regex = re.compile(
        r'^(?:http|ftp)s?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, query) is not None


@bot.tree.command(description="Add a music to the queue")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    if not await ensure_voice(interaction):
        return
    try:
        if is_url(query):
            if 'bilibili' in query:
                bv = query.split('/')[4]
                await enqueue_bilibili(interaction, bv)
            elif 'youtube' in query:
                await enqueue_ytb(interaction, query, False)
            else:
                await interaction.followup.send("Unsupported URL")
        else:
            # search on ytb
            await enqueue_ytb(interaction, query, True)
    except Exception as e:
        traceback.print_exc()
        await interaction.followup.send("出问题了")


async def enqueue_bilibili(interaction: discord.Interaction, bv) -> None:
    # await interaction.response.defer()
    v = video.Video(bvid=bv)
    url = await v.get_download_url(page_index=0)
    detector = video.VideoDownloadURLDataDetecter(url)
    stream = detector.detect_best_streams(
        audio_accepted_qualities=[AudioQuality._64K, AudioQuality._132K, AudioQuality._192K])
    stream: List[AudioStreamDownloadURL] = [s for s in stream if isinstance(s, AudioStreamDownloadURL)]
    if not stream:
        await interaction.followup.send("找不到啊")
        return
    music = stream[0].url
    i = await v.get_info()
    data = Data.from_bili(i)

    header = f'User-Agent: {HEADERS["User-Agent"]}\r\nReferer: {HEADERS["Referer"]}\r\n'
    ffmpeg_options = {
        'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -headers "{header}"',
        'options': '-vn'
    }
    await queue.put((interaction, data, discord.FFmpegPCMAudio(music, **ffmpeg_options)))
    await interaction.followup.send(f"Added **{data.title}** to queue")


async def enqueue_ytb(interaction: discord.Interaction, url, search) -> None:
    # await interaction.response.defer()
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
        result = ytdl.extract_info(url=f"ytsearch:{url}", download=False)['entries']
        result = [r for r in result if r['duration'] < 1800]
        if not result:
            await interaction.followup.send("找不到啊")
            return
        i = result[0]
    else:
        i = ytdl.extract_info(url=url, download=False)
    data = Data.from_yt(i)
    ffmpeg_options = {
        'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }
    await queue.put((interaction, data, discord.FFmpegPCMAudio(i['url'], **ffmpeg_options)))
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
        try:
            print("wait", flush=True)
            interaction: discord.Interaction
            interaction, data, music = await queue.get()
            print("pop", flush=True)
            await interaction.channel.send(embed=create_embed(interaction, data))
            interaction.guild.voice_client.play(music)
            while interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
                await asyncio.sleep(2)
            if queue.empty() and interaction.guild.voice_client:
                await interaction.guild.voice_client.disconnect(force=True)
        except Exception as e:
            traceback.print_exc()


async def ensure_voice(interaction: discord.Interaction):
    try:
        if interaction.user.voice:
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(interaction.user.voice.channel)
            else:
                await interaction.user.voice.channel.connect(self_deaf=True, self_mute=True)
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
            await interaction.guild.voice_client.disconnect(force=True)
        await interaction.response.send_message("Skipped")
    else:
        await interaction.response.send_message("Not playing anything")


@bot.event
async def on_ready():
    await bot.tree.sync()
    # print "ready" in the console when the bot is ready to work
    print("ready", flush=True)


class Data:
    def __init__(self, title, duration, image):
        self.title = title
        self.duration = duration
        self.image = image

    def __str__(self):
        return self.title + " " + str(self.duration) + " " + self.image

    @classmethod
    def from_bili(cls, info):
        return cls(info['title'], info['duration'], info['pic'])

    @classmethod
    def from_yt(cls, info):
        return cls(info['title'], info['duration'], info['thumbnail'])


async def main():
    t1 = asyncio.create_task(_play())
    await bot.start(TOKEN)
    await t1


if __name__ == '__main__':
    asyncio.run(main())
