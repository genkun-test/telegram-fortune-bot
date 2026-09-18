"""
Telegram Fortune Bot - Autonomous Fortune Generation & Sales
Free tier: Haiku 4.5 | Premium tier: Fable 5.1
"""

import os
import json
import asyncio
from datetime import datetime, time
from typing import Optional
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError
import anthropic
import pytz
from zoneinfo import ZoneInfo

# ============================================================================
# Configuration
# ============================================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]  # 未設定なら起動時に落とす（環境変数のみ）
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Database file (simple JSON)
USER_DB = "users.json"
JAPAN_TZ = pytz.timezone("Asia/Tokyo")
DAILY_SEND_TIME = time(7, 0, tzinfo=ZoneInfo("Asia/Tokyo"))  # 7 AM JST

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # URLにBotトークンが含まれるためログに出さない
logger = logging.getLogger(__name__)

# ============================================================================
# Database Management
# ============================================================================

def load_users() -> dict:
    """Load user database from JSON file."""
    if os.path.exists(USER_DB):
        with open(USER_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(users: dict):
    """Save user database to JSON file."""
    with open(USER_DB, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def add_user(user_id: int, birth_date: str, is_premium: bool = False):
    """Add or update user."""
    users = load_users()
    users[str(user_id)] = {
        "birth_date": birth_date,  # Format: YYYY-MM-DD or YYYY-MM-DD HH:MM
        "is_premium": is_premium,
        "registered_at": datetime.now().isoformat(),
        "last_fortune": None
    }
    save_users(users)

def get_user(user_id: int) -> Optional[dict]:
    """Get user data."""
    users = load_users()
    return users.get(str(user_id))

def update_premium(user_id: int, is_premium: bool):
    """Update user premium status."""
    users = load_users()
    if str(user_id) in users:
        users[str(user_id)]["is_premium"] = is_premium
        save_users(users)

# ============================================================================
# Fortune Generation with Claude
# ============================================================================

def generate_fortune(birth_date: str, is_premium: bool = False) -> str:
    """
    Generate personalized fortune using Claude.

    Args:
        birth_date: Birth date in format "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
        is_premium: Use Fable 5.1 for premium, Haiku 4.5 for free

    Returns:
        Generated fortune text
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    model = "claude-fable-5-1" if is_premium else "claude-haiku-4-5-20251001"

    prompt = f"""あなたは経験豊かな占い師です。ユーザーの生年月日に基づいて、今日の運勢を占ってください。

【ユーザーの生年月日】
{birth_date}

【今日の日付】
{datetime.now(JAPAN_TZ).strftime('%Y年%m月%d日')}

以下の要素を含めて、詳しく占ってください：
1. 今日の全体運
2. 仕事運
3. 金運
4. 恋愛運
5. 健康運
6. 今日のアドバイス/ラッキーアイテム

形式：
- 簡潔で読みやすく
- 前向きで希望的なメッセージ
- 絵文字は適度に使用

{"(プレミアム版は、より深い分析と詳細なアドバイスを含めてください)" if is_premium else ""}"""

    message = client.messages.create(
        model=model,
        max_tokens=1024 if is_premium else 512,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return message.content[0].text

# ============================================================================
# Telegram Bot Handlers
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_id = update.effective_user.id

    # Check if user already registered
    existing_user = get_user(user_id)
    if existing_user:
        await update.message.reply_text(
            f"ようこそ！👋\n\n"
            f"登録済みの生年月日: {existing_user['birth_date']}\n"
            f"ステータス: {'プレミアム ✨' if existing_user['is_premium'] else '無料'}\n\n"
            f"コマンド:\n"
            f"/today - 今日の占い\n"
            f"/premium - プレミアムに登録\n"
            f"/help - ヘルプ"
        )
        return

    # New user - ask for birth date
    await update.message.reply_text(
        "🌟 Daily Fortune Bot へようこそ！\n\n"
        "あなたの生年月日を教えてください。\n"
        "形式: YYYY-MM-DD (例: 1998-12-27)\n\n"
        "出生時刻がわかれば、さらに詳しく占えます:\n"
        "形式: YYYY-MM-DD HH:MM (例: 1998-12-27 14:30)\n\n"
        "時刻なしでも OK です。"
    )
    context.user_data["awaiting_birthdate"] = True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user messages (birth date input)."""
    user_id = update.effective_user.id
    text = update.message.text

    if context.user_data.get("awaiting_birthdate"):
        # Validate birth date format
        try:
            if len(text.split()) == 1:
                datetime.strptime(text, "%Y-%m-%d")
            else:
                datetime.strptime(text, "%Y-%m-%d %H:%M")

            # Save user
            add_user(user_id, text, is_premium=False)

            await update.message.reply_text(
                f"✨ 登録完了！\n\n"
                f"生年月日: {text}\n"
                f"毎日朝7時に占いを送ります。\n\n"
                f"コマンド:\n"
                f"/today - 今すぐ占いを見る\n"
                f"/premium - プレミアム登録 (月額 480円)\n"
                f"/help - ヘルプ"
            )
            context.user_data["awaiting_birthdate"] = False

        except ValueError:
            await update.message.reply_text(
                "❌ 形式が正しくありません。\n"
                "YYYY-MM-DD または YYYY-MM-DD HH:MM で入力してください。"
            )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate today's fortune."""
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user:
        await update.message.reply_text("❌ まず /start で登録してください。")
        return

    # Show loading message
    msg = await update.message.reply_text("🔮 占い中...")

    try:
        # Generate fortune
        fortune = generate_fortune(user["birth_date"], user["is_premium"])

        # Build response with buttons
        keyboard = [
            [InlineKeyboardButton("💰 応援する (投げ銭)", callback_data="donate")],
            [InlineKeyboardButton("⭐ プレミアム登録", callback_data="premium")],
            [InlineKeyboardButton("🏪 関連グッズ", callback_data="affiliate")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Edit message with fortune
        fortune_text = (
            f"✨ {update.effective_user.first_name}さんの今日の占い\n"
            f"{datetime.now(JAPAN_TZ).strftime('%Y年%m月%d日')}\n\n"
            f"{fortune}\n\n"
            f"{'🌟 プレミアム版' if user['is_premium'] else '📌 無料版'}"
        )

        await msg.edit_text(fortune_text, reply_markup=reply_markup)

        # Update last fortune timestamp
        users = load_users()
        users[str(user_id)]["last_fortune"] = datetime.now().isoformat()
        save_users(users)

    except Exception as e:
        logger.error(f"Error generating fortune: {e}")
        await msg.edit_text("❌ エラーが発生しました。しばらくしてからもう一度お試しください。")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()

    if query.data == "donate":
        await query.edit_message_text(
            "💰 応援ありがとうございます！\n\n"
            "Stripe または PayPal でのご支援も受け付けています。\n"
            "[寄付ページ] (準備中)\n\n"
            "ご支援は、より詳しい占い生成と、サービス改善に使わせていただきます。"
        )

    elif query.data == "premium":
        keyboard = [
            [InlineKeyboardButton("登録する", url="https://buy.stripe.com/test")],
            [InlineKeyboardButton("キャンセル", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "⭐ プレミアムプラン\n\n"
            "月額: 480円\n\n"
            "【プレミアム限定】\n"
            "🔮 Fable 5.1 による深い占い分析\n"
            "📊 より詳細な運勢予測\n"
            "💫 ラッキーアイテムの詳しい説明\n"
            "🎯 カスタマイズされたアドバイス\n\n"
            "毎月自動更新。いつでもキャンセル可能。",
            reply_markup=reply_markup
        )

    elif query.data == "affiliate":
        keyboard = [
            [InlineKeyboardButton("パワーストーン", url="https://amazon.co.jp")],
            [InlineKeyboardButton("占い本", url="https://amazon.co.jp")],
            [InlineKeyboardButton("キャンセル", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "🏪 関連商品\n\n"
            "今日の占いにピッタリな商品をセレクト！\n"
            "(Amazon アフィリエイト)",
            reply_markup=reply_markup
        )

    elif query.data == "cancel":
        await query.edit_message_text("キャンセルしました。")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message."""
    await update.message.reply_text(
        "📖 ヘルプ\n\n"
        "/start - 登録\n"
        "/today - 今日の占いを見る\n"
        "/premium - プレミアム登録\n"
        "/help - このメッセージ\n\n"
        "毎日朝7時（日本時間）に、自動で占い結果をお送りします。"
    )

async def scheduled_fortune(context: ContextTypes.DEFAULT_TYPE):
    """Send daily fortune to all registered users."""
    users = load_users()

    for user_id_str, user_data in users.items():
        try:
            user_id = int(user_id_str)
            fortune = generate_fortune(user_data["birth_date"], user_data["is_premium"])

            text = (
                f"✨ 今日の占い\n"
                f"{datetime.now(JAPAN_TZ).strftime('%Y年%m月%d日')}\n\n"
                f"{fortune}\n\n"
                f"{'🌟 プレミアム版' if user_data['is_premium'] else ''}"
            )

            keyboard = [
                [InlineKeyboardButton("詳しく見る", callback_data="today")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error sending fortune to {user_id}: {e}")

async def set_daily_task(app: Application):
    """Schedule daily fortune delivery."""
    job_queue = app.job_queue

    # Schedule for 7 AM JST every day
    job_queue.run_daily(
        scheduled_fortune,
        time=DAILY_SEND_TIME
    )

# ============================================================================
# Main
# ============================================================================

def main():
    """Start the bot."""
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Setup daily task
    app.post_init = set_daily_task

    logger.info("Bot started. Polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
