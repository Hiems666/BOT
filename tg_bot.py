import telebot
from telebot import types

import football_api
import json

with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

user_state = {}

ANALYSIS_OPTIONS = (
    ("1", "📋 Результаты"),
    ("2", "🚩 Фолы"),
    ("3", "🟨 Желтые карточки"),
    ("4", "🎯 Удары в створ"),
    ("5", "📊 Всё сразу"),
    ("6", "🚩 Офсайды"),
    ("7", "⚽ Удары"),
    ("8", "📐 Угловые"),
)

LIMIT_OPTIONS = (1, 5, 10, football_api.MAX_FIXTURE_LIMIT)

TELEGRAM_MESSAGE_LIMIT = 4096


def get_state(chat_id):
    if chat_id not in user_state:
        user_state[chat_id] = {}
    return user_state[chat_id]


def clear_state(chat_id):
    user_state.pop(chat_id, None)


def format_stat_line(choice, stats, exact_name):
    if choice == "2":
        return f"   🚩 Фолы ({exact_name}): {stats['Fouls']}"
    if choice == "3":
        return f"   🟨 Желтые карточки ({exact_name}): {stats['Yellow cards']}"
    if choice == "4":
        return f"   🎯 Удары в створ ({exact_name}): {stats['Shots on target']}"
    if choice == "5":
        return (
            f"   📊 Фолы: {stats['Fouls']} | ЖК: {stats['Yellow cards']} | "
            f"Удары: {stats['Shots']} | Удары в створ: {stats['Shots on target']} | "
            f"Угловые: {stats['Corners']} | Офсайды: {stats['Offsides']}"
        )
    if choice == "6":
        return f"   🚩 Офсайды ({exact_name}): {stats['Offsides']}"
    if choice == "7":
        return f"   ⚽ Удары ({exact_name}): {stats['Shots']}"
    if choice == "8":
        return f"   📐 Угловые ({exact_name}): {stats['Corners']}"
    return None


def build_results_text(selected_team, matches, choice):
    team_id = selected_team["id"]
    exact_name = selected_team["name"]
    divider = "-" * 40
    lines = [
        f"✅ {exact_name}",
        f"Матчей: {len(matches)}",
        "",
    ]

    for match in matches:
        fix_id = match["fixture_id"]
        date = match["date"]
        home = match["home_name"]
        away = match["away_name"]
        hg = match["home_goals"]
        ag = match["away_goals"]

        lines.append(f"[{date}] {home} {hg}:{ag} {away}")

        if choice != "1":
            is_home_team = team_id == match["home_id"]
            stats = football_api.get_fixture_statistics(fix_id, is_home_team)
            stat_line = format_stat_line(choice, stats, exact_name)
            if stat_line:
                lines.append(stat_line)

        lines.append(divider)

    return "\n".join(lines)


def send_long_message(chat_id, text):
    while text:
        chunk = text[:TELEGRAM_MESSAGE_LIMIT]
        if len(text) > TELEGRAM_MESSAGE_LIMIT:
            split_at = chunk.rfind("\n")
            if split_at > 0:
                chunk = text[:split_at]
        bot.send_message(chat_id, chunk)
        text = text[len(chunk):].lstrip("\n")


@bot.message_handler(commands=["start"])
def send_welcome(message):
    clear_state(message.chat.id)
    bot.send_message(
        message.chat.id,
        "Привет! ⚽️ Напиши название футбольной команды (например: Аргентина или Зенит), "
        "и я найду её последние матчи со статистикой.",
    )


