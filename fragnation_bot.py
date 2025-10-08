"""
FragNation Genesis 2025 - DM-secure registration bot
Python 3.11+, discord.py, stores data in JSON (data.json)

Features:
- DM-based registration for Solo & Team
- Team join codes (shareable) for teammates to join via DM: !jointeam <CODE>
- Bot posts bot-authored embeds to #payments and saves message IDs so it can safely update them
- Admin commands: !verify, !reject, !pending, !paymentsummary
- Auto-create channels / roles on startup
- Uses JSON file (data.json) to persist state
"""

import discord
from discord.ext import commands
import os
import asyncio
import json
import random
import string
from dotenv import load_dotenv
from typing import Optional
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run).start()


# ---------------- Config & Environment ----------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None
UPI_ID = os.getenv("UPI_ID") or "yuvraj9648@fam"

if not TOKEN:
    raise SystemExit("DISCORD_TOKEN not set in .env")

# Channel & role names
CHANNEL_REGISTRATION = "registration"
CHANNEL_PAYMENTS = "payments"
CHANNEL_FIXTURES = "fixtures"
CHANNEL_RESULTS = "results"

ROLE_PARTICIPANT = "Registered Player"
ROLE_CAPTAIN = "Team Captain"
ROLE_ADMIN = "Tournament Admin"

# JSON data file
DATA_FILE = "data.json"
DATA_LOCK = asyncio.Lock()  # ensure atomic writes

# ---------------- Intents & Bot ----------------
intents = discord.Intents.default()
intents.members = True        # privileged: enable in dev portal
intents.message_content = True  # privileged: enable in dev portal
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- Helper: JSON persistence ----------------
async def load_data() -> dict:
    """Load data.json (create if missing)."""
    async with DATA_LOCK:
        if not os.path.exists(DATA_FILE):
            data = {"solos": {}, "teams": {}, "payments": {}}  # structure
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return data
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

async def save_data(data: dict):
    async with DATA_LOCK:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

def make_join_code(length: int = 6) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def mention_or_id(user_id: int) -> str:
    return f"<@{user_id}>"

# ---------------- On ready: setup server resources ----------------
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Streaming(name="FNCT - Valorant", url="https://www.youtube.com/@miniyuvi/streams"))
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    # ensure channels/roles in each guild we are in (prefer using GUILD_ID if provided)
    guilds = bot.guilds
    if GUILD_ID:
        g = bot.get_guild(GUILD_ID)
        if g:
            await ensure_channels_and_roles(g)
        else:
            print(f"⚠️ Warning: GUILD_ID {GUILD_ID} not found among bot guilds.")
    else:
        for g in guilds:
            await ensure_channels_and_roles(g)
    print("Bot ready. DM registration is active.")

async def ensure_channels_and_roles(guild: discord.Guild):
    # create channels if missing (bot requires Manage Channels)
    text_channel_names = {c.name for c in guild.text_channels}
    for name in (CHANNEL_REGISTRATION, CHANNEL_PAYMENTS, CHANNEL_FIXTURES, CHANNEL_RESULTS):
        if name not in text_channel_names:
            try:
                await guild.create_text_channel(name)
                print(f"Created channel #{name} in {guild.name}")
            except discord.Forbidden:
                print(f"Missing permission to create channel #{name} in {guild.name}")

    # create roles if missing
    role_names = {r.name for r in guild.roles}
    for rname in (ROLE_PARTICIPANT, ROLE_CAPTAIN, ROLE_ADMIN):
        if rname not in role_names:
            try:
                await guild.create_role(name=rname)
                print(f"Created role {rname} in {guild.name}")
            except discord.Forbidden:
                print(f"Missing permission to create role {rname} in {guild.name}")

# ---------------- Utility: post payment embed (bot authored) ----------------
async def post_payment_embed(guild: discord.Guild, title: str, fields: dict) -> tuple:
    """
    posts an embed to #payments, returns (channel_id, message_id)
    fields is dict of field_name->value
    """
    ch = discord.utils.get(guild.text_channels, name=CHANNEL_PAYMENTS)
    if ch is None:
        # fallback: pick first text channel
        ch = guild.text_channels[0]
    embed = discord.Embed(title=title, color=discord.Color.orange())
    for k, v in fields.items():
        embed.add_field(name=k, value=v, inline=False)
    embed.set_footer(text=f"FragNation Genesis 2025 • UPI: {UPI_ID}")
    msg = await ch.send(embed=embed)
    return (ch.id, msg.id)

