from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

import pandas as pd
from bot.cogs.utils import heatmap
from bot.cogs.utils.context import Context
from bot.db.activity import ActivityDao
from disnake import File, Member, TextChannel
from disnake.ext import commands
from matplotlib.cm import get_cmap


class Activity(commands.Cog):
    activityDao = ActivityDao()

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def activity(
        self,
        ctx: Context,
        member: Optional[Member] = None,
        channel: Optional[TextChannel] = None,
        color_map: str = "GitHub",
        past_days: int = 365
    ) -> None:
        """
        Show frequency of messages sent
        |past_days| <= 365
        """

        try:
            color_map = get_cmap(color_map)
        except ValueError:
            color_map = "GitHub"

        member_id = member.id if member else None
        channel_id = channel.id if channel else None

        past_days = max(1, min(abs(past_days), 365))
        past_days = 7 * round(past_days / 7)

        today = (datetime.now()
                         .replace(hour=0, minute=0, second=0, microsecond=0))
        tomorrow = today + timedelta(days=1)
        past = tomorrow - timedelta(days=past_days + tomorrow.weekday())

        rows = await self.activityDao.select((ctx.guild.id, channel_id, member_id, past, tomorrow))
        series = self.prepare_data(rows, from_date=past, to_date=today)

        fig = heatmap.generate_heatmap(series, color_map)

        with BytesIO() as buffer:
            fig.savefig(buffer, format="PNG", bbox_inches="tight", dpi=400)
            buffer.seek(0)
            await ctx.reply(file=File(buffer, filename=f"{member_id}_activity.png"))

    @staticmethod
    def prepare_data(data, from_date: datetime, to_date: datetime):
        data = pd.Series(dict(data))
        data.index = pd.DatetimeIndex(data.index)

        idx = pd.date_range(from_date, to_date)
        return data.reindex(idx, fill_value=0)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Activity(bot))
