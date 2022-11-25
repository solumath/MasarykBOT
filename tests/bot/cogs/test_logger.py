import unittest
from datetime import datetime

import asyncpg
import inject
import discord

import tests.helpers as helpers
from bot.cogs import logger
import bot.db


class LoggerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = helpers.MockBot(guilds=[guild])
        self.cog = logger.Logger(self.bot)
        inject.clear_and_configure(self._setup_injections)


    async def test_backup(self) -> None:
        await self.cog.backup()

        self.assertEqual(1, inject.instance(bot.db.GuildRepository).insert.call_count) # type: ignore[attr-defined]
        self.assertEqual(2, inject.instance(bot.db.UserRepository).insert.call_count) # type: ignore[attr-defined]
        self.assertEqual(1, inject.instance(bot.db.RoleRepository).insert.call_count) # type: ignore[attr-defined]
        self.assertEqual(1, inject.instance(bot.db.EmojiRepository).insert.call_count) # type: ignore[attr-defined]
        self.assertEqual(1, inject.instance(bot.db.CategoryRepository).insert.call_count) # type: ignore[attr-defined]
        self.assertEqual(2, inject.instance(bot.db.ChannelRepository).insert.call_count) # type: ignore[attr-defined]
        self.assertEqual(2, inject.instance(bot.db.MessageRepository).insert.call_count) # type: ignore[attr-defined]
        self.assertEqual(1, inject.instance(bot.db.ReactionRepository).insert.call_count) # type: ignore[attr-defined]
        self.assertEqual(1, inject.instance(bot.db.AttachmentRepository).insert.call_count) # type: ignore[attr-defined]


    @staticmethod
    def _setup_injections(binder: inject.Binder) -> None:
        binder.bind(asyncpg.Pool, unittest.mock.MagicMock())

        for repository in bot.db.discord.REPOSITORIES:
            binder.bind(repository, unittest.mock.AsyncMock())

        for mapper in bot.db.discord.MAPPERS:
            binder.bind_to_constructor(mapper, mapper)

# ---- data ---- #

# guilds
guild = helpers.MockGuild(
    id=1123, 
    name='Large guild',
    icon=None,
    created_at=datetime(2022, 11, 10, 15, 33, 00),
)

# members
member1 = helpers.MockMember(
    id=2123,
    name='Will',
    avatar=None,
    bot=False,
    created_at=datetime(2010, 11, 10, 15, 33, 00),
    guild=guild
)  
member2 = helpers.MockMember(
    id=2456,
    name='BOT',
    avatar=None,
    bot=True,
    created_at=datetime(2010, 11, 10, 15, 33, 00),
    guild=guild
)
guild.members = [member1, member2]

# roles
role1 = helpers.MockRole(
    id=3123,
    name='Admin',
    color=discord.Color.yellow(),
    created_at=datetime(2010, 11, 10, 15, 33, 00),
    guild=guild
)
guild.roles = [role1]

# emojis
emoji1 = helpers.MockEmoji(
    id=4123,
    name='kek',
    animated=False,
    created_at=datetime(2010, 11, 10, 15, 33, 00),
    guild=guild
)
guild.emojis = [emoji1]

# channels
uncategories_channel = helpers.MockTextChannel(
    id=5123,
    name='uncategories',
    created_at=datetime(2010, 11, 10, 15, 33, 00),
    category=None,
    guild=guild
)
category = helpers.MockCategoryChannel(
    id=4123,
    name='mycategory',
    created_at=datetime(2010, 11, 10, 15, 33, 00),
    guild=guild
)
categorised_channel = helpers.MockTextChannel(
    id=5456,
    name='categorised',
    created_at=datetime(2010, 11, 10, 15, 33, 00),
    category=category,
    guild=guild
)
category.text_channels = [categorised_channel]
guild.text_channels = [uncategories_channel, categorised_channel]
guild.categories = [category]

# messages
message1 = helpers.MockMessage(
    id=6123,
    content="Hello",
    created_at=datetime(2010, 11, 10, 15, 33, 00),
    author=member1,
    channel=categorised_channel,
    guild=guild
)
message2 = helpers.MockMessage(
    id=6456,
    content="Oh, Hi",
    created_at=datetime(2010, 11, 10, 15, 33, 00),
    author=member2,
    channel=categorised_channel,
    guild=guild
)
categorised_channel.history = unittest.mock.MagicMock(return_value=helpers.AsyncIterator([message1, message2]))

# reactions
reaction1 = helpers.MockReaction(
    emoji=emoji1,
    message=message1,
    count=4
)
message1.reactions = [reaction1]

# attachments
attachment1 = helpers.MockAttachment(
    content_type='plain/text',
    filename='test.txt',
    url='http://google.com'
)
message1.attachments = [attachment1]