async def edit_payment_embed(guild: discord.Guild, channel_id: int, message_id: int, new_fields: dict, new_title: Optional[str] = None):
    ch = guild.get_channel(channel_id)
    if ch is None:
        return
    try:
        msg = await ch.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden):
        return
    embed = msg.embeds[0] if msg.embeds else discord.Embed()
    if new_title:
        embed.title = new_title
    # clear old fields and add new
    embed.clear_fields()
    for k, v in new_fields.items():
        embed.add_field(name=k, value=v, inline=False)
    embed.set_footer(text=f"FragNation Genesis 2025 • UPI: {UPI_ID}")
    try:
        await msg.edit(embed=embed)
    except discord.Forbidden:
        # cannot edit (shouldn't happen because bot authored), safe fallback: send a new embed
        await ch.send(embed=embed)

# ---------------- Registration command: triggers DM ----------------
@bot.command(name="register")
async def register_cmd(ctx: commands.Context):
    """
    Usage: any user runs !register anywhere. Bot will DM the user and start the flow.
    """
    # Try to DM user
    try:
        dm = await ctx.author.create_dm()
        await dm.send(f"Hello {ctx.author.name}! Welcome to **FragNation Genesis 2025** registration.\nDo you want to register as `solo` or `team`? Reply with `solo` or `team`.")
    except discord.Forbidden:
        await ctx.send(f"{ctx.author.mention}, I couldn't DM you. Please enable DMs and try again.")
        return

    def check_dm(m: discord.Message):
        return m.author.id == ctx.author.id and isinstance(m.channel, discord.DMChannel)

    try:
        reply = await bot.wait_for("message", check=check_dm, timeout=300)
    except asyncio.TimeoutError:
        await dm.send("Timed out. Please run `!register` again when ready.")
        return

    choice = reply.content.strip().lower()
    if choice == "solo":
        await dm.send("You chose **Solo** registration. I'll ask a few private questions.\n(Reply 'cancel' at any time to abort.)")
        await handle_solo_registration(ctx.author, dm, ctx.guild)
    elif choice == "team":
        await dm.send("You chose **Team** registration. I'll ask for the Team Name and create a join code that your teammates can use in DM.\n(Reply 'cancel' at any time to abort.)")
        await handle_team_registration(ctx.author, dm, ctx.guild)
    else:
        await dm.send("Unrecognized option. Please run `!register` and reply with `solo` or `team`.")

