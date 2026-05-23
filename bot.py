#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import TelegramError

import config
import database as db

LOG_FILE = os.path.join(os.path.dirname(__file__), 'bot_console.log')

_file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
_file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(), _file_handler]
)
logger = logging.getLogger(__name__)

def read_log_tail(lines=40):
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        return ''.join(all_lines[-lines:])
    except FileNotFoundError:
        return '(лог-файл пуст)'

def mask_secret(value: str) -> str:
    if not value:
        return '(пусто)'
    n = len(value)
    if n <= 8:
        return '*' * n
    keep = max(3, n // 6)
    return value[:keep] + '*' * (n - keep * 2) + value[-keep:]

WATCHED_SECRETS = [
    'BOT_TOKEN', 'ADMIN_GROUP_ID', 'OWNER_ID',
    'CHANNEL_USERNAME', 'DATABASE_URL', 'SESSION_SECRET',
]

MSK = timezone(timedelta(hours=3))

def msk_now():
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M:%S")

def ts_to_msk(ts):
    return datetime.fromtimestamp(ts, tz=MSK).strftime("%d.%m.%Y %H:%M:%S")

def fmt_remaining(seconds):
    if seconds <= 0:
        return "0ч 0м 0с"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}ч {m}м {s}с"

# ═══════════════════════════════════════════════════════════
#  KEYBOARDS
# ═══════════════════════════════════════════════════════════

def main_menu_kb():
    return ReplyKeyboardMarkup([
        ["👤Профиль", "📋Объявления"],
        ["🌐Клуб", "🆘Техподдержка"]
    ], resize_keyboard=True)

def ann_menu_kb():
    return ReplyKeyboardMarkup([
        ["🚨Трансфер", "📢Свободный агент"],
        ["🥀Завершение карьеры", "⚔️Поиск скрима"],
        ["✅Возвращение карьеры", "⏸️Приостановление карьеры"],
        ["✏️Свой текст", "💳Реклама"],
        ["🔄Смена никнейма", "🔙Назад"]
    ], resize_keyboard=True)

def preview_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅Отправить", callback_data="ann:submit"),
        InlineKeyboardButton("❌Начать заново", callback_data="ann:restart"),
        InlineKeyboardButton("🔙Назад", callback_data="ann:back")
    ]])

def club_preview_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅Отправить", callback_data="club:submit"),
        InlineKeyboardButton("❌Начать заново", callback_data="club:restart"),
        InlineKeyboardButton("🔙Назад", callback_data="club:back")
    ]])

def admin_ann_kb(ann_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅Принять", callback_data=f"aann:accept:{ann_id}"),
        InlineKeyboardButton("❌Отклонить", callback_data=f"aann:reject:{ann_id}")
    ]])

def admin_sup_kb(ticket_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📤Ответить", callback_data=f"asup:reply:{ticket_id}"),
        InlineKeyboardButton("❌Отклонить", callback_data=f"asup:reject:{ticket_id}")
    ]])

def admin_club_req_kb(req_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅Принять", callback_data=f"aclub:accept:{req_id}"),
        InlineKeyboardButton("❌Отклонить", callback_data=f"aclub:reject:{req_id}")
    ]])

def console_kb(level):
    rows = [
        [InlineKeyboardButton("🧨Снять администратора", callback_data="con:remove_admin"),
         InlineKeyboardButton("➕Добавить администратора", callback_data="con:add_admin")],
        [InlineKeyboardButton("📋Список администраторов", callback_data="con:list_admins"),
         InlineKeyboardButton("❌Забанить пользователя", callback_data="con:ban")],
        [InlineKeyboardButton("✅Разбанить пользователя", callback_data="con:unban"),
         InlineKeyboardButton("🚫Список в бане", callback_data="con:ban_list")],
        [InlineKeyboardButton("🗂Лог", callback_data="con:log:1"),
         InlineKeyboardButton("📤Рассылка", callback_data="con:broadcast")],
    ]
    if level >= 2:
        rows.append([
            InlineKeyboardButton("🔑Реклама", callback_data="con:ads"),
            InlineKeyboardButton("⬆️Повысить администратора", callback_data="con:promote")
        ])
    if level >= 3:
        rows.append([
            InlineKeyboardButton("🛠Панель владельца", callback_data="con:owner_panel"),
            InlineKeyboardButton("👑Дать 2 влд", callback_data="con:give2vld")
        ])
    rows.append([InlineKeyboardButton("🔙Меню", callback_data="con:back")])
    return InlineKeyboardMarkup(rows)

def no_club_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⚙️Создать клуб", callback_data="club_menu:create"),
        InlineKeyboardButton("🔎Найти клуб", callback_data="club_menu:find"),
        InlineKeyboardButton("🔙Назад", callback_data="club_menu:back")
    ]])

def club_manage_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️Изменить роли", callback_data="cm:roles"),
         InlineKeyboardButton("👤Управление участниками", callback_data="cm:members")],
        [InlineKeyboardButton("❌Закрыть клуб", callback_data="cm:delete"),
         InlineKeyboardButton("🔙Назад", callback_data="cm:back")]
    ])

def delete_channel_post_kb(ann_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌Удалить", callback_data=f"del_post:{ann_id}")
    ]])

def log_nav_kb(page, total_pages):
    btns = []
    if page > 1:
        btns.append(InlineKeyboardButton(f"◀️{page-1}", callback_data=f"con:log:{page-1}"))
    if page < total_pages:
        btns.append(InlineKeyboardButton(f"{page+1}▶️", callback_data=f"con:log:{page+1}"))
    rows = []
    if btns:
        rows.append(btns)
    rows.append([InlineKeyboardButton("📦Очистить лог", callback_data="con:clear_log"),
                 InlineKeyboardButton("🔙Меню", callback_data="con:back")])
    return InlineKeyboardMarkup(rows)

# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def user_mention(user):
    nick = user.get('nickname') or 'Нет'
    uname = f"@{user.get('username')}" if user.get('username') else f"ID:{user['tg_id']}"
    return nick, uname

async def check_subscriptions(user_id, bot):
    active = db.get_active_ad_channels()
    if not active:
        return True, []
    unsub = []
    for ch in active:
        try:
            m = await bot.get_chat_member(ch['url'], user_id)
            if m.status in ('left', 'kicked', 'banned'):
                unsub.append(ch)
        except Exception:
            pass
    return len(unsub) == 0, unsub

async def send_main_menu(bot, chat_id):
    await bot.send_message(
        chat_id,
        "👋Добро пожаловать в бот Transfer Market - Brawl Stars!\n⬇️Выбери нужную категорию снизу",
        reply_markup=main_menu_kb()
    )

async def notify_admin_group(bot, text, reply_markup=None, photo_file_id=None, video_file_id=None):
    try:
        if photo_file_id:
            msg = await bot.send_photo(config.ADMIN_GROUP_ID, photo_file_id,
                                        caption=text, reply_markup=reply_markup)
        elif video_file_id:
            msg = await bot.send_video(config.ADMIN_GROUP_ID, video_file_id,
                                        caption=text, reply_markup=reply_markup)
        else:
            msg = await bot.send_message(config.ADMIN_GROUP_ID, text, reply_markup=reply_markup)
        return msg.message_id
    except Exception as e:
        logger.error(f"Error sending to admin group: {e}")
        return 0

async def post_to_channel(bot, text, file_id='', file_type='', ann_id=0):
    kb = delete_channel_post_kb(ann_id) if ann_id else None
    try:
        if file_type == 'photo' and file_id:
            msg = await bot.send_photo(config.CHANNEL_USERNAME, file_id, caption=text, reply_markup=kb)
        elif file_type == 'video' and file_id:
            msg = await bot.send_video(config.CHANNEL_USERNAME, file_id, caption=text, reply_markup=kb)
        else:
            msg = await bot.send_message(config.CHANNEL_USERNAME, text, reply_markup=kb)
        return msg.message_id
    except Exception as e:
        logger.error(f"Error posting to channel: {e}")
        return 0

async def remove_buttons(bot, chat_id, message_id):
    try:
        await bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
    except Exception:
        pass

async def safe_send(bot, chat_id, text, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"safe_send error to {chat_id}: {e}")

# ═══════════════════════════════════════════════════════════
#  ANNOUNCEMENT TEXT BUILDERS
# ═══════════════════════════════════════════════════════════

def build_transfer(data, nick, uname):
    old = data.get('old_club', '?')
    new = data.get('new_club', '?')
    contract = data.get('contract', '?')
    deal = data.get('deal', '?')
    buyout = data.get('buyout', '?')
    ps = data.get('ps', '?')
    return (
        f"🚨 ОФИЦИАЛЬНЫЙ ПЕРЕХОД 📢\n\n"
        f"{nick} ({uname}) — {old} ➡️ {new}\n\n"
        f"📄 Контракт: до {contract}\n"
        f"💰 Сумма сделки: {deal} TMC\n"
        f"💸 Отступные: {buyout} TMC\n\n"
        f"P.S.: {ps}"
    )

def build_free_agent(data, nick, uname, cost):
    ps = data.get('ps', '?')
    return (
        f"📢 СВОБОДНЫЙ АГЕНТ ❗️🚨\n\n"
        f"{nick} ({uname}) — ищет клуб\n\n"
        f"💰Стоимость игрока: {cost} TMC\n\n"
        f"P.S.: {ps}"
    )

def build_career_end(data, nick, uname):
    ps = data.get('ps', '?')
    return (
        f"🥀 ОФИЦИАЛЬНОЕ ЗАВЕРШЕНИЕ КАРЬЕРЫ ❗️\n\n"
        f"{nick} ({uname}) — завершает карьеру\n\n"
        f"P.S.: {ps}"
    )

def build_scrim(data, uname):
    club = data.get('club', '?')
    t = data.get('time', '?')
    return (
        f"❗️ ПОИСК СКРИМА❗️\n\n"
        f"Клуб: {club}\n"
        f"Время: {t}\n"
        f"Юзернейм: {uname}"
    )

