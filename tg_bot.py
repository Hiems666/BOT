import telebot
from telebot import types
import ai_expert

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

FORM_MATCHES = 5  # сколько последних матчей анализировать для формы команды в режиме ИИ

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
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            text="📊 Просмотр статистики",
            callback_data="mode_stats",
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            text="🧠 ИИ-прогноз на матч",
            callback_data="mode_ai",
        )
    )
    bot.send_message(
        message.chat.id,
        "Привет! ⚽️ Выбери режим работы:\n\n"
        "📊 *Просмотр статистики* — классический разбор последних матчей команды.\n"
        "🧠 *ИИ-прогноз на матч* — найду ближайший матч команды и дам прогноз "
        "по статистике обеих команд и коэффициентам букмекеров.",
        parse_mode="Markdown",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("mode_"))
def handle_mode_selection(call):
    chat_id = call.message.chat.id
    clear_state(chat_id)
    state = get_state(chat_id)
    mode = call.data.split("_", 1)[1]
    state["mode"] = mode
    bot.answer_callback_query(call.id)

    if mode == "ai":
        text = (
            "🧠 Режим ИИ-прогноза.\n\n"
            "Напиши название команды — найду её ближайший матч и подготовлю прогноз."
        )
    else:
        text = (
            "📊 Режим просмотра статистики.\n\n"
            "Напиши название команды (например: Аргентина или Зенит), "
            "и я найду её последние матчи со статистикой."
        )

    bot.edit_message_text(text, chat_id, call.message.message_id)


@bot.message_handler(content_types=["text"])
def handle_team_search(message):
    if message.text.startswith("/"):
        return

    chat_id = message.chat.id
    team_input = message.text.strip()
    mode = get_state(chat_id).get("mode", "stats")
    clear_state(chat_id)
    state = get_state(chat_id)
    state["mode"] = mode

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

    if state.get("mode") == "ai":
        show_ai_nearest_match(chat_id, call.message.message_id, state)
        return

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


def show_ai_nearest_match(chat_id, message_id, state):
    selected_team = state["selected_team"]
    bot.edit_message_text(
        f"🔎 Ищу ближайший матч команды {selected_team['name']}...",
        chat_id,
        message_id,
    )

    upcoming = football_api.get_nearest_upcoming_fixture(selected_team["id"])
    if not upcoming:
        bot.edit_message_text(
            f"⚠️ Не нашёл предстоящих матчей для {selected_team['name']}.\n"
            "Напиши название другой команды или /start.",
            chat_id,
            message_id,
        )
        return

    match = upcoming
    state["ai_match"] = match

    odds_preview = ""
    if match.get("fixture_id"):
        line = football_api.get_fixture_betting_line(
            match["fixture_id"],
            match["home_name"],
            match["away_name"],
            preferred_team=selected_team["name"],
        )
        if line and line.get("bookmakers"):
            book = line["bookmakers"][0]
            markets = book.get("markets", {})
            if "1" in markets and "X" in markets and "2" in markets:
                odds_preview = (
                    f"\n📊 Линия ({book['bookmaker']}): "
                    f"П1 {markets['1']} | X {markets['X']} | П2 {markets['2']}"
                )
            state["betting_line"] = line

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            text="🧠 Сделать ИИ-прогноз",
            callback_data="predict_go",
        )
    )

    bot.edit_message_text(
        f"📅 Ближайший матч:\n\n"
        f"*{match['home_name']}* — *{match['away_name']}*\n"
        f"🗓 {match['date']}{odds_preview}\n\n"
        "Запустить прогноз ИИ по форме обеих команд и линии букмекера?",
        chat_id,
        message_id,
        parse_mode="Markdown",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("analysis_"))
def handle_analysis_selection(call):
    chat_id = call.message.chat.id
    state = get_state(chat_id)

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


def _resolve_team_id(name, candidate_id):
    """Возвращает id команды: берёт готовый id, иначе ищет по названию."""
    if candidate_id and str(candidate_id) != "0":
        return candidate_id
    found = football_api.search_teams(name)
    return found[0]["id"] if found else None


@bot.callback_query_handler(func=lambda call: call.data == "predict_go")
def handle_ai_prediction(call):
    chat_id = call.message.chat.id
    state = get_state(chat_id)
    match = state.get("ai_match")
    selected_team = state.get("selected_team")

    if not match or not selected_team:
        bot.answer_callback_query(call.id, "Данные устарели. Начни заново: /start")
        return

    bot.answer_callback_query(call.id, "Запускаю ИИ-аналитика...")
    msg = bot.send_message(
        chat_id,
        "⏳ Собираю форму обеих команд и линию букмекера...\n"
        "Это может занять до минуты.",
    )

    home_name = match["home_name"]
    away_name = match["away_name"]

    home_id = _resolve_team_id(home_name, match.get("home_id"))
    away_id = _resolve_team_id(away_name, match.get("away_id"))

    home_form = football_api.get_team_form_stats(home_id, limit=FORM_MATCHES) if home_id else None
    away_form = football_api.get_team_form_stats(away_id, limit=FORM_MATCHES) if away_id else None

    odds_info = state.get("betting_line")
    if not odds_info:
        odds_info = football_api.get_fixture_betting_line(
            match.get("fixture_id"),
            home_name,
            away_name,
            preferred_team=selected_team["name"],
        )

    ai_text = ai_expert.get_match_prediction(
        home_name,
        away_name,
        home_form,
        away_form,
        odds_info,
        fixture_id=match.get("fixture_id"),
        home_id=home_id,
        away_id=away_id,
    )

    header = f"🧠 ИИ-прогноз на матч:\n{home_name} — {away_name}\n\n"
    bot.edit_message_text("✅ Готово! Вот разбор:", chat_id, msg.message_id)
    send_long_message(chat_id, header + ai_text)

    bot.send_message(
        chat_id,
        "Напиши название другой команды или отправь /start, чтобы сменить режим.",
    )


if __name__ == "__main__":
    print("🤖 Бот успешно запущен и ждет сообщений...")
    bot.infinity_polling()