# ---------------- Solo registration flow (in DM) ----------------
async def handle_solo_registration(user: discord.User, dm_channel: discord.DMChannel, guild: Optional[discord.Guild]):
    def check(m: discord.Message):
        return m.author.id == user.id and isinstance(m.channel, discord.DMChannel)

    questions = [
        ("What is your REAL NAME? (exact full name)", "real_name"),
        ("Enter your VALORANT IGN (In-Game Name)", "ign"),
        ("Current Rank (e.g., Gold II)", "current_rank"),
        ("Peak Rank (e.g., Immortal I)", "peak_rank"),
        (f"Please pay ₹50 to UPI ID: `{UPI_ID}` and reply here with the **transaction ID** OR upload a screenshot link. After payment, enter the transaction ID or paste the screenshot URL:", "payment_proof"),
    ]
    answers = {}
    try:
        for q_text, key in questions:
            await dm_channel.send(q_text)
            msg = await bot.wait_for("message", check=check, timeout=600)
            text = msg.content.strip()
            if text.lower() == "cancel":
                await dm_channel.send("Registration cancelled.")
                return
            answers[key] = text
    except asyncio.TimeoutError:
        await dm_channel.send("Timed out. Please run `!register` again when ready.")
        return

    # save to data.json
    data = await load_data()
    data["solos"][str(user.id)] = {
        "discord_id": user.id,
        "real_name": answers["real_name"],
        "ign": answers["ign"],
        "current_rank": answers["current_rank"],
        "peak_rank": answers["peak_rank"],
        "paid": False,
        "payment_proof": answers["payment_proof"],
        "payment_msg": None  # will store (channel_id, message_id)
    }
    # Post a bot-authored embed to #payments so admins can verify
    # Use ctx.guild: try to find the guild where user invoked registration; if None fallback to first guild
    target_guild = guild or (bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None))
    if not target_guild:
        await dm_channel.send("⚠️ Registration saved locally but bot is not in any guild to post payments. Contact admin.")
        await save_data(data)
        return

    # Create embed fields
    fields = {
        "Type": "Solo Registration",
        "Player": f"{user.mention} (ID: {user.id})",
        "Real Name": answers["real_name"],
        "IGN": answers["ign"],
        "Current Rank": answers["current_rank"],
        "Peak Rank": answers["peak_rank"],
        "Payment Proof": answers["payment_proof"],
        "Status": "❌ Pending Verification"
    }
    ch_id, msg_id = await post_payment_embed(target_guild, "🧾 New Solo Registration", fields)
    data["solos"][str(user.id)]["payment_msg"] = {"channel_id": ch_id, "message_id": msg_id}
    # store in payments map for easy lookup
    data["payments"][f"solo-{user.id}"] = {
        "type": "solo",
        "user_id": user.id,
        "channel_id": ch_id,
        "message_id": msg_id,
        "status": "pending"
    }
    await save_data(data)

    await dm_channel.send("Thanks — your solo registration is submitted and sent to admins for verification. You will be notified once verified.")
    # optional: inform in registration channel that someone registered privately
    try:
        reg_ch = discord.utils.get(target_guild.text_channels, name=CHANNEL_REGISTRATION)
        if reg_ch:
            await reg_ch.send(f"🔔 New solo registration received from {user.mention} (check {discord.utils.get(target_guild.text_channels, name=CHANNEL_PAYMENTS).mention}).")
    except Exception:
        pass

# ---------------- Team registration flow (in DM) ----------------
async def handle_team_registration(user: discord.User, dm_channel: discord.DMChannel, guild: Optional[discord.Guild]):
    def check(m: discord.Message):
        return m.author.id == user.id and isinstance(m.channel, discord.DMChannel)

    try:
        await dm_channel.send("Enter your desired TEAM NAME (keep it short).")
        team_name_msg = await bot.wait_for("message", check=check, timeout=300)
        team_name = team_name_msg.content.strip()
        if team_name.lower() == "cancel":
            await dm_channel.send("Registration cancelled.")
            return
    except asyncio.TimeoutError:
        await dm_channel.send("Timed out. Please run `!register` again when ready.")
        return

    # create a join code and team structure
    code = make_join_code()
    data = await load_data()
    # ensure unique code
    while code in data["teams"]:
        code = make_join_code()

    # initial team structure: captain is added as first member (captain must still submit payment)
    data["teams"][code] = {
        "team_name": team_name,
        "captain_id": user.id,
        "members": [
            {
                "discord_id": user.id,
                "ign": None,
                "paid": False,
                "payment_proof": None,
                "payment_msg": None
            }
        ],
        "confirmed": False  # true when all 5 members present and paid+verified
    }

    await save_data(data)

    # DM back that code and instructions to captain
    await dm_channel.send(
        f"Team **{team_name}** created. Share this join code with your teammates:\n\n"
        f"`{code}`\n\n"
        "Each teammate should DM the bot and run the command:\n"
        "`!jointeam <CODE>`\n\n"
        "When each teammate uses `!jointeam`, the bot will ask for their IGN and payment proof (₹50 to UPI). "
        "Once 5 members have joined and payments are verified by admins, your team will be confirmed automatically."
    )

    # post an initial team registration embed in #payments so admins know a team was created
    target_guild = guild or (bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None))
    if target_guild:
        fields = {
            "Type": "Team Created (Awaiting members/payments)",
            "Team Name": team_name,
            "Join Code": code,
            "Captain": f"{user.mention} (ID: {user.id})",
            "Members (so far)": f"{user.mention}"
        }
        ch_id, msg_id = await post_payment_embed(target_guild, "🧾 New Team Created", fields)
        data["teams"][code]["admin_msg"] = {"channel_id": ch_id, "message_id": msg_id}
        # also create a payments mapping entry for team creation (not a payment)
        data["payments"][f"team-{code}-created"] = {
            "type": "team_created",
            "team_code": code,
            "channel_id": ch_id,
            "message_id": msg_id,
            "status": "awaiting_members"
        }
        await save_data(data)

