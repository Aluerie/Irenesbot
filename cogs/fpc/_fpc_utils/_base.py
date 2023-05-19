from __future__ import annotations

from difflib import get_close_matches
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

from utils import AluContext
from utils.const import Emote, MaterialPalette
from utils.pagination import EnumeratedPages

if TYPE_CHECKING:
    from utils import AluBot


class FPCBase:
    """Base class for cogs representing FPC (Favourite Player+Character) feature
    for different games:

    * Dota 2
    * League of Legends
    * and probably more to come.

    Since many base features can be generalized -
    here is the base class containing base methods.
    """

    def __init__(
        self,
        /,
        *,
        feature_name: str,
        game_name: str,
        game_codeword: str,
        game_logo: str,
        colour: discord.Colour,
        bot: AluBot,
        players_table: str,
        accounts_table: str,
        channel_id_column: str,
        players_column: str,
        characters_column: str,
        spoil_column: str,
        acc_info_columns: List[str],
        get_char_name_by_id: Callable[[int], Awaitable[str]],
        get_char_id_by_name: Callable[[str], Awaitable[int]],
        get_all_character_names: Callable[[], Awaitable[List[str]]],
        character_gather_word: str,
    ) -> None:
        self.feature_name: str = feature_name
        self.game_name: str = game_name
        self.game_codeword: str = game_codeword
        self.game_logo: str = game_logo
        self.colour: discord.Colour = colour
        self.bot: AluBot = bot
        self.players_table: str = players_table
        self.accounts_table: str = accounts_table
        self.channel_id_column: str = channel_id_column
        self.players_column: str = players_column
        self.characters_column: str = characters_column
        self.spoil_column: str = spoil_column
        self.acc_info_columns: List[str] = acc_info_columns
        self.get_char_name_by_id: Callable[[int], Awaitable[str]] = get_char_name_by_id
        self.get_char_id_by_name: Callable[[str], Awaitable[int]] = get_char_id_by_name
        self.get_all_character_names: Callable[[], Awaitable[List[str]]] = get_all_character_names
        self.character_gather_word: str = character_gather_word

    async def channel_set(
        self,
        ctx: AluContext | discord.Interaction[AluBot],
        channel: Optional[discord.TextChannel],
    ) -> None:
        """Base function for setting channel for FPC Feed feature"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        ch = channel or ctx.channel
        if not ch.permissions_for(ctx.guild.me).send_messages:
            raise commands.BotMissingPermissions(['I do not have permission to `send_messages` in that channel'])

        query = f'UPDATE guilds SET {self.channel_id_column}=$1 WHERE id=$2'
        await ctx.client.pool.execute(query, ch.id, ctx.guild.id)
        e = discord.Embed(colour=self.colour)
        e.description = f'Channel {ch.mention} is set to be the {self.feature_name} channel for this server'
        await ctx.reply(embed=e)

    async def channel_disable(
        self,
        ctx: AluContext | discord.Interaction[AluBot],
    ) -> None:
        """Base function for disabling channel for FPC Feed feature"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        query = f'SELECT {self.channel_id_column} FROM guilds WHERE id=$1'
        ch_id = await ctx.client.pool.fetchval(query, ctx.guild.id)

        if (ch := ctx.client.get_channel(ch_id)) is None:
            raise commands.BadArgument(f'{self.feature_name} channel is not set or already was reset')
        query = f'UPDATE guilds SET {self.channel_id_column}=NULL WHERE id=$1'
        await ctx.client.pool.execute(query, ctx.guild.id)
        e = discord.Embed(colour=self.colour)
        e.description = f'Channel {ch.mention} is no longer the {self.feature_name} channel.'
        await ctx.reply(embed=e)

    async def channel_check(
        self,
        ctx: AluContext | discord.Interaction[AluBot],
    ) -> None:
        """Base function for checking if channel is set for FPC Feed feature"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        query = f'SELECT {self.channel_id_column} FROM guilds WHERE id=$1'
        ch_id = await ctx.client.pool.fetchval(query, ctx.guild.id)

        if (ch := ctx.client.get_channel(ch_id)) is None:
            e = discord.Embed(colour=self.colour)
            e.description = f'{self.feature_name} channel is not currently set.'
        else:
            e = discord.Embed(colour=self.colour)
            e.description = f'{self.feature_name} channel is currently set to {ch.mention}.'
        await ctx.reply(embed=e)

    @staticmethod
    def player_name_string(display_name: str, twitch: Union[int, None]) -> str:
        if twitch:
            return f"\N{BLACK CIRCLE} [{display_name}](https://www.twitch.tv/{display_name})"
        else:
            return f"\N{BLACK CIRCLE} {display_name}"

    @staticmethod
    def cmd_usage_str(**kwargs):
        raise NotImplementedError

    @staticmethod
    def player_acc_string(**kwargs) -> str:
        raise NotImplementedError

    def player_name_acc_string(self, display_name: str, twitch_id: Union[int, None], **kwargs) -> str:
        return f'{self.player_name_string(display_name, twitch_id)}\n' f'{self.player_acc_string(**kwargs)}'

    async def database_list(self, ctx: AluContext | discord.Interaction[AluBot]) -> None:
        """Base function for sending database list embed"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        await ctx.typing()

        query = f'SELECT {self.players_column} FROM guilds WHERE id=$1'
        fav_player_id_list = await ctx.client.pool.fetchval(query, ctx.guild.id)

        query = f"""SELECT {', '.join(['player_id', 'display_name', 'twitch_id', 'a.id'] + self.acc_info_columns)}
                    FROM {self.players_table} p
                    JOIN {self.accounts_table} a
                    ON p.id = a.player_id
                    ORDER BY {'display_name'} 
                """
        rows = await ctx.client.pool.fetch(query) or []

        player_dict = dict()

        for row in rows:
            if row.player_id not in player_dict:
                followed = ' {0} {0} {0}'.format(Emote.DankLove) if row.player_id in fav_player_id_list else ''
                player_dict[row.player_id] = {
                    'name': f"{self.player_name_string(row.display_name, row.twitch_id)}{followed}",
                    'info': [],
                }
            kwargs = {col: row[col] for col in ['id'] + self.acc_info_columns}
            player_dict[row.player_id]['info'].append(self.player_acc_string(**kwargs))

        ans_array = [f"{v['name']}\n{chr(10).join(v['info'])}" for v in player_dict.values()]

        pgs = EnumeratedPages(
            ctx,
            ans_array,
            per_page=10,
            no_enumeration=True,
            colour=self.colour,
            title=f"List of {self.game_name} players in Database",
            footer_text=f'With love, {ctx.guild.me.display_name}',
        )
        await pgs.start()

    async def get_player_dict(self, *, name_flag: str, twitch_flag: bool) -> dict:
        name_lower = name_flag.lower()
        if twitch_flag:
            twitch_id, display_name = await self.bot.twitch.twitch_id_and_display_name_by_login(name_lower)
        else:
            twitch_id, display_name = None, name_flag

        return {'name_lower': name_lower, 'display_name': display_name, 'twitch_id': twitch_id}

    async def get_account_dict(self, **kwargs) -> dict:
        ...

    async def check_if_already_in_database(self, account_dict: dict):
        query = f""" SELECT display_name, name_lower
                    FROM {self.players_table} 
                    WHERE id =(
                        SELECT player_id
                        FROM {self.accounts_table}
                        WHERE id=$1
                    )
                """
        user = await self.bot.pool.fetchrow(query, account_dict['id'])
        if user is not None:
            raise commands.BadArgument(
                'This steam account is already in the database.\n'
                f'It is marked as {user.display_name}\'s account.\n\n'
                f'Did you mean to use `/dota player add {user.name_lower}` to add the stream into your fav list?'
            )

    async def database_add(self, ctx: AluContext | discord.Interaction[AluBot], player_dict: dict, account_dict: dict):
        """Base function for adding accounts into the database"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        await ctx.typing()
        await self.check_if_already_in_database(account_dict)

        query = f"""WITH e AS (
                        INSERT INTO {self.players_table}
                            (name_lower, display_name, twitch_id)
                                VALUES ($1, $2, $3)
                            ON CONFLICT DO NOTHING
                            RETURNING id
                    )
                    SELECT * FROM e
                    UNION 
                        SELECT {'id'} FROM {self.players_table} WHERE {'name_lower'}=$1
                """
        player_id = await ctx.client.pool.fetchval(query, *player_dict.values())
        dollars = [f'${i}' for i in range(1, len(self.acc_info_columns) + 3)]  # [$1, $2, ... ]
        query = f"""INSERT INTO {self.accounts_table}
                    (player_id, id, {', '.join(self.acc_info_columns)})
                    VALUES {'('}{', '.join(dollars)}{')'}
                """
        await ctx.client.pool.execute(query, player_id, *account_dict.values())
        e = discord.Embed(colour=self.colour)
        e.add_field(
            name=f'Successfully added the account to the database',
            value=self.player_name_acc_string(player_dict['display_name'], player_dict['twitch_id'], **account_dict),
        )
        e.set_footer(text=self.game_name, icon_url=self.game_logo)
        await ctx.reply(embed=e)
        e.colour = MaterialPalette.green(shade=200)
        e.set_author(name=ctx.author, icon_url=ctx.author.display_avatar.url)
        await self.bot.hideout.global_logs.send(embed=e)

    async def database_request(
        self,
        ctx: AluContext | discord.Interaction[AluBot],
        player_dict: dict,
        account_dict: dict,
    ) -> None:
        """Base function for requesting to add accounts into the database"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        await ctx.typing()
        await self.check_if_already_in_database(account_dict)

        player_string = self.player_name_acc_string(
            player_dict['display_name'], player_dict['twitch_id'], **account_dict
        )
        warn_e = discord.Embed(colour=self.colour, title='Confirmation Prompt')
        warn_e.description = (
            'Are you sure you want to request this streamer steam account to be added into the database?\n'
            'This information will be sent to Aluerie. Please, double check before confirming.'
        )
        warn_e.add_field(name='Request to add an account into the database', value=player_string)
        warn_e.set_footer(text=self.game_name, icon_url=self.game_logo)
        if not await ctx.prompt(embed=warn_e):
            await ctx.reply('Aborting...', delete_after=5.0)
            return

        e = discord.Embed(colour=self.colour)
        e.add_field(name='Successfully made a request to add the account into the database', value=player_string)
        await ctx.reply(embed=e)

        warn_e.colour = MaterialPalette.orange(shade=200)
        warn_e.title = ''
        warn_e.description = ''
        warn_e.set_author(name=ctx.user, icon_url=ctx.user.display_avatar.url)
        # cmd_str = ' '.join(f'{k}: {v}' for k, v in flags.__dict__.items())
        # warn_em.add_field(name='Command', value=f'`$dota stream add {cmd_str}`', inline=False)
        cmd_usage_str = f"name: {player_dict['display_name']} {self.cmd_usage_str(**account_dict)}"
        warn_e.add_field(name='Command', value=f'{self.game_codeword} player add {cmd_usage_str}')
        await self.bot.hideout.global_logs.send(embed=warn_e)

    async def database_remove(
        self,
        ctx: AluContext | discord.Interaction[AluBot],
        name_lower: Optional[str],
        account_id: Optional[Union[str, int]],  # steam_id for dota, something else for lol
    ) -> None:
        """Base function for removing accounts from the database"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        await ctx.typing()
        if name_lower is None and account_id is None:
            raise commands.BadArgument('You need to provide at least one of flags: `name`, `steam`')

        if account_id:
            if name_lower:  # check for both name_lower and account_id
                query = f"""SELECT a.id 
                            FROM {self.players_table} p
                            JOIN {self.accounts_table} a
                            ON p.id = a.player_id
                            WHERE a.id=$1 AND p.name_lower=$2
                        """
                val = await ctx.client.pool.fetchval(query, account_id, name_lower)
                if val is None:
                    raise commands.BadArgument(
                        'This account either is not in the database ' 'or does not belong to the said player'
                    )

            # query for account only
            query = f"""WITH del_child AS (
                            DELETE FROM {self.accounts_table}
                            WHERE  id = $1
                            RETURNING player_id, id
                            )
                        DELETE FROM {self.players_table} p
                        USING  del_child x
                        WHERE  p.id = x.player_id
                        AND    NOT EXISTS (
                            SELECT 1
                            FROM   {self.accounts_table} c
                            WHERE  c.player_id = x.player_id
                            AND    c.id <> x.id
                            )
                        RETURNING display_name
                    """
            ans_name = await ctx.client.pool.fetchval(query, account_id)
            if ans_name is None:
                raise commands.BadArgument('There is no account with such account details')
        else:
            # query for name_lower only
            query = f"""DELETE FROM {self.players_table}
                        WHERE name_lower=$1
                        RETURNING display_name
                    """
            ans_name = await ctx.client.pool.fetchval(query, name_lower)
            if ans_name is None:
                raise commands.BadArgument('There is no account with such player name')

        e = discord.Embed(colour=self.colour)
        e.add_field(
            name='Successfully removed account(-s) from the database',
            value=f'{ans_name}{" - " + str(account_id) if account_id else ""}',
        )
        e.set_footer(text=self.game_name, icon_url=self.game_logo)
        await ctx.reply(embed=e)

    @staticmethod
    def construct_the_embed(
        s_names: List[str], a_names: List[str], f_names: List[str], *, gather_word: str, mode_add: bool
    ) -> discord.Embed:
        e = discord.Embed()
        if s_names:
            e.colour = MaterialPalette.green(shade=500)
            e.add_field(
                name=f"Success: {gather_word} were {'added to' if mode_add else 'removed from'} your list",
                value=f"`{', '.join(s_names)}`",
                inline=False,
            )
        if a_names:
            e.colour = MaterialPalette.orange(shade=500)
            e.add_field(
                name=f'Already: {gather_word} are already {"" if mode_add else "not"} in your list',
                value=f"`{', '.join(a_names)}`",
                inline=False,
            )
        if f_names:
            e.colour = MaterialPalette.red(shade=500)
            e.add_field(
                name=f'Fail: These {gather_word} are not in the database', value=f"`{', '.join(f_names)}`", inline=False
            )
        return e

    @staticmethod
    def get_names_list_from_locals(
        ctx: AluContext | discord.Interaction[AluBot],
        local_dict: Dict[str, Any],
    ) -> List[str]:
        if isinstance(ctx, discord.Interaction):
            # if it's interaction then locals is dictionary with keys
            # "cog(self), ntr, name1, name2, ..." where each name is a string
            # meaning we only need [2:]
            names = list(dict.fromkeys([name for name in list(local_dict.values())[2:] if name is not None]))
        else:
            # if it's Context then our locals is dictionary with keys
            # "cog(self), ctx, char_names" where char_names is a string
            # meaning we only need [2] and then strip all commas
            names_string = list(local_dict.values())[2]
            names = [b for x in names_string.split(",") if (b := x.lstrip().rstrip())]
        return names

    async def player_add_remove(
        self, ctx: AluContext | discord.Interaction[AluBot], local_dict: Dict[str, Any], *, mode_add: bool
    ) -> None:
        """
        Base function to add/remove players from user's favourite list.

        Parameters
        ----------
        ctx :
        local_dict :
        mode_add :
        """
        player_names = self.get_names_list_from_locals(ctx, local_dict)
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)

        if not player_names:
            raise commands.BadArgument("You cannot use this command without naming at least one player.")
        await ctx.typing()
        query = f'SELECT {self.players_column} FROM guilds WHERE id=$1'
        fav_ids: List[int] = await ctx.client.pool.fetchval(query, ctx.guild.id)  # type: ignore
        query = f"""SELECT id, name_lower, display_name 
                    FROM {self.players_table}
                    WHERE name_lower=ANY($1)
                """  # AND NOT id=ANY($2)
        sa_rows = await ctx.client.pool.fetch(query, [name.lower() for name in player_names])
        # The following notations are assumed logically for mode_add being `True`.
        # +-----------------+-----------------------+-----------------------+
        # | variable_name   | `mode_add = True`     | `mode_add = False`    |
        # +=================+=======================+=======================+
        # | s               | successfully added    | already removed       |
        # +-----------------+-----------------------+-----------------------+
        # | a               | already added         | successfully removed  |
        # +-----------------+-----------------------+-----------------------+
        # | f               | failed to add         | failed to remove      |
        # +-----------------+-----------------------+-----------------------+
        s_ids = [row.id for row in sa_rows if row.id not in fav_ids]
        s_names = [row.display_name for row in sa_rows if row.id not in fav_ids]
        a_ids = [row.id for row in sa_rows if row.id in fav_ids]
        a_names = [row.display_name for row in sa_rows if row.id in fav_ids]
        f_names = [name for name in player_names if name.lower() not in [row.name_lower for row in sa_rows]]

        query = f"UPDATE guilds SET {self.players_column}=$1 WHERE id=$2"
        new_fav_ids = fav_ids + s_ids if mode_add else [i for i in fav_ids if i not in a_ids]
        await ctx.client.pool.execute(query, new_fav_ids, ctx.guild.id)

        if mode_add:
            e = self.construct_the_embed(s_names, a_names, f_names, gather_word='players', mode_add=mode_add)
        else:
            e = self.construct_the_embed(a_names, s_names, f_names, gather_word='players', mode_add=mode_add)
        if f_names:
            e.set_footer(
                text=(
                    'Check your argument or consider adding (for trustees)/requesting such player with '
                    '`$ or /dota database add|request name: <name> steam: <steam_id> twitch: <yes/no>`'
                )
            )
        await ctx.reply(embed=e)

    async def player_add_remove_autocomplete(
        self, ntr: discord.Interaction, current: str, *, mode_add: bool
    ) -> List[app_commands.Choice[str]]:
        """Base function for player add/remove autocomplete"""
        query = f'SELECT {self.players_column} FROM guilds WHERE id=$1'
        fav_ids = await self.bot.pool.fetch(query, ntr.guild.id)
        clause = 'NOT' if mode_add else ''
        query = f"""SELECT display_name
                    FROM {self.players_table}
                    WHERE {clause} id=ANY($1)
                    ORDER BY similarity(display_name, $2) DESC
                    LIMIT 6;
                """
        rows = await self.bot.pool.fetch(query, fav_ids, current)
        namespace_list = [x.lower() for x in ntr.namespace.__dict__.values() if x != current]
        choice_list = [x for x in [a for a, in rows] if x.lower() not in namespace_list]
        return [app_commands.Choice(name=n, value=n) for n in choice_list if current.lower() in n.lower()]

    async def player_list(self, ctx: AluContext | discord.Interaction[AluBot]):
        """Base function for player list command"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        await ctx.typing()
        query = f'SELECT {self.players_column} FROM guilds WHERE id=$1'
        fav_ids = await self.bot.pool.fetchval(query, ctx.guild.id)

        query = f"""SELECT display_name, twitch_id 
                    FROM {self.players_table}
                    WHERE id=ANY($1)
                    ORDER BY display_name
                """
        rows = await self.bot.pool.fetch(query, fav_ids) or []

        player_names = [self.player_name_string(row.display_name, row.twitch_id) for row in rows]
        e = discord.Embed(title=f'List of favourite {self.game_name} players', colour=self.colour)
        e.description = '\n'.join(player_names)
        await ctx.reply(embed=e)

    async def character_add_remove(
        self, ctx: AluContext | discord.Interaction[AluBot], local_dict: Dict[str, Any], *, mode_add: bool
    ):
        """Base function for adding/removing characters such as heroes/champs from fav lists"""
        character_names = self.get_names_list_from_locals(ctx, local_dict)
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)

        if not character_names:
            raise commands.BadArgument("You cannot use this command without naming at least one character.")

        await ctx.typing()
        query = f'SELECT {self.characters_column} FROM guilds WHERE id=$1'
        fav_ids: List[int] = await ctx.client.pool.fetchval(query, ctx.guild.id)  # type: ignore

        f_names, sa_ids = [], []
        for name in character_names:
            try:
                sa_ids.append(await self.get_char_id_by_name(name))
            except KeyError:
                f_names.append(name)

        s_ids = [i for i in sa_ids if i not in fav_ids]
        a_ids = [i for i in sa_ids if i in fav_ids]
        s_names = [await self.get_char_name_by_id(i) for i in s_ids]
        a_names = [await self.get_char_name_by_id(i) for i in a_ids]

        query = f"UPDATE guilds SET {self.characters_column}=$1 WHERE id=$2"
        new_fav_ids = fav_ids + s_ids if mode_add else [i for i in fav_ids if i not in a_ids]
        await ctx.client.pool.execute(query, new_fav_ids, ctx.guild.id)

        if mode_add:
            e = self.construct_the_embed(
                s_names, a_names, f_names, gather_word=self.character_gather_word, mode_add=mode_add
            )
        else:
            e = self.construct_the_embed(
                a_names, s_names, f_names, gather_word=self.character_gather_word, mode_add=mode_add
            )
        await ctx.reply(embed=e)

    async def character_add_remove_autocomplete(
        self, ntr: discord.Interaction, current: str, *, mode_add: bool
    ) -> List[app_commands.Choice[str]]:
        """Base function for character add/remove autocomplete"""
        query = f'SELECT {self.characters_column} FROM guilds WHERE id=$1'
        fav_ids: List[int] = await self.bot.pool.fetchval(query, ntr.guild.id)  # type: ignore

        fav_names = [await self.get_char_name_by_id(i) for i in fav_ids]

        if mode_add:
            all_names = await self.get_all_character_names()
            choice_names = [i for i in all_names if i not in fav_names]
        else:
            choice_names = fav_names
        namespace_list = [x.lower() for x in ntr.namespace.__dict__.values() if x != current]
        choice_names = [x for x in choice_names if x.lower() not in namespace_list]

        precise_match = [x for x in choice_names if current.lower().startswith(x.lower())]
        close_match = get_close_matches(current, choice_names, n=5, cutoff=0)

        return_list = list(dict.fromkeys(precise_match + close_match))
        return [app_commands.Choice(name=n, value=n) for n in return_list][:25]  # type: ignore

    async def character_list(self, ctx: AluContext | discord.Interaction[AluBot]) -> None:
        """Base function for character list commands"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        await ctx.typing()
        query = f'SELECT {self.characters_column} FROM guilds WHERE id=$1'
        fav_ids: List[int] = await ctx.client.pool.fetchval(query, ctx.guild.id) or []  # type: ignore
        fav_names = [f'{await self.get_char_name_by_id(i)} - `{i}`' for i in fav_ids]

        e = discord.Embed(title=f'List of your favourite {self.character_gather_word}', colour=self.colour)
        e.description = '\n'.join(fav_names)
        await ctx.reply(embed=e)

    async def spoil(self, ctx: AluContext | discord.Interaction[AluBot], spoil: bool):
        """Base function for spoil commands"""
        if isinstance(ctx, discord.Interaction):
            ctx = await AluContext.from_interaction(ctx)
        query = f'UPDATE guilds SET {self.spoil_column}=$1 WHERE id=$2'
        await self.bot.pool.execute(query, spoil, ctx.guild.id)
        e = discord.Embed(description=f"Changed spoil value to {spoil}", colour=self.colour)
        await ctx.reply(embed=e)