def build_career_return(data, nick, uname):
    ps = data.get('ps', '?')
    return (
        f"✅ ОФИЦИАЛЬНОЕ ВОЗВРАЩЕНИЕ КАРЬЕРЫ 🥳\n\n"
        f"{nick} ({uname}) — возвращает карьеру\n\n"
        f"P.S: {ps}"
    )

def build_career_pause(data, nick, uname):
    ps = data.get('ps', '?')
    return (
        f"❗️ ОФИЦИАЛЬНОЕ ПРИОСТАНОВЛЕНИЕ КАРЬЕРЫ 🚨\n\n"
        f"{nick} ({uname}) — приостановление карьеры\n\n"
        f"P.S: {ps}"
    )

# ═══════════════════════════════════════════════════════════
#  /start HANDLER
# ═══════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if chat.type != 'private':
        return

    db.upsert_user(user.id, user.username or '')
    u = db.get_user(user.id)

    if u['is_banned']:
        await update.message.reply_text(
            "❌Сейчас вы не можете пользоваться функциями бота, так как вас заблокировал его администратор."
        )
        return

    ok, unsub = await check_subscriptions(user.id, ctx.bot)
    if not ok:
        btns = [[InlineKeyboardButton(f"Канал {i+1}", url=ch['url'])] for i, ch in enumerate(unsub)]
        btns.append([InlineKeyboardButton("✅ Я подписался", callback_data="check_sub")])
        await update.message.reply_text(
            "Подпишитесь для пользования ботом:",
            reply_markup=InlineKeyboardMarkup(btns)
        )
        return

    db.set_state(user.id, 'NONE', {})

    if not u['is_registered']:
        await update.message.reply_text(
            "👋Добро пожаловать в бот Transfer Market - Brawl Stars!\n"
            "❗️ Перед использованием данного бота вам нужно будет зарегистрироваться.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅Начать регистрацию", callback_data="start_reg")
            ]])
        )
    else:
        await send_main_menu(ctx.bot, user.id)

# ═══════════════════════════════════════════════════════════
#  /console HANDLER
# ═══════════════════════════════════════════════════════════

async def cmd_console(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if chat.type != 'private':
        return
    if not db.is_admin(user.id) and user.id != config.OWNER_ID:
        await update.message.reply_text("❌ Нет доступа.")
        return

    level = db.admin_level(user.id)
    if user.id == config.OWNER_ID:
        level = 3

    db.set_state(user.id, 'NONE', {})
    await update.message.reply_text(
        f"👤Админ панель бота\n"
        f"- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -\n"
        f"⏳Время(МСК): {msk_now()}\n"
        f"🤖Состояние бота: включен✅",
        reply_markup=console_kb(level)
    )

# ═══════════════════════════════════════════════════════════
#  CALLBACK QUERY HANDLER
# ═══════════════════════════════════════════════════════════

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    user = q.from_user

    # ── Subscription check ──
    if data == "check_sub":
        ok, unsub = await check_subscriptions(user.id, ctx.bot)
        if ok:
            u = db.get_user(user.id)
            if u and u['is_registered']:
                await q.message.delete()
                await send_main_menu(ctx.bot, user.id)
            else:
                await q.message.delete()
                await ctx.bot.send_message(user.id,
                    "👋Добро пожаловать в бот Transfer Market - Brawl Stars!\n"
                    "❗️ Перед использованием данного бота вам нужно будет зарегистрироваться.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅Начать регистрацию", callback_data="start_reg")
                    ]])
                )
        else:
            await q.answer("❌ Вы ещё не подписались на все каналы!", show_alert=True)
        return

    # ── Registration ──
    if data == "start_reg":
        db.set_state(user.id, 'REG_NICK', {})
        await q.message.edit_text(
            "⬇️Для регистрации, введите свой никнейм.\n"
            "❗️ Он будет отображаться во всех трансферах (потом вы можете его сменить)"
        )
        return

    # ── Announcement submit/restart/back ──
    if data.startswith("ann:"):
        await handle_ann_callback(q, user, ctx, data[4:])
        return

    # ── Club creation submit/restart/back ──
    if data.startswith("club:"):
        await handle_club_callback(q, user, ctx, data[5:])
        return

    # ── Club menu (no club) ──
    if data.startswith("club_menu:"):
        await handle_club_menu_callback(q, user, ctx, data[10:])
        return

    # ── Club management (owner) ──
    if data.startswith("cm:"):
        await handle_cm_callback(q, user, ctx, data[3:])
        return

    # ── Admin: announce ──
    if data.startswith("aann:"):
        await handle_admin_ann_callback(q, user, ctx, data[5:])
        return

    # ── Admin: support ──
    if data.startswith("asup:"):
        await handle_admin_sup_callback(q, user, ctx, data[5:])
        return

    # ── Admin: club request ──
    if data.startswith("aclub:"):
        await handle_admin_club_callback(q, user, ctx, data[6:])
        return

    # ── Delete channel post ──
    if data.startswith("del_post:"):
        ann_id = int(data.split(':')[1])
        if not db.is_admin(user.id) and user.id != config.OWNER_ID:
            await q.answer("❌ Нет доступа.", show_alert=True)
            return
        ann = db.get_ann(ann_id)
        if ann and ann['channel_message_id']:
            try:
                await ctx.bot.delete_message(config.CHANNEL_USERNAME, ann['channel_message_id'])
                db.update_ann(ann_id, status='deleted')
                db.add_log(user.id, "Удалил объявление из канала", f"ann_id={ann_id}")
                await q.message.edit_reply_markup(None)
            except Exception as e:
                await q.answer(f"Ошибка: {e}", show_alert=True)
        return

    # ── Console panel ──
    if data.startswith("con:"):
        await handle_console_callback(q, user, ctx, data[4:])
        return

    # ── Owner panel ──
    if data.startswith("op:"):
        level = db.admin_level(user.id)
        if user.id == config.OWNER_ID:
            level = 3
        if level < 3:
            await q.answer("❌ Нет доступа.", show_alert=True)
            return
        await handle_owner_panel_action(q, user, ctx, data[3:])
        return

    # ── Role buttons (club) ──
    if data.startswith("role:"):
        await handle_role_callback(q, user, ctx, data[5:])
        return

    # ── Kick member ──
    if data.startswith("kick:"):
        await handle_kick_callback(q, user, ctx, data[5:])
        return

    # ── Owner manage button ──
    if data == "club_manage":
        await handle_owner_manage(q, user, ctx)
        return

    # ── Ad channel controls ──
    if data.startswith("ad:"):
        await handle_ad_callback(q, user, ctx, data[3:])
        return

# ═══════════════════════════════════════════════════════════
#  ANNOUNCEMENT CALLBACKS
# ═══════════════════════════════════════════════════════════

async def handle_ann_callback(q, user, ctx, action):
    state, sdata = db.get_state(user.id)
    ann_type = sdata.get('ann_type', '')

    if action == "submit":
        now = int(time.time())
        u = db.get_user(user.id)
        last = u.get('last_announcement', 0)
        if now - last < config.COOLDOWN:
            remaining = config.COOLDOWN - (now - last)
            await q.answer(f"⏳ Подождите ещё {remaining} сек.", show_alert=True)
            return

        text = sdata.get('preview_text', '')
        file_id = sdata.get('file_id', '')
        file_type = sdata.get('file_type', '')

        ann_id = db.create_ann(user.id, ann_type, text, file_id, file_type)
        uname = f"@{u['username']}" if u.get('username') else f"ID:{u['tg_id']}"
        group_text = (
            f"📋Новая заявка!\n\n"
            f"🆔ID: {u['tg_id']} - ({uname})\n\n"
            f"✏️Текст: {text}\n"
            f"🖼Изображение: {'прикреплено' if file_id else 'нет'}"
        )
        mid = await notify_admin_group(ctx.bot, group_text,
                                        reply_markup=admin_ann_kb(ann_id),
                                        photo_file_id=file_id if file_type == 'photo' else None,
                                        video_file_id=file_id if file_type == 'video' else None)
        db.update_ann(ann_id, group_message_id=mid)
        db.update_user(user.id, last_announcement=now)

        if ann_type == 'transfer':
            new_club = sdata.get('new_club', '')
            if new_club:
                db.update_user(user.id, club=new_club)
                club = db.get_club_by_name(new_club)
                if club:
                    if not db.get_member(club['id'], user.id):
                        db.add_member(club['id'], user.id)

        db.set_state(user.id, 'NONE', {})
        await q.message.edit_text("✅Ваша анкета отправлена админам!")

    elif action == "restart":
        db.set_state(user.id, f'ANN_START_{ann_type}', {'ann_type': ann_type})
        await q.message.edit_text("🔄 Начинаем заново...")
        await start_ann_flow(q.message.chat_id, ann_type, user.id, ctx.bot)

    elif action == "back":
        db.set_state(user.id, 'NONE', {})
        await q.message.delete()
        await ctx.bot.send_message(q.message.chat_id,
            "💠Выберите тип объявления:", reply_markup=ann_menu_kb())

async def start_ann_flow(chat_id, ann_type, user_id, bot):
    db.set_state(user_id, f'ANN_{ann_type.upper()}_STEP1', {'ann_type': ann_type})
    msgs = {
        'transfer': "⚔️Введите название прошлого клуба, из которого переходите (или 👤Сво агент, если нету)",
        'free_agent': "Введите P.S: (без самого P.S, просто текст)",
        'career_end': "Введите P.S: (без самого P.S, просто текст)",
        'scrim': "⚔️Введите название клуба:",
        'career_return': "Введите P.S: (без самого P.S, просто текст)",
        'career_pause': "Введите P.S: (без самого P.S, просто текст)",
        'custom': "❗️Здесь вы можете написать свой текст для поиска игроков. Если надо, прикрепите изображение или видео.\nВАЖНАЯ ДЕТАЛЬ: пишите свой юз, чтобы пользователи знали, кому писать.",
    }
    await bot.send_message(chat_id, msgs.get(ann_type, "Введите данные:"))