# ---------------- Command for teammates to join (DM only) ----------------
@bot.command(name="jointeam")
async def jointeam_cmd(ctx: commands.Context, code: str = None):
    """
    Usage (DM): !jointeam <CODE>
    Team members use this in DM to add themselves to a team created by captain.
    """
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("Please use this command in a DM with the bot (privacy).")
        return
    if not code:
        await ctx.send("Usage: `!jointeam <CODE>` (the join code is provided by team captain).")
        return
    data = await load_data()
    code = code.strip().upper()
    if code not in data["teams"]:
        await ctx.send("Invalid join code. Please check with your team captain.")
        return
    team = data["teams"][code]
    # check if member already in team
    for m in team["members"]:
        if m["discord_id"] == ctx.author.id:
            await ctx.send("You are already a member of this team.")
            return
    if len(team["members"]) >= 5:
        await ctx.send("This team already has 5 members.")
        return

    # Ask for IGN and payment proof in DM
    await ctx.send(f"Joining team **{team['team_name']}**. Please reply with your VALORANT IGN:")
    def check(m): return m.author.id == ctx.author.id and isinstance(m.channel, discord.DMChannel)
    try:
        ign_msg = await bot.wait_for("message", check=check, timeout=300)
        ign = ign_msg.content.strip()
        if ign.lower() == "cancel":
            await ctx.send("Join cancelled.")
            return
        await ctx.send(f"Please pay ₹50 to `{UPI_ID}` and reply here with the transaction ID or paste a screenshot link:")
        pay_msg = await bot.wait_for("message", check=check, timeout=600)
        payment_proof = pay_msg.content.strip()
    except asyncio.TimeoutError:
        await ctx.send("Timed out. Please run `!jointeam <CODE>` again when ready.")
        return

    # add member to team
    member_entry = {
        "discord_id": ctx.author.id,
        "ign": ign,
        "paid": False,
        "payment_proof": payment_proof,
        "payment_msg": None
    }
    team["members"].append(member_entry)
    await save_data(data)

    # Post payment embed for this member (bot-authored) to #payments for admin verification
    target_guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
    if not target_guild:
        await ctx.send("⚠️ Bot is not connected to any guild to post payments. Contact admins.")
        return
    fields = {
        "Type": f"Team Join - {team['team_name']}",
        "Team Code": code,
        "Player": f"{ctx.author.mention} (ID: {ctx.author.id})",
        "IGN": ign,
        "Payment Proof": payment_proof,
        "Status": "❌ Pending Verification"
    }
    ch_id, msg_id = await post_payment_embed(target_guild, "🧾 Team Member Payment (Pending)", fields)
    # save payment mapping and message ref
    payment_key = f"team-{code}-member-{ctx.author.id}"
    data = await load_data()  # reload because might have changed
    # locate member in team and attach payment_msg
    for m in data["teams"][code]["members"]:
        if m["discord_id"] == ctx.author.id:
            m["payment_msg"] = {"channel_id": ch_id, "message_id": msg_id}
            m["payment_proof"] = payment_proof
            break
    data["payments"][payment_key] = {
        "type": "team_member",
        "team_code": code,
        "user_id": ctx.author.id,
        "channel_id": ch_id,
        "message_id": msg_id,
        "status": "pending"
    }
    await save_data(data)
    await ctx.send("Thanks — your join request and payment proof have been submitted for admin verification.")
    # update admin team creation embed to show new member list (edit bot-authored admin message)
    admin_msg_info = data["teams"][code].get("admin_msg")
    if admin_msg_info:
        members_str = ", ".join([f"<@{m['discord_id']}>" for m in data["teams"][code]["members"]])
        new_fields = {
            "Type": "Team Created (Awaiting members/payments)",
            "Team Name": data["teams"][code]["team_name"],
            "Join Code": code,
            "Captain": f"<@{data['teams'][code]['captain_id']}>",
            "Members (so far)": members_str
        }
        await edit_payment_embed(target_guild, admin_msg_info["channel_id"], admin_msg_info["message_id"], new_fields)

    # Auto-confirm team if 5 members and all payments verified (admins must set verified via !verify)
    # check here: if team has 5 members and all member entries have paid==True (which is only set by !verify), mark confirmed and announce
    # We'll not auto-confirm here because payments are pending verification; confirmation happens in verify flow after each verification

