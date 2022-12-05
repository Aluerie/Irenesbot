from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    List, Literal, Dict, Tuple, Callable, Coroutine, Optional, Union
)

from discord import Embed, app_commands
from discord.ext.commands import BadArgument

from .distools import send_pages_list
from .var import Clr, MP, Ems, Cid

if TYPE_CHECKING:
    from asyncpg import Pool
    from discord import Colour, Interaction, TextChannel
    from .context import Context
    from .bot import AluBot
    from main import DRecord


class PlayerNamesCache:
    # todo: delete this if we dont find any usage to it
    def __init__(
            self,
            table_name: str,
            pool: Pool
    ):
        self.table_name = table_name
        self.pool = pool
        self.cache: List[DRecord] = []
        self.display_names: List[str] = []
        self.name_lowers: List[str] = []

    async def update_cache(self):
        query = f"SELECT * FROM {self.table_name}"
        rows = await self.pool.fetch(query)
        self.cache = rows
        self.display_names = [row.display_name for row in rows]
        self.name_lowers = [row.name_lower for row in rows]


class FPCBase:
    """
    Base class for cogs representing FPC (Favourite Player+Character) feature
    for different games: Dota 2, League of Legends and probably more to come.

    Since many base features can be generalized -
    here is the base class containing base methods.
    """
    def __init__(
            self,
            /,
            *,
            feature_name: str,
            game_name: str,
            colour: Colour,
            bot: AluBot,
            players_table: str,
            accounts_table: str,
            channel_id_column: str,
            players_column: str,
            acc_info_columns: List[str]
    ) -> None:
        self.feature_name = feature_name
        self.game_name = game_name
        self.colour = colour
        self.bot = bot
        self.players_table = players_table
        self.accounts_table = accounts_table
        self.channel_id_column = channel_id_column
        self.players_column = players_column
        self.acc_info_columns = acc_info_columns

    async def channel_set(
            self,
            ctx: Context,
            channel: Optional[TextChannel] = None,
    ) -> None:
        """Base function for setting channel for FPC Feed feature"""
        ch = channel or ctx.channel
        if not ch.permissions_for(ctx.guild.me).send_messages:
            em = Embed(colour=Clr.error)
            em.description = 'I do not have permissions to send messages in that channel :('
            await ctx.reply(embed=em)  # todo: change this to commands.BotMissingPermissions
            return

        query = f'UPDATE guilds SET {self.channel_id_column}=$1 WHERE id=$2'
        await ctx.pool.execute(query, ch.id, ctx.guild.id)
        em = Embed(colour=self.colour)
        em.description = f'Channel {ch.mention} is set to be the {self.feature_name} channel for this server'
        await ctx.reply(embed=em)

    async def channel_disable(
            self,
            ctx: Context,
    ) -> None:
        """Base function for disabling channel for FPC Feed feature"""
        # ToDo: add confirmation prompt "are you sure you want to disable the feature" alert here
        query = f'SELECT {self.channel_id_column} FROM guilds WHERE id=$1'
        ch_id = await ctx.pool.fetchval(query, ctx.guild.id)

        if (ch := ctx.bot.get_channel(ch_id)) is None:
            em = Embed(colour=Clr.error)
            em.description = f'{self.feature_name} channel is not set or already was reset'
            await ctx.reply(embed=em)
            return
        query = f'UPDATE guilds SET {self.channel_id_column}=NULL WHERE id=$1'
        await ctx.pool.execute(query, ctx.guild.id)
        em = Embed(colour=self.colour)
        em.description = f'Channel {ch.mention} is no longer the {self.feature_name} channel.'
        await ctx.reply(embed=em)

    async def channel_check(
            self,
            ctx: Context,
    ) -> None:
        """Base function for checking if channel is set for FPC Feed feature"""
        query = f'SELECT {self.channel_id_column} FROM guilds WHERE id=$1'
        ch_id = await ctx.pool.fetchval(query, ctx.guild.id)

        if (ch := ctx.bot.get_channel(ch_id)) is None:
            em = Embed(colour=self.colour)
            em.description = f'{self.feature_name} channel is not currently set.'
            await ctx.reply(embed=em)
        else:
            em = Embed(colour=self.colour)
            em.description = f'{self.feature_name} channel is currently set to {ch.mention}.'
            await ctx.reply(embed=em)

    @staticmethod
    def player_name_string(
            display_name: str,
            twitch: Union[int, None]
    ) -> str:
        if twitch:
            return f"● [{display_name}](https://www.twitch.tv/{display_name})"
        else:
            return f"● {display_name}"

    @staticmethod
    def player_acc_string(
            **kwargs
    ) -> str:
        ...

    def player_name_acc_string(
            self,
            display_name: str,
            twitch_id: Union[int, None],
            **kwargs
    ) -> str:
        return (
            f'{self.player_name_string(display_name, twitch_id)}\n'
            f'{self.player_acc_string(**kwargs)}'
        )

    async def database_list(
            self,
            ctx: Context
    ) -> None:
        """Base function for sending database list embed"""
        await ctx.typing()

        query = f'SELECT {self.players_column} FROM guilds WHERE id=$1'
        fav_player_id_list = await ctx.pool.fetchval(query, ctx.guild.id)

        query = f"""SELECT {', '.join(['player_id', 'display_name', 'twitch_id', 'a.id'] + self.acc_info_columns)}
                    FROM {self.players_table} p
                    JOIN {self.accounts_table} a
                    ON p.id = a.player_id
                    ORDER BY {'display_name'} 
                """
        rows = await ctx.pool.fetch(query)

        player_dict = dict()

        for row in rows:
            if row.player_id not in player_dict:
                followed = ' {0} {0} {0}'.format(Ems.DankLove) if row.player_id in fav_player_id_list else ''
                player_dict[row.player_id] = {
                    'name': f"{self.player_name_string(row.display_name, row.twitch_id)}{followed}",
                    'info': []
                }
            kwargs = {col: row[col] for col in ['id'] + self.acc_info_columns}
            player_dict[row.player_id]['info'].append(self.player_acc_string(**kwargs))

        ans_array = [f"{v['name']}\n{chr(10).join(v['info'])}" for v in player_dict.values()]

        await send_pages_list(
            ctx,
            ans_array,
            split_size=10,
            colour=Clr.prpl,
            title=f"List of {self.game_name} players in Database",
            footer_text=f'With love, {ctx.guild.me.display_name}'
        )

    async def get_player_dict(
            self,
            *,
            name_flag: str,
            twitch_flag: bool
    ) -> dict:
        name_lower = name_flag.lower()
        if twitch_flag:
            twitch_id, display_name = await self.bot.twitch.twitch_id_and_display_name_by_login(name_lower)
        else:
            twitch_id, display_name = None, name_flag

        return {
            'name_lower': name_lower,
            'display_name': display_name,
            'twitch_id': twitch_id
        }

    async def get_account_dict(
            self,
            **kwargs
    ) -> dict:
        ...
    
    async def check_if_already_in_database(
            self,
            account_dict: dict
    ):
        query = f'SELECT * FROM {self.accounts_table} WHERE id=$1'
        user = await self.bot.pool.fetchrow(query, account_dict['id'])
        if user is not None:
            raise BadArgument(
                'This steam account is already in the database.\n'
                f'It is marked as {user.name}\'s account.\n\n'
                f'Did you mean to use `/dota player add {user.name}` to add the stream into your fav list?'
            )
        
    async def database_add(
            self,
            ctx: Context,
            player_dict: dict,
            account_dict: dict
    ):
        """Base function for adding accounts into the database"""
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
        player_id = await ctx.pool.fetchval(query, *player_dict.values())

        dollars = [f'${i}' for i in range(1, len(self.acc_info_columns)+3)]  # [$1, $2, ... ]
        query = f"""INSERT INTO {self.accounts_table}
                    (player_id, id, {', '.join(self.acc_info_columns)})
                    VALUES {'('}{', '.join(dollars)}{')'}
                """
        await ctx.pool.execute(query, player_id, *account_dict.values())

        em = Embed(colour=Clr.prpl)
        em.add_field(
            name=f'Successfully added the account to the database',
            value=self.player_name_acc_string(
                player_dict['display_name'], player_dict['twitch_id'], **account_dict
            )
        )
        await ctx.reply(embed=em)
        em.colour = MP.green(shade=200)
        em.set_author(name=ctx.author, icon_url=ctx.author.avatar.url)
        await self.bot.get_channel(Cid.global_logs).send(embed=em)

    async def database_request(
            self,
            ctx: Context,
            player_dict: dict,
            account_dict: dict,
    ) -> None:
        await self.check_if_already_in_database(account_dict)

        player_string = self.player_name_acc_string(
            player_dict['display_name'], player_dict['twitch_id'], **account_dict
        )
        warn_em = Embed(colour=Clr.prpl, title='Confirmation Prompt')
        warn_em.description = (
            'Are you sure you want to request this streamer steam account to be added into the database?\n'
            'This information will be sent to Aluerie. Please, double check before confirming.'
        )
        warn_em.add_field(name='Request to add an account into the database', value=player_string)
        if not await ctx.prompt(embed=warn_em):
            await ctx.reply('Aborting...', delete_after=5.0)
            return

        em = Embed(colour=self.colour)
        em.add_field(name='Successfully made a request to add the account into the database', value=player_string)
        await ctx.reply(embed=em)

        warn_em.colour = MP.orange(shade=200)
        warn_em.title = ''
        warn_em.description = ''
        warn_em.set_author(name=ctx.author, icon_url=ctx.author.avatar.url)
        # cmd_str = ' '.join(f'{k}: {v}' for k, v in flags.__dict__.items())
        # warn_em.add_field(name='Command', value=f'`$dota stream add {cmd_str}`', inline=False)
        await self.bot.get_channel(Cid.global_logs).send(embed=warn_em)

    async def database_remove(
            self,
            ctx: Context,
            name_lower: str = None,
            account_id: Union[str, int] = None  # steam_id for dota, something else for lol
    ) -> None:
        """Base function for removing accounts from the database"""
        if name_lower is None and account_id is None:
            raise BadArgument('You need to provide at least one of flags: `name`, `steam`')

        if account_id:
            if name_lower:  # check for both name_lower and account_id
                query = f"""SELECT a.id 
                            FROM {self.players_table} p
                            JOIN {self.accounts_table} a
                            ON p.id = a.player_id
                            WHERE a.id=$1 AND p.name_lower=$2
                        """
                val = await ctx.pool.fetchval(query, account_id, name_lower)
                if val is None:
                    raise BadArgument(
                        'This account either is not in the database '
                        'or does not belong to the said player'
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
            ans_name = await ctx.pool.fetchval(query, account_id)
            if ans_name is None:
                raise BadArgument('There is no account with such account details')
        else:
            # query for name_lower only
            query = f"""DELETE FROM {self.players_table}
                        WHERE name_lower=$1
                        RETURNING display_name
                    """
            ans_name = await ctx.pool.fetchval(query, name_lower)
            if ans_name is None:
                raise BadArgument('There is no account with such player name')

        em = Embed(colour=self.colour)
        em.add_field(
            name='Successfully removed account(-s) from the database',
            value=f'{ans_name}{" - " + str(account_id) if account_id else ""}'
        )
        await ctx.reply(embed=em)

    async def player_add_remove(
            self,
            ctx: Context,
            player_names: List[str],
            *,
            mode_add: bool
    ):
        """

        @param ctx:
        @param player_names:
        @param mode_add:
        @return: None

        ---
        in the code - for add. Note that for remove s and a are swapped.
        s: success
        a: already
        f: fail
        """
        query = f'SELECT {self.players_column} FROM guilds WHERE id=$1'
        fav_ids = await ctx.pool.fetchval(query, ctx.guild.id)

        query = f"""SELECT id, name_lower, display_name 
                    FROM {self.players_table}
                    WHERE name_lower=ANY($1)
                """  # AND NOT id=ANY($2)
        sa_rows = await ctx.pool.fetch(query, [name.lower() for name in player_names])

        s_ids = [row.id for row in sa_rows if row.id not in fav_ids]
        s_names = [row.display_name for row in sa_rows if row.id not in fav_ids]
        a_ids = [row.id for row in sa_rows if row.id in fav_ids]
        a_names = [row.display_name for row in sa_rows if row.id in fav_ids]
        f_names = [name for name in player_names if name.lower() not in [row.name_lower for row in sa_rows]]

        query = f"UPDATE guilds SET {self.players_column}=$1 WHERE id=$2"
        new_fav_ids = fav_ids + s_ids if mode_add else [i for i in fav_ids if i not in a_ids]
        await ctx.pool.execute(query, new_fav_ids, ctx.guild.id)

        def construct_the_embed(s_names: List[str], a_names: List[str], f_names: List[str], *, mode_add: bool) -> Embed:
            em = Embed()
            if s_names:
                em.colour = MP.green(shade=500)
                em.add_field(name=f"Success: These names were {'added to' if mode_add else 'removed from'} your list",
                             value=f"`{', '.join(s_names)}`", inline=False)
            if a_names:
                em.colour = MP.orange(shade=500)
                em.add_field(name=f'Already: These names are already {"" if mode_add else "not"} in your list',
                             value=f"`{', '.join(a_names)}`", inline=False)
            if f_names:
                em.colour = MP.red(shade=500)
                em.add_field(name='Fail: These names are not in the database',
                             value=f"`{', '.join(f_names)}`", inline=False)
                em.set_footer(text='Check your argument or consider adding (for trustees)/requesting such player with '
                                   '`$ or /dota database add|request name: <name> steam: <steam_id> twitch: <yes/no>`')
            return em

        if mode_add:
            em = construct_the_embed(s_names, a_names, f_names, mode_add=mode_add)
        else:
            em = construct_the_embed(a_names, s_names, f_names, mode_add=mode_add)
        await ctx.reply(embed=em)

    async def player_add_remove_autocomplete(
            self,
            ntr: Interaction,
            current: str,
            *,
            mode_add: bool
    ) -> List[app_commands.Choice[str]]:
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








    @staticmethod
    async def sort_out_names(
            names: str,
            initial_list: List[int],
            mode: Literal['add', 'remov'],
            data_dict: Dict[str, str],
            get_proper_name_and_id: Callable[[str], Coroutine[str, str]]
    ) -> Tuple[List, List[Embed]]:
        initial_list = set(initial_list)
        res_dict = {
            i: {'names': [], 'embed': None}
            for i in ['success', 'already', 'fail']
        }

        for name in [x.strip() for x in names.split(',')]:
            proper_name, named_id = await get_proper_name_and_id(name)
            if named_id is None:
                res_dict['fail']['names'].append(f'`{proper_name}`')
            else:
                if mode == 'add':
                    if named_id in initial_list:
                        res_dict['already']['names'].append(f'`{proper_name}`')
                    else:
                        initial_list.add(named_id)
                        res_dict['success']['names'].append(f'`{proper_name}`')
                elif mode == 'remov':
                    if named_id not in initial_list:
                        res_dict['already']['names'].append(f'`{proper_name}`')
                    else:
                        initial_list.remove(named_id)
                        res_dict['success']['names'].append(f'`{proper_name}`')

        res_dict['success']['colour'] = MP.green()
        res_dict['already']['colour'] = MP.orange()
        res_dict['fail']['colour'] = Clr.error

        for k, v in res_dict.items():
            if len(v['names']):
                v['embed'] = Embed(
                    colour=v['colour']
                ).add_field(
                    name=data_dict[k],
                    value=", ".join(v['names'])
                )
                if k == 'fail':
                    v['embed'].set_footer(
                        text=data_dict['fail_footer']
                    )
        embed_list = [v['embed'] for v in res_dict.values() if v['embed'] is not None]
        return list(initial_list), embed_list

    @staticmethod
    async def x_eq_x(x):
        return x

    @staticmethod
    async def add_remove_autocomplete_work(
            current: str,
            mode: Literal['add', 'remov'],
            *,
            all_items: List[str],
            fav_items: List[str],
            func: Callable = x_eq_x,
            reverse_func: Callable = x_eq_x
    ) -> List[app_commands.Choice[str]]:

        input_strs = [x.strip() for x in current.split(',')]
        try:
            input_items = [await reverse_func(i) for i in input_strs[:-1]]
        except Exception:
            x = 'ERROR: It looks like you already typed something wrong'
            return [app_commands.Choice(name=x, value=x)]

        if mode == 'add':
            fav_items = fav_items + input_items
        if mode == 'remov':
            fav_items = [x for x in fav_items if x not in input_items]

        old_input = [await func(y) for y in input_items]
        answer = [
            ", ".join(old_input + [await func(x)]) for x in all_items
            if (mode == 'add' and x not in fav_items) or (mode == 'remov' and x in fav_items)
        ]
        answer.sort()
        return [
            app_commands.Choice(name=x, value=x)
            for x in answer if current.lower() in x.lower()
        ][:25]