# ═══════════════════════════════════════════════════════════
#  CLUB CALLBACKS
# ═══════════════════════════════════════════════════════════

async def handle_club_callback(q, user, ctx, action):
    state, sdata = db.get_state(user.id)

    if action == "submit":
        club_name = sdata.get('club_name', '')
        budget = sdata.get('budget', '0')
        u = db.get_user(user.id)
        uname = f"@{u['username']}" if u.get('username') else f"ID:{u['tg_id']}"
        req_id = db.create_club_request(user.id, club_name, budget)
        group_text = (
            f"📋Новая заявка!\n\n"
            f"🆔ID: {u['tg_id']} - ({uname})\n\n"
            f"✏️Текст: Регистрация клуба\nНазвание клуба: {club_name}\nБюджет клуба: {budget}"
        )
        mid = await notify_admin_group(ctx.bot, group_text, reply_markup=admin_club_req_kb(req_id))
        db.update_club_request(req_id, group_message_id=mid)
        db.set_state(user.id, 'NONE', {})
        await q.message.edit_text("✅Ваша заявка на регистрацию клуба отправлена админам!")

    elif action == "restart":
        db.set_state(user.id, 'CC_NAME', {'action': 'create_club'})
        await q.message.edit_text("Введите название клуба:")

    elif action == "back":
        db.set_state(user.id, 'NONE', {})
        await q.message.delete()
        await ctx.bot.send_message(q.message.chat_id,
            "❌У вас еще нет клуба!",
            reply_markup=no_club_kb()
        )

async def handle_club_menu_callback(q, user, ctx, action):
    if action == "create":
        db.set_state(user.id, 'CC_NAME', {'action': 'create_club'})
        await q.message.edit_text("Введите название клуба:")

    elif action == "find":
        db.set_state(user.id, 'CLUB_FIND', {})
        await q.message.edit_text("🔎Введите название клуба для поиска:")

    elif action == "back":
        db.set_state(user.id, 'NONE', {})
        await q.message.delete()
        await send_main_menu(ctx.bot, user.id)

# ═══════════════════════════════════════════════════════════
#  CLUB MANAGEMENT CALLBACKS
# ═══════════════════════════════════════════════════════════

async def handle_cm_callback(q, user, ctx, action):
    u = db.get_user(user.id)
    club = db.get_club_by_name(u['club']) if u['club'] else None
    if not club or club['owner_id'] != user.id:
        await q.answer("❌ Нет доступа.", show_alert=True)
        return

    if action == "back":
        await show_club_info(q.message, user, ctx.bot, club, u)
        return

    if action == "delete":
        db.delete_club(club['id'])
        db.update_user(user.id, club='')
        db.add_log(user.id, "Закрыл клуб", f"club={club['name']}")
        await q.message.edit_text("❌ Клуб закрыт.")
        return

    if action == "roles":
        members = db.get_club_members(club['id'])
        if not members:
            await q.answer("Нет участников.", show_alert=True)
            return
        lines = []
        btns = []
        for i, m in enumerate(members):
            nick = m.get('nickname') or f"ID:{m['user_tg_id']}"
            lines.append(f"{i+1}. {nick} - {m['role']}")
            btns.append([InlineKeyboardButton(
                f"✏️Изменить ({i+1})", callback_data=f"role:select:{club['id']}:{m['user_tg_id']}"
            )])
        btns.append([InlineKeyboardButton("🔙Назад", callback_data="cm:back")])
        text = (
            "⚙️👤Добро пожаловать в панель по изменению ролей.\n"
            "- " * 20 + "\n"
            + "\n".join(lines)
        )
        await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(btns))
        return

    if action == "members":
        members = db.get_club_members(club['id'])
        if not members:
            await q.answer("Нет участников.", show_alert=True)
            return
        lines = []
        btns = []
        for i, m in enumerate(members):
            nick = m.get('nickname') or f"ID:{m['user_tg_id']}"
            lines.append(f"{i+1}. {nick}")
            if m['user_tg_id'] != user.id:
                btns.append([InlineKeyboardButton(
                    f"❌Выгнать ({i+1})", callback_data=f"kick:{club['id']}:{m['user_tg_id']}"
                )])
        btns.append([InlineKeyboardButton("🔙Назад", callback_data="cm:back")])
        text = (
            "⚙️👤Добро пожаловать в панель по управлению участниками клуба.\n"
            "- " * 20 + "\n"
            "📌Текущие участники клуба:\n"
            + "\n".join(lines)
        )
        await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(btns))
        return

async def handle_role_callback(q, user, ctx, rest):
    parts = rest.split(':')

    if parts[0] == "select":
        club_id = int(parts[1])
        target_id = int(parts[2])
        club = db.get_club_by_id(club_id)
        if not club or club['owner_id'] != user.id:
            await q.answer("❌ Нет доступа.", show_alert=True)
            return
        target_u = db.get_user(target_id)
        member = db.get_member(club_id, target_id)
        nick = target_u['nickname'] if target_u else f"ID:{target_id}"
        await q.message.edit_text(
            f"👤Управление ролью игрока {nick}\n"
            f"💼Текущая роль: {member['role'] if member else 'нет'}\n"
            f"❗️Выберите роль снизу для изменения:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("2й влд", callback_data=f"role:set:{club_id}:{target_id}:второй владелец"),
                 InlineKeyboardButton("3й влд", callback_data=f"role:set:{club_id}:{target_id}:третий владелец")],
                [InlineKeyboardButton("4й влд", callback_data=f"role:set:{club_id}:{target_id}:четвертый владелец"),
                 InlineKeyboardButton("обычный игрок", callback_data=f"role:set:{club_id}:{target_id}:обычный игрок")],
                [InlineKeyboardButton("✏️Своя роль", callback_data=f"role:custom:{club_id}:{target_id}")],
                [InlineKeyboardButton("🔙Назад", callback_data="cm:roles")]
            ])
        )
        return

    if parts[0] == "set":
        club_id = int(parts[1])
        target_id = int(parts[2])
        role = ':'.join(parts[3:])
        club = db.get_club_by_id(club_id)
        if not club or club['owner_id'] != user.id:
            await q.answer("❌ Нет доступа.", show_alert=True)
            return
        db.set_member_role(club_id, target_id, role)
        db.add_log(user.id, f"Изменил роль участника клуба", f"club={club['name']}, target={target_id}, role={role}")
        await q.answer(f"✅ Роль изменена: {role}", show_alert=True)
        return

    if parts[0] == "custom":
        club_id = int(parts[1])
        target_id = int(parts[2])
        club = db.get_club_by_id(club_id)
        if not club or club['owner_id'] != user.id:
            await q.answer("❌ Нет доступа.", show_alert=True)
            return
        db.set_state(user.id, 'ROLE_CUSTOM', {'club_id': club_id, 'target_id': target_id})
        await q.message.edit_text(
            "⬇️Введите текст для присваивания роли игроку. "
            "(В списке будет отображаться в качестве роли тот текст, который вы напишите).\n"
            "⚠️ВНИМАНИЕ: если текст не будет соответствовать правилам, ваш клуб будет закрыт\\роль будет изменена админами"
        )
        return

async def handle_kick_callback(q, user, ctx, rest):
    parts = rest.split(':')
    club_id = int(parts[0])
    target_id = int(parts[1])
    club = db.get_club_by_id(club_id)
    if not club or club['owner_id'] != user.id:
        await q.answer("❌ Нет доступа.", show_alert=True)
        return
    db.remove_member(club_id, target_id)
    target_u = db.get_user(target_id)
    if target_u and target_u.get('club', '').lower() == club['name'].lower():
        db.update_user(target_id, club='')
    db.add_log(user.id, "Выгнал участника из клуба", f"club={club['name']}, target={target_id}")
    await q.answer("❌Пользователь изгнан из клуба.", show_alert=True)
    await handle_cm_callback(q, user, ctx, "members")

async def handle_owner_manage(q, user, ctx):
    u = db.get_user(user.id)
    club = db.get_club_by_name(u['club']) if u['club'] else None
    if not club or club['owner_id'] != user.id:
        await q.answer("❌ Нет доступа.", show_alert=True)
        return
    await q.message.edit_text(
        "❗️Выберите нужную категорию:",
        reply_markup=club_manage_kb()
    )

async def show_club_info(message, user, bot, club, u):
    members = db.get_club_members(club['id'])
    lines = []
    for i, m in enumerate(members):
        nick = m.get('nickname') or f"ID:{m['user_tg_id']}"
        lines.append(f"{i+1}. {nick} - {m['role']}")

    text = (
        f"💼Твой клуб: {club['name']}\n"
        f"🍋Бюджет: {club['budget']}TMC\n\n"
        f"👤 Участники:\n"
        + "\n".join(lines) if lines else "Нет участников."
    )

    btns = []
    if club['owner_id'] == user.id:
        btns.append([InlineKeyboardButton("⚙️Управление клубом", callback_data="club_manage")])

    try:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(btns) if btns else None)
    except Exception:
        await bot.send_message(user.id, text, reply_markup=InlineKeyboardMarkup(btns) if btns else None)

# ═══════════════════════════════════════════════════════════
#  ADMIN ANNOUNCEMENT CALLBACKS
# ═══════════════════════════════════════════════════════════

