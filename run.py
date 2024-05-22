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
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
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
            **kwargs,
    ):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(command_prefix=commands.when_mentioned, *args, intents=intents, **kwargs)
        self.testing_guild_id = testing_guild_id

    async def setup_hook(self) -> None:

        if self.testing_guild_id:
            guild = discord.Object(self.testing_guild_id)

            # self.tree.clear_commands(guild=guild)

            # self.tree.copy_global_to(guild=guild)

            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        print(f'Авторизован как {self.user} (Status: online)')
        print('------------------------')
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.listening, name='музыку'))


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.songs_queue = lq.Queue()
        self.loop_flag = False

    # ########################[JOIN BLOCK]#########################

    @commands.hybrid_command()
    async def join(self, ctx):
        """Добавить бота в ваш голосовой канал"""

        if ctx.message.author.voice:
            flag = True

            if not ctx.voice_client:
                await ctx.message.author.voice.channel.connect(reconnect=True)
            else:
                if ctx.voice_client.channel == ctx.author.voice.channel:
                    flag = False
                else:
                    await ctx.voice_client.move_to(ctx.message.author.voice.channel)

            if flag:
                embed = discord.Embed(title='🎵 Активация',
                                      description=f'Бот присоединился к каналу {ctx.author.voice.channel.mention}',
                                      color=discord.Colour.blue(),
                                      timestamp=datetime.datetime.now())
                embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
                await ctx.reply(embed=embed)
        else:
            embed = discord.Embed(title='❗ Отказ',
                                  description='Вы должны находиться в голосовом канале',
                                  color=discord.Colour.brand_red(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def disconnect(self, ctx):
        """Отключить бота от голосового канала"""

        if ctx.voice_client:
            embed = discord.Embed(title='💤 Отключение',
                                  description=f'Бот отключен от канала {ctx.voice_client.channel.mention}',
                                  color=discord.Colour.dark_green(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)

            await ctx.voice_client.disconnect()
            await ctx.reply(embed=embed)
        else:
            embed = discord.Embed(title='❗ Отказ',
                                  description='Бот не подключен ни к одному голосовому каналу',
                                  color=discord.Colour.brand_red(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def stop(self, ctx):
        """Отключить бота и очистить очередь"""

        if ctx.voice_client:
            embed = discord.Embed(title='💤 Отключение',
                                  description=f'Бот отключен от канала {ctx.voice_client.channel.mention}',
                                  color=discord.Colour.dark_green(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)

            await ctx.voice_client.disconnect()
            await self._clear()
            await ctx.reply(embed=embed)
        else:
            embed = discord.Embed(title='❗ Отказ',
                                  description='Бот не подключен к голосовому каналу',
                                  color=discord.Colour.brand_red(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)

    # ########################[PLAY MUSIC BLOCK]#########################

    @commands.hybrid_command()
    async def add(self, ctx, url):
        """Добавить видео из Youtube по url или названию"""

        source = await YTDLSource.from_url(url)

        URL = source.data['formats'][0]['url']
        name = source.data['title']
        time = str(datetime.timedelta(seconds=source.data['duration']))
        link = source.data.get('webpage_url')
        self.songs_queue.q_add([name, time, URL, link])

        embed = discord.Embed(title='⚡️ Обновление очереди',
                              description=f'**Добавлено [{name}]({link})**',
                              color=discord.Colour.brand_green(),
                              timestamp=datetime.datetime.now())
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        await ctx.reply(embed=embed)

    def step_and_remove(self, voice_client, channel):
        if self.loop_flag:
            self.songs_queue.q_add(self.songs_queue.get_value()[0])
        self.songs_queue.q_remove()

        asyncio.run(self.audio_player_task(voice_client, channel))

    async def audio_player_task(self, voice_client, channel):
        if not voice_client.is_playing() and self.songs_queue.get_value():
            url = self.songs_queue.get_value()[0][2]

            source = await YTDLSource.from_url(url)
            try:
                voice_client.play(source, after=lambda e: self.step_and_remove(voice_client, channel))
            except Exception as e:
                print(f"Произошла ошибка: {type(e).__name__}")

            name = self.songs_queue.get_value()[0][0]
            time = self.songs_queue.get_value()[0][1]
            link = self.songs_queue.get_value()[0][3]

            embed = discord.Embed(title='🔥 Сейчас играет',
                                  description=f'**[{name}]({link})**',
                                  color=discord.Colour.blurple(),
                                  timestamp=datetime.datetime.now())
            embed.add_field(name='**Длительность**', value=f'{time}')

            asyncio.run_coroutine_threadsafe(self._track(channel, embed), self.bot.loop)

    @commands.hybrid_command()
    async def play(self, ctx, url):
        """Включить видео из Youtube по url или названию"""

        await self.join(ctx)
        await self.add(ctx, url)
        await self.audio_player_task(ctx.guild.voice_client, ctx.channel)

    @commands.hybrid_command()
    async def loop(self, ctx):
        """Включить повтор"""

        self.loop_flag = True

        embed = discord.Embed(title='⚡️ Параметры очереди',
                              description=f'**`Включено` повторение всей очереди**',
                              color=discord.Colour.brand_green(),
                              timestamp=datetime.datetime.now())
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def unloop(self, ctx):
        """Отключить повтор"""

        self.loop_flag = False

        embed = discord.Embed(title='⚡️ Параметры очереди',
                              description=f'**`Отключено` повторение всей очереди**',
                              color=discord.Colour.brand_red(),
                              timestamp=datetime.datetime.now())
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        await ctx.reply(embed=embed)

    @staticmethod
    async def _track(channel, embed):
        await channel.send(embed=embed)

    @commands.hybrid_command()
    async def track(self, ctx):
        """Информация о текущем треке"""

        voice = ctx.guild.voice_client
        if voice:
            if voice.is_playing():
                name = self.songs_queue.get_value()[0][0]
                time = self.songs_queue.get_value()[0][1]
                link = self.songs_queue.get_value()[0][3]

                embed = discord.Embed(title='🔥 Сейчас играет',
                                      description=f'**[{name}]({link})**',
                                      color=discord.Colour.blurple(),
                                      timestamp=datetime.datetime.now())
                embed.add_field(name='**Длительность**', value=f'{time}')
                embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
                await ctx.send(embed=embed)
            else:
                embed = discord.Embed(title='❗ Бот ничего не воспроизводит',
                                      color=discord.Colour.brand_red(),
                                      timestamp=datetime.datetime.now())
                embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
                await ctx.reply(embed=embed)
        else:
            embed = discord.Embed(title='❗ Отказ',
                                  description='Бот не подключен к голосовому каналу',
                                  color=discord.Colour.brand_red(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def queue(self, ctx):
        """Очередь треков"""

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

            embed = discord.Embed(title=f"🧾 Очередь треков [Повтор: {'**Включен**' if self.loop_flag else '**Отключен**'}]",
                                  description=''.join(queue_of_queues[0]),
                                  colour=discord.Colour.gold())
            await ctx.send(embed=embed)

            for i in range(1, len(queue_of_queues)):
                embed = discord.Embed(description=''.join(queue_of_queues[i]),
                                      colour=discord.Colour.gold())
                await ctx.send(embed=embed)
        else:
            embed = discord.Embed(title=f"🧾 Очередь треков [Повтор: {'**Включен**' if self.loop_flag else '**Отключен**'}]",
                                  description='**Пусто**',
                                  colour=discord.Colour.gold())
            await ctx.send(embed=embed)

    @commands.hybrid_command()
    async def pause(self, ctx):
        """Пауза"""

        voice = ctx.guild.voice_client
        if voice:
            voice.pause()

            embed = discord.Embed(title='⚡️ Пауза',
                                  color=discord.Colour.brand_green(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)
        else:
            embed = discord.Embed(title='❗ Отказ',
                                  description='Бот не подключен к голосовому каналу',
                                  color=discord.Colour.brand_red(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def resume(self, ctx):
        """Снять с паузы"""

        voice = ctx.guild.voice_client
        if voice:
            if not voice.is_playing() and not self.songs_queue.is_empty():
                if voice.is_paused():
                    voice.resume()
                else:
                    await self.audio_player_task(ctx.guild.voice_client, ctx.channel)

                embed = discord.Embed(title='⚡️ Снят с паузы',
                                      color=discord.Colour.brand_green(),
                                      timestamp=datetime.datetime.now())
                embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
                await ctx.reply(embed=embed)
            else:
                embed = discord.Embed(title='❗ Очередь пуста',
                                      color=discord.Colour.brand_red(),
                                      timestamp=datetime.datetime.now())
                embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
                await ctx.reply(embed=embed)
        else:
            if not self.songs_queue.is_empty():
                await self.join(ctx)
                await self.audio_player_task(ctx.guild.voice_client, ctx.channel)
            else:
                embed = discord.Embed(title='❗ Очередь пуста',
                                      color=discord.Colour.brand_red(),
                                      timestamp=datetime.datetime.now())
                embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
                await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def skip(self, ctx):
        """Пропустить трек"""

        voice = ctx.guild.voice_client
        if voice:
            voice.stop()

            embed = discord.Embed(title='⚡️ Пропущен текущий трек',
                                  color=discord.Colour.brand_green(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)

    async def _clear(self):
        while not self.songs_queue.is_empty():
            self.songs_queue.q_remove()

    @commands.hybrid_command()
    async def clear(self, ctx):
        """Очистить очередь"""

        voice = ctx.guild.voice_client
        if voice:
            voice.stop()

        await self._clear()

        embed = discord.Embed(title='⚡️ Очередь очищена',
                              color=discord.Colour.brand_green(),
                              timestamp=datetime.datetime.now())
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def remove(self, ctx, index):
        """Удалить трек по номеру в очереди"""

        try:
            if len(self.songs_queue.get_value()) > 0:
                index = int(index) - 1
                if index >= 0:
                    track = self.songs_queue.q_rem_by_index(index)
                    name = track[0]
                    link = track[3]

                    embed = discord.Embed(title='⛔️ Удаление из очереди',
                                          description=f'**[{name}]({link})**',
                                          color=discord.Colour.brand_green(),
                                          timestamp=datetime.datetime.now())
                    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
                    await ctx.reply(embed=embed)
            else:
                embed = discord.Embed(title='⚡️ Очередь пуста',
                                      color=discord.Colour.brand_green(),
                                      timestamp=datetime.datetime.now())
                embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
                await ctx.reply(embed=embed)
        except:
            embed = discord.Embed(title='❗ Песни с таким индексом не существует',
                                  color=discord.Colour.brand_red(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def volume(self, ctx, volume: int):
        """Изменить громкость бота"""

        if ctx.voice_client is None:
            embed = discord.Embed(title='❗ Отказ',
                                  description='Бот не подключен ни к одному голосовому каналу',
                                  color=discord.Colour.brand_red(),
                                  timestamp=datetime.datetime.now())
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            return await ctx.reply(embed=embed)

        ctx.voice_client.source.volume = volume / 100

        embed = discord.Embed(title=f'⚡️ Громкость бота установлена на {volume}%',
                              color=discord.Colour.dark_blue(),
                              timestamp=datetime.datetime.now())
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def ping(self, ctx):
        """Узнать задержку бота"""

        await ctx.send(f'Задержка отклика бота: {round(self.bot.latency * 1000)}ms 🧠')


async def main():

    async with Pixel() as bot:

        await bot.add_cog(Music(bot))
        await bot.start(os.getenv('DISCORD_TOKEN', ''))


# For most use cases, after defining what needs to run, we can just tell asyncio to run it:
if __name__ == '__main__':
    asyncio.run(main())
