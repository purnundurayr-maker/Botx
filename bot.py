import sqlite3
import logging
import urllib.request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters
)

# ==========================================
# ⚠️ CONFIGURATION - CHANGE THESE VALUES ⚠️
# ==========================================
BOT_TOKEN = "9100672101:AAFLOl1CxIMYft8DVpAav0yEMPMCFTDy7SY"
ADMIN_ID = 8405534278  # Your Telegram ID

# ==========================================
# 🗄️ DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  balance REAL DEFAULT 0.0, 
                  invites INTEGER DEFAULT 0, 
                  upi_id TEXT DEFAULT '', 
                  referred_by INTEGER DEFAULT 0,
                  verified INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    
    defaults = {
        'force_channel_id': '@your_channel',
        'force_channel_link': 'https://t.me/your_channel',
        'min_withdraw': '50',
        'refer_reward': '10'
    }
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

# ==========================================
# ⚙️ HELPER FUNCTIONS
# ==========================================
async def is_joined(bot, user_id, channel_id):
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def check_leave_penalty(bot, user_id):
    """Checks if invited users left the channel and applies negative balance penalty."""
    user = get_user(user_id)
    reward_amount = float(get_setting('refer_reward'))
    force_channel = get_setting('force_channel_id')
    
    refs = get_all_referrals(user_id)
    penalties = 0
    
    for ref_id in refs:
        joined = await is_joined(bot, ref_id, force_channel)
        if not joined:
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
    
    force_channel = get_setting('force_channel_id')
    force_link = get_setting('force_channel_link')
    
    # 1. Check Force Join
    if not await is_joined(context.bot, user_id, force_channel):
        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=force_link)],
            [InlineKeyboardButton("✅ Verify", callback_data="verify_join")]
        ]
        await update.message.reply_text("⚠️ **You must join our channel to use this bot!**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # 2. Handle Referral
    args = context.args
    if args and args[0].startswith("ref_"):
        referrer_id = int(args[0].replace("ref_", ""))
        user_data = get_user(user_id)
        
        if referrer_id != user_id and user_data[5] == 0: # 0 means not referred yet
            reward = float(get_setting('refer_reward'))
            ref_data = get_user(referrer_id)
            
            if ref_data:
                update_user_field(referrer_id, 'balance', ref_data[1] + reward)
                update_user_field(referrer_id, 'invites', ref_data[2] + 1)
                update_user_field(user_id, 'referred_by', referrer_id)
                update_user_field(user_id, 'verified', 1)
                
                try:
                    await context.bot.send_message(referrer_id, f"🎉 **New Referral!**\nSomeone joined using your link. You earned ₹{reward}!")
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
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown', disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown', disable_web_page_preview=True)