async def handle_admin_ann_callback(q, user, ctx, rest):
    if not db.is_admin(user.id) and user.id != config.OWNER_ID:
        await q.answer("❌ Нет доступа.", show_alert=True)
        return

    parts = rest.split(':')
    action = parts[0]
    ann_id = int(parts[1])
    ann = db.get_ann(ann_id)

    if not ann or ann['status'] != 'pending':
        await q.answer("⚠️ Заявка уже обработана.", show_alert=True)
        return

    if action == "accept":
        ch_mid = await post_to_channel(ctx.bot, ann['text'], ann['file_id'], ann['file_type'], ann_id)
        db.update_ann(ann_id, status='accepted', channel_message_id=ch_mid)
        db.add_log(user.id, "Принял объявление", f"ann_id={ann_id}")
        await remove_buttons(ctx.bot, config.ADMIN_GROUP_ID, ann['group_message_id'])
        await ctx.bot.send_message(config.ADMIN_GROUP_ID,
            f"✅ Объявление #{ann_id} принято администратором 🆔{user.id}")
        await safe_send(ctx.bot, ann['user_id'], "✅ Ваша заявка принята и опубликована в канале!")

    elif action == "reject":
        db.update_ann(ann_id, status='rejecting')
        db.set_state(user.id, 'ADM_ANN_REJECT', {'ann_id': ann_id, 'group_msg_id': ann['group_message_id']})
        await safe_send(ctx.bot, user.id, "❗️Введите причину:")

async def handle_admin_sup_callback(q, user, ctx, rest):
    if not db.is_admin(user.id) and user.id != config.OWNER_ID:
        await q.answer("❌ Нет доступа.", show_alert=True)
        return

    parts = rest.split(':')
    action = parts[0]
    ticket_id = int(parts[1])
    ticket = db.get_ticket(ticket_id)

    if not ticket or ticket['status'] != 'pending':
        await q.answer("⚠️ Обращение уже обработано.", show_alert=True)
        return

    db.update_ticket(ticket_id, status=action + 'ing', admin_id=user.id)

    if action == "reply":
        db.set_state(user.id, 'ADM_SUP_REPLY', {'ticket_id': ticket_id, 'group_msg_id': ticket['group_message_id']})
        await safe_send(ctx.bot, user.id, "❗️Напишите ответ на обращение пользователя:")
    elif action == "reject":
        db.set_state(user.id, 'ADM_SUP_REJECT', {'ticket_id': ticket_id, 'group_msg_id': ticket['group_message_id']})
        await safe_send(ctx.bot, user.id, "✏️Введите причину отклонения обращения:")

async def handle_admin_club_callback(q, user, ctx, rest):
    if not db.is_admin(user.id) and user.id != config.OWNER_ID:
        await q.answer("❌ Нет доступа.", show_alert=True)
        return

    parts = rest.split(':')
    action = parts[0]
    req_id = int(parts[1])
    req = db.get_club_request(req_id)

    if not req or req['status'] != 'pending':
        await q.answer("⚠️ Заявка уже обработана.", show_alert=True)
        return

    if action == "accept":
        existing = db.get_club_by_name(req['club_name'])
        if not existing:
            club_id = db.create_club(req['club_name'], req['budget'], req['user_id'])
            db.update_user(req['user_id'], club=req['club_name'])
            users_with_club = db.get_users_with_club(req['club_name'])
            for uw in users_with_club:
                if uw['tg_id'] != req['user_id']:
                    db.add_member(club_id, uw['tg_id'])
        db.update_club_request(req_id, status='accepted')
        db.add_log(user.id, "Принял заявку на создание клуба", f"club={req['club_name']}, req_id={req_id}")
        await remove_buttons(ctx.bot, config.ADMIN_GROUP_ID, req['group_message_id'])
        await ctx.bot.send_message(config.ADMIN_GROUP_ID,
            f"✅ Клуб {req['club_name']} зарегистрирован. Администратор 🆔{user.id}")
        await safe_send(ctx.bot, req['user_id'], f"✅ Ваш клуб «{req['club_name']}» успешно зарегистрирован!")

    elif action == "reject":
        db.update_club_request(req_id, status='rejecting')
        db.set_state(user.id, 'ADM_CLUB_REJECT', {'req_id': req_id, 'group_msg_id': req['group_message_id'], 'user_id': req['user_id']})
        await safe_send(ctx.bot, user.id, "❗️Введите причину:")

# ═══════════════════════════════════════════════════════════
#  CONSOLE CALLBACKS
# ═══════════════════════════════════════════════════════════

async def handle_console_callback(q, user, ctx, action):
    if not db.is_admin(user.id) and user.id != config.OWNER_ID:
        await q.answer("❌ Нет доступа.", show_alert=True)
        return

    level = db.admin_level(user.id)
    if user.id == config.OWNER_ID:
        level = 3

    if action == "back":
        await q.message.edit_text(
            f"👤Админ панель бота\n"
            f"- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -\n"
            f"⏳Время(МСК): {msk_now()}\n"
            f"🤖Состояние бота: включен✅",
            reply_markup=console_kb(level)
        )
        db.set_state(user.id, 'NONE', {})
        return

    if action == "remove_admin":
        db.set_state(user.id, 'ADM_REMOVE_ID', {})
        await safe_send(ctx.bot, user.id,
            "🆔Введите Telegram ID пользователя, которого вы хотите снять (в формате 12345678)")
        return

    if action == "add_admin":
        db.set_state(user.id, 'ADM_ADD_ID', {})
        await safe_send(ctx.bot, user.id,
            "🆔Введите Telegram ID пользователя, которого вы хотите добавить на пост администратора (в формате 12345678)")
        return

    if action == "list_admins":
        admins = db.all_admins()
        if not admins:
            text = "👤Список администраторов в боте:\n- - -\nСписок пуст."
        else:
            lines = [f"💼{i+1}. TG ID: {a['tg_id']} (уровень {a['level']})" for i, a in enumerate(admins)]
            text = "👤Список администраторов в боте:\n- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -\n" + "\n".join(lines)
        await safe_send(ctx.bot, user.id, text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙Меню", callback_data="con:back")]]))
        return

    if action == "ban":
        db.set_state(user.id, 'ADM_BAN_ID', {})
        await safe_send(ctx.bot, user.id,
            "🆔Введите Telegram ID пользователя, которого вы хотите забанить в боте (в формате 12345678)")
        return

    if action == "unban":
        db.set_state(user.id, 'ADM_UNBAN_ID', {})
        await safe_send(ctx.bot, user.id,
            "🆔Введите Telegram ID пользователя, которого вы хотите разбанить в боте (в формате 12345678)")
        return

    if action == "ban_list":
        all_u = db.all_users()
        banned = [u for u in all_u if u['is_banned']]
        if not banned:
            text = "🔰Список забаненных пользователей:\n- - -\nСписок пуст."
        else:
            lines = [f"{i+1}. 🚫{u['tg_id']} - забанен" for i, u in enumerate(banned)]
            text = "🔰Список забаненных пользователей:\n- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -\n" + "\n".join(lines)
        await safe_send(ctx.bot, user.id, text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙Меню", callback_data="con:back")]]))
        return

    if action == "broadcast":
        if level < 2:
            await q.answer("❌ Недостаточно прав.", show_alert=True)
            return
        db.set_state(user.id, 'ADM_BROADCAST', {})
        await safe_send(ctx.bot, user.id, "✏️Введите текст, и если надо, прикрепите изображение, для рассылки.")
        return

    if action == "promote":
        if level < 2:
            await q.answer("❌ Недостаточно прав.", show_alert=True)
            return
        db.set_state(user.id, 'ADM_PROMOTE_ID', {})
        await safe_send(ctx.bot, user.id,
            "✏️Введите TG ID администратора, которого хотите повысить(в формате 12345678):")
        return

    if action == "give2vld":
        if level < 3:
            await q.answer("❌ Недостаточно прав.", show_alert=True)
            return
        db.set_state(user.id, 'ADM_GIVE2VLD', {})
        await safe_send(ctx.bot, user.id,
            "✏️Введите TG ID пользователя которому хотите дать уровень 2-го владельца:")
        return

    if action.startswith("log:"):
        page = int(action.split(':')[1])
        logs, total = db.get_logs(page, config.LOG_PAGE_SIZE)
        total_pages = max(1, (total + config.LOG_PAGE_SIZE - 1) // config.LOG_PAGE_SIZE)
        if not logs:
            text = "🗂Недавние действия администраторов:\n- - -\nЛог пуст. Никаких действий еще не было совершено."
        else:
            lines = [
                f"---{ts_to_msk(l['created_at'])}—{l['action']}: 🆔{l['admin_id']}"
                + (f"\n  └ {l['details']}" if l['details'] else "")
                for l in logs
            ]
            text = (
                f"🗂Недавние действия администраторов:\n"
                f"- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -\n"
                f"(Страница {page}/{total_pages})\n\n"
                + "\n\n".join(lines)
            )
        await safe_send(ctx.bot, user.id, text, reply_markup=log_nav_kb(page, total_pages))
        return

    if action == "clear_log":
        db.clear_logs()
        await q.answer("✅ Лог очищен.", show_alert=True)
        return

    if action == "ads":
        if level < 2:
            await q.answer("❌ Недостаточно прав.", show_alert=True)
            return
        await show_ads_panel(ctx.bot, user.id)
        return

    if action == "owner_panel":
        if level < 3:
            await q.answer("❌ Недостаточно прав.", show_alert=True)
            return
        await show_owner_panel(ctx.bot, user.id)
        return

    if action.startswith("op:"):
        if level < 3:
            await q.answer("❌ Нет доступа.", show_alert=True)
            return
        await handle_owner_panel_action(q, user, ctx, action[3:])
        return

def owner_panel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊Статистика", callback_data="op:stats"),
         InlineKeyboardButton("👥Все пользователи", callback_data="op:users:1")],
        [InlineKeyboardButton("🏆Все клубы", callback_data="op:clubs:1"),
         InlineKeyboardButton("📋Объявления", callback_data="op:anns:1")],
        [InlineKeyboardButton("💰Установить стоимость игрока", callback_data="op:setcost"),
         InlineKeyboardButton("🍋Установить бюджет клуба", callback_data="op:setbudget")],
        [InlineKeyboardButton("🔍Найти пользователя", callback_data="op:finduser"),
         InlineKeyboardButton("🔍Найти клуб", callback_data="op:findclub")],
        [InlineKeyboardButton("📟Консоль бота", callback_data="op:console_log"),
         InlineKeyboardButton("🔐Секреты", callback_data="op:secrets")],
        [InlineKeyboardButton("🗑Очистить лог-файл", callback_data="op:clear_log_file"),
         InlineKeyboardButton("🔙Меню", callback_data="con:back")]
    ])

