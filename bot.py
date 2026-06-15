import os
import logging
from datetime import date, datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
import database as db
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
BOT_TOKEN = os.getenv('BOT_TOKEN')

TAGS_STATE, NOTE_STATE = range(2)
GOAL_TYPE_STATE, GOAL_TEXT_STATE, GOAL_COMPLETE_STATE = range(3, 6)


def make_progress_bar(current: int, maximum: int, size: int = 10) -> str:
    filled = min(int((current / maximum) * size), size) if maximum > 0 else 0
    return '█' * filled + '░' * (size - filled)


def tags_keyboard(selected: list) -> InlineKeyboardMarkup:
    rows = []
    current_row = []
    for tag in db.TAGS:
        emoji = db.TAG_EMOJIS.get(tag, '')
        if tag in selected:
            label = f'✅ {tag}'
        else:
            label = f'{emoji} {tag}'
        current_row.append(InlineKeyboardButton(label, callback_data=f'tag:{tag}'))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([
        InlineKeyboardButton('📝 Заметка', callback_data='action:note'),
        InlineKeyboardButton('💾 Сохранить', callback_data='action:save'),
    ])
    return InlineKeyboardMarkup(rows)


def format_tags(tags: list) -> str:
    if not tags:
        return 'не выбраны'
    return ' '.join(f"{db.TAG_EMOJIS.get(t, '')} {t}" for t in tags)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username or '', user.first_name or '')
    text = (
        f'Привет, {user.first_name}! 👋\n\n'
        'Я твой личный календарь-трекер.\n'
        'Каждый день фиксируй что происходит — и в конце года увидишь свой год целиком.\n\n'
        '📋 Команды:\n'
        '/today — записать день\n'
        '/goals — цели и задачи\n'
        '/stats — моя статистика\n'
        '/help — помощь'
    )
    await update.message.reply_text(text)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        '📋 Команды:\n\n'
        '/today — записать сегодняшний день: выбрать теги и добавить заметку\n'
        '/goals — просмотр целей, добавление и завершение\n'
        '/stats — твоя статистика: уровень, XP, стрики, прогресс года\n\n'
        'Теги дней:\n'
        '💼 WORK · 🏠 HOME · ❤️ LOVE\n'
        '👥 FRIENDS · ✈️ TRAVEL · 🏃 SPORT · 🎵 MUSIC'
    )
    await update.message.reply_text(text)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    stats = db.get_user_stats(user_tg.id)
    if not stats:
        await update.message.reply_text('Сначала зарегистрируйся: /start')
        return
    u = stats['user']
    xp = u.get('xp', 0)
    level = u.get('level', 1)
    xp_in_level = xp % 100
    bar = make_progress_bar(xp_in_level, 100, 10)
    year_bar = make_progress_bar(stats['year_entries'], 365, 20)
    streak = u.get('streak', 0)
    text = (
        f'📊 Статистика\n\n'
        f'⚡ Уровень {level}  [{bar}]  {xp_in_level}/100 XP\n'
        f'🔥 Стрик: {streak} дн.\n\n'
        f'📅 Дней записано в этом году:\n'
        f'{year_bar} {stats["year_entries"]}/365\n\n'
        f'🎯 Целей активных: {stats["total_goals"] - stats["completed_goals"]}\n'
        f'✅ Целей выполнено: {stats["completed_goals"]}'
    )
    await update.message.reply_text(text)


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    db.get_or_create_user(user.id, user.username or '', user.first_name or '')
    today = date.today()
    existing = db.get_day_entry(user.id, today)
    ctx.user_data['selected_tags'] = list(existing['tags']) if existing and existing.get('tags') else []
    ctx.user_data['note'] = existing.get('note', '') if existing else ''
    ctx.user_data['today'] = today
    mode = 'Редактируем запись' if existing else 'Как прошёл день?'
    text = (
        f'{mode} — {today.strftime("%d.%m.%Y")}\n\n'
        'Выбери теги (можно несколько):'
    )
    kb = tags_keyboard(ctx.user_data['selected_tags'])
    await update.message.reply_text(text, reply_markup=kb)
    return TAGS_STATE


async def cb_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    tag = query.data.split(':')[1]
    selected = ctx.user_data.get('selected_tags', [])
    if tag in selected:
        selected.remove(tag)
    else:
        selected.append(tag)
    ctx.user_data['selected_tags'] = selected
    text = (
        f'Выбери теги для {ctx.user_data["today"].strftime("%d.%m.%Y")}:\n\n'
        f'Выбрано: {format_tags(selected)}'
    )
    await query.edit_message_text(text, reply_markup=tags_keyboard(selected))
    return TAGS_STATE


async def cb_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(':')[1]
    if action == 'note':
        await query.edit_message_text(
            f'✏️ Напиши заметку к этому дню:\n(или /skip чтобы пропустить)'
        )
        return NOTE_STATE
    elif action == 'save':
        await _do_save(query, ctx, is_callback=True)
        return ConversationHandler.END


async def receive_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text != '/skip':
        ctx.user_data['note'] = text
    await _do_save(update, ctx, is_callback=False)
    return ConversationHandler.END


