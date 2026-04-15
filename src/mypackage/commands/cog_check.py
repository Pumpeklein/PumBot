from discord.ext import commands

ALLOWED_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}

class UserManagementCog(commands.Cog):


    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context):

        if ctx.author.guild_permissions.administrator:
            return True


        if any(role.name in ALLOWED_ROLES for role in ctx.author.roles):
            return True


        await ctx.send("Du hast keine Berechtigung, diesen Befehl zu nutzen.")
        return False
