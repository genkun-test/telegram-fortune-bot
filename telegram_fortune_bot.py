"""
Telegram Fortune Bot - Daily fortune generation (ja / en)
Free tier: Haiku 4.5 | Premium tier: Fable 5.1
"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import logging
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (Application, CommandHandler, MessageHandler, filters, ContextTypes,
                          CallbackQueryHandler, PreCheckoutQueryHandler)
import anthropic

# ============================================================================
# Configuration
# ============================================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]  # 未設定なら起動時に落とす（環境変数のみ）
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

USER_DB = os.path.join(os.environ.get("DATA_DIR", "."), "users.json")
JAPAN_TZ = ZoneInfo("Asia/Tokyo")
FREE_DAILY_LIMIT = 3       # /today per day, free
PREMIUM_DAILY_LIMIT = 5    # /today per day, premium (cost guard)
PREMIUM_STARS = 250        # price of a 30-day pass, in Telegram Stars (XTR)
PREMIUM_DAYS = 30
OWNER_IDS = {int(x) for x in os.environ.get("OWNER_IDS", "").replace(" ", "").split(",") if x}  # 無制限・プレミアム扱い
SEND_HOUR = 7  # 各ユーザーの現地時間の朝7時
DEFAULT_TZ = {"ja": "Asia/Tokyo", "en": "UTC"}
TZ_CHOICES = [
    ("🇯🇵 Tokyo", "Asia/Tokyo"), ("🇰🇷 Seoul", "Asia/Seoul"), ("🇸🇬 Singapore", "Asia/Singapore"),
    ("🇮🇳 India", "Asia/Kolkata"), ("🇬🇧 London", "Europe/London"), ("🇫🇷 Paris/Berlin", "Europe/Paris"),
    ("🇺🇸 New York", "America/New_York"), ("🇺🇸 Los Angeles", "America/Los_Angeles"),
    ("🇦🇺 Sydney", "Australia/Sydney"), ("UTC", "UTC"),
]

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # URLにBotトークンが含まれるためログに出さない
logger = logging.getLogger(__name__)

# ============================================================================
# i18n (ja / en). Language comes from Telegram's language_code.
# ============================================================================

TEXTS = {
    "ja": {
        "welcome_back": "ようこそ！👋\n\n登録済みの生年月日: {birth}\nステータス: {status}\n\nコマンド:\n/today - 今日の占い\n/premium - プレミアム\n/help - ヘルプ",
        "status_premium": "プレミアム ✨",
        "status_free": "無料",
        "welcome_new": "🌟 Daily Fortune へようこそ！\n\nあなたの生年月日を教えてください。\n形式: YYYY-MM-DD (例: 1998-12-27)\n\n出生時刻がわかれば、さらに詳しく占えます:\n形式: YYYY-MM-DD HH:MM (例: 1998-12-27 14:30)\n\n時刻なしでも OK です。",
        "registered": "✨ 登録完了！\n\n生年月日: {birth}\n毎日朝7時（{tz}）に占いを送ります。\n時間帯の変更: /timezone\n\nコマンド:\n/today - 今すぐ占いを見る\n/premium - プレミアム\n/help - ヘルプ",
        "bad_format": "❌ 形式が正しくありません。\nYYYY-MM-DD または YYYY-MM-DD HH:MM で入力してください。",
        "need_start": "❌ まず /start で登録してください。",
        "loading": "🔮 占い中...",
        "error": "❌ エラーが発生しました。しばらくしてからもう一度お試しください。",
        "title_today": "✨ {name}さんの今日の占い",
        "title_daily": "✨ 今日の占い",
        "date_fmt": "%Y年%m月%d日",
        "badge_premium": "🌟 プレミアム版",
        "badge_free": "📌 無料版",
        "btn_premium": "⭐ プレミアム",
        "btn_cancel": "閉じる",
        "premium": "⭐ プレミアムプラン（{d}日パス / {s} Stars）\n\n🔮 より深い占い分析\n📊 詳細な運勢予測\n💫 ラッキーアイテムの詳しい説明\n🔁 /today は1日{p}回まで（無料は{f}回）\n\n下の請求書からお支払いください。自動更新はありません。",
        "tz_ask": "🕖 お住まいの時間帯を選んでください。毎朝7時（現地時間）に占いをお送りします。",
        "tz_set": "✅ 時間帯を {tz} に設定しました。",
        "birth_updated": "✅ 生年月日を {birth} に更新しました。",
        "closed": "閉じました。",
        "limit_free": "🔒 本日の無料枠（{n}回）を使い切りました。\n明日また占えます。プレミアムなら1日{p}回まで、より深い占いが使えます → /premium",
        "limit_premium": "🔒 本日の上限（{n}回）に達しました。明日またどうぞ。",
        "invoice_title": "プレミアム {d}日パス",
        "invoice_desc": "より深い占い分析と詳細なアドバイス。1日{p}回まで /today が使えます。自動更新はありません。",
        "premium_active": "✨ プレミアム有効期限: {until}まで",
        "paid": "🎉 ありがとうございます！プレミアムが {until} まで有効になりました。",
        "paysupport": "お支払いに関するお問い合わせ: /paysupport の後ろに内容を書いて送ってください。返金の相談も受け付けます。",
        "help": "📖 ヘルプ\n\n/start - 登録\n/today - 今日の占いを見る（例: /today 明日なにをすべき？ と質問も付けられます）\n/premium - プレミアム\n/birthday - 生年月日を変更\n/timezone - 配信の時間帯を変更\n/help - このメッセージ\n\n毎日朝7時（設定した時間帯）に、自動で占い結果をお送りします。\n※ 占いはエンターテインメントです。",
    },
    "en": {
        "welcome_back": "Welcome back! 👋\n\nBirth date on file: {birth}\nStatus: {status}\n\nCommands:\n/today - Today's fortune\n/premium - Premium\n/help - Help",
        "status_premium": "Premium ✨",
        "status_free": "Free",
        "welcome_new": "🌟 Welcome to Daily Fortune!\n\nPlease tell me your birth date.\nFormat: YYYY-MM-DD (e.g. 1998-12-27)\n\nIf you know your birth time, I can be more detailed:\nFormat: YYYY-MM-DD HH:MM (e.g. 1998-12-27 14:30)\n\nThe time is optional.",
        "registered": "✨ You're registered!\n\nBirth date: {birth}\nI'll send your fortune every day at 7:00 AM ({tz}).\nChange time zone: /timezone\n\nCommands:\n/today - Get your fortune now\n/premium - Premium\n/help - Help",
        "bad_format": "❌ Invalid format.\nPlease use YYYY-MM-DD or YYYY-MM-DD HH:MM.",
        "need_start": "❌ Please register with /start first.",
        "loading": "🔮 Reading the stars...",
        "error": "❌ Something went wrong. Please try again later.",
        "title_today": "✨ {name}'s fortune for today",
        "title_daily": "✨ Today's fortune",
        "date_fmt": "%B %d, %Y",
        "badge_premium": "🌟 Premium",
        "badge_free": "📌 Free",
        "btn_premium": "⭐ Premium",
        "btn_cancel": "Close",
        "premium": "⭐ Premium plan ({d}-day pass / {s} Stars)\n\n🔮 Deeper fortune analysis\n📊 Detailed forecasts\n💫 Lucky item guide\n🔁 Up to {p} /today readings a day (free: {f})\n\nPay with the invoice below. No auto-renewal.",
        "tz_ask": "🕖 Pick your time zone. I'll send your fortune every morning at 7:00 AM local time.",
        "tz_set": "✅ Time zone set to {tz}.",
        "birth_updated": "✅ Birth date updated to {birth}.",
        "closed": "Closed.",
        "limit_free": "🔒 You've used today's free readings ({n}). Come back tomorrow, or go Premium for up to {p} deeper readings a day → /premium",
        "limit_premium": "🔒 You've reached today's limit ({n}). Please come back tomorrow.",
        "invoice_title": "Premium {d}-day pass",
        "invoice_desc": "Deeper fortune analysis and detailed advice. Up to {p} /today readings a day. No auto-renewal.",
        "premium_active": "✨ Premium active until {until}",
        "paid": "🎉 Thank you! Premium is active until {until}.",
        "paysupport": "Payment questions: send /paysupport followed by your message. Refund requests are welcome.",
        "help": "📖 Help\n\n/start - Register\n/today - Today's fortune (add a question: /today what should I do tomorrow?)\n/premium - Premium\n/birthday - Change birth date\n/timezone - Change delivery time zone\n/help - This message\n\nA fortune is sent automatically every day at 7:00 AM in your time zone.\n* For entertainment purposes only.",
    },
}

def pick_lang(language_code: Optional[str]) -> str:
    """ja for Japanese Telegram clients, en for everyone else."""
    return "ja" if (language_code or "").lower().startswith("ja") else "en"

def t(lang: str, key: str, **kw) -> str:
    return TEXTS[lang][key].format(**kw) if kw else TEXTS[lang][key]

# ============================================================================
# Database Management
# ============================================================================

def load_users() -> dict:
    if os.path.exists(USER_DB):
        with open(USER_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(users: dict):
    with open(USER_DB, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def add_user(user_id: int, birth_date: str, lang: str):
    """Create a user, or update the birth date of an existing one (keeps tz/premium/lang)."""
    users = load_users()
    prev = users.get(str(user_id), {})
    users[str(user_id)] = {
        "birth_date": birth_date,  # YYYY-MM-DD or YYYY-MM-DD HH:MM
        "lang": prev.get("lang", lang),
        "tz": prev.get("tz", DEFAULT_TZ[lang]),
        "last_daily": prev.get("last_daily"),
        "registered_at": prev.get("registered_at", datetime.now().isoformat()),
        "last_fortune": prev.get("last_fortune"),
        "premium_until": prev.get("premium_until"),
        "usage": prev.get("usage"),
    }
    save_users(users)

def get_user(user_id: int) -> Optional[dict]:
    return load_users().get(str(user_id))

def is_premium(user: Optional[dict], user_id: Optional[int] = None) -> bool:
    if user_id in OWNER_IDS:
        return True
    until = (user or {}).get("premium_until")
    return bool(until) and datetime.fromisoformat(until) > datetime.now()

def user_today(user: dict) -> str:
    return datetime.now(ZoneInfo(user.get("tz") or DEFAULT_TZ[user.get("lang") or "ja"])).date().isoformat()

def used_today(user: dict) -> int:
    u = user.get("usage") or {}
    return u.get("count", 0) if u.get("date") == user_today(user) else 0

def user_lang(user: Optional[dict], update: Update) -> str:
    """Stored language wins; otherwise infer from the Telegram client."""
    if user and user.get("lang"):
        return user["lang"]
    return pick_lang(update.effective_user.language_code)

# ============================================================================
# Fortune Generation with Claude
# ============================================================================

def generate_fortune(birth_date: str, lang: str, is_premium: bool = False, question: str = "") -> str:
    """Generate a personalized fortune in the user's language."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    model = "claude-opus-5" if is_premium else "claude-haiku-4-5-20251001"
    today_str = datetime.now(JAPAN_TZ).strftime("%Y-%m-%d")

    if lang == "ja":
        prompt = f"""あなたは経験豊かな占い師です。ユーザーの生年月日に基づいて、今日の運勢を占ってください。

【ユーザーの生年月日】
{birth_date}

【今日の日付】
{today_str}

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
- 断定的な予言や不安を煽る表現は避ける
- Markdown記法（#、**、---）は使わず、プレーンテキストで書く

{"(プレミアム版は、より深い分析と詳細なアドバイスを含めてください)" if is_premium else ""}
{f"【ユーザーからの質問】{chr(10)}{question}{chr(10)}※まず占い師としてこの質問に具体的に答え、その後に上の6要素を簡潔にまとめてください。" if question else ""}"""
    else:
        prompt = f"""You are an experienced fortune teller. Give today's fortune based on the user's birth date.

[Birth date]
{birth_date}

[Today's date]
{today_str}

Cover, in order:
1. Overall fortune
2. Work
3. Money
4. Love
5. Health
6. Advice / lucky item

Style:
- Concise and easy to read
- Positive and hopeful
- Use emoji in moderation
- Avoid absolute predictions or fear-inducing statements
- Write in English
- Plain text only: no Markdown (#, **, ---)

{"(Premium: include deeper analysis and more detailed advice.)" if is_premium else ""}
{f"[User's question]{chr(10)}{question}{chr(10)}First answer this question concretely as a fortune teller, then cover the six points above briefly." if question else ""}"""

    kwargs = {}
    if is_premium:
        # Opus 5 thinks by default and thinking counts toward max_tokens; keep it light.
        kwargs["extra_body"] = {"output_config": {"effort": "low"}}
    message = client.messages.create(
        model=model,
        max_tokens=2048 if is_premium else 512,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    u = message.usage
    logger.info(f"usage model={model} in={u.input_tokens} out={u.output_tokens} stop={message.stop_reason}")
    return next(b.text for b in message.content if b.type == "text")

# ============================================================================
# Telegram Bot Handlers
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    lang = user_lang(user, update)

    if user:
        status = t(lang, "status_premium" if is_premium(user, update.effective_user.id) else "status_free")
        await update.message.reply_text(t(lang, "welcome_back", birth=user["birth_date"], status=status))
        return

    await update.message.reply_text(t(lang, "welcome_new"))
    context.user_data["awaiting_birthdate"] = True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    lang = user_lang(get_user(update.effective_user.id), update)

    if context.user_data.get("awaiting_birthdate"):
        try:
            if len(text.split()) == 1:
                datetime.strptime(text, "%Y-%m-%d")
            else:
                datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            await update.message.reply_text(t(lang, "bad_format"))
            return

        existing = get_user(update.effective_user.id)
        lang = pick_lang(update.effective_user.language_code)
        add_user(update.effective_user.id, text, lang)
        user = get_user(update.effective_user.id)
        if existing:
            await update.message.reply_text(t(user["lang"], "birth_updated", birth=text))
        else:
            await update.message.reply_text(t(user["lang"], "registered", birth=text, tz=user["tz"]))
        context.user_data["awaiting_birthdate"] = False

async def birthday_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(get_user(update.effective_user.id), update)
    await update.message.reply_text(t(lang, "welcome_new"))
    context.user_data["awaiting_birthdate"] = True

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    lang = user_lang(user, update)

    if not user:
        await update.message.reply_text(t(lang, "need_start"))
        return

    premium = is_premium(user, user_id)
    limit = PREMIUM_DAILY_LIMIT if premium else FREE_DAILY_LIMIT
    if user_id not in OWNER_IDS and used_today(user) >= limit:
        if premium:
            await update.message.reply_text(t(lang, "limit_premium", n=limit))
        else:
            await update.message.reply_text(t(lang, "limit_free", n=limit, p=PREMIUM_DAILY_LIMIT))
        return

    msg = await update.message.reply_text(t(lang, "loading"))

    try:
        question = " ".join(context.args or [])[:300].strip()
        fortune = await asyncio.to_thread(generate_fortune, user["birth_date"], lang, premium, question)

        keyboard = [[InlineKeyboardButton(t(lang, "btn_premium"), callback_data="premium")]]
        badge = t(lang, "badge_premium" if premium else "badge_free")
        text = (
            f"{t(lang, 'title_today', name=update.effective_user.first_name)}\n"
            f"{datetime.now(JAPAN_TZ).strftime(t(lang, 'date_fmt'))}\n\n"
            f"{fortune}\n\n{badge}"
        )
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        users = load_users()
        me = users[str(user_id)]
        me["last_fortune"] = datetime.now().isoformat()
        me["usage"] = {"date": user_today(me), "count": used_today(me) + 1}
        save_users(users)

    except Exception as e:
        logger.error(f"Error generating fortune: {e}")
        await msg.edit_text(t(lang, "error"))

async def premium_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shared by /premium and the premium button: pitch + Stars invoice."""
    if update.callback_query:
        await update.callback_query.answer()
        target = update.callback_query.message
    else:
        target = update.message
    user = get_user(update.effective_user.id)
    lang = user_lang(user, update)
    if is_premium(user):
        await target.reply_text(t(lang, "premium_active", until=user["premium_until"][:10]))
    await target.reply_text(t(lang, "premium", d=PREMIUM_DAYS, s=PREMIUM_STARS, p=PREMIUM_DAILY_LIMIT, f=FREE_DAILY_LIMIT))
    await context.bot.send_invoice(
        chat_id=target.chat_id,
        title=t(lang, "invoice_title", d=PREMIUM_DAYS),
        description=t(lang, "invoice_desc", d=PREMIUM_DAYS, p=PREMIUM_DAILY_LIMIT),
        payload="premium30",
        provider_token="",  # Telegram Stars needs no provider token
        currency="XTR",
        prices=[LabeledPrice(t(lang, "invoice_title", d=PREMIUM_DAYS), PREMIUM_STARS)],
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    ok = q.invoice_payload == "premium30" and get_user(q.from_user.id) is not None
    await q.answer(ok=ok, error_message=None if ok else "Please register with /start first.")

async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pay = update.message.successful_payment
    users = load_users()
    user = users.get(str(update.effective_user.id))
    if not user:
        logger.error(f"Payment from unregistered user {update.effective_user.id}: {pay.telegram_payment_charge_id}")
        return
    now = datetime.now()
    base = max(now, datetime.fromisoformat(user["premium_until"])) if user.get("premium_until") else now
    user["premium_until"] = (base + timedelta(days=PREMIUM_DAYS)).isoformat()
    save_users(users)
    logger.info(f"Premium paid: user={update.effective_user.id} charge={pay.telegram_payment_charge_id}")
    await update.message.reply_text(t(user_lang(user, update), "paid", until=user["premium_until"][:10]))
    for oid in OWNER_IDS:
        try:
            await context.bot.send_message(oid, f"💰 paid: user={update.effective_user.id} charge={pay.telegram_payment_charge_id}")
        except Exception:
            pass

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(str(update.effective_user.id))

async def refund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner only: /refund <user_id> <charge_id> returns the Stars and clears premium."""
    if update.effective_user.id not in OWNER_IDS or len(context.args) != 2:
        return
    uid, charge = int(context.args[0]), context.args[1]
    try:
        await context.bot.refund_star_payment(user_id=uid, telegram_payment_charge_id=charge)
        users = load_users()
        if str(uid) in users:
            users[str(uid)]["premium_until"] = None
            save_users(users)
        await update.message.reply_text("refunded")
    except Exception as e:
        await update.message.reply_text(f"refund failed: {e}")

async def paysupport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(get_user(update.effective_user.id), update)
    if context.args:
        logger.info(f"PAYSUPPORT from {update.effective_user.id}: {' '.join(context.args)}")
    await update.message.reply_text(t(lang, "paysupport"))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(get_user(update.effective_user.id), update)
    await update.message.reply_text(t(lang, "help"))

async def scheduled_fortune(context: ContextTypes.DEFAULT_TYPE):
    """10分ごとに実行。現地時間が朝7時台で、今日まだ送っていないユーザーに送る。"""
    users = load_users()
    changed = False
    for user_id_str, user_data in users.items():
        try:
            lang = user_data.get("lang") or "ja"
            local = datetime.now(ZoneInfo(user_data.get("tz") or DEFAULT_TZ[lang]))
            if local.hour != SEND_HOUR or user_data.get("last_daily") == local.date().isoformat():
                continue
            fortune = await asyncio.to_thread(generate_fortune, user_data["birth_date"], lang, is_premium(user_data))
            text = (
                f"{t(lang, 'title_daily')}\n"
                f"{local.strftime(t(lang, 'date_fmt'))}\n\n"
                f"{fortune}"
            )
            await context.bot.send_message(chat_id=int(user_id_str), text=text)
            user_data["last_daily"] = local.date().isoformat()
            changed = True
        except Exception as e:
            logger.error(f"Error sending fortune to {user_id_str}: {e}")
    if changed:
        save_users(users)

async def timezone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(get_user(update.effective_user.id), update)
    rows = [[InlineKeyboardButton(label, callback_data=f"tz:{name}")] for label, name in TZ_CHOICES]
    await update.message.reply_text(t(lang, "tz_ask"), reply_markup=InlineKeyboardMarkup(rows))

async def timezone_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    name = query.data.split(":", 1)[1]
    if name not in {n for _, n in TZ_CHOICES}:
        return
    users = load_users()
    user = users.get(str(update.effective_user.id))
    lang = user_lang(user, update)
    if user:
        user["tz"] = name
        save_users(users)
    await query.edit_message_text(t(lang, "tz_set", tz=name))

async def set_daily_task(app: Application):
    app.job_queue.run_repeating(scheduled_fortune, interval=600, first=30)

# ============================================================================
# Main
# ============================================================================

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("premium", premium_info))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("timezone", timezone_cmd))
    app.add_handler(CommandHandler("birthday", birthday_cmd))
    app.add_handler(CommandHandler("paysupport", paysupport))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("refund", refund))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    app.add_handler(CallbackQueryHandler(timezone_pick, pattern="^tz:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(premium_info, pattern="^premium$"))

    app.post_init = set_daily_task

    logger.info("Bot started. Polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
