import logging

import discord

from channel.category.model import CategoryChannel
from channel.category.repository import CategoryChannelRepository
from sync.syncer import Syncer, Diff

log = logging.getLogger(__name__)


class CategoryChannelSyncer(Syncer[CategoryChannel]):
    """Synchronise the database with category channels in the cache."""

    name = "category_channel"

    def __init__(self, repository: CategoryChannelRepository):
        self.repository = repository

    async def _get_diff(self, guild: discord.Guild) -> Diff:
        """Return the difference of category channels between the cache of `guild` and the database."""
        log.debug("Getting the diff for category channels.")

        db_categories = set(await self.repository.find_all())
        guild_categories = {CategoryChannel.from_discord(category) for category in guild.categories}

        categories_to_create = guild_categories - db_categories
        categories_to_update = guild_categories - categories_to_create
        categories_to_delete = db_categories - guild_categories

        return Diff(categories_to_create, categories_to_update, categories_to_delete)

    async def _sync(self, diff: Diff[CategoryChannel]) -> None:
        """Synchronise the database with the category channels cache of `guild`."""
        log.debug("Syncing created categories...")
        for category in diff.created:
            await self.repository.create(category)

        log.debug("Syncing updated categories...")
        for category in diff.updated:
            await self.repository.update(category)

        log.debug("Syncing deleted categories...")
        for category in diff.deleted:
            await self.repository.delete(category.id)