async def show_owner_panel(bot, user_id):
    await bot.send_message(
        user_id,
        "🛠 Панель владельца\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Выберите раздел для просмотра или управления базой данных:",
        reply_markup=owner_panel_kb()
    )

async def handle_owner_panel_action(q, user, ctx, action):
    parts = action.split(':')
    cmd = parts[0]

    if cmd == "stats":
        stats = db.get_stats()
        text = (
            "📊 Статистика бота\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Пользователей: {stats['users']}\n"
            f"✅ Зарегистрировано: {stats['registered']}\n"
            f"🚫 Забанено: {stats['banned']}\n"
            f"👮 Администраторов: {stats['admins']}\n"
            f"🏆 Клубов: {stats['clubs']}\n"
            f"📋 Объявлений всего: {stats['announcements']}\n"
            f"✅ Принято: {stats['accepted']}\n"
            f"❌ Отклонено: {stats['rejected']}\n"
            f"⏳ На рассмотрении: {stats['pending']}\n"
            f"🆘 Обращений в поддержку: {stats['tickets']}\n"
            f"📝 Записей в логе: {stats['logs']}"
        )
        await safe_send(ctx.bot, user.id, text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙Назад", callback_data="con:owner_panel")]
        ]))
        return

    if cmd == "users":
        page = int(parts[1]) if len(parts) > 1 else 1
        users, total = db.get_users_page(page, 10)
        total_pages = max(1, (total + 9) // 10)
        lines = []
        for u in users:
            nick = u['nickname'] or '—'
            club = u['club'] or '—'
            status = "🚫" if u['is_banned'] else ("✅" if u['is_registered'] else "⭕")
            lines.append(
                f"{status} 🆔{u['tg_id']}\n"
                f"   📌 {nick} | 🌐 {club} | 💰 {u['cost']}TMC"
            )
        text = (
            f"👥 Все пользователи (стр. {page}/{total_pages}, всего {total}):\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines) if lines else "Нет пользователей."
        )
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(f"◀️{page-1}", callback_data=f"op:users:{page-1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton(f"{page+1}▶️", callback_data=f"op:users:{page+1}"))
        btns = [nav] if nav else []
        btns.append([InlineKeyboardButton("🔙Назад", callback_data="con:owner_panel")])
        await safe_send(ctx.bot, user.id, text, reply_markup=InlineKeyboardMarkup(btns))
        return

    if cmd == "clubs":
        page = int(parts[1]) if len(parts) > 1 else 1
        clubs, total = db.get_clubs_page(page, 10)
        total_pages = max(1, (total + 9) // 10)
        lines = []
        for c in clubs:
            members_count = db.count_club_members(c['id'])
            lines.append(
                f"🏆 {c['name']}\n"
                f"   🆔Владелец: {c['owner_id']} | 🍋 {c['budget']}TMC | 👥 {members_count} чел."
            )
        text = (
            f"🏆 Все клубы (стр. {page}/{total_pages}, всего {total}):\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines) if lines else "Нет клубов."
        )
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(f"◀️{page-1}", callback_data=f"op:clubs:{page-1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton(f"{page+1}▶️", callback_data=f"op:clubs:{page+1}"))
        btns = [nav] if nav else []
        btns.append([InlineKeyboardButton("🔙Назад", callback_data="con:owner_panel")])
        await safe_send(ctx.bot, user.id, text, reply_markup=InlineKeyboardMarkup(btns))
        return

    if cmd == "anns":
        page = int(parts[1]) if len(parts) > 1 else 1
        anns, total = db.get_anns_page(page, 8)
        total_pages = max(1, (total + 7) // 8)
        status_icons = {'pending': '⏳', 'accepted': '✅', 'rejected': '❌', 'deleted': '🗑', 'rejecting': '🔄'}
        lines = []
        for a in anns:
            icon = status_icons.get(a['status'], '❓')
            t = ts_to_msk(a['created_at']) if a['created_at'] else '—'
            preview = (a['text'] or '')[:60].replace('\n', ' ')
            lines.append(
                f"{icon} #{a['id']} [{a['ann_type']}] 🆔{a['user_id']}\n"
                f"   📅 {t}\n"
                f"   ✏️ {preview}{'…' if len(a['text'] or '') > 60 else ''}"
            )
        text = (
            f"📋 Объявления (стр. {page}/{total_pages}, всего {total}):\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n\n".join(lines) if lines else "Нет объявлений."
        )
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(f"◀️{page-1}", callback_data=f"op:anns:{page-1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton(f"{page+1}▶️", callback_data=f"op:anns:{page+1}"))
        btns = [nav] if nav else []
        btns.append([InlineKeyboardButton("🔙Назад", callback_data="con:owner_panel")])
        await safe_send(ctx.bot, user.id, text, reply_markup=InlineKeyboardMarkup(btns))
        return

    if cmd == "setcost":
        db.set_state(user.id, 'OP_SETCOST', {})
        await safe_send(ctx.bot, user.id,
            "💰 Установить стоимость игрока\n\n"
            "Введите данные в формате:\n"
            "<TG_ID> <стоимость>\n\n"
            "Например: <code>123456789 500</code>",
            parse_mode="HTML"
        )
        return

    if cmd == "setbudget":
        db.set_state(user.id, 'OP_SETBUDGET', {})
        await safe_send(ctx.bot, user.id,
            "🍋 Установить бюджет клуба\n\n"
            "Введите данные в формате:\n"
            "<название клуба> | <бюджет>\n\n"
            "Например: <code>Team Alpha | 10000</code>",
            parse_mode="HTML"
        )
        return

    if cmd == "finduser":
        db.set_state(user.id, 'OP_FINDUSER', {})
        await safe_send(ctx.bot, user.id,
            "🔍 Поиск пользователя\n\n"
            "Введите TG ID или никнейм (частично):"
        )
        return

    if cmd == "findclub":
        db.set_state(user.id, 'OP_FINDCLUB', {})
        await safe_send(ctx.bot, user.id,
            "🔍 Поиск клуба\n\n"
            "Введите название клуба (частично):"
        )
        return

    if cmd == "console_log":
        page = int(parts[1]) if len(parts) > 1 else 1
        lines_per_page = 35
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
        except FileNotFoundError:
            all_lines = []

        total_lines = len(all_lines)
        total_pages = max(1, (total_lines + lines_per_page - 1) // lines_per_page)
        # Page 1 = last lines (newest), page 2 = previous chunk, etc.
        start = total_lines - page * lines_per_page
        end   = total_lines - (page - 1) * lines_per_page
        chunk = all_lines[max(0, start):end]

        log_text = ''.join(chunk).strip() or '(лог пуст)'
        # Telegram message limit is 4096, truncate if needed
        header = (
            f"📟 Консоль бота — последние строки\n"
            f"📄 Страница {page}/{total_pages} | всего строк: {total_lines}\n"
            f"🕐 {msk_now()} (МСК)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        body = header + f"<code>{log_text}</code>"
        if len(body) > 4090:
            body = header + f"<code>{log_text[-(4090 - len(header)):]}</code>"

        nav = []
        if page < total_pages:
            nav.append(InlineKeyboardButton(f"⬆️Старше ({page+1})", callback_data=f"op:console_log:{page+1}"))
        if page > 1:
            nav.append(InlineKeyboardButton(f"⬇️Новее ({page-1})", callback_data=f"op:console_log:{page-1}"))
        btns = [nav] if nav else []
        btns.append([
            InlineKeyboardButton("🔄Обновить", callback_data="op:console_log:1"),
            InlineKeyboardButton("🔙Назад", callback_data="con:owner_panel")
        ])
        await safe_send(ctx.bot, user.id, body,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(btns)
        )
        return

    if cmd == "secrets":
        back_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙Назад", callback_data="con:owner_panel")
        ]])

        # Watched secrets block
        lines = []
        for key in WATCHED_SECRETS:
            val = os.environ.get(key, '')
            lines.append(f"🔑 <b>{key}</b>\n   <code>{mask_secret(val)}</code>")

        # Extra env vars that look like secrets — max 8, short names only
        extra = []
        for k, v in sorted(os.environ.items()):
            if k in WATCHED_SECRETS or k.startswith('_'):
                continue
            if k.isupper() and any(w in k for w in ('KEY', 'TOKEN', 'SECRET', 'PASS', 'AUTH')):
                extra.append(f"🔒 <b>{k}</b>: <code>{mask_secret(v)}</code>")
            if len(extra) >= 8:
                break

        header = (
            "🔐 Секреты и переменные окружения\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Значения замаскированы\n\n"
        )
        body = header + "📌 Основные:\n" + "\n".join(lines)
        if extra:
            body += "\n\n🗂 Прочие:\n" + "\n".join(extra)

        # Hard trim to Telegram limit
        if len(body) > 4000:
            body = body[:4000] + "\n…(обрезано)"

        await safe_send(ctx.bot, user.id, body, parse_mode="HTML", reply_markup=back_kb)
        return

    if cmd == "clear_log_file":
        try:
            open(LOG_FILE, 'w').close()
            await q.answer("✅ Лог-файл очищен.", show_alert=True)
        except Exception as e:
            await q.answer(f"❌ Ошибка: {e}", show_alert=True)
        return

async def show_ads_panel(bot, user_id):
    channels = db.get_ad_channels()
    now = int(time.time())
    lines = []
    btns = []
    for ch in channels:
        status = "🟢ВКЛ" if ch['enabled'] and not ch['paused'] else "⏸️Пауза" if ch['paused'] else "🔴ВЫКЛ"
        remaining = ch['expires_at'] - now if not ch['paused'] else ch['paused_remaining']
        rem_str = fmt_remaining(remaining)
        lines.append(f"Реклама {ch['id']} - {ch['url']} - {status}\n⏳Истекает через: {rem_str}")
        btns.append([
            InlineKeyboardButton("⏸️Пауза", callback_data=f"ad:pause:{ch['id']}"),
            InlineKeyboardButton("✅Включить", callback_data=f"ad:enable:{ch['id']}"),
            InlineKeyboardButton("❌Удалить", callback_data=f"ad:delete:{ch['id']}")
        ])

    text = (
        f"🔑Управление обязательными подписками в боте\n"
        f"- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -\n"
        f"⏳Время(МСК): {msk_now()}\n\n"
        f"Текущие каналы:\n" + ("\n\n".join(lines) if lines else "Нет каналов.")
    )
    btns.append([InlineKeyboardButton("➕Добавить канал", callback_data="ad:add")])
    btns.append([InlineKeyboardButton("🔙Меню", callback_data="con:back")])
    await bot.send_message(user_id, text, reply_markup=InlineKeyboardMarkup(btns))

async def handle_ad_callback(q, user, ctx, rest):
    level = db.admin_level(user.id)
    if user.id == config.OWNER_ID:
        level = 3
    if level < 2:
        await q.answer("❌ Нет доступа.", show_alert=True)
        return

    parts = rest.split(':')
    action = parts[0]

    if action == "add":
        db.set_state(user.id, 'ADM_AD_URL', {})
        await safe_send(ctx.bot, user.id, "✏️Введите ссылку на канал:")
        return

    ch_id = int(parts[1])

    if action == "pause":
        ch = next((c for c in db.get_ad_channels() if c['id'] == ch_id), None)
        if ch:
            now = int(time.time())
            remaining = ch['expires_at'] - now
            db.update_ad_channel(ch_id, paused=1, paused_remaining=max(0, remaining))
        await q.answer("⏸️ Реклама приостановлена.", show_alert=True)
        return

    if action == "enable":
        ch = next((c for c in db.get_ad_channels() if c['id'] == ch_id), None)
        if ch:
            now = int(time.time())
            new_expires = now + ch.get('paused_remaining', 0)
            db.update_ad_channel(ch_id, paused=0, enabled=1, expires_at=new_expires)
        await q.answer("✅ Реклама включена.", show_alert=True)
        return

    if action == "delete":
        db.delete_ad_channel(ch_id)
        await q.answer("❌ Реклама удалена.", show_alert=True)
        return

# ═══════════════════════════════════════════════════════════
#  MESSAGE HANDLER (state machine)
# ═══════════════════════════════════════════════════════════

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    user = msg.from_user
    chat = msg.chat

    if chat.type != 'private':
        return

    db.upsert_user(user.id, user.username or '')
    u = db.get_user(user.id)

    if u['is_banned']:
        await msg.reply_text("❌Сейчас вы не можете пользоваться функциями бота, так как вас заблокировал его администратор.")
        return

    text = msg.text or ''
    state, sdata = db.get_state(user.id)

    # ── Registration ──
    if state == 'REG_NICK':
        nickname = text.strip()
        if not nickname:
            await msg.reply_text("❌ Никнейм не может быть пустым. Введите ещё раз:")
            return
        db.update_user(user.id, nickname=nickname, is_registered=1)
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text(
            f"👤Регистрация в системе успешна. Ваш никнейм: {nickname}.\n"
            f"📌 Для смены никнейма зайдите в раздел «Объявления» и «🔄Смена никнейма».",
            reply_markup=main_menu_kb()
        )
        return

    # ── Nickname change ──
    if state == 'NICK_CHANGE':
        nickname = text.strip()
        if not nickname:
            await msg.reply_text("❌ Никнейм не может быть пустым. Введите ещё раз:")
            return
        db.update_user(user.id, nickname=nickname)
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text(f"✅ Никнейм изменён на: {nickname}", reply_markup=main_menu_kb())
        return

    # ── Support message ──
    if state == 'SUP_MSG':
        ticket_id = db.create_ticket(user.id, text)
        group_text = (
            f"🔊Новое обращение в техподдержку от: 🆔{user.id}\n"
            f"✏️Сообщение:\n{text}"
        )
        mid = await notify_admin_group(ctx.bot, group_text, reply_markup=admin_sup_kb(ticket_id))
        db.update_ticket(ticket_id, group_message_id=mid)
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text("✅ Ваше обращение отправлено в техподдержку!", reply_markup=main_menu_kb())
        return

    # ── Club find ──
    if state == 'CLUB_FIND':
        club = db.get_club_by_name(text.strip())
        if club:
            members = db.get_club_members(club['id'])
            lines = [f"{i+1}. {m.get('nickname') or ('ID:' + str(m['user_tg_id']))} - {m['role']}" for i, m in enumerate(members)]
            await msg.reply_text(
                f"💼Клуб: {club['name']}\n🍋Бюджет: {club['budget']}TMC\n\n"
                f"👤 Участники:\n" + ("\n".join(lines) if lines else "Нет участников.")
            )
        else:
            await msg.reply_text("❌ Клуб не найден.")
        db.set_state(user.id, 'NONE', {})
        return

    # ── Custom role input ──
    if state == 'ROLE_CUSTOM':
        club_id = sdata.get('club_id')
        target_id = sdata.get('target_id')
        role = text.strip()
        if role:
            db.set_member_role(club_id, target_id, role)
            db.add_log(user.id, "Установил кастомную роль", f"club_id={club_id}, target={target_id}, role={role}")
            await msg.reply_text(f"👤Пользователь назначен на роль {role}.")
        db.set_state(user.id, 'NONE', {})
        return

    # ── Club create ──
    if state == 'CC_NAME':
        db.set_state(user.id, 'CC_BUDGET', {'action': 'create_club', 'club_name': text.strip()})
        await msg.reply_text("Введите бюджет клуба(если нету - вводите 0, без TMC):")
        return

    if state == 'CC_BUDGET':
        club_name = sdata.get('club_name', '')
        budget = text.strip()
        db.set_state(user.id, 'CC_PREVIEW', {'action': 'create_club', 'club_name': club_name, 'budget': budget})
        await msg.reply_text(
            f"Название клуба: {club_name}\nБюджет клуба: {budget}",
            reply_markup=club_preview_kb()
        )
        return

    # ── Admin states ──
    if state.startswith('ADM_'):
        await handle_admin_state(msg, user, ctx, state, sdata, text)
        return

    # ── Announcement flows ──
    if state.startswith('ANN_'):
        await handle_ann_state(msg, user, ctx, state, sdata, text, u)
        return

    # ── Main menu buttons (registered users only) ──
    if not u['is_registered']:
        await msg.reply_text("Пожалуйста, зарегистрируйтесь сначала с помощью /start")
        return

    ok, unsub = await check_subscriptions(user.id, ctx.bot)
    if not ok:
        btns = [[InlineKeyboardButton(f"Канал {i+1}", url=ch['url'])] for i, ch in enumerate(unsub)]
        btns.append([InlineKeyboardButton("✅ Я подписался", callback_data="check_sub")])
        await msg.reply_text("Подпишитесь для пользования ботом:", reply_markup=InlineKeyboardMarkup(btns))
        return

    if text == "👤Профиль":
        nick = u['nickname'] or "Не указан"
        club = u['club'] or "Нет"
        cost = u['cost']
        await msg.reply_text(
            f"👤Ваш профиль:\n\n"
            f"📌Ваш никнейм: {nick}\n"
            f"🌐Ваш клуб: {club}\n"
            f"💰Ваша стоимость: {cost}TMC"
        )

    elif text == "📋Объявления":
        await msg.reply_text("💠Выберите тип объявления:", reply_markup=ann_menu_kb())

    elif text == "🌐Клуб":
        club_name = u.get('club', '')
        if club_name:
            club = db.get_club_by_name(club_name)
            if club:
                await show_club_info(msg, user, ctx.bot, club, u)
                return
        await msg.reply_text("❌У вас еще нет клуба!", reply_markup=no_club_kb())

    elif text == "🆘Техподдержка":
        db.set_state(user.id, 'SUP_MSG', {})
        await msg.reply_text("💭Опишите свой вопрос или проблему, и мы постараемся ответить в ближайшее время.")

    elif text == "🔙Назад":
        db.set_state(user.id, 'NONE', {})
        await send_main_menu(ctx.bot, user.id)

    elif text == "🚨Трансфер":
        db.set_state(user.id, 'ANN_TRANSFER_OLD', {'ann_type': 'transfer'})
        await msg.reply_text("⚔️Введите название прошлого клуба, из которого переходите (или 👤Сво агент, если нету)")

    elif text == "📢Свободный агент":
        db.set_state(user.id, 'ANN_FA_PS', {'ann_type': 'free_agent'})
        await msg.reply_text("Введите P.S: (без самого P.S, просто текст)")

    elif text == "🥀Завершение карьеры":
        db.set_state(user.id, 'ANN_CE_PS', {'ann_type': 'career_end'})
        await msg.reply_text("Введите P.S: (без самого P.S, просто текст)")

    elif text == "⚔️Поиск скрима":
        db.set_state(user.id, 'ANN_SCRIM_CLUB', {'ann_type': 'scrim'})
        await msg.reply_text("⚔️Введите название клуба:")

    elif text == "✅Возвращение карьеры":
        db.set_state(user.id, 'ANN_CR_PS', {'ann_type': 'career_return'})
        await msg.reply_text("Введите P.S: (без самого P.S, просто текст)")

    elif text == "⏸️Приостановление карьеры":
        db.set_state(user.id, 'ANN_CP_PS', {'ann_type': 'career_pause'})
        await msg.reply_text("Введите P.S: (без самого P.S, просто текст)")

    elif text == "✏️Свой текст":
        db.set_state(user.id, 'ANN_CUSTOM', {'ann_type': 'custom'})
        await msg.reply_text(
            "❗️Здесь вы можете написать свой текст для поиска игроков. "
            "Если надо, прикрепите изображение или видео.\n"
            "ВАЖНАЯ ДЕТАЛЬ: пишите свой юз, чтобы пользователи знали, кому писать."
        )

    elif text == "💳Реклама":
        await msg.reply_text(
            "Пользователь не сможет использовать бота, пока не подпишется на ваш канал. "
            "Гарантированный приток живой аудитории!\n\n"
            "⏳ 1 день — 25 ⭐️\n"
            "⚡️ 3 дня — 50 ⭐️\n"
            "🚀 7 дней — 100 ⭐️\n\n"
            "📩 Рассылка по базе\n"
            "Отправка вашего рекламного поста всем пользователям бота:\n\n"
            "📢 1 рассылка — 50 ⭐️\n"
            "За покупкой @Sosison5209",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙Назад", callback_data="ann:back")
            ]])
        )

    elif text == "🔄Смена никнейма":
        db.set_state(user.id, 'NICK_CHANGE', {})
        await msg.reply_text("✏️Введите новый никнейм:")

# ═══════════════════════════════════════════════════════════
#  ANNOUNCEMENT STATE MACHINE
# ═══════════════════════════════════════════════════════════

async def handle_ann_state(msg, user, ctx, state, sdata, text, u):
    nick = u['nickname'] or user.first_name
    uname = f"@{u['username']}" if u.get('username') else f"ID:{user.id}"
    ann_type = sdata.get('ann_type', '')

    file_id = ''
    file_type = ''
    if msg.photo:
        file_id = msg.photo[-1].file_id
        file_type = 'photo'
        if not text:
            text = msg.caption or ''
    elif msg.video:
        file_id = msg.video.file_id
        file_type = 'video'
        if not text:
            text = msg.caption or ''

    # TRANSFER
    if state == 'ANN_TRANSFER_OLD':
        sdata['old_club'] = text
        db.set_state(user.id, 'ANN_TRANSFER_NEW', sdata)
        await msg.reply_text("⚔️Введите название нового клуба")
        return

    if state == 'ANN_TRANSFER_NEW':
        sdata['new_club'] = text
        db.set_state(user.id, 'ANN_TRANSFER_CONTRACT', sdata)
        await msg.reply_text("⏳Введите время контракта (к примеру - 19.06.2026)")
        return

    if state == 'ANN_TRANSFER_CONTRACT':
        sdata['contract'] = text
        db.set_state(user.id, 'ANN_TRANSFER_DEAL', sdata)
        await msg.reply_text("💰Введите сумму сделки (цифрой, без TMC, можно k для обозначение тысяч)")
        return

    if state == 'ANN_TRANSFER_DEAL':
        sdata['deal'] = text
        db.set_state(user.id, 'ANN_TRANSFER_BUYOUT', sdata)
        await msg.reply_text("💸Введите сумму отступных (цифрой, без TMC, можно k для обозначение тысяч)")
        return

    if state == 'ANN_TRANSFER_BUYOUT':
        sdata['buyout'] = text
        db.set_state(user.id, 'ANN_TRANSFER_PS', sdata)
        await msg.reply_text("❗️Введите P.S (без самого P.S, просто текст)")
        return

    if state == 'ANN_TRANSFER_PS':
        sdata['ps'] = text
        preview = build_transfer(sdata, nick, uname)
        sdata['preview_text'] = preview
        db.set_state(user.id, 'ANN_PREVIEW', sdata)
        await msg.reply_text(preview, reply_markup=preview_kb())
        return

    # FREE AGENT
    if state == 'ANN_FA_PS':
        sdata['ps'] = text
        preview = build_free_agent(sdata, nick, uname, u['cost'])
        sdata['preview_text'] = preview
        db.set_state(user.id, 'ANN_PREVIEW', sdata)
        await msg.reply_text(preview, reply_markup=preview_kb())
        return

    # CAREER END
    if state == 'ANN_CE_PS':
        sdata['ps'] = text
        preview = build_career_end(sdata, nick, uname)
        sdata['preview_text'] = preview
        db.set_state(user.id, 'ANN_PREVIEW', sdata)
        await msg.reply_text(preview, reply_markup=preview_kb())
        return

    # SCRIM
    if state == 'ANN_SCRIM_CLUB':
        sdata['club'] = text
        db.set_state(user.id, 'ANN_SCRIM_TIME', sdata)
        await msg.reply_text("⏳Введите время матча:")
        return

    if state == 'ANN_SCRIM_TIME':
        sdata['time'] = text
        preview = build_scrim(sdata, uname)
        sdata['preview_text'] = preview
        db.set_state(user.id, 'ANN_PREVIEW', sdata)
        await msg.reply_text(preview, reply_markup=preview_kb())
        return

    # CAREER RETURN
    if state == 'ANN_CR_PS':
        sdata['ps'] = text
        preview = build_career_return(sdata, nick, uname)
        sdata['preview_text'] = preview
        db.set_state(user.id, 'ANN_PREVIEW', sdata)
        await msg.reply_text(preview, reply_markup=preview_kb())
        return

    # CAREER PAUSE
    if state == 'ANN_CP_PS':
        sdata['ps'] = text
        preview = build_career_pause(sdata, nick, uname)
        sdata['preview_text'] = preview
        db.set_state(user.id, 'ANN_PREVIEW', sdata)
        await msg.reply_text(preview, reply_markup=preview_kb())
        return

    # CUSTOM TEXT
    if state == 'ANN_CUSTOM':
        if not text and not file_id:
            await msg.reply_text("❌ Введите текст или прикрепите медиа.")
            return
        sdata['preview_text'] = text
        sdata['file_id'] = file_id
        sdata['file_type'] = file_type
        db.set_state(user.id, 'ANN_PREVIEW', sdata)
        if file_type == 'photo' and file_id:
            await msg.reply_photo(file_id, caption=text or '(без текста)', reply_markup=preview_kb())
        elif file_type == 'video' and file_id:
            await msg.reply_video(file_id, caption=text or '(без текста)', reply_markup=preview_kb())
        else:
            await msg.reply_text(text, reply_markup=preview_kb())
        return

# ═══════════════════════════════════════════════════════════
#  ADMIN STATE MACHINE
# ═══════════════════════════════════════════════════════════

async def handle_admin_state(msg, user, ctx, state, sdata, text):
    if not db.is_admin(user.id) and user.id != config.OWNER_ID:
        return

    level = db.admin_level(user.id)
    if user.id == config.OWNER_ID:
        level = 3

    # Remove admin
    if state == 'ADM_REMOVE_ID':
        try:
            target_id = int(text.strip())
        except ValueError:
            await msg.reply_text("❌ Неверный формат ID.")
            return
        if not db.is_admin(target_id):
            await msg.reply_text("❌ Этот пользователь не является администратором.")
            db.set_state(user.id, 'NONE', {})
            return
        db.set_state(user.id, 'ADM_REMOVE_REASON', {'target_id': target_id})
        db.remove_admin(target_id)
        await msg.reply_text(
            f"🧨Администратор был успешно снят(TG ID: {target_id}). Напишите причину⬇️"
        )
        return

    if state == 'ADM_REMOVE_REASON':
        target_id = sdata.get('target_id')
        reason = text.strip()
        db.add_log(user.id, "Снял администратора", f"target={target_id}, причина={reason}")
        db.set_state(user.id, 'NONE', {})
        await safe_send(ctx.bot, target_id,
            f"❌ Вы были сняты с поста администратора.\n❗️Причина: {reason}")
        await msg.reply_text("✅ Причина записана, администратор уведомлён.")
        return

    # Add admin
    if state == 'ADM_ADD_ID':
        try:
            target_id = int(text.strip())
        except ValueError:
            await msg.reply_text("❌ Неверный формат ID.")
            return
        db.upsert_user(target_id)
        db.add_admin(target_id, level=1)
        db.add_log(user.id, "Добавил администратора", f"target={target_id}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text(f"✅👤Администратор (TG ID: {target_id} успешно добавлен на пост админа!")
        await safe_send(ctx.bot, target_id, "✅👤Вы были успешно добавлены на пост администратора!")
        return

    # Ban
    if state == 'ADM_BAN_ID':
        try:
            target_id = int(text.strip())
        except ValueError:
            await msg.reply_text("❌ Неверный формат ID.")
            return
        db.upsert_user(target_id)
        db.update_user(target_id, is_banned=1)
        db.add_log(user.id, "Забанил пользователя", f"target={target_id}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text(f"❌Пользователь успешно забанен, теперь он не может пользоваться ботом.")
        return

    # Unban
    if state == 'ADM_UNBAN_ID':
        try:
            target_id = int(text.strip())
        except ValueError:
            await msg.reply_text("❌ Неверный формат ID.")
            return
        db.update_user(target_id, is_banned=0)
        db.add_log(user.id, "Разбанил пользователя", f"target={target_id}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text(f"✅Пользователь успешно разбанен, теперь он может пользоваться ботом.")
        return

    # Announce reject
    if state == 'ADM_ANN_REJECT':
        ann_id = sdata.get('ann_id')
        group_msg_id = sdata.get('group_msg_id')
        reason = text.strip()
        ann = db.get_ann(ann_id)
        if ann:
            db.update_ann(ann_id, status='rejected')
            db.add_log(user.id, "Отклонил объявление", f"ann_id={ann_id}, причина={reason}")
            await remove_buttons(ctx.bot, config.ADMIN_GROUP_ID, group_msg_id)
            await ctx.bot.send_message(config.ADMIN_GROUP_ID,
                f"❌ Объявление #{ann_id} отклонено. 🆔{user.id}\nПричина: {reason}")
            await safe_send(ctx.bot, ann['user_id'],
                f"❌Ваша заявка была отклонена\n❗️Причина: {reason}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text("✅ Причина записана.")
        return

    # Support reply
    if state == 'ADM_SUP_REPLY':
        ticket_id = sdata.get('ticket_id')
        group_msg_id = sdata.get('group_msg_id')
        reply_text = text.strip()
        ticket = db.get_ticket(ticket_id)
        if ticket:
            db.update_ticket(ticket_id, status='replied')
            db.add_log(user.id, "Ответил на обращение в поддержку", f"ticket_id={ticket_id}, ответ={reply_text}")
            await remove_buttons(ctx.bot, config.ADMIN_GROUP_ID, group_msg_id)
            await ctx.bot.send_message(config.ADMIN_GROUP_ID,
                f"✅ Обращение #{ticket_id} — ответ отправлен. 🆔{user.id}")
            await safe_send(ctx.bot, ticket['user_id'],
                f"✅Вам пришел ответ от поддержки!\n\n✏️Текст:\n{reply_text}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text("✅ Ответ отправлен пользователю.")
        return

    # Support reject
    if state == 'ADM_SUP_REJECT':
        ticket_id = sdata.get('ticket_id')
        group_msg_id = sdata.get('group_msg_id')
        reason = text.strip()
        ticket = db.get_ticket(ticket_id)
        if ticket:
            db.update_ticket(ticket_id, status='rejected')
            db.add_log(user.id, "Отклонил обращение в поддержку", f"ticket_id={ticket_id}, причина={reason}")
            await remove_buttons(ctx.bot, config.ADMIN_GROUP_ID, group_msg_id)
            await ctx.bot.send_message(config.ADMIN_GROUP_ID,
                f"❌ Обращение #{ticket_id} отклонено. 🆔{user.id}")
            await safe_send(ctx.bot, ticket['user_id'],
                f"❌Ваше обращение было отклонено\n\n❗️Причина: {reason}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text("✅ Причина записана.")
        return

    # Club request reject
    if state == 'ADM_CLUB_REJECT':
        req_id = sdata.get('req_id')
        group_msg_id = sdata.get('group_msg_id')
        target_user_id = sdata.get('user_id')
        reason = text.strip()
        req = db.get_club_request(req_id)
        if req:
            db.update_club_request(req_id, status='rejected')
            db.add_log(user.id, "Отклонил заявку на создание клуба", f"req_id={req_id}, причина={reason}")
            await remove_buttons(ctx.bot, config.ADMIN_GROUP_ID, group_msg_id)
            await safe_send(ctx.bot, target_user_id,
                f"❌Ваша заявка была отклонена\n❗️Причина: {reason}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text("✅ Причина записана.")
        return

    # Broadcast
    if state == 'ADM_BROADCAST':
        if level < 2:
            db.set_state(user.id, 'NONE', {})
            return
        broadcast_text = msg.text or msg.caption or ''
        file_id = ''
        file_type = ''
        if msg.photo:
            file_id = msg.photo[-1].file_id
            file_type = 'photo'
        elif msg.video:
            file_id = msg.video.file_id
            file_type = 'video'

        await msg.reply_text("⚠️Начинаю рассылку...")
        all_ids = db.all_user_ids()
        sent = 0
        for uid in all_ids:
            try:
                if file_type == 'photo':
                    await ctx.bot.send_photo(uid, file_id, caption=broadcast_text)
                elif file_type == 'video':
                    await ctx.bot.send_video(uid, file_id, caption=broadcast_text)
                else:
                    await ctx.bot.send_message(uid, broadcast_text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        db.set_state(user.id, 'NONE', {})
        db.add_log(user.id, "Сделал рассылку", f"отправлено={sent}")
        await msg.reply_text(f"✅Рассылка успешно окончена. Отправлено: {sent}")
        return

    # Promote
    if state == 'ADM_PROMOTE_ID':
        if level < 2:
            db.set_state(user.id, 'NONE', {})
            return
        try:
            target_id = int(text.strip())
        except ValueError:
            await msg.reply_text("❌ Неверный формат ID.")
            return
        if not db.is_admin(target_id):
            await msg.reply_text("❌ Пользователь не является администратором.")
            db.set_state(user.id, 'NONE', {})
            return
        db.promote_admin(target_id, 2)
        db.add_log(user.id, "Повысил администратора", f"target={target_id}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text("✅Администратор повышен!")
        await safe_send(ctx.bot, target_id, "✅ Вас повысили до старшего администратора!")
        return

    # Give 2nd owner (level 3)
    if state == 'ADM_GIVE2VLD':
        if level < 3:
            db.set_state(user.id, 'NONE', {})
            return
        try:
            target_id = int(text.strip())
        except ValueError:
            await msg.reply_text("❌ Неверный формат ID.")
            return
        db.upsert_user(target_id)
        db.add_admin(target_id, level=3)
        db.add_log(user.id, "Дал статус 2-го владельца", f"target={target_id}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text(f"✅ Пользователю {target_id} выдан статус 2-го владельца!")
        await safe_send(ctx.bot, target_id, "✅ Вам выдан статус 2-го владельца бота!")
        return

    # Owner panel: set cost
    if state == 'OP_SETCOST':
        parts = text.strip().split()
        if len(parts) != 2:
            await msg.reply_text("❌ Формат: <TG_ID> <стоимость>\nПример: 123456789 500")
            return
        try:
            target_id = int(parts[0])
            cost = int(parts[1])
        except ValueError:
            await msg.reply_text("❌ Неверный формат. TG ID и стоимость должны быть числами.")
            return
        target = db.get_user(target_id)
        if not target:
            await msg.reply_text("❌ Пользователь не найден.")
            db.set_state(user.id, 'NONE', {})
            return
        db.update_user(target_id, cost=cost)
        db.add_log(user.id, "Изменил стоимость игрока", f"target={target_id}, cost={cost}")
        db.set_state(user.id, 'NONE', {})
        nick = target.get('nickname') or f"ID:{target_id}"
        await msg.reply_text(f"✅ Стоимость игрока {nick} (🆔{target_id}) установлена: {cost} TMC")
        return

    # Owner panel: set club budget
    if state == 'OP_SETBUDGET':
        if '|' not in text:
            await msg.reply_text("❌ Формат: <название клуба> | <бюджет>\nПример: Team Alpha | 10000")
            return
        club_name, budget_str = text.split('|', 1)
        club_name = club_name.strip()
        budget_str = budget_str.strip()
        club = db.get_club_by_name(club_name)
        if not club:
            await msg.reply_text(f"❌ Клуб «{club_name}» не найден.")
            db.set_state(user.id, 'NONE', {})
            return
        db.update_club_budget(club['id'], budget_str)
        db.add_log(user.id, "Изменил бюджет клуба", f"club={club_name}, budget={budget_str}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text(f"✅ Бюджет клуба «{club_name}» установлен: {budget_str} TMC")
        return

    # Owner panel: find user
    if state == 'OP_FINDUSER':
        query = text.strip()
        results = db.search_users(query)
        db.set_state(user.id, 'NONE', {})
        if not results:
            await msg.reply_text("❌ Пользователи не найдены.")
            return
        lines = []
        for u in results[:15]:
            nick = u['nickname'] or '—'
            club = u['club'] or '—'
            uname = f"@{u['username']}" if u.get('username') else '—'
            status = "🚫Бан" if u['is_banned'] else ("✅Рег" if u['is_registered'] else "⭕Нерег")
            adm = db.get_admin(u['tg_id'])
            adm_str = f" | 👮Адм.ур.{adm['level']}" if adm else ""
            lines.append(
                f"🆔 {u['tg_id']} {uname}\n"
                f"   📌 {nick} | 🌐 {club} | 💰 {u['cost']}TMC | {status}{adm_str}"
            )
        await msg.reply_text(
            f"🔍 Результаты поиска ({len(results)} найдено):\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n" +
            "\n\n".join(lines) + ("\n\n…и ещё." if len(results) > 15 else ""),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙Панель", callback_data="con:owner_panel")]])
        )
        return

    # Owner panel: find club
    if state == 'OP_FINDCLUB':
        query = text.strip()
        results = db.search_clubs(query)
        db.set_state(user.id, 'NONE', {})
        if not results:
            await msg.reply_text("❌ Клубы не найдены.")
            return
        lines = []
        for c in results[:10]:
            members = db.get_club_members(c['id'])
            owner = db.get_user(c['owner_id'])
            owner_nick = owner['nickname'] if owner else f"ID:{c['owner_id']}"
            member_lines = [f"   {i+1}. {m.get('nickname') or ('ID:'+str(m['user_tg_id']))} — {m['role']}" for i, m in enumerate(members)]
            lines.append(
                f"🏆 {c['name']}\n"
                f"   👑 Владелец: {owner_nick} (🆔{c['owner_id']})\n"
                f"   🍋 Бюджет: {c['budget']} TMC\n"
                f"   👥 Участники ({len(members)}):\n" +
                "\n".join(member_lines)
            )
        await msg.reply_text(
            f"🔍 Результаты поиска ({len(results)} найдено):\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n" +
            "\n\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙Панель", callback_data="con:owner_panel")]])
        )
        return

    # Ad channel URL
    if state == 'ADM_AD_URL':
        if level < 2:
            db.set_state(user.id, 'NONE', {})
            return
        db.set_state(user.id, 'ADM_AD_HOURS', {'url': text.strip()})
        await msg.reply_text("⏳Введите время, сколько будет висеть реклама, в формате: 42 (число часов):")
        return

    if state == 'ADM_AD_HOURS':
        if level < 2:
            db.set_state(user.id, 'NONE', {})
            return
        url = sdata.get('url', '')
        try:
            hours = int(text.strip())
        except ValueError:
            await msg.reply_text("❌ Введите число часов (цифрой).")
            return
        db.add_ad_channel(url, hours)
        db.add_log(user.id, "Добавил рекламный канал", f"url={url}, hours={hours}")
        db.set_state(user.id, 'NONE', {})
        await msg.reply_text(f"✅ Канал добавлен в список рекламы на {hours} часов.")
        return

# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def main():
    db.init_db()

    # Ensure owner is admin
    if not db.is_admin(config.OWNER_ID):
        db.add_admin(config.OWNER_ID, level=3)

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("console", cmd_console))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(
        filters.ALL & ~filters.COMMAND,
        on_message
    ))

    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
