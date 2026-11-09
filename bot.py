import json
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters
)

# ==========================================
# ⚠️ CONFIGURATION - CHANGE THESE VALUES ⚠️
# ==========================================
BOT_TOKEN = "9100672101:AAFLOl1CxIMYft8DVpAav0yEMPMCFTDy7SY"  # Get from @BotFather
ADMIN_ID = 8405534278               # Get from @userinfobot
CONFIG_FILE = "config.json"

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# ⚙️ HELPER FUNCTIONS
# ==========================================
def load_config():
    """Loads settings from config.json. Creates default if missing."""
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "channels": [],
            "app_link": "https://your-app-link.com",
            "photo_file_id": "",
            "caption": "<b>Payment</b>\n\nOMG 🤯 :- Fully New 10% Commission Buy/Sell App Launched 🎯🔥🔥\n\n📌 Commission - 10% 💰💰\n📌 Sign-up Bonus - 500₹ 💰💰\n\n📢 <b>For App Link, Must Join All Channel's</b>\n👇👇👇👇👇👇👇👇👇👇"
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=4)
        return default_config
    
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(config):
    """Saves settings to config.json."""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)

async def is_user_member(bot, user_id: int, channel_id: str) -> bool:
    """Checks if a user is a member of a specific channel."""
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        # If status is 'left' or 'kicked', they are not a member
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking membership for {channel_id}: {e}")
        # If the bot isn't admin, it will throw an error. We assume False to be safe.
        return False

# ==========================================
# 👤 USER COMMANDS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command and shows the main menu."""
    config = load_config()
    
    # Build the Inline Keyboard dynamically
    keyboard = []
    
    # Add Join Buttons (Max 2 per row)
    channel_buttons = []
    for ch in config['channels']:
        channel_buttons.append(InlineKeyboardButton(f"🔒 {ch['name']}", url=ch['url']))
    
    for i in range(0, len(channel_buttons), 2):
        keyboard.append(channel_buttons[i:i+2])
        
    # Add the main "Get App" button at the bottom
    keyboard.append([InlineKeyboardButton("💰 Get 10% App ✅", callback_data="verify_join")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send photo if admin set one, otherwise send text
    if config.get('photo_file_id'):
        await update.message.reply_photo(
            photo=config['photo_file_id'],
            caption=config['caption'],
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            text=config['caption'],
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

async def verify_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers when user clicks 'Get App'. Checks if they joined all channels."""
    query = update.callback_query
    await query.answer() # Stop the loading animation
    
    config = load_config()
    user_id = query.from_user.id
    
    if not config['channels']:
        # If no channels are set, just give the link
        await query.message.reply_text(
            f"✅ Here is your app link:\n{config['app_link']}", 
            disable_web_page_preview=True
        )
        return

    # Check all channels
    missing_channels = []
    for ch in config['channels']:
        joined = await is_user_member(context.bot, user_id, ch['id'])
        if not joined:
            missing_channels.append(ch['name'])
            
    if not missing_channels:
        # Success!
        await query.message.reply_text(
            f"✅ Verification successful!\n\nHere is your app link:\n{config['app_link']}",
            disable_web_page_preview=True
        )
    else:
        # Failed
        await query.answer(
            f"⚠️ You must join all channels first!\n\nMissing: {', '.join(missing_channels)}", 
            show_alert=True
        )

# ==========================================
# 👑 ADMIN COMMANDS
# ==========================================
async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows admin commands."""
    if update.effective_user.id != ADMIN_ID: return
    text = (
        "👑 **Admin Panel**\n\n"
        "**Commands:**\n"
        "1. Reply to an image with `/setphoto`\n"
        "2. Reply to a text message with `/setcaption`\n"
        "3. `/setchannel Name | Link | @username`\n"
        "4. `/clearchannels` - Removes all channels\n"
        "5. `/setlink https://...` - Set app link\n"
        "6. `/viewconfig` - See current JSON"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def set_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("❌ Reply to a photo with `/setphoto`")
        return
    
    # Get highest quality photo
    file_id = update.message.reply_to_message.photo[-1].file_id
    config = load_config()
    config['photo_file_id'] = file_id
    save_config(config)
    await update.message.reply_text("✅ Photo updated successfully!")

async def set_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        await update.message.reply_text("❌ Reply to a text message with `/setcaption`")
        return
    
    config = load_config()
    config['caption'] = update.message.reply_to_message.text
    save_config(config)
    await update.message.reply_text("✅ Caption updated successfully!")

async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    try:
        # Format: /setchannel Name | Link | @username
        args = " ".join(context.args).split("|")
        name = args[0].strip()
        url = args[1].strip()
        channel_id = args[2].strip()
        
        config = load_config()
        config['channels'].append({"name": name, "url": url, "id": channel_id})
        save_config(config)
        await update.message.reply_text(f"✅ Added channel: {name}")
    except Exception:
        await update.message.reply_text("❌ Format error. Use:\n`/setchannel Name | Link | @username`")

async def clear_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    config = load_config()
    config['channels'] = []
    save_config(config)
    await update.message.reply_text("✅ All channels cleared from the bot.")

async def set_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("❌ Use: `/setlink https://your-app-link`")
        return
    
    config = load_config()
    config['app_link'] = context.args[0]
    save_config(config)
    await update.message.reply_text("✅ App link updated.")

async def view_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    config = load_config()
    # Send as code block for easy copying
    await update.message.reply_text(f"```json\n{json.dumps(config, indent=2)}\n```", parse_mode='MarkdownV2')

# ==========================================
# 🚀 MAIN EXECUTION
# ==========================================
def main():
    # Ensure config exists on first run
    load_config()
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()

    # User Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(verify_join_callback, pattern="verify_join"))

    # Admin Handlers
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("setphoto", set_photo))
    app.add_handler(CommandHandler("setcaption", set_caption))
    app.add_handler(CommandHandler("setchannel", set_channel))
    app.add_handler(CommandHandler("clearchannels", clear_channels))
    app.add_handler(CommandHandler("setlink", set_link))
    app.add_handler(CommandHandler("viewconfig", view_config))

    # Start the Bot
    logger.info("Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()