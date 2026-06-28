import json
from groq import Groq

import football_api

with open("config.json", "r", encoding="utf-8") as config_file:
    config_data = json.load(config_file)

client = Groq(api_key=config_data["GROQ_API_KEY"])

STAT_LABELS = {
    "Shots": "удары",
    "Shots on target": "удары в створ",
    "Corners": "угловые",
    "Fouls": "фолы",
    "Yellow cards": "жёлтые карточки",
    "Offsides": "офсайды",
}


def get_match_analysis(team_name, stats_dict):
    """Отправляет статистику нейросети и получает экспертный комментарий."""
    system_prompt = (
        "Ты - профессиональный футбольный аналитик. "
        "Пиши коротко, емко и по делу. Никакой воды. "
        "Сделай вывод о форме и возможностях команды на основе предоставленной статистики."
    )
    user_message = (
        f"Проанализируй последний матч команды {team_name}. "
        f"Вот статистика : {stats_dict}. "
        "Что можешь сказать об их игре?"
    )

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=250,
        )
        return chat_completion.choices[0].message.content

    except Exception as e:
        print(f"[Дебаг] ❌ Ошибка API Groq: {e}")
        return "Аналитик сейчас пьет кофе и недоступен. Вернемся к голым цифрам."


def _format_form(name, form):
    if not form:
        return f"{name}: статистика формы недоступна."

    avg = form["averages"]
    rec = form["record"]
    results = ", ".join(form["recent_results"]) if form["recent_results"] else "нет данных"
    return (
        f"{name}: проанализировано матчей — {form['matches_analyzed']}; "
        f"баланс В-Н-П: {rec['wins']}-{rec['draws']}-{rec['losses']}; "
        f"в среднем забивает {form['avg_goals_for']}, пропускает {form['avg_goals_against']} за матч. "
        f"Средние за матч — удары: {avg.get('Shots')}, удары в створ: {avg.get('Shots on target')}, "
        f"угловые: {avg.get('Corners')}, фолы: {avg.get('Fouls')}, "
        f"жёлтые карточки: {avg.get('Yellow cards')}, офсайды: {avg.get('Offsides')}. "
        f"Последние результаты: {results}."
    )


