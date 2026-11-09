import sqlite3
import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters
)

# ==========================================
# ⚠️ CONFIGURATION
# ==========================================
BOT_TOKEN = "9100672101:AAFLOl1CxIMYft8DVpAav0yEMPMCFTDy7SY"
ADMIN_ID = 8405534278
DB_FILE = "bot_data.db"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ==========================================
# 🗄️ DATABASE SETUP (Fast & Persistent)
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0.0, invites INTEGER DEFAULT 0, 
                  upi_id TEXT DEFAULT '', referred_by INTEGER DEFAULT 0, verified INTEGER DEFAULT 0,
                  has_penalty INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT UNIQUE, link TEXT, name TEXT)''')
    
    defaults = {'min_withdraw': '50', 'refer_reward': '10'}
    for k, v in defaults.items():
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key=?', (key,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else None

def set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE settings SET value=? WHERE key=?', (value, key))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
    res = c.fetchone()
    conn.close()
    return res

def create_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def update_user_field(user_id, field, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f'UPDATE users SET {field}=? WHERE user_id=?', (value, user_id))
    conn.commit()
    conn.close()

def get_all_referrals(referrer_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE referred_by=?', (referrer_id,))
    res = c.fetchall()
    conn.close()
    return [row[0] for row in res]

def get_all_channels():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT channel_id, link, name FROM channels')
    res = c.fetchall()
    conn.close()
    return res

def add_channel(channel_id, link, name):
    conn = sqlite3.connect(DB_FILE)
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
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('DELETE FROM channels WHERE channel_id=?', (channel_id,))
    conn.commit()
    conn.close()

# ==========================================
# ⚙️ HELPER FUNCTIONS
# ==========================================
async def is_joined(bot, user_id, channel_id):
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def check_all_channels(bot, user_id):
    channels = get_all_channels()
    missing = []
    for ch_id, link, name in channels:
        if not await is_joined(bot, user_id, ch_id):
            missing.append(name)
    return missing

async def check_leave_penalty(bot, user_id):
    """Checks if invited users left and applies negative balance."""
    user = get_user(user_id)
    if not user: return 0
    
    reward_amount = float(get_setting('refer_reward'))
    refs = get_all_referrals(user_id)
    penalties = 0
    
    for ref_id in refs:
        # Check if referred user is still in all channels
        missing = await check_all_channels(bot, ref_id)
        if missing: 
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
# 👤 USER PANEL
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    create_user(user_id)
    
    # 1. Check Force Joins
    missing_channels = await check_all_channels(context.bot, user_id)
    if missing_channels:
        keyboard = []
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
                except: pass

    await show_user_panel(update, context, user_id)

async def show_user_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    data = get_user(user_id)
    
    # Persistent Reply Keyboard (Fixed at bottom)
    reply_keyboard = [
        [KeyboardButton("💸 Withdraw"), KeyboardButton("👤 Account")],
        [KeyboardButton("👥 Refer & Earn"), KeyboardButton("💳 Setup UPI")]
    ]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    
    text = (
        f"👋 **Welcome to the Earning Bot!**\n\n"
        f"💰 **Balance:** ₹{data[1]:.2f}\n"
        f"👥 **Invites:** {data[2]}/10\n"
        f"💳 **UPI ID:** `{data[3] if data[3] else 'Not Set'}`\n\n"
        f"🔗 **Your Referral Link:**\n`https://t.me/{context.bot.username}?start=ref_{user_id}`\n\n"
        f"ℹ️ *Note: You need at least 10 invites to make your first withdrawal.*"
    )
    
    if update.callback_query:
        try: await update.callback_query.edit_message_text(text, parse_mode='Markdown', disable_web_page_preview=True)
        except: await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown', disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown', disable_web_page_preview=True)

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

    elif action == "user_withdraw":
        # 1. Check Invites
        if data[2] < 10:
            await query.answer("❌ You need at least 10 invites to withdraw!", show_alert=True)
            return
            
        # 2. Check Penalty (Leave Channel logic)
        await query.message.reply_text("🔄 *Checking referrals status...*", parse_mode='Markdown')
        penalties, reward = await check_leave_penalty(context.bot, user_id)
        data = get_user(user_id) 
        
        if penalties > 0:
            await query.message.reply_text(f"⚠️ **Penalty Applied!**\n{penalties} users left the channels. ₹{penalties * reward} deducted. New balance: ₹{data[1]:.2f}")
            if data[1] < 0: return 

        # 3. Check Min Withdraw & UPI
        if data[1] < float(get_setting('min_withdraw')):
            await query.answer(f"❌ Minimum withdrawal is ₹{get_setting('min_withdraw')}", show_alert=True)
            return
        if not data[3]:
            await query.answer("❌ Please click '💳 Setup UPI' first.", show_alert=True)
            return
            
        # 4. Send to Admin
        admin_text = f"🚨 **NEW WITHDRAW REQUEST**\n\nUser ID: `{user_id}`\nUPI ID: `{data[3]}`\nAmount: ₹{data[1]:.2f}\nInvites: {data[2]}"
        keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"adm_approve_{user_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{user_id}")]]
        await context.bot.send_message(ADMIN_ID, admin_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        await query.message.reply_text("✅ Withdrawal request sent to Admin. Please wait.")

# ==========================================
# 💬 MESSAGE HANDLER (Buttons & Inputs)
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    data = get_user(user_id)

    if not data: create_user(user_id)

    # --- USER BUTTONS ---
    if text == "💸 Withdraw":
        # Trigger the same logic as the inline callback
        fake_query = type('obj', (object,), {'data': 'user_withdraw', 'from_user': update.effective_user, 'message': update.message, 'answer': lambda *args, **kwargs: None})
        await user_callback(type('obj', (object,), {'callback_query': fake_query})(), context)

    elif text == "👤 Account":
        await update.message.reply_text(
            f"👤 **Your Account**\n\nBalance: ₹{data[1]:.2f}\nUPI ID: `{data[3] if data[3] else 'Not Set'}`\nInvites: {data[2]}",
            parse_mode='Markdown'
        )

    elif text == "👥 Refer & Earn":
        link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
        await update.message.reply_text(f"👥 **Refer & Earn**\n\nInvite users to get ₹{get_setting('refer_reward')} per user.\n\nYour link:\n`{link}`", parse_mode='Markdown')

    elif text == "💳 Setup UPI":
        await update.message.reply_text("💳 **Please reply with your UPI ID:**\n*(Example: yourname@paytm)*")
        context.user_data['user_state'] = 'WAITING_UPI'

    # --- USER INPUTS ---
    elif context.user_data.get('user_state') == 'WAITING_UPI':
        update_user_field(user_id, 'upi_id', text)
        context.user_data['user_state'] = None
        await update.message.reply_text(f"✅ UPI ID updated successfully to: `{text}`", parse_mode='Markdown')

    # --- ADMIN BUTTONS ---
    elif user_id == ADMIN_ID:
        if text == "⚙️ Admin Settings":
            await admin_panel_settings(update, context)
        elif text == "📢 Manage Channels":
            await admin_manage_channels(update, context)
        elif text == "📊 Stats & Broadcast":
            await admin_stats(update, context)
        
        # --- ADMIN INPUTS ---
        elif context.user_data.get('admin_state'):
            state = context.user_data['admin_state']
            if state == 'WAITING_MIN':
                set_setting('min_withdraw', text)
                await update.message.reply_text(f"✅ Min withdrawal updated to ₹{text}")
            elif state == 'WAITING_REWARD':
                set_setting('refer_reward', text)
                await update.message.reply_text(f"✅ Refer reward updated to ₹{text}")
            elif state == 'WAITING_CHANNEL':
                try:
                    name, ch_id, ch_link = [p.strip() for p in text.split("|")]
                    if add_channel(ch_id, ch_link, name):
                        await update.message.reply_text(f"✅ Channel '{name}' added successfully!")
                    else:
                        await update.message.reply_text("❌ This channel ID is already added.")
                except:
                    await update.message.reply_text("❌ Format error. Use:\n`Name | @username | https://link`", parse_mode='Markdown')
            elif state == 'WAITING_BROADCAST':
                conn = sqlite3.connect(DB_FILE)
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
# 👑 ADMIN PANEL (Persistent)
# ==========================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    reply_keyboard = [
        [KeyboardButton("⚙️ Admin Settings"), KeyboardButton("📢 Manage Channels")],
        [KeyboardButton("📊 Stats & Broadcast")]
    ]
    await update.message.reply_text("👑 **Admin Panel Activated**\nUse the buttons below:", reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True), parse_mode='Markdown')

async def admin_panel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"⚙️ **Current Settings**\n\nMin Withdraw: ₹{get_setting('min_withdraw')}\nRefer Reward: ₹{get_setting('refer_reward')}"
    keyboard = [
        [InlineKeyboardButton("💵 Set Min Withdraw", callback_data="adm_set_min")],
        [InlineKeyboardButton("🎁 Set Refer Reward", callback_data="adm_set_reward")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_manage_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = get_all_channels()
    text = "📢 **Your Force-Join Channels:**\n\n"
    keyboard = []
    if not channels:
        text += "*No channels added yet.*"
    else:
        for ch_id, link, name in channels:
            text += f"• {name} (`{ch_id}`)\n"
            keyboard.append([InlineKeyboardButton(f"❌ Delete {name}", callback_data=f"adm_delch_{ch_id}")])
    keyboard.append([InlineKeyboardButton("➕ Add New Channel", callback_data="adm_add_channel")])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]
    c.execute('SELECT SUM(balance) FROM users')
    total_balance = c.fetchone()[0] or 0.0
    conn.close()
    text = f"📊 **Bot Stats**\n\nTotal Users: `{total_users}`\nPending Balance: `₹{total_balance:.2f}`"
    keyboard = [[InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return
    await query.answer()
    action = query.data

    if action == "adm_set_min":
        await query.edit_message_text("💵 **Send the new Minimum Withdrawal amount:**")
        context.user_data['admin_state'] = 'WAITING_MIN'
    elif action == "adm_set_reward":
        await query.edit_message_text("🎁 **Send the new Refer Reward amount:**")
        context.user_data['admin_state'] = 'WAITING_REWARD'
    elif action == "adm_add_channel":
        await query.edit_message_text("📢 **Send Channel Details:**\n\nFormat:\n`Channel Name | @username | https://t.me/link`")
        context.user_data['admin_state'] = 'WAITING_CHANNEL'
    elif action == "adm_broadcast":
        await query.edit_message_text("📢 **Send the message you want to broadcast:**")
        context.user_data['admin_state'] = 'WAITING_BROADCAST'
    elif action.startswith("adm_delch_"):
        ch_id = action.replace("adm_delch_", "")
        delete_channel(ch_id)
        await query.edit_message_text("✅ Channel deleted. (Send /admin to see updated list)")
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

# ==========================================
# 🚀 MAIN EXECUTION
# ==========================================
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(user_callback, pattern="^(verify_join)"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    
    # Main message handler for all buttons and text inputs
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running FAST...")
    # Removed drop_pending_updates to make it respond instantly
    app.run_polling() 

if __name__ == "__main__":
    main()