import contextlib
from pathlib import Path
from typing import Dict, List, cast

import discord
import inject
from discord.app_commands import Choice
from discord.ext import commands
from discord.utils import get

from bot.constants import CONFIG
from bot.db import CourseRepository
from bot.db.muni.course import CourseEntity
from .course_service import CourseService
from ..utils import Context, GuildContext, requires_database


_reg_msg_path = Path(__file__).parent.parent.parent.joinpath('assets/course_registration_message.txt')
with open(_reg_msg_path, 'r') as file:
    COURSE_REGISTRATION_MESSAGE = file.read()


class NotInRegistrationChannel(commands.UserInputError):
    pass


def in_registration_channel():
    def predicate(ctx: Context) -> bool:
        assert isinstance(ctx.cog, CourseCog)
        if ctx.channel.id not in cast(CourseCog, ctx.cog).course_registration_channels:
            raise NotInRegistrationChannel(f"{ctx.channel.mention} is not a course registration channel")
        return True
    return commands.check(predicate)


class Course(commands.Converter, CourseEntity):
    @classmethod
    @inject.autoparams('course_repository')
    async def convert(cls, ctx: Context, argument: str, course_repository: CourseRepository = None) -> CourseEntity:
        faculty, code = argument.split(':', 1) if ':' in argument else ('FI', argument)
        if not (course := await course_repository.find_by_code(faculty, code)):
            raise commands.BadArgument(f'Course {argument} not found')
        return course



class CourseCog(commands.Cog):
    def __init__(self, bot: commands.Bot, subject_service: CourseService = None) -> None:
        self.bot = bot
        self._service = subject_service or CourseService(bot)
        self.course_registration_channels: Dict[int, discord.abc.Messageable] = {}


    @commands.Cog.listener()
    async def on_ready(self):
        self.course_registration_channels = self._service.load_course_registration_channels()
        await self._service.load_category_trie()


    @commands.hybrid_group(aliases=['subject'])
    @commands.guild_only()
    async def course(self, ctx: GuildContext) -> None:
        pass


    @course.command(aliases=['add', 'show'])
    @in_registration_channel()
    async def join(self, ctx: GuildContext, courses: commands.Greedy[Course]) -> None:
        if len(courses) > 10:
            raise commands.BadArgument('You can only join 10 courses with one command')
        for course in courses:
            status = await self._service.join_course(ctx.guild, ctx.author, course)
            match status:
                case status.REGISTERED: await ctx.send_success(f"Registered course {course.faculty}:{course.code}")
                case status.SHOWN: await ctx.send_success(f"Shown course {course.faculty}:{course.code}")


    @course.command(aliases=['remove', 'hide'])
    @in_registration_channel()
    async def leave(self, ctx: GuildContext, courses: commands.Greedy[Course]) -> None:
        if len(courses) > 10:
            raise commands.BadArgument('You can only leave 10 courses with one command, consider using `!course leave_all`')
        for course in courses:
            await self._service.leave_course(ctx.guild, ctx.author, course)
            await ctx.send(f'Left course {course.faculty}:{course.code}')


    @course.command()
    async def leave_all(self, ctx: GuildContext) -> None:
        await self._service.leave_all_courses(ctx.guild, ctx.author)


    @course.command()
    async def search(self, ctx: GuildContext, pattern: str) -> None:
        embed = await self._service.search_courses(pattern)
        await ctx.send(embed=embed)


    @course.command()
    async def find(self, ctx: GuildContext, course: Course) -> None:
        embed = await self._service.get_course_info(course)
        await ctx.send(embed=embed)


    @join.autocomplete('courses')
    @leave.autocomplete('courses')
    @find.autocomplete('course')
    async def course_autocomplete(self, _interaction: discord.Interaction, current: str) -> List[Choice[str]]:
        return [
            Choice(
                name=f"{subject.faculty}:{subject.code} {subject.name}"[:95],
                value=f"{subject.faculty}:{subject.code}"
            )
            for subject in await self._service.autocomplete(current)]


    @course.command()
    @commands.has_permissions(administrator=True)
    async def resend_subject_message(self, ctx: GuildContext) -> None:
        if not (channel := get(self.course_registration_channels.values(), guild__id=ctx.guild.id)):
            return

        embed = discord.Embed(description=COURSE_REGISTRATION_MESSAGE, color=CONFIG.colors.MUNI_YELLOW)
        embed.set_footer(text="👇 Zapiš si své předměty zde 👇")
        await channel.send(embed=embed)


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.channel.id not in self.course_registration_channels:
            return
        if message.embeds and message.embeds[0].description == COURSE_REGISTRATION_MESSAGE:
            return
        with contextlib.suppress(discord.errors.NotFound):
            await message.delete(delay=5.2 if message.embeds else 0.2)