async def _do_save(source, ctx: ContextTypes.DEFAULT_TYPE, is_callback: bool):
    if is_callback:
        user_id = source.from_user.id
    else:
        user_id = source.effective_user.id
    tags = ctx.user_data.get('selected_tags', [])
    note = ctx.user_data.get('note', '')
    today = ctx.user_data.get('today', date.today())
    db.save_day_entry(user_id, today, tags, note)
    user = db.get_user(user_id)
    xp = user.get('xp', 0) if user else 0
    level = user.get('level', 1) if user else 1
    streak = user.get('streak', 0) if user else 0
    xp_in_level = xp % 100
    bar = make_progress_bar(xp_in_level, 100, 10)
    lines = [
        f'✅ День {today.strftime("%d.%m.%Y")} сохранён!',
        '',
        f'Теги: {format_tags(tags)}',
    ]
    if note:
        lines.append(f'Заметка: {note}')
    lines += [
        '',
        f'🔥 Стрик: {streak} дн.',
        f'⚡ Уровень {level}  [{bar}]  {xp_in_level}/100 XP',
    ]
    reply_text = '\n'.join(lines)
    if is_callback:
        await source.edit_message_text(reply_text)
    else:
        await source.message.reply_text(reply_text)


async def cmd_goals(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    goals = db.get_active_goals(user_id)
    rows = []
    if goals:
        text_lines = ['🎯 Активные цели:\n']
        for g in goals:
            type_emoji = {'day': '📅', 'week': '📆', 'month': '🗓'}.get(g['goal_type'], '🎯')
            text_lines.append(f"{type_emoji} {g['title']}")
            rows.append([InlineKeyboardButton(f"✅ Выполнено: {g['title'][:20]}", callback_data=f"done:{g['id']}")])
        text = '\n'.join(text_lines)
    else:
        text = '🎯 Активных целей нет. Добавь первую!'
    rows.append([
        InlineKeyboardButton('📅 + день', callback_data='newgoal:day'),
        InlineKeyboardButton('📆 + неделя', callback_data='newgoal:week'),
        InlineKeyboardButton('🗓 + месяц', callback_data='newgoal:month'),
    ])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))
    return GOAL_TYPE_STATE


async def cb_new_goal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    goal_type = query.data.split(':')[1]
    ctx.user_data['new_goal_type'] = goal_type
    type_name = {'day': 'день', 'week': 'неделю', 'month': 'месяц'}.get(goal_type, 'период')
    await query.edit_message_text(f'✏️ Напиши цель на {type_name}:')
    return GOAL_TEXT_STATE


async def receive_goal_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    title = update.message.text
    goal_type = ctx.user_data.get('new_goal_type', 'day')
    period_start = date.today().isoformat()
    db.add_goal(user_id, goal_type, period_start, title)
    type_name = {'day': 'день', 'week': 'неделю', 'month': 'месяц'}.get(goal_type, 'период')
    await update.message.reply_text(
        f'✅ Цель на {type_name} добавлена:\n«{title}»\n\nУдачи! 💪'
    )
    return ConversationHandler.END


async def cb_complete_goal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    goal_id = query.data.split(':')[1]
    ctx.user_data['completing_goal_id'] = goal_id
    await query.edit_message_text(
        '🏆 Отлично! Напиши пару слов о том, как это было:\n(или /skip чтобы пропустить)'
    )
    return GOAL_COMPLETE_STATE


async def receive_goal_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text
    closing_note = '' if text == '/skip' else text
    goal_id = ctx.user_data.get('completing_goal_id', '')
    db.complete_goal(user_id, goal_id, closing_note)
    user = db.get_user(user_id)
    xp = user.get('xp', 0) if user else 0
    level = user.get('level', 1) if user else 1
    xp_in_level = xp % 100
    bar = make_progress_bar(xp_in_level, 100, 10)
    await update.message.reply_text(
        f'🎉 Цель выполнена! +25 XP\n\n'
        f'⚡ Уровень {level}  [{bar}]  {xp_in_level}/100 XP'
    )
    return ConversationHandler.END


async def fallback_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await cmd_start(update, ctx)
    return ConversationHandler.END


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    today_conv = ConversationHandler(
        entry_points=[
            CommandHandler('today', cmd_today),
            MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_today),
        ],
        states={
            TAGS_STATE: [
                CallbackQueryHandler(cb_tag, pattern='^tag:'),
                CallbackQueryHandler(cb_action, pattern='^action:'),
            ],
            NOTE_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_note),
                CommandHandler('skip', receive_note),
            ],
        },
        fallbacks=[
            CommandHandler('start', fallback_start),
            CommandHandler('today', cmd_today),
            CommandHandler('goals', fallback_start),
            CommandHandler('stats', fallback_start),
        ],
        allow_reentry=True,
        per_message=False,
    )

    goals_conv = ConversationHandler(
        entry_points=[CommandHandler('goals', cmd_goals)],
        states={
            GOAL_TYPE_STATE: [
                CallbackQueryHandler(cb_new_goal, pattern='^newgoal:'),
                CallbackQueryHandler(cb_complete_goal, pattern='^done:'),
            ],
            GOAL_TEXT_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_goal_text),
            ],
            GOAL_COMPLETE_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_goal_note),
                CommandHandler('skip', receive_goal_note),
            ],
        },
        fallbacks=[
            CommandHandler('start', fallback_start),
            CommandHandler('goals', cmd_goals),
            CommandHandler('today', fallback_start),
            CommandHandler('stats', fallback_start),
        ],
        allow_reentry=True,
        per_message=False,
    )

    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('help', cmd_help))
    app.add_handler(CommandHandler('stats', cmd_stats))
    app.add_handler(today_conv)
    app.add_handler(goals_conv)

    logger.info('Бот запущен...')
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()