async def user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = get_user(user_id)
    action = query.data

    if action == "verify_join":
        if await is_joined(context.bot, user_id, get_setting('force_channel_id')):
            await query.message.delete()
            await show_user_panel(update, context, user_id)
        else:
            await query.answer("❌ You haven't joined the channel yet!", show_alert=True)

    elif action == "user_account":
        text = (
            f"👤 **Your Account**\n\n"
            f"Balance: ₹{data[1]:.2f}\n"
            f"UPI ID: `{data[3] if data[3] else 'Not Set'}`\n"
            f"Invites: {data[2]}\n\n"
            f"*(To change UPI, send `/setupi yourname@upi` in chat)*"
        )
        await query.message.reply_text(text, parse_mode='Markdown')

    elif action == "user_refer":
        link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
        await query.message.reply_text(f"👥 **Refer & Earn**\n\nInvite users to get ₹{get_setting('refer_reward')} per user.\n\nYour link:\n`{link}`", parse_mode='Markdown')

    elif action == "user_withdraw":
        if data[2] < 10:
            await query.answer("❌ You need at least 10 invites to withdraw!", show_alert=True)
            return
            
        # Automatic Leave Penalty Check
        await query.message.reply_text("🔄 *Checking referrals status...*", parse_mode='Markdown')
        penalties, reward = await check_leave_penalty(context.bot, user_id)
        data = get_user(user_id) # refresh data
        
        if penalties > 0:
            await query.message.reply_text(f"⚠️ **Penalty Applied!**\n{penalties} users left the channel. ₹{penalties * reward} has been deducted from your balance. Your new balance is ₹{data[1]:.2f}.")
            if data[1] < 0:
                return # Stop them if balance is negative

        if data[1] < float(get_setting('min_withdraw')):
            await query.answer(f"❌ Minimum withdrawal is ₹{get_setting('min_withdraw')}", show_alert=True)
            return
            
        if not data[3]:
            await query.answer("❌ Please set your UPI ID in the Account section first.", show_alert=True)
            return
            
        # Send request to admin
        admin_text = (
            f"🚨 **NEW WITHDRAW REQUEST**\n\n"
            f"User ID: `{user_id}`\n"
            f"UPI ID: `{data[3]}`\n"
            f"Amount: ₹{data[1]:.2f}\n"
            f"Invites: {data[2]}"
        )
        keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"adm_approve_{user_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{user_id}")]]
        await context.bot.send_message(ADMIN_ID, admin_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        await query.message.reply_text("✅ Withdrawal request sent to Admin. Please wait.")

async def set_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/setupi yourname@upi`")
        return
    upi = context.args[0]
    update_user_field(update.effective_user.id, 'upi_id', upi)
    await update.message.reply_text(f"✅ UPI ID updated to: `{upi}`")

# ==========================================
# 👑 ADMIN PANEL (Button Driven)
# ==========================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    text = "👑 **Admin Control Panel**\nSelect an option below:"
    keyboard = [
        [InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="adm_stats")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return
    await query.answer()
    action = query.data

    if action == "adm_settings":
        text = (
            f"⚙️ **Current Settings**\n\n"
            f"Min Withdraw: ₹{get_setting('min_withdraw')}\n"
            f"Refer Reward: ₹{get_setting('refer_reward')}\n"
            f"Force Channel: `{get_setting('force_channel_id')}`\n"
        )
        keyboard = [
            [InlineKeyboardButton("💵 Set Min Withdraw", callback_data="adm_set_min")],
            [InlineKeyboardButton("🎁 Set Refer Reward", callback_data="adm_set_reward")],
            [InlineKeyboardButton("📢 Set Force Channel", callback_data="adm_set_channel")],
            [InlineKeyboardButton("🔙 Back", callback_data="adm_back")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif action == "adm_set_min":
        await query.edit_message_text("💵 **Send the new Minimum Withdrawal amount:**\n*(Example: `100`)*")
        context.user_data['admin_state'] = 'WAITING_MIN'

    elif action == "adm_set_reward":
        await query.edit_message_text("🎁 **Send the new Refer Reward amount:**\n*(Example: `15`)*")
        context.user_data['admin_state'] = 'WAITING_REWARD'

    elif action == "adm_set_channel":
        await query.edit_message_text("📢 **Send Channel Details:**\n\nFormat:\n`@username | https://t.me/link`\n\n*(Make sure the bot is Admin in this channel!)*")
        context.user_data['admin_state'] = 'WAITING_CHANNEL'

    elif action == "adm_broadcast":
        await query.edit_message_text("📢 **Send the message you want to broadcast to all users:**")
        context.user_data['admin_state'] = 'WAITING_BROADCAST'

    elif action == "adm_stats":
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        total_users = c.fetchone()[0]
        c.execute('SELECT SUM(balance) FROM users')
        total_balance = c.fetchone()[0] or 0.0
        conn.close()
        
        text = f"📊 **Bot Statistics**\n\nTotal Users: `{total_users}`\nTotal Balance Pending: `₹{total_balance:.2f}`"
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="adm_back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif action == "adm_back":
        text = "👑 **Admin Control Panel**\nSelect an option below:"
        keyboard = [
            [InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast")],
            [InlineKeyboardButton("📊 Bot Stats", callback_data="adm_stats")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    # Handle Approve / Reject
    elif action.startswith("adm_approve_") or action.startswith("adm_reject_"):
        is_approve = "approve" in action
        user_id = int(action.split("_")[-1])
        
        if is_approve:
            update_user_field(user_id, 'balance', 0.0)
            await query.edit_message_text(f"✅ Withdrawal Approved for `{user_id}`. Balance reset to 0.")
            await context.bot.send_message(user_id, "✅ **Your withdrawal was approved and sent!**")
        else:
            await query.edit_message_text(f"❌ Withdrawal Rejected for `{user_id}`.")
            await context.bot.send_message(user_id, "❌ **Your withdrawal request was rejected. Please contact support.**")

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
            ch_id = parts[0].strip()
            ch_link = parts[1].strip()
            set_setting('force_channel_id', ch_id)
            set_setting('force_channel_link', ch_link)
            await update.message.reply_text(f"✅ Force channel updated to {ch_id}")
        except:
            await update.message.reply_text("❌ Format error. Use: `@username | https://link`")
    elif state == 'WAITING_BROADCAST':
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM users')
        users = c.fetchall()
        conn.close()
        
        success = 0
        await update.message.reply_text("🔄 Broadcasting started...")
        for u in users:
            try:
                await context.bot.send_message(u[0], f"📢 **Announcement**\n\n{text}", parse_mode='Markdown')
                success += 1
            except:
                pass
        await update.message.reply_text(f"✅ Broadcast sent to {success} users.")

    context.user_data['admin_state'] = None

# ==========================================
# 🚀 MAIN EXECUTION
# ==========================================
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # User Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setupi", set_upi))
    app.add_handler(CallbackQueryHandler(user_callback, pattern="^(verify_join|user_)"))

    # Admin Handlers
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_input))

    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()