# ---------------- Admin commands: verify / reject / pending / paymentsummary ----------------
def parse_member_arg(arg: str, guild: discord.Guild) -> Optional[discord.Member]:
    # attempt mention / id / name (very basic)
    arg = arg.strip()
    member = None
    if arg.startswith("<@") and arg.endswith(">"):
        digits = ''.join(ch for ch in arg if ch.isdigit())
        try:
            member = guild.get_member(int(digits))
        except:
            member = None
    else:
        # try ID
        if arg.isdigit():
            member = guild.get_member(int(arg))
        else:
            # try by name
            member = discord.utils.find(lambda m: m.name == arg or (m.nick and m.nick == arg), guild.members)
    return member

@bot.command(name="verify")
@commands.has_permissions(manage_guild=True)
async def verify_cmd(ctx: commands.Context, member: discord.Member, *, txn_ref: Optional[str] = None):
    """
    Admin command: mark a user's payment as verified.
    Usage: !verify @user [txn_ref]
    """
    guild = ctx.guild
    data = await load_data()
    uid = str(member.id)

    # Check for solo payment
    if uid in data["solos"]:
        data["solos"][uid]["paid"] = True
        data["solos"][uid]["payment_txn"] = txn_ref or "verified-by-admin"
        # update payments mapping
        pay_key = f"solo-{uid}"
        if pay_key in data["payments"]:
            data["payments"][pay_key]["status"] = "verified"
            ch_id = data["payments"][pay_key]["channel_id"]
            msg_id = data["payments"][pay_key]["message_id"]
            # edit the embed to show verified
            new_fields = {
                "Type": "Solo Registration",
                "Player": f"{member.mention} (ID: {member.id})",
                "Real Name": data["solos"][uid].get("real_name", ""),
                "IGN": data["solos"][uid].get("ign", ""),
                "Current Rank": data["solos"][uid].get("current_rank", ""),
                "Peak Rank": data["solos"][uid].get("peak_rank", ""),
                "Payment Proof": data["solos"][uid].get("payment_proof", ""),
                "Status": f"✅ Verified by {ctx.author.mention}\nTxn: {txn_ref or 'N/A'}"
            }
            await edit_payment_embed(guild, ch_id, msg_id, new_fields, new_title="✅ Solo Payment Verified")
        # assign Registered Player role
        role = discord.utils.get(guild.roles, name=ROLE_PARTICIPANT)
        if not role:
            try:
                role = await guild.create_role(name=ROLE_PARTICIPANT)
            except discord.Forbidden:
                role = None
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass
        await save_data(data)
        await ctx.send(f"✅ Marked {member.mention} (solo) as verified.")
        try:
            await member.send(f"✅ Your payment for FragNation Genesis 2025 has been verified by {ctx.author.display_name}.")
        except:
            pass
        return

    # else, check team members (iterate all teams)
    found = False
    for code, team in data["teams"].items():
        for m in team["members"]:
            if m["discord_id"] == member.id:
                # mark as paid
                m["paid"] = True
                m["payment_txn"] = txn_ref or "verified-by-admin"
                found = True
                # update payments mapping key
                pay_key = f"team-{code}-member-{member.id}"
                if pay_key in data["payments"]:
                    data["payments"][pay_key]["status"] = "verified"
                    ch_id = data["payments"][pay_key]["channel_id"]
                    msg_id = data["payments"][pay_key]["message_id"]
                    # edit that member's embed to show verified
                    new_fields = {
                        "Type": f"Team Join - {team['team_name']}",
                        "Team Code": code,
                        "Player": f"{member.mention} (ID: {member.id})",
                        "IGN": m.get("ign", ""),
                        "Payment Proof": m.get("payment_proof", ""),
                        "Status": f"✅ Verified by {ctx.author.mention}\nTxn: {txn_ref or 'N/A'}"
                    }
                    await edit_payment_embed(guild, ch_id, msg_id, new_fields, new_title="✅ Team Member Payment Verified")
                # assign Registered Player role
                role = discord.utils.get(guild.roles, name=ROLE_PARTICIPANT)
                if not role:
                    try:
                        role = await guild.create_role(name=ROLE_PARTICIPANT)
                    except discord.Forbidden:
                        role = None
                if role:
                    try:
                        await member.add_roles(role)
                    except discord.Forbidden:
                        pass
                await ctx.send(f"✅ Marked {member.mention} as verified for team `{team['team_name']}`.")
                try:
                    await member.send(f"✅ Your payment for FragNation Genesis 2025 (team {team['team_name']}) has been verified by {ctx.author.display_name}.")
                except:
                    pass
                # After verifying, check if team is now full (5 members) and all paid -> confirm
                if len(team["members"]) == 5 and all(mbr.get("paid", False) for mbr in team["members"]):
                    team["confirmed"] = True
                    # notify in registration channel
                    reg_ch = discord.utils.get(guild.text_channels, name=CHANNEL_REGISTRATION)
                    if reg_ch:
                        member_mentions = ", ".join(f"<@{mbr['discord_id']}>" for mbr in team["members"])
                        await reg_ch.send(f"✅ Team **{team['team_name']}** (code `{code}`) is fully registered and confirmed!\nMembers: {member_mentions}")
                    # assign Team Captain role to captain and Registered Player role to members if not assigned
                    cap = guild.get_member(team["captain_id"])
                    cap_role = discord.utils.get(guild.roles, name=ROLE_CAPTAIN)
                    if cap_role and cap:
                        try:
                            await cap.add_roles(cap_role)
                        except:
                            pass
                await save_data(data)
                return
    if not found:
        await ctx.send("Could not find this user in solos or teams data. Make sure they registered via DM before verifying.")