@requires_database
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CourseCog(bot))



"""
from datetime import datetime
import logging
from collections import defaultdict
from contextlib import suppress
from re import sub
from textwrap import dedent
from typing import (Any, Dict, List, NoReturn, Optional, Text, Tuple, Union,
                    cast)

from bot.cogs.utils.context import Context, GuildChannel
from bot.constants import Config
from bot.db.categories import CategoryDao
from bot.db.channels import ChannelDao
from bot.db.subjects import SubjectDao
from bot.db.utils import Record
from disnake import (CategoryChannel, Color, Embed, Forbidden, HTTPException, Member,
                     Message, PermissionOverwrite, Role, TextChannel)
from disnake.errors import NotFound
from disnake.ext import commands
from disnake.ext.commands import has_permissions
from disnake.utils import find, get

log = logging.getLogger(__name__)

Id = int


DISCORD_CATEGORY_LIMIT = 50
ERR_EMBED_BODY_TOO_LONG = 50035
MAX_CHANNEL_OVERWRITES = 500
SUBJECT_MESSAGE = {
    "body": dedent("\""
        zde si můžete "zapsat" (zobrazit) místnost na tomto discordu pro daný předmět

        :warning: tento bot není nijak napojen na IS.MUNI
        :warning: předmět si můžeš zapsat/zrušit každých 5 sekund
        :information_source: lze zapsat až 10 předmetů najednou

        příkazem !course add/remove <faculty>:<subject_code>
        např.
        ```yaml
        !course add IB000
        !course remove IB000
        !course add FF:CJL09
        !course remove FF:CJL09
        ```
        na zobrazení seznamu předmětů které si můžeš přidat použij !course search <pattern>%
        např.
        ```yaml
        !course find IB000
        !course find IB0%
        ```
        pro odregistrování všech předmětů lze použít `!course remove all`

        Podporované fakulty:
        informatika (FI), filozofická (FF), sociálních studií (FSS), Sportovních studií (FSpS), Přírodovědecká (PřF), Právnická (PrF)
        "\"").strip(),
    "footer": "👇 Zapiš si své předměty zde 👇"\""
}



class ChannelNotFound(Exception):
    def __init__(self, course: str, searched: str, potential: Optional[TextChannel], *args: Any) -> None:
        super().__init__(self, *args)
        self.course = course
        self.searched = searched
        self.potential = potential

    def __str__(self) -> str:
        return (f"channel for course {self.course} not found. \n" +
                f"looked for {self.searched}. Did you mean {self.potential}?")



class Trie:
    def __init__(self):
        self.items = 0
        self.children = {}
        self.is_word = False

    def __repr__(self):
        return repr(self.children)

    def insert(self, word):
        letter, *rest = word
        word = ''.join(rest)

        self.children[letter] = self.children.get(letter, Trie())

        if word == "":
            self.children[letter].is_word = True
        else:
            self.children[letter].insert(word)

        self.items += 1

    def find(self, word):
        if word == "":
            return self.is_word

        if word[0] not in self.children:
            return False

        letter, *rest = word
        word = ''.join(rest)
        return self.children[letter].find(word)

    def generate_categories(self, limit, *, prefix=""):
        if self.items == 0:
            return []

        if self.items < limit:
            return [prefix]

        categories = []
        for letter, subtree in self.children.items():
            categories += subtree.generate_categories(limit, prefix=prefix + letter)
        return categories

    def find_category_for(self, word, limit):
        if not self.find(word):
            return None
        return self._find_category_for(word, limit)

    def _find_category_for(self, word, limit, *, prefix="", i=0):
        if self.items < limit:
            return prefix

        for letter, subtree in self.children.items():
            if word[i] == letter:
                return subtree._find_category_for(word, limit, prefix=prefix + letter, i=i+1)



class Subject(commands.Cog):
    subjectDao = SubjectDao()
    channelDao = ChannelDao()
    categoryDao = CategoryDao()


    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot



    @commands.group(name="course", aliases=["subjects"], invoke_without_command=True)
    async def course(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)



    @course.command(name="add")
    @commands.bot_has_permissions(manage_channels=True)
    async def add(self, ctx: Context, *subject_codes: str) -> None:
        "\""
        sign up to a course channel

        usage:
        !course add ib000 ib002
        !course add fi:ib000 ib002
        ""\"

        await ctx.safe_delete(delay=5)

        if len(subject_codes) > 10:
            await self.send_subject_embed(ctx, "can add max of 10 channels at once")
            return

        for subject_code in subject_codes:
            await self.add_subject(ctx, subject_code)



    async def add_subject(self, ctx: Context, code_pattern: str) -> None:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        if not await self._in_subject_channel(ctx):
            return

        faculty, code = self.pattern_to_faculty_code(code_pattern)

        log.info("User %s adding course %s:%s", ctx.author, faculty, code)

        if (course := await self.find_subject(code, faculty)) is None:
            await self.send_subject_embed(ctx, "Could not find one course matching the code")
            return

        await self.subjectDao.sign_user((ctx.guild.id, course["faculty"], course["code"], ctx.author.id))
        await self.try_to_sign_user_to_channel(ctx, course)



    @staticmethod
    def pattern_to_faculty_code(subject_code: str) -> Tuple[str, str]:
        if ":" in subject_code:
            faculty, code = subject_code.split(":", 1)
            return faculty, code
        return "FI", subject_code



    @staticmethod
    async def send_subject_embed(ctx: Context, message: str) -> Message:
        return await ctx.send_embed(message,
                             color=Config.colors.MUNI_YELLOW,
                             delete_after=10)



    async def _in_subject_channel(self, ctx: Context) -> bool:
        assert ctx.guild is not None, "ERROR: method can only run inside a guild"

        guild_config = get(Config.guilds, id = ctx.guild.id)
        assert guild_config is not None, "ERROR: missing guild_config"

        if ctx.channel.id != guild_config.channels.subject_registration:
            designated_channel = get(ctx.guild.text_channels, id=guild_config.channels.subject_registration)
            if designated_channel:
                await ctx.send_error("You can't add subjects here, use a designated channel: " + designated_channel.mention, delete_after=5)
            else:
                await ctx.send_error("You can't add subjects on this server", delete_after=5)
            return False
        return True



    @course.command(name="remove")
    @commands.bot_has_permissions(manage_channels=True)
    async def remove(self, ctx: Context, *subject_codes: str) -> None:
        "\""
        unsign from subjects you have signed up to

        usage:
        !course remove ib000 ib002
        !course remove fi:ib000 ib002
        !course remove all
        "\""

        await ctx.safe_delete(delay=5)

        if len(subject_codes) > 10:
            await self.send_subject_embed(ctx, "can remove max of 10 channels at once")
            return

        for subject_code in subject_codes:
            await self.remove_subject(ctx, subject_code)



    async def remove_subject(self, ctx: Context, code_pattern: str) -> None:
        assert ctx.guild is not None, "ERROR: method can only run inside a guild"

        if not await self._in_subject_channel(ctx):
            return

        if code_pattern == "all":
            await self.remove_all_subjects(ctx)
            return

        faculty, code = self.pattern_to_faculty_code(code_pattern)

        if not (course := await self.find_subject(code, faculty)):
            await self.send_subject_embed(ctx, "Could not find one course matching the code")
            return

        await self.subjectDao.unsign_user((ctx.guild.id, course["faculty"], course["code"], ctx.author.id))
        await self.try_to_unsign_user_from_channel(ctx, course)



    async def remove_all_subjects(self, ctx: Context) -> None:
        assert ctx.guild is not None, "ERROR: method can only run inside a guild"

        users_subjects = await self.subjectDao.find_users_subjects((ctx.guild.id, ctx.author.id))
        subject_names = [f'{course["faculty"]}:{course["code"]}' for course in users_subjects]

        if len(subject_names) == 0:
            await self.send_subject_embed(ctx, "you have no subjects to unsign from")
            return

        for subject_name in subject_names:
            faculty, code = self.pattern_to_faculty_code(subject_name)
            if not (course := await self.find_subject(code, faculty)):
                log.info(f"failed to find course {subject_name} during remove all")
                continue
            await self.try_to_unsign_user_from_channel(ctx, course)

        await self.subjectDao.unsign_user_from_all((ctx.guild.id, ctx.author.id))
        await self.send_subject_embed(ctx, "unsigned from all subjects: " + ", ".join(subject_names))



    @course.command(aliases=["search", "lookup"])    
    async def find(self, ctx: Context, subject_code: str) -> None:
        faculty, code = self.pattern_to_faculty_code(subject_code)

        subjects = await self.subjectDao.find((faculty, code))
        grouped_by_term = self.group_by_term(subjects)
        await self.display_list_of_subjects(ctx, grouped_by_term)



    @course.command()
    async def status(self, ctx: Context, subject_code: str) -> None:
        assert ctx.guild is not None, "ERROR: method can only run inside a guild"
        faculty, code = self.pattern_to_faculty_code(subject_code)

        if not (course := await self.find_subject(code, faculty)):
            await self.send_subject_embed(ctx, "Could not find one course matching the code")
            return

        registers = await self.subjectDao.find_registered((ctx.guild.id, faculty, code))
        num_registeres = len(registers['member_ids']) if registers is not None else 0
        await ctx.send_embed(f"Subject {course['faculty']}:{course['code']} has {num_registeres} registered")



    @course.command()
    @has_permissions(administrator=True)    
    async def resend_subject_message(self, ctx: Context, channel_id: int) -> None:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        guild_config = get(Config.guilds, id=ctx.guild.id)
        if guild_config is None:
            log.warn("guild configuration not found")
            return

        if channel_id != guild_config.channels.subject_registration:
            await ctx.send_error("channel not in constants")
            return

        menu_text_channel = self.bot.get_channel(channel_id)
        if not isinstance(menu_text_channel, TextChannel):
            return

        if not menu_text_channel:
            await ctx.send_error("channel does not exist")
            return

        embed = Embed(description=SUBJECT_MESSAGE['body'], color=Color(0xFFD800))
        embed.set_footer(text=SUBJECT_MESSAGE['footer'])
        await menu_text_channel.send(embed=embed)


    @course.command()
    @has_permissions(administrator=True)
    async def recover_database(self, ctx: Context) -> None:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if not (course := await self.get_subject_from_channel(channel)):
                    continue

                faculty = code = course["faculty"]
                code = course["code"]
                log.info("database recovery for course %s started (%s)", channel, guild)

                shown_to = [key.id
                            for (key, value) in channel.overwrites.items()
                            if value.read_messages and isinstance(key, Member)]

                await self.subjectDao.set_channel((ctx.guild.id, faculty, code, channel.id))
                if channel.category:
                    await self.subjectDao.set_category((ctx.guild.id, faculty, code, channel.category.id))

                for member_id in shown_to:
                    await self.subjectDao.sign_user((ctx.guild.id, faculty, code, member_id))
        log.info("database recovery finished")



    @course.command()
    @has_permissions(administrator=True)
    async def reorder(self, ctx: Context) -> None:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        subject_channels, subject_categories = await self._get_subject_channels_and_categories(ctx)
        tries = await self._build_category_tries(ctx)        
        new_categories = await self._create_categories_from_tries(ctx, tries)

        for channel in subject_channels:
            for faculty, trie in tries.items():
                category_name = trie.find_category_for(channel.name, DISCORD_CATEGORY_LIMIT)
                if category_name is None:
                    continue
                category_to_assign = get(new_categories, name=self.subject_to_category_name(faculty, category_name))
                if channel.category != category_to_assign:
                    try:
                        await channel.edit(category=category_to_assign)
                    except Forbidden as ex:
                        log.warn("Forbidden: {}", ex)
                        continue

        categories_to_remove = set(subject_categories) - set(new_categories)
        for category in categories_to_remove:
            await category.delete()

        for category in new_categories:
            if len(category.channels) == 0:
                await category.delete()
            else:
                await self._sort_category(category)

        log.info("reordering finished")
        await ctx.reply("reorder finished")



    async def _sort_category(self, category: CategoryChannel) -> None:
        channels = sorted(category.channels, key=lambda channel: channel.name)
        for i, channel in enumerate(channels):
            if channel.position == i:
                continue
            try:
                await channel.edit(position=i)
            except Forbidden as ex:
                log.warn("Forbidden: {}", ex)
                continue



    async def _get_subject_channels_and_categories(self, ctx: Context) -> Tuple[List[TextChannel], List[CategoryChannel]]:
        subject_channels = []
        subject_categories = set()
        for channel in ctx.guild.text_channels:
            if (await self.get_subject_from_channel(channel)) is not None:
                subject_channels.append(channel)
                if channel.category is not None:
                    subject_categories.add(channel.category)
        return (subject_channels, subject_categories)



    async def _build_category_tries(self, ctx: Context) -> Dict[str, Trie]:
        tries: Dict[str, Trie] = {}

        for course in await self.subjectDao.find_all_recent_for_faculty(("FI", datetime.now())):
            faculty = course['faculty']
            tries.setdefault(faculty, Trie())
            tries[faculty].insert(self.subject_to_channel_name(ctx, course))

        for channel in ctx.guild.text_channels:
            if (course := await self.get_subject_from_channel(channel)) is not None:
                faculty = course['faculty']
                tries.setdefault(faculty, Trie())
                tries[faculty].insert(channel.name)

        return tries



    async def _create_categories_from_tries(self, ctx: Context, tries: Dict[str, Trie]) -> List[CategoryChannel]:
        new_categories: List[CategoryChannel] = []
        for faculty, trie in tries.items():
            for category_name in trie.generate_categories(DISCORD_CATEGORY_LIMIT):
                category_name = self.subject_to_category_name(faculty, category_name)
                category = await self.create_or_get_category(ctx, category_name)
                new_categories.append(category)
        return new_categories



    async def reorder_channels(self) -> None:
        for guild in self.bot.guilds:
            for category in guild.categories:
                if ':' not in category.name:
                    continue

                ordered = sorted(category.text_channels, key=lambda c: c.name)
                if category.channels == ordered:
                    continue

                for i, channel in enumerate(ordered):
                    await channel.edit(position=i)



    async def get_subject_from_channel(self, channel: TextChannel) -> Optional[Record]:
        if "-" not in channel.name:
            return None

        pattern = channel.name.split("-")[0]
        faculty, code = pattern.split("꞉") if "꞉" in pattern else ["fi", pattern]

        return await self.find_subject(code, faculty)



    async def find_subject(self, code: str, faculty: str="FI") -> Optional[Record]:
        subjects = await self.subjectDao.find((faculty, code))
        if len(subjects) != 1:
            return None
        return subjects[0]



    async def try_to_sign_user_to_channel(self, ctx: Context, course: Record) -> None:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"
        assert isinstance(ctx.author, Member), "ERROR: user must part of a guild"

        channel_name = self.subject_to_channel_name(ctx, course)

        if not await self.check_if_engough_users_signed(ctx.guild.id, course):
            log.info("Not enough users signed for course %s", course)
            await self.send_subject_embed(ctx, f"Signed to course {channel_name} successfully, but not enough users to create the course room")
            return

        channel = await self.create_or_get_existing_channel(ctx, course)
        if role := get(channel.guild.roles, name=f"📖{course.get('code')}"):
            log.info("adding role %s to %s", str(role), ctx.author)
            await ctx.author.add_roles(role)

        elif len(channel.overwrites) < MAX_CHANNEL_OVERWRITES:
            log.info("adding permission overwrite to %s in %s", ctx.author, channel)
            await channel.set_permissions(ctx.author, overwrite=PermissionOverwrite(read_messages=True))

        else:
            await self._migrate_from_overwrites_to_role(course, channel, ctx.author)

        await self.send_subject_embed(ctx, f"Signed to course {channel_name} successfully")
        log.info("Signed user %s to channel %s", str(ctx.author), channel_name)

    async def _migrate_from_overwrites_to_role(self, course, channel: GuildChannel, user: Member):
        log.info("creating role instead of permission overwrite")
        role = await channel.guild.create_role(name=f"📖{course.get('code')}")

        for i, (key, overwrite) in enumerate(channel.overwrites.items()):
            if not isinstance(key, Member) or overwrite != PermissionOverwrite(read_messages=True):
                continue

            await key.add_roles(role)
            await channel.set_permissions(key, overwrite=None)

            if i == 10 or len(channel.overwrites) <= max(0, MAX_CHANNEL_OVERWRITES - 10):
                log.info('showing role')
                await channel.set_permissions(role, overwrite=PermissionOverwrite(read_messages=True))
                await user.add_roles(role)

        log.info('adding role overwrite')
        await channel.set_permissions(role, overwrite=PermissionOverwrite(read_messages=True))
        await user.add_roles(role)

    async def try_to_unsign_user_from_channel(self, ctx: Context, course: Record) -> None:
        assert isinstance(ctx.author, Member), "ERROR: user must part of a guild"

        try:
            channel = await self.lookup_channel_or_err(ctx, course)

            if role := get(channel.guild.roles, name=f"📖{course.get('code')}"):
                log.info("removing role %s to %s", str(role), ctx.author)
                await ctx.author.remove_roles(role)
            else:
                log.info("removing permission overwrite from %s in %s", ctx.author, channel)
                await channel.set_permissions(ctx.author, overwrite=None)

            await self.send_subject_embed(ctx, f"Unsigned from course {self.subject_to_channel_name(ctx, course)} successfully")

        except ChannelNotFound as err:
            await self.send_subject_embed(ctx, f"Channel {self.subject_to_channel_name(ctx, course)} does not exist")
            if err.potential is not None:
                raise err from None



    async def create_or_get_existing_channel(self, ctx: Context, course: Record) -> TextChannel:
        if (channel := await self.try_to_get_existing_channel(ctx, course)) is not None:
            return channel

        return await self.create_channel(ctx, course)



    async def try_to_get_existing_channel(self, ctx: Context, course: Record) -> Optional[TextChannel]:
        def is_subject_channel(channel: TextChannel) -> bool:
            faculty, code = course["faculty"].lower(), course["code"].lower()
            channel_prefix = channel.name.split("-", 1)[0]
            return (channel_prefix.lower() == code or
                    channel_prefix.lower() == f"{faculty}꞉{code}")

        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"
        channel = find(is_subject_channel, ctx.guild.text_channels)
        if channel is not None:
            await self.subjectDao.set_channel((ctx.guild.id, course["faculty"], course["code"], channel.id))
        return channel



    async def check_if_engough_users_signed(self, guild_id: int, course: Record) -> bool:
        registers = await self.subjectDao.find_registered((guild_id, course["faculty"], course["code"]))
        if registers is None:
            return False

        guild_config = get(Config.guilds, id=guild_id)
        if guild_config is None:
            log.warn("Missing guild_config for guild with id %d", guild_id)
            return False

        return len(registers["member_ids"]) >= cast(Id, guild_config.NEEDED_REACTIONS)



    async def lookup_channel_or_err(self, ctx: Context, course: Record) -> TextChannel:
        def is_subject_channel(channel: TextChannel) -> bool:
            faculty, code = course["faculty"].lower(), course["code"].lower()
            return (channel.name.lower().startswith(code+"-") or
                    channel.name.lower().startswith(f"{faculty}꞉{code}-"))

        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        channel = find(is_subject_channel, ctx.guild.text_channels)
        if channel is None:
            self.throw_not_found(ctx, course)

        return channel



    def throw_not_found(self, ctx: Context, course: Record) -> NoReturn:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        faculty = course['faculty']
        code = course['code']
        channel_name = self.subject_to_channel_name(ctx, course)
        potential = find(lambda channel: channel.name.lower().startswith(code.lower()), ctx.guild.text_channels)
        raise ChannelNotFound(course=f"{faculty}:{code}", searched=channel_name, potential=potential)



    @staticmethod
    def subject_to_channel_name(ctx: Context, course: Record) -> str:
        faculty = course["faculty"]
        code = course["code"]
        name = course["name"]
        if faculty == "FI":
            return ctx.channel_name(f'{code} {name}')
        return ctx.channel_name(f'{faculty}:{code} {name}')



    async def create_channel(self, ctx: Context, course: Record) -> TextChannel:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        guild_config = get(Config.guilds, id=ctx.guild.id)
        assert guild_config is not None, "ERROR: config for guild missing"

        channel_name = self.subject_to_channel_name(ctx, course)
        category = await self.assign_category(ctx, course)
        overwrites = self.get_overwrites_for_new_channel(ctx, guild_config)

        channel = await ctx.guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic="Místnost pro předmět " + course["name"]
        )

        await self._sort_category(category)

        data = await self.channelDao.prepare_one(channel)
        await self.channelDao.insert([data])

        await self.subjectDao.set_channel((ctx.guild.id, course["faculty"], course["code"], channel.id))
        if category:
            await self.subjectDao.set_category((ctx.guild.id, course["faculty"], course["code"], category.id))

        return channel



    def get_overwrites_for_new_channel(self, ctx: Context, guild_config: Config) -> Dict[Union[Member, Role], PermissionOverwrite]:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        overwrites: Dict[Union[Member, Role], PermissionOverwrite] = {
            ctx.guild.default_role: PermissionOverwrite(read_messages=False),
            ctx.guild.me: PermissionOverwrite(read_messages=True)
        }

        show_all = ctx.guild.get_role(cast(int, guild_config.roles.show_all))
        if show_all is not None:
            overwrites[show_all] = PermissionOverwrite(read_messages=True)

        muted = ctx.guild.get_role(cast(Id, guild_config.roles.muted))
        if muted is not None:
            overwrites[muted] = PermissionOverwrite(send_messages=False)

        return overwrites



    @staticmethod
    def subject_to_category_name(faculty: str, text: str):
        return f"{faculty}:{text:X<5}".upper()



    async def assign_category(self, ctx: Context, course: Record) -> CategoryChannel:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        tries = await self._build_category_tries(ctx)
        faculty_trie = tries[course['faculty']]

        faculty_categories = [category for category in ctx.guild.categories 
                              if category.name.startswith(course['faculty'])]

        channel_name = self.subject_to_channel_name(ctx, course)
        category_name = faculty_trie.find_category_for(channel_name, DISCORD_CATEGORY_LIMIT) or 'XXXXX'
        return get(faculty_categories, name=self.subject_to_category_name(course['faculty'], category_name))



    async def create_or_get_category(self, ctx: Context, name: str) -> CategoryChannel:
        assert ctx.guild is not None, "ERROR: this method can only be run inside a guild"

        if category := get(ctx.guild.categories, name=name):
            return category

        category = await ctx.guild.create_category(name)
        await self.categoryDao.insert(await self.categoryDao.prepare([category]))
        return category



    @staticmethod
    def group_by_term(subjects: List[Record]) -> Dict[str, List[Record]]:
        grouped_by_term = defaultdict(list)
        for course in subjects:
            for term in course["terms"]:
                grouped_by_term[term].append(course)
        return grouped_by_term



    async def display_list_of_subjects(self, ctx: Context, grouped_by_term: Dict[str, List[Record]]) -> None:
        def prepare(course: Record) -> str:
            faculty = course["faculty"]
            code = course["code"]
            name = course["name"]
            url = course["url"]
            return f"**[{faculty}:{code}]({url})** {name}"

        def by_term(term: str) -> Tuple[int, str]:
            semester, year = term.split()
            return (int(year), semester)

        embed = Embed(color=Config.colors.MUNI_YELLOW)
        if not grouped_by_term:
            embed.add_field(
                inline=False,
                name="No subjects found",
                value="you can add % to the beginning or the end to match a pattern")

        for term, subjects_in_term in sorted(grouped_by_term.items(), key=lambda x: by_term(x[0]), reverse=True):
            embed.add_field(
                inline=False,
                name=term,
                value="\n".join(prepare(course) for course in subjects_in_term))

        try:
            await ctx.send(embed=embed)
        except HTTPException as err:
            if err.code == ERR_EMBED_BODY_TOO_LONG:
                await ctx.send_error("Found too many results to display, please be more specific")
                return
            raise err



    @commands.Cog.listener()
    async def on_message(self, message: Message) -> None:
        if message.guild is None:
            return

        if (guild_config := get(Config.guilds, id = message.guild.id)) is None:
            return

        if message.channel.id != guild_config.channels.subject_registration:
            return

        if message.author.id == self.bot.user.id and message.embeds:
            embed = message.embeds[0]
            if embed.description == SUBJECT_MESSAGE['body']:
                return

            if isinstance(embed.color, Color) and embed.color.value == cast(int, Config.colors.MUNI_YELLOW):
                with suppress(NotFound):
                    await message.delete(delay=60)
                return

        with suppress(NotFound):
            await message.delete(delay=0.2)



    async def delete_messages_in_subject_channel(self, channel: TextChannel) -> None:        
        async for message in channel.history():
            if message.author.id == self.bot.user.id and message.embeds:
                if message.embeds[0].description == SUBJECT_MESSAGE['body']:
                    continue

            await message.delete()



    async def delete_messages_in_subject_channels(self) -> None:
        subject_registrations = [guild.channels.subject_registration for guild in Config.guilds]
        for channel_id in subject_registrations:
            if not (channel := self.bot.get_channel(channel_id)):
                continue

            if not isinstance(channel, TextChannel):
                continue

            await self.delete_messages_in_subject_channel(channel)


    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.delete_messages_in_subject_channels()



def setup(bot: commands.Bot) -> None:
    bot.add_cog(Subject(bot))
"""