@bot.message_handler(content_types=["text"])
def handle_team_search(message):
    if message.text.startswith("/"):
        return

    chat_id = message.chat.id
    team_input = message.text.strip()
    clear_state(chat_id)
    state = get_state(chat_id)

    msg = bot.send_message(chat_id, f"🔍 Ищу команду «{team_input}»...")
    teams = football_api.search_teams(team_input)

    if not teams:
        bot.edit_message_text(
            "❌ Команда не найдена. Попробуй другое название.",
            chat_id,
            msg.message_id,
        )
        return

    state["teams"] = teams

    markup = types.InlineKeyboardMarkup()
    for index, team in enumerate(teams):
        markup.add(
            types.InlineKeyboardButton(
                text=team["name"],
                callback_data=f"team_{index}",
            )
        )

    bot.edit_message_text(
        f"Найдено совпадений для «{team_input}». Выбери нужную команду:",
        chat_id,
        msg.message_id,
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("team_"))
def handle_team_selection(call):
    chat_id = call.message.chat.id
    state = get_state(chat_id)
    teams = state.get("teams", [])

    try:
        index = int(call.data.split("_", 1)[1])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "Некорректный выбор.")
        return

    if index < 0 or index >= len(teams):
        bot.answer_callback_query(call.id, "Устаревший выбор. Начни заново с /start")
        return

    selected_team = teams[index]
    state["selected_team"] = selected_team
    bot.answer_callback_query(call.id)

    markup = types.InlineKeyboardMarkup(row_width=2)
    for key, label in ANALYSIS_OPTIONS:
        markup.add(
            types.InlineKeyboardButton(
                text=label,
                callback_data=f"analysis_{key}",
            )
        )

    bot.edit_message_text(
        f"✅ Ты выбрал: {selected_team['name']}\n\n"
        "Что именно ты хочешь проанализировать?",
    chat_id,
    call.message.message_id,
    reply_markup=markup,
)

    try:
        choice = call.data.split("_", 1)[1]
    except IndexError:
        bot.answer_callback_query(call.id, "Некорректный выбор.")
        return

    if choice not in {key for key, _ in ANALYSIS_OPTIONS}:
        bot.answer_callback_query(call.id, "Некорректный выбор.")
        return

    state["analysis_choice"] = choice
    bot.answer_callback_query(call.id)

    markup = types.InlineKeyboardMarkup(row_width=4)
    for limit in LIMIT_OPTIONS:
        markup.add(
            types.InlineKeyboardButton(
                text=str(limit),
                callback_data=f"limit_{limit}",
            )
        )

    bot.edit_message_text(
        f"Сколько последних матчей показать? (макс. {football_api.MAX_FIXTURE_LIMIT})",
        chat_id,
        call.message.message_id,
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("limit_"))
def handle_limit_selection(call):
    chat_id = call.message.chat.id
    state = get_state(chat_id)
    selected_team = state.get("selected_team")
    choice = state.get("analysis_choice", "1")

    if not selected_team:
        bot.answer_callback_query(call.id, "Сначала выбери команду. /start")
        return

    try:
        limit = int(call.data.split("_", 1)[1])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "Некорректный выбор.")
        return

    if limit < 1:
        limit = 1
    elif limit > football_api.MAX_FIXTURE_LIMIT:
        limit = football_api.MAX_FIXTURE_LIMIT

    bot.answer_callback_query(call.id, "Загружаю данные...")
    bot.edit_message_text(
        "⏳ Загружаю данные (это может занять пару секунд)...",
        chat_id,
        call.message.message_id,
    )

    team_id = selected_team["id"]
    exact_name = selected_team["name"]
    matches = football_api.get_recent_fixtures(team_id, limit=limit)

    if not matches:
        bot.edit_message_text(
            f"⚠️ Нет завершенных матчей для {exact_name}.",
            chat_id,
            call.message.message_id,
        )
        return

    result_text = build_results_text(selected_team, matches, choice)
    bot.edit_message_text(
        f"✅ Готово. Отправляю статистические данные команды {exact_name}...",
        chat_id,
        call.message.message_id,
    )
    send_long_message(chat_id, result_text)
    bot.send_message(
        chat_id,
        "Напиши название другой команды или отправь /start для нового запроса.",
    )
    clear_state(chat_id)


if __name__ == "__main__":
    print("🤖 Бот успешно запущен и ждет сообщений...")
    bot.infinity_polling()
