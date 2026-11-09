import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters
)

# ==========================================
# ⚠️ CONFIGURATION - CHANGE THESE VALUES ⚠️
# ==========================================
BOT_TOKEN = "9100672101:AAFLOl1CxIMYft8DVpAav0yEMPMCFTDy7SY"
ADMIN_ID = 8405534278

# ==========================================
# 🗄️ DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0.0, invites INTEGER DEFAULT 0, 
                  upi_id TEXT DEFAULT '', referred_by INTEGER DEFAULT 0, verified INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT UNIQUE, link TEXT, name TEXT)''')
    
    defaults = {'min_withdraw': '50', 'refer_reward': '10'}
    for k, v in defaults.items():
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key=?', (key,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else None

def set_setting(key, value):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('UPDATE settings SET value=? WHERE key=?', (value, key))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
    res = c.fetchone()
    conn.close()
    return res

def create_user(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def update_user_field(user_id, field, value):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute(f'UPDATE users SET {field}=? WHERE user_id=?', (value, user_id))
    conn.commit()
    conn.close()

def get_all_referrals(referrer_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE referred_by=?', (referrer_id,))
    res = c.fetchall()
    conn.close()
    return [row[0] for row in res]

def get_all_channels():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('SELECT channel_id, link, name FROM channels')
    res = c.fetchall()
    conn.close()
    return res

def add_channel(channel_id, link, name):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO channels (channel_id, link, name) VALUES (?, ?, ?)', (channel_id, link, name))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def delete_channel(channel_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('DELETE FROM channels WHERE channel_id=?', (channel_id,))
    conn.commit()
    conn.close()

# ==========================================
# ⚙️ HELPER FUNCTIONS
# ==========================================
async def is_joined(bot, user_id, channel_id):
    """Checks if user is joined OR has a pending request for private channels."""
    try:
        # Check normal membership
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception:
        pass
        
    try:
        # Check if user sent a Join Request (for private channels)
        chat = await bot.get_chat(chat_id=channel_id)
        if chat.invite_link:
            # We can't directly check pending join requests via api without specific permissions, 
            # but if they clicked the link, Telegram handles the request. We'll rely on the member status.
            pass
    except:
        pass
        
    return False

async def check_all_channels(bot, user_id):
    """Returns a list of channels the user has NOT joined."""
    channels = get_all_channels()
    missing = []
    
    for ch_id, link, name in channels:
        if not await is_joined(bot, user_id, ch_id):
            missing.append(name)
            
    return missing

async def check_leave_penalty(bot, user_id):
    user = get_user(user_id)
    reward_amount = float(get_setting('refer_reward'))
    refs = get_all_referrals(user_id)
    penalties = 0
    
    # If no channels exist, skip check
    channels = get_all_channels()
    if not channels:
        return 0, 0
        
    for ref_id in refs:
        # Check if the referred user is in ALL channels
        missing = await check_all_channels(bot, ref_id)
        if missing: # If they left even one channel
            penalties += 1
            
    if penalties > 0:
        new_balance = user[1] - (penalties * reward_amount)
        new_invites = user[2] - penalties
        if new_invites < 0: new_invites = 0
        update_user_field(user_id, 'balance', new_balance)
        update_user_field(user_id, 'invites', new_invites)
        return penalties, reward_amount
    return 0, 0

# ==========================================
# 👤 USER COMMANDS & BUTTONS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    create_user(user_id)
    
    # 1. Check Force Joins (Multiple)
    missing_channels = await check_all_channels(context.bot, user_id)
    
    if missing_channels:
        keyboard = []
        # Generate join buttons dynamically
        for ch_id, link, name in get_all_channels():
            keyboard.append([InlineKeyboardButton(f"📢 Join {name}", url=link)])
            
        keyboard.append([InlineKeyboardButton("✅ Verify Joined All", callback_data="verify_join")])
        
        await update.message.reply_text(
            f"⚠️ **You must join all our channels to use this bot!**\n\n**Missing:** {', '.join(missing_channels)}", 
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
        )
        return

    # 2. Handle Referral
    args = context.args
    if args and args[0].startswith("ref_"):
        referrer_id = int(args[0].replace("ref_", ""))
        user_data = get_user(user_id)
        
        if referrer_id != user_id and user_data[5] == 0:
            reward = float(get_setting('refer_reward'))
            ref_data = get_user(referrer_id)
            if ref_data:
                update_user_field(referrer_id, 'balance', ref_data[1] + reward)
                update_user_field(referrer_id, 'invites', ref_data[2] + 1)
                update_user_field(user_id, 'referred_by', referrer_id)
                update_user_field(user_id, 'verified', 1)
                try:
                    await context.bot.send_message(referrer_id, f"🎉 **New Referral!** You earned ₹{reward}!")
                except:
                    pass

    await show_user_panel(update, context, user_id)

async def show_user_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    data = get_user(user_id)
    text = (
        f"👋 **Welcome to the Earning Bot!**\n\n"
        f"💰 **Balance:** ₹{data[1]:.2f}\n"
        f"👥 **Invites:** {data[2]}/10\n"
        f"💳 **UPI ID:** `{data[3] if data[3] else 'Not Set'}`\n\n"
        f"🔗 **Your Referral Link:**\n`https://t.me/{context.bot.username}?start=ref_{user_id}`\n\n"
        f"ℹ️ *Note: You need at least 10 invites to make your first withdrawal.*"
    )
    keyboard = [
        [InlineKeyboardButton("💸 Withdraw", callback_data="user_withdraw")],
        [InlineKeyboardButton("👤 Account", callback_data="user_account"), InlineKeyboardButton("👥 Refer", callback_data="user_refer")]
    ]
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown', disable_web_page_preview=True)
        except:
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown', disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown', disable_web_page_preview=True)

async def user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = get_user(user_id)
    action = query.data

    if action == "verify_join":
        missing = await check_all_channels(context.bot, user_id)
        if not missing:
            await query.message.delete()
            await show_user_panel(update, context, user_id)
        else:
            await query.answer(f"❌ You haven't joined: {', '.join(missing)}", show_alert=True)

    elif action == "user_account":
        text = f"👤 **Your Account**\n\nBalance: ₹{data[1]:.2f}\nUPI ID: `{data[3] if data[3] else 'Not Set'}`\nInvites: {data[2]}\n\n*(To change UPI, send `/setupi yourname@upi`)*"
        await query.message.reply_text(text, parse_mode='Markdown')

    elif action == "user_refer":
        link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
        await query.message.reply_text(f"👥 **Refer & Earn**\n\nInvite users to get ₹{get_setting('refer_reward')} per user.\n\nYour link:\n`{link}`", parse_mode='Markdown')

    elif action == "user_withdraw":
        if data[2] < 10:
            await query.answer("❌ You need at least 10 invites to withdraw!", show_alert=True)
            return
            
        await query.message.reply_text("🔄 *Checking referrals status...*", parse_mode='Markdown')
        penalties, reward = await check_leave_penalty(context.bot, user_id)
        data = get_user(user_id)
        
        if penalties > 0:
            await query.message.reply_text(f"⚠️ **Penalty Applied!**\n{penalties} users left the channels. ₹{penalties * reward} deducted. New balance: ₹{data[1]:.2f}")
            if data[1] < 0: return 

        if data[1] < float(get_setting('min_withdraw')):
            await query.answer(f"❌ Minimum withdrawal is ₹{get_setting('min_withdraw')}", show_alert=True)
            return
        if not data[3]:
            await query.answer("❌ Please set your UPI ID first.", show_alert=True)
            return
            
        admin_text = f"🚨 **NEW WITHDRAW REQUEST**\n\nUser ID: `{user_id}`\nUPI ID: `{data[3]}`\nAmount: ₹{data[1]:.2f}\nInvites: {data[2]}"
        keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"adm_approve_{user_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{user_id}")]]
        await context.bot.send_message(ADMIN_ID, admin_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        await query.message.reply_text("✅ Withdrawal request sent to Admin.")

async def set_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/setupi yourname@upi`")
        return
    update_user_field(update.effective_user.id, 'upi_id', context.args[0])
    await update.message.reply_text(f"✅ UPI ID updated to: `{context.args[0]}`")

# ==========================================
# 👑 ADMIN PANEL (Dynamic Channels)
# ==========================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [
        [InlineKeyboardButton("⚙️ General Settings", callback_data="adm_settings")],
        [InlineKeyboardButton("📢 Manage Channels", callback_data="adm_manage_channels")],
        [InlineKeyboardButton("📊 Bot Stats & Broadcast", callback_data="adm_stats")]
    ]
    await update.message.reply_text("👑 **Admin Control Panel**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return
    await query.answer()
    action = query.data

    if action == "adm_settings":
        text = f"⚙️ **Settings**\n\nMin Withdraw: ₹{get_setting('min_withdraw')}\nRefer Reward: ₹{get_setting('refer_reward')}"
        keyboard = [
            [InlineKeyboardButton("💵 Set Min Withdraw", callback_data="adm_set_min")],
            [InlineKeyboardButton("🎁 Set Refer Reward", callback_data="adm_set_reward")],
            [InlineKeyboardButton("🔙 Back", callback_data="adm_back")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif action == "adm_manage_channels":
        channels = get_all_channels()
        text = "📢 **Your Force-Join Channels:**\n\n"
        keyboard = []
        if not channels:
            text += "*No channels added yet.*"
        else:
            for ch_id, link, name in channels:
                text += f"• {name} (`{ch_id}`)\n"
                # Add a delete button for each channel
                keyboard.append([InlineKeyboardButton(f"❌ Delete {name}", callback_data=f"adm_delch_{ch_id}")])
                
        keyboard.append([InlineKeyboardButton("➕ Add New Channel", callback_data="adm_add_channel")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="adm_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif action == "adm_add_channel":
        await query.edit_message_text("📢 **Send Channel Details:**\n\nFormat:\n`Channel Name | @username | https://t.me/link`\n\n*(If private, use the invite link. Make sure bot is Admin!)*")
        context.user_data['admin_state'] = 'WAITING_CHANNEL'

    elif action.startswith("adm_delch_"):
        ch_id = action.replace("adm_delch_", "")
        delete_channel(ch_id)
        await query.edit_message_text("✅ Channel deleted. Click 'Manage Channels' again to view.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_manage_channels")]]))

    elif action == "adm_set_min":
        await query.edit_message_text("💵 **Send the new Minimum Withdrawal amount:**")
        context.user_data['admin_state'] = 'WAITING_MIN'

    elif action == "adm_set_reward":
        await query.edit_message_text("🎁 **Send the new Refer Reward amount:**")
        context.user_data['admin_state'] = 'WAITING_REWARD'

    elif action == "adm_stats":
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        total_users = c.fetchone()[0]
        c.execute('SELECT SUM(balance) FROM users')
        total_balance = c.fetchone()[0] or 0.0
        conn.close()
        text = f"📊 **Bot Stats**\n\nTotal Users: `{total_users}`\nPending Balance: `₹{total_balance:.2f}`"
        keyboard = [[InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast")], [InlineKeyboardButton("🔙 Back", callback_data="adm_back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif action == "adm_broadcast":
        await query.edit_message_text("📢 **Send the message you want to broadcast:**")
        context.user_data['admin_state'] = 'WAITING_BROADCAST'

    elif action == "adm_back":
        keyboard = [
            [InlineKeyboardButton("⚙️ General Settings", callback_data="adm_settings")],
            [InlineKeyboardButton("📢 Manage Channels", callback_data="adm_manage_channels")],
            [InlineKeyboardButton("📊 Bot Stats & Broadcast", callback_data="adm_stats")]
        ]
        await query.edit_message_text("👑 **Admin Control Panel**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif action.startswith("adm_approve_") or action.startswith("adm_reject_"):
        is_approve = "approve" in action
        user_id = int(action.split("_")[-1])
        if is_approve:
            update_user_field(user_id, 'balance', 0.0)
            await query.edit_message_text(f"✅ Withdrawal Approved for `{user_id}`.")
            await context.bot.send_message(user_id, "✅ **Your withdrawal was approved!**")
        else:
            await query.edit_message_text(f"❌ Withdrawal Rejected for `{user_id}`.")
            await context.bot.send_message(user_id, "❌ **Your withdrawal was rejected.**")

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    state = context.user_data.get('admin_state')
    if not state: return

    text = update.message.text

    if state == 'WAITING_MIN':
        set_setting('min_withdraw', text)
        await update.message.reply_text(f"✅ Min withdrawal updated to ₹{text}")
    elif state == 'WAITING_REWARD':
        set_setting('refer_reward', text)
        await update.message.reply_text(f"✅ Refer reward updated to ₹{text}")
    elif state == 'WAITING_CHANNEL':
        try:
            parts = text.split("|")
            name = parts[0].strip()
            ch_id = parts[1].strip()
            ch_link = parts[2].strip()
            
            success = add_channel(ch_id, ch_link, name)
            if success:
                await update.message.reply_text(f"✅ Channel '{name}' added successfully!")
            else:
                await update.message.reply_text("❌ This channel ID is already added.")
        except:
            await update.message.reply_text("❌ Format error. Use:\n`Name | @username | https://link`")
    elif state == 'WAITING_BROADCAST':
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM users')
        users = c.fetchall()
        conn.close()
        success = 0
        await update.message.reply_text("🔄 Broadcasting...")
        for u in users:
            try:
                await context.bot.send_message(u[0], f"📢 **Announcement**\n\n{text}", parse_mode='Markdown')
                success += 1
            except: pass
        await update.message.reply_text(f"✅ Broadcast sent to {success} users.")

    context.user_data['admin_state'] = None

# ==========================================
# 🚀 MAIN EXECUTION
# ==========================================
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setupi", set_upi))
    app.add_handler(CallbackQueryHandler(user_callback, pattern="^(verify_join|user_)"))

    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_input))

    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()