def _format_match_intelligence(home_name, away_name, intelligence):
    """Форматирует блок силы, контекста и скорректированных ожиданий для нейросети."""
    if not intelligence:
        return "Контекст матча недоступен — учитывай силу соперника и мотивацию вручную."

    lines = ["АНАЛИТИЧЕСКИЙ КОНТЕКСТ МАТЧА (используй как основу, не игнорируй):"]

    if intelligence.get("competition"):
        lines.append(f"- Турнир / контекст: {intelligence['competition']}")

    hs = intelligence.get("home_strength")
    aws = intelligence.get("away_strength")
    if hs is not None and aws is not None:
        lines.append(
            f"- Индекс силы (1–10, по форме): {home_name} {hs} vs {away_name} {aws} "
            f"(разница {intelligence.get('strength_gap', '—')})."
        )
        if intelligence.get("strength_gap") is not None:
            gap = intelligence["strength_gap"]
            if gap >= 2:
                lines.append(
                    f"  → {home_name} заметно сильнее — {away_name} вряд ли покажет свою среднюю результативность."
                )
            elif gap <= -2:
                lines.append(
                    f"  → {away_name} заметно сильнее — {home_name} вряд ли покажет свою среднюю результативность."
                )

    home_elo = intelligence.get("home_elo")
    away_elo = intelligence.get("away_elo")
    if home_elo is not None and away_elo is not None:
        lines.append(
            f"- Рейтинг Elo (по последним {football_api.ELO_HISTORY_LIMIT} матчам): "
            f"{home_name} {home_elo} vs {away_name} {away_elo} "
            f"(разница {intelligence.get('elo_gap', '—')})."
        )
        elo_probs = intelligence.get("elo_probs")
        if elo_probs:
            lines.append(
                f"  → Вероятности Elo: П1 {elo_probs['home_win_pct']}% | "
                f"X {elo_probs['draw_pct']}% | П2 {elo_probs['away_win_pct']}%."
            )

    h2h = intelligence.get("head_to_head")
    if h2h and h2h.get("count"):
        lines.append(
            f"- Личные встречи ({h2h['count']} матчей): "
            f"{home_name} {h2h['home_wins']} побед, {h2h['draws']} ничьих, "
            f"{away_name} {h2h['away_wins']} побед; "
            f"средний тотал {h2h['avg_total_goals']} гола."
        )
        if h2h.get("recent_results"):
            lines.append(f"  → Последние: {'; '.join(h2h['recent_results'][:3])}.")

    odds_balance = intelligence.get("odds_balance")
    if odds_balance:
        lines.append(
            f"- Оценка линии ({odds_balance.get('bookmaker', 'БК')}): "
            f"П1 {odds_balance['home_odds']} | X {odds_balance.get('draw_odds', '—')} | "
            f"П2 {odds_balance['away_odds']}. "
            f"Фаворит: {odds_balance['favorite']}. {odds_balance['mismatch']}."
        )

    for note in intelligence.get("importance_notes", []):
        lines.append(f"- Мотивация / контекст: {note}")

    expected = intelligence.get("expected_goals")
    naive = intelligence.get("naive_total_goals")
    if expected:
        lines.extend([
            "",
            "СКОРРЕКТИРОВАННЫЕ ОЖИДАНИЯ (с учётом обороны соперника и разницы в классе):",
            f"- Ожидаемые голы: {home_name} ~{expected['home']}, {away_name} ~{expected['away']}, "
            f"тотал ~{expected['total']}.",
        ])
        if naive is not None:
            lines.append(
                f"- ⚠️ НЕ используй наивную сумму средних ({naive} гола) — это завышение, "
                f"если одна команда слабее и играет против сильной обороны."
            )

    lines.extend([
        "",
        "ОРИЕНТИРЫ ПО СТАТИСТИКЕ (корректируй вниз при большом разрыве класса и игре аутсайдера от обороны):",
    ])

    return "\n".join(lines)


def _build_stat_insights(home_name, away_name, home_form, away_form, intelligence=None):
    """Дополнительные ориентиры по статистическим рынкам с поправкой на разрыв в классе."""
    if not home_form or not away_form:
        return "Статистических ориентиров мало."

    dampening = 1.0
    if intelligence:
        gap = intelligence.get("strength_gap")
        if gap is not None and abs(gap) >= 2:
            dampening = 0.85
        odds_balance = intelligence.get("odds_balance") or {}
        if odds_balance.get("odds_gap", 0) >= 3:
            dampening = min(dampening, 0.75)

    lines = []
    for stat_key, label in STAT_LABELS.items():
        home_avg = home_form["averages"].get(stat_key) or 0
        away_avg = away_form["averages"].get(stat_key) or 0
        if not home_avg and not away_avg:
            continue
        combined = round((home_avg + away_avg) * dampening, 1)
        lines.append(
            f"- {label}: сырая сумма средних {round(home_avg + away_avg, 1)}, "
            f"скорректированный ориентир ~{combined} (поправка на класс соперника)."
        )

    return "\n".join(lines) if lines else "Статистические ориентиры ограничены."