@bot.command(name="reject")
@commands.has_permissions(manage_guild=True)
async def reject_cmd(ctx: commands.Context, member: discord.Member, *, reason: Optional[str] = "No reason provided"):
    """
    Admin command to reject a user's payment.
    Usage: !reject @user <reason>
    """
    guild = ctx.guild
    data = await load_data()
    uid = str(member.id)
    # Check solo
    if uid in data["solos"]:
        # update payments mapping
        pay_key = f"solo-{uid}"
        if pay_key in data["payments"]:
            data["payments"][pay_key]["status"] = "rejected"
            ch_id = data["payments"][pay_key]["channel_id"]
            msg_id = data["payments"][pay_key]["message_id"]
            new_fields = {
                "Type": "Solo Registration",
                "Player": f"{member.mention} (ID: {member.id})",
                "Real Name": data["solos"][uid].get("real_name", ""),
                "IGN": data["solos"][uid].get("ign", ""),
                "Current Rank": data["solos"][uid].get("current_rank", ""),
                "Peak Rank": data["solos"][uid].get("peak_rank", ""),
                "Payment Proof": data["solos"][uid].get("payment_proof", ""),
                "Status": f"❌ Rejected by {ctx.author.mention}\nReason: {reason}"
            }
            await edit_payment_embed(guild, ch_id, msg_id, new_fields, new_title="❌ Solo Payment Rejected")
        await save_data(data)
        try:
            await member.send(f"🚫 Your payment submission for FragNation Genesis 2025 was rejected by {ctx.author.display_name}.\nReason: {reason}\nPlease re-submit your payment proof or contact the admins.")
        except:
            pass
        await ctx.send(f"🚫 Rejected solo payment for {member.mention}.")
        return

    # team member
    found = False
    for code, team in data["teams"].items():
        for m in team["members"]:
            if m["discord_id"] == member.id:
                found = True
                # update payments mapping
                pay_key = f"team-{code}-member-{member.id}"
                if pay_key in data["payments"]:
                    data["payments"][pay_key]["status"] = "rejected"
                    ch_id = data["payments"][pay_key]["channel_id"]
                    msg_id = data["payments"][pay_key]["message_id"]
                    new_fields = {
                        "Type": f"Team Join - {team['team_name']}",
                        "Team Code": code,
                        "Player": f"{member.mention} (ID: {member.id})",
                        "IGN": m.get("ign", ""),
                        "Payment Proof": m.get("payment_proof", ""),
                        "Status": f"❌ Rejected by {ctx.author.mention}\nReason: {reason}"
                    }
                    await edit_payment_embed(guild, ch_id, msg_id, new_fields, new_title="❌ Team Member Payment Rejected")
                try:
                    await member.send(f"🚫 Your payment for team **{team['team_name']}** was rejected by {ctx.author.display_name}.\nReason: {reason}\nPlease re-submit your payment proof.")
                except:
                    pass
                await ctx.send(f"🚫 Rejected payment for {member.mention} in team `{team['team_name']}`.")
                await save_data(data)
                break
        if found:
            break
    if not found:
        await ctx.send("Could not find this user in registration records.")

