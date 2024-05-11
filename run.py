import asyncio
import os
from dotenv import load_dotenv

from typing import Optional

import discord
from discord.ext import commands
import youtube_dl
import datetime
import lqueue as lq

MY_GUILD = 1234859743634526229  # айдишник нашего сервера
# MY_GUILD = 612673564268560394  # айдишник моего сервера

load_dotenv()

# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ''

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
    'preferredquality': '192',
    'preferredcodec': 'mp3',
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'executable': 'ffmpeg.exe',
    'options': '-vn',
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        except:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{url}", download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class Pixel(commands.Bot):
    def __init__(
            self,
            *args,
            testing_guild_id: Optional[int] = None,
            # testing_guild_id: Optional[int] = MY_GUILD,
            **kwargs,
    ):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(command_prefix=commands.when_mentioned, *args, intents=intents, **kwargs)
        self.testing_guild_id = testing_guild_id

    async def setup_hook(self) -> None:

        # here, we are loading extensions prior to sync to ensure we are syncing interactions defined in those extensions.

        # for extension in self.initial_extensions:
        #     await self.load_extension(extension)

        # In overriding setup hook,
        # we can do things that require a bot prior to starting to process events from the websocket.
        # In this case, we are using this to ensure that once we are connected, we sync for the testing guild.
        # You should not do this for every guild or for global sync, those should only be synced when changes happen.
        if self.testing_guild_id:
            guild = discord.Object(self.testing_guild_id)
            # We'll copy in the global commands to test with:
            self.tree.copy_global_to(guild=guild)
            # followed by syncing to the testing guild.
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

        # This would also be a good place to connect to our database and
        # load anything that should be in memory prior to handling events.

    async def on_ready(self):
        print(f'Авторизован как {self.user} (Status: online)')
        print('------------------------')
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.listening, name='лютое музло'))


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.songs_queue = lq.Queue()
        self.loop_flag = False

    # ########################[JOIN BLOCK]#########################

    @commands.hybrid_command()
    async def join(self, ctx):
        """Joins a voice channel"""

        if ctx.message.author.voice:
            if not ctx.voice_client:
                await ctx.message.author.voice.channel.connect(reconnect=True)
            else:
                await ctx.voice_client.move_to(ctx.message.author.voice.channel)
        else:
            await ctx.reply('❗ Вы должны находиться в голосовом канале ❗')

    @commands.hybrid_command()
    async def disconnect(self, ctx):

        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.message.reply(f'🍺 Ушёл в запой вместе с \
    {ctx.message.author.mention} 🍺')
        else:
            await ctx.reply('Вы попытались разбудить бота,\
     но он в отключке 💤')

    # ########################[PLAY MUSIC BLOCK]#########################

    @commands.hybrid_command()
    async def add(self, ctx, url):
        source = await YTDLSource.from_url(url)

        URL = source.data['formats'][0]['url']
        name = source.data['title']
        time = str(datetime.timedelta(seconds=source.data['duration']))
        self.songs_queue.q_add([name, time, URL])
        embed = discord.Embed(description=f'Записываю [{name}]({url}) в очередь 📝',
                              colour=discord.Colour.red())
        await ctx.reply(embed=embed)

    def step_and_remove(self, voice_client):
        if self.loop_flag:
            self.songs_queue.q_add(self.songs_queue.get_value()[0])
        self.songs_queue.q_remove()
        asyncio.run(self.audio_player_task(voice_client))

    async def audio_player_task(self, voice_client):
        if not voice_client.is_playing() and self.songs_queue.get_value():
            url = self.songs_queue.get_value()[0][2]
            source = await YTDLSource.from_url(url)
            voice_client.play(source, after=lambda e: self.step_and_remove(voice_client))

    @commands.hybrid_command()
    async def play(self, ctx, url):
        await self.join(ctx)
        await self.add(ctx, url)
        voice_client = ctx.guild.voice_client
        await self.audio_player_task(voice_client)

    @commands.hybrid_command()
    async def loop(self, ctx):
        self.loop_flag = True
        await ctx.reply('Залуплено')

    @commands.hybrid_command()
    async def unloop(self, ctx):
        self.loop_flag = False
        await ctx.reply('Отлуплено')

    @commands.hybrid_command()
    async def queue(self, ctx):
        if len(self.songs_queue.get_value()) > 0:
            only_names_and_time_queue = []
            for i in self.songs_queue.get_value():
                name = i[0]
                if len(i[0]) > 30:
                    name = i[0][:30] + '...'
                only_names_and_time_queue.append(f'📀 `{name:<33}   {i[1]:>20}`\n')
            c = 0
            queue_of_queues = []
            while c < len(only_names_and_time_queue):
                queue_of_queues.append(only_names_and_time_queue[c:c + 10])
                c += 10

            embed = discord.Embed(title=f'ОЧЕРЕДЬ [LOOP: {self.loop_flag}]',
                                  description=''.join(queue_of_queues[0]),
                                  colour=discord.Colour.red())
            await ctx.send(embed=embed)

            for i in range(1, len(queue_of_queues)):
                embed = discord.Embed(description=''.join(queue_of_queues[i]),
                                      colour=discord.Colour.red())
                await ctx.send(embed=embed)
        else:
            await ctx.send('Очередь пуста 📄')

    @commands.hybrid_command()
    async def pause(self, ctx):
        voice = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if voice:
            voice.pause()
            await ctx.reply('Шо ты сделал? Порвал струну. Без неё играй!')

    @commands.hybrid_command()
    async def resume(self, ctx):
        voice = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if voice:
            if voice.is_paused():
                voice.resume()
                await ctx.reply('Поменял струну.')

    @commands.hybrid_command()
    async def skip(self, ctx):
        voice = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if voice:
            voice.stop()

    @commands.hybrid_command()
    async def clear(self, ctx):
        voice = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if voice:
            voice.stop()
            while not self.songs_queue.is_empty():
                self.songs_queue.q_remove()

    @commands.hybrid_command()
    async def remove(self, ctx, index):
        try:
            if len(self.songs_queue.get_value()) > 0:
                index = int(index) - 1
                if index >= 0:
                    d = self.songs_queue.q_rem_by_index(index)[0]
                    await ctx.reply(f'Вычеркнул из списка: {d}')
            else:
                await ctx.reply('Нечего удалять')
        except:
            await ctx.reply(f'Песни с таким индексом не существует')

    @commands.hybrid_command()
    async def volume(self, ctx, volume: int):
        """Changes the player's volume"""

        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send(f"Changed volume to {volume}%")


async def main():

    async with Pixel() as bot:

        @bot.hybrid_command()
        async def ping(ctx):
            await ctx.send(f'Задержка отклика бота: {round(bot.latency * 1000)}ms 🧠')

        await bot.add_cog(Music(bot))
        await bot.start(os.getenv('DISCORD_TOKEN', ''))


# For most use cases, after defining what needs to run, we can just tell asyncio to run it:
if __name__ == '__main__':
    asyncio.run(main())