def _format_odds(odds_info):
    """Передаёт нейросети только реальные коэффициенты из спарсенной линии."""
    if not odds_info or not odds_info.get("bookmakers"):
        return (
            "Линия букмекера недоступна. "
            "НЕ ПРИДУМЫВАЙ коэффициенты — для таких прогнозов пиши «коэф. уточни в линии»."
        )

    source = odds_info.get("source", "soccer365")
    source_label = "Soccer365 (линия букмекера на странице матча)"
    if source == "the-odds-api":
        source_label = "The Odds API (резерв)"

    lines = [
        f"Источник линии: {source_label}.",
        "Используй ТОЛЬКО эти коэффициенты. Запрещено выдумывать или округлять произвольно.",
        "",
    ]

    for book in odds_info["bookmakers"]:
        lines.append(f"📌 {book['bookmaker']}:")
        markets = book.get("markets", {})
        if isinstance(markets, dict):
            for market_name, odds_value in markets.items():
                if isinstance(odds_value, dict):
                    parts = [f"{k}={v}" for k, v in odds_value.items() if v is not None]
                    if parts:
                        lines.append(f"   {market_name}: " + " | ".join(parts))
                elif odds_value is not None:
                    lines.append(f"   {market_name}: {odds_value}")
        elif "odds_1" in book:
            lines.append(
                f"   1X2: П1 {book.get('odds_1')} | X {book.get('odds_x')} | П2 {book.get('odds_2')}"
            )
        lines.append("")

    return "\n".join(lines).strip()


def get_match_prediction(
    home_name,
    away_name,
    home_form,
    away_form,
    odds_info,
    fixture_id=None,
    home_id=None,
    away_id=None,
):
    """Делает прогноз на матч с учётом силы команд, Elo, H2H и реальной линии."""

    intelligence = football_api.build_match_intelligence(
        home_name,
        away_name,
        home_form,
        away_form,
        odds_info=odds_info,
        fixture_id=fixture_id,
        home_id=home_id,
        away_id=away_id,
    )
    context_block = _format_match_intelligence(home_name, away_name, intelligence)
    stat_insights = _build_stat_insights(
        home_name, away_name, home_form, away_form, intelligence
    )

    system_prompt = (
        "Ты — профессиональный футбольный аналитик и беттинг-эксперт.\n\n"
        "КРИТИЧЕСКИ ВАЖНО:\n"
        "• НИКОГДА не складывай просто средние голы двух команд — это ошибка.\n"
        "• Слабая команда против фаворита забивает МЕНЬШЕ своего среднего.\n"
        "• Учитывай: индекс силы, Elo, личные встречи, оборону соперника, фаворита по линии, мотивацию.\n"
        "• Elo и H2H — отдельные сигналы; если они противоречат сырым средним, верь Elo/H2H.\n"
        "• Если аутсайдер играет от обороны — тоталы и угловые могут быть НИЖЕ сырых средних.\n"
        "• Блок «СКОРРЕКТИРОВАННЫЕ ОЖИДАНИЯ» важнее сырых средних из формы.\n\n"
        "ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ПРОГНОЗОВ:\n"
        "1. Предложи 3-4 прогноза. Минимум ДВА — на статистические рынки "
        "(угловые, карточки, фолы, удары), скорректированные под контекст матча.\n"
        "2. Один прогноз — на исход или тотал голов, но аргументируй через контекст, не через наивную сумму.\n"
        "3. Коэффициент ТОЛЬКО из блока ЛИНИЯ БУКМЕКЕРА; иначе «коэф. уточни в линии».\n"
        "4. Формат: • Ставка / • Коэффициент / • Обоснование (сила, мотивация, цифры).\n"
        "5. В конце — «⭐ Лучший прогноз».\n"
        "6. Пиши по-русски, структурированно, без воды."
    )

    user_message = (
        f"Матч: {home_name} (дома) — {away_name} (в гостях).\n\n"
        f"{context_block}\n\n"
        f"{stat_insights}\n\n"
        f"ФОРМА КОМАНД (сырые средние — не суммируй напрямую):\n"
        f"{_format_form(home_name, home_form)}\n\n"
        f"{_format_form(away_name, away_form)}\n\n"
        f"ЛИНИЯ БУКМЕКЕРА:\n{_format_odds(odds_info)}\n\n"
        "Дай прогнозы."
    )

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.45,
            max_tokens=1000,
        )
        return chat_completion.choices[0].message.content

    except Exception as e:
        print(f"[Дебаг] ❌ Ошибка API Groq (prediction): {e}")
        return "Аналитик сейчас занят и не смог построить прогноз. Попробуй чуть позже."