@bot.command(name="pending")
@commands.has_permissions(manage_guild=True)
async def pending_cmd(ctx: commands.Context):
    """
    Lists pending payments (embed contains 'Pending' status)
    """
    data = await load_data()
    pending_list = []
    # solos
    for uid, s in data.get("solos", {}).items():
        pay_key = f"solo-{uid}"
        pay = data["payments"].get(pay_key)
        if pay and pay.get("status") == "pending":
            pending_list.append(f"Solo - <@{uid}> (IGN: {s.get('ign')})")
    # team members
    for code, team in data.get("teams", {}).items():
        for m in team["members"]:
            pay_key = f"team-{code}-member-{m['discord_id']}"
            pay = data["payments"].get(pay_key)
            if pay and pay.get("status") == "pending":
                pending_list.append(f"Team {team['team_name']} ({code}) - <@{m['discord_id']}> (IGN: {m.get('ign')})")
    if not pending_list:
        await ctx.send("✅ No pending payments.")
        return
    msg = "🕓 Pending Payments:\n" + "\n".join(pending_list)
    await ctx.send(msg)

@bot.command(name="paymentsummary")
@commands.has_permissions(manage_guild=True)
async def paymentsummary_cmd(ctx: commands.Context):
    """
    Summary counts of Verified / Pending / Rejected
    """
    data = await load_data()
    verified = pending = rejected = 0
    for key, p in data.get("payments", {}).items():
        status = p.get("status")
        if status == "verified":
            verified += 1
        elif status == "pending":
            pending += 1
        elif status == "rejected":
            rejected += 1
    embed = discord.Embed(title="💸 Payment Summary", color=discord.Color.blurple())
    embed.add_field(name="✅ Verified", value=str(verified))
    embed.add_field(name="🕓 Pending", value=str(pending))
    embed.add_field(name="❌ Rejected", value=str(rejected))
    await ctx.send(embed=embed)

# ---------------- Small helper commands ----------------
@bot.command(name="myregistration")
async def myregistration_cmd(ctx: commands.Context):
    """DM-only: lets a user view their stored registration data."""
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("Use this command in a DM with the bot for privacy.")
        return
    data = await load_data()
    uid = str(ctx.author.id)
    if uid in data.get("solos", {}):
        s = data["solos"][uid]
        embed = discord.Embed(title="Your Solo Registration", color=discord.Color.blue())
        embed.add_field(name="IGN", value=s.get("ign", ""))
        embed.add_field(name="Real Name", value=s.get("real_name", ""))
        embed.add_field(name="Current Rank", value=s.get("current_rank", ""))
        embed.add_field(name="Peak Rank", value=s.get("peak_rank", ""))
        embed.add_field(name="Paid", value=str(s.get("paid", False)))
        await ctx.send(embed=embed)
        return
    # check teams membership
    for code, team in (await load_data())["teams"].items():
        for m in team["members"]:
            if m["discord_id"] == ctx.author.id:
                embed = discord.Embed(title=f"Team: {team['team_name']} (Code: {code})", color=discord.Color.blue())
                embed.add_field(name="Captain", value=f"<@{team['captain_id']}>")
                embed.add_field(name="Your IGN", value=m.get("ign", ""))
                embed.add_field(name="Paid", value=str(m.get("paid", False)))
                await ctx.send(embed=embed)
                return
    await ctx.send("You don't have a saved registration yet. Run `!register` anywhere to start (bot will DM you).")

# ---------------- Error handling ----------------
@bot.event
async def on_command_error(ctx: commands.Context, error):
    # Friendly messages for common errors
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❗ Missing argument. Check command usage.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You do not have permission to use this command.")
    else:
        # for debugging, print to console then notify admin
        print("Command error:", error)
        try:
            await ctx.send(f"⚠️ Error: {error}")
        except:
            pass

# ---------------- Run ----------------
if __name__ == "__main__":
    bot.run(TOKEN)


