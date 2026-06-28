import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import time
from ddgs import DDGS

# ==========================================
# ИНФРАСТРУКТУРА (Слой работы с сетью)
# ==========================================
def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }

def fetch_html(url):
    """Универсальный курьер для скачивания HTML кода страницы."""
    try:
        # Добавили timeout, чтобы скрипт не висел вечно, если сайт упал
        response = requests.get(url, headers=get_headers(), timeout=10)
        
        # Проверяем, что сервер вернул статус 200 (Успешно)
        if response.status_code == 200:
            return response.text
        return None
            
    except requests.exceptions.RequestException:
        return None

def _extract_club_id(url):
    match = re.search(r"/clubs/(\d+)", url)
    return match.group(1) if match else None

_EXCLUDED_TEAM_PATTERNS = (
    re.compile(r"\(ж\)", re.I),
    re.compile(r"\(жен", re.I),
    re.compile(r"женск", re.I),
    re.compile(r"\bwomen\b", re.I),
    re.compile(r"\bU\d{1,2}\b", re.I),
    re.compile(r"молодёж", re.I),
    re.compile(r"молодеж", re.I),
    re.compile(r"юнош", re.I),
    re.compile(r"юниор", re.I),
    re.compile(r"до\s*\d{2}", re.I),
    re.compile(r"\bдевуш", re.I),
    re.compile(r"студ", re.I),
    re.compile(r"легенд", re.I),
    re.compile(r"-\d+$"),
    re.compile(r"\s+[БB]$", re.I),
)

def _is_excluded_team(name):
    normalized = name.lower()
    return any(pattern.search(normalized) for pattern in _EXCLUDED_TEAM_PATTERNS)

def _is_relevant_team(name, query):
    return query.lower().strip() in name.lower()

def _clean_team_name(title):
    name = title.replace(" - Soccer365.ru", "").replace(" - Soccer365", "").strip()
    if " - " in name:
        name = name.split(" - ", 1)[0].strip()

    fk_match = re.match(r'^ФК\s+["«](.+?)["»]', name)
    if fk_match:
        return fk_match.group(1).strip()

    if name.startswith("Состав сборной "):
        name = name.replace("Состав сборной ", "", 1)
        if " по футболу" in name:
            name = name.split(" по футболу", 1)[0].strip()

    if ":" in name:
        name = name.split(":", 1)[0].strip()

    return name

def _extract_team_id_from_img(img_tag):
    if not img_tag:
        return "0"
    src = img_tag.get("src", "")
    match = re.search(r"_32_(\d+)\.", src)
    return match.group(1) if match else "0"

_STAT_KEYS = (
    "Fouls",
    "Yellow cards",
    "Shots on target",
    "Offsides",
    "Shots",
    "Corners",
)
_STAT_TITLE_MAP = {
    "Фолы": "Fouls",
    "Желтые карточки": "Yellow cards",
    "Удары в створ": "Shots on target",
    "Офсайды": "Offsides",
    "Удары": "Shots",
    "Угловые": "Corners",
}
MAX_FIXTURE_LIMIT = 15
ODDS_API_ENABLED = False  # Временно выключено — не тратить лимит The Odds API при тестах
THE_ODDS_API_BASE = "https://api.the-odds-api.com/v4"

ELO_START = 1500
ELO_K = 24
ELO_HOME_ADVANTAGE = 100
ELO_OPPONENT_BASE = 1500
ELO_HISTORY_LIMIT = 15

_TEAM_NAME_ALIASES = {
    "португалия": "portugal",
    "венгрия": "hungary",
    "англия": "england",
    "уэльс": "wales",
    "шотландия": "scotland",
    "аргентина": "argentina",
    "бразилия": "brazil",
    "германия": "germany",
    "испания": "spain",
    "франция": "france",
    "италия": "italy",
    "нидерланды": "netherlands",
    "голландия": "netherlands",
    "бельгия": "belgium",
    "хорватия": "croatia",
    "сербия": "serbia",
    "турция": "turkey",
    "россия": "russia",
    "украина": "ukraine",
    "польша": "poland",
    "чехия": "czech republic",
    "австрия": "austria",
    "швейцария": "switzerland",
    "швеция": "sweden",
    "норвегия": "norway",
    "дания": "denmark",
    "финляндия": "finland",
    "греция": "greece",
    "румыния": "romania",
    "словакия": "slovakia",
    "словения": "slovenia",
    "зенит": "zenit",
    "спартак": "spartak",
    "цска": "cska",
    "локомотив": "lokomotiv",
    "краснодар": "krasnodar",
    "динамо": "dynamo",
}

_INTERNATIONAL_SPORT_PRIORITY = (
    "soccer_fifa_world_cup_qualifiers_europe",
    "soccer_fifa_world_cup_qualifiers_south_america",
    "soccer_uefa_nations_league",
    "soccer_uefa_european_championship",
    "soccer_fifa_world_cup",
    "soccer_conmebol_copa_america",
    "soccer_uefa_europa_league",
    "soccer_uefa_champs_league",
)

_the_odds_api_key = None
_soccer_sport_keys = None

def _empty_stats():
    return {key: None for key in _STAT_KEYS}

def _stat_to_number(value):
    """Превращает строковое значение статистики в число (или None, если не число)."""
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _is_live_status(status_text):
    return bool(re.match(r"^\d+['\u2019]", str(status_text).strip()))


def _has_final_score(home_goals, away_goals):
    home_num = _stat_to_number(home_goals)
    away_num = _stat_to_number(away_goals)
    if home_num is None or away_num is None:
        return False
    home_raw = str(home_goals).strip()
    away_raw = str(away_goals).strip()
    return home_raw not in ("", "-", "—") and away_raw not in ("", "-", "—")


def _parse_fixture_datetime(status_text, now=None):
    """Превращает текст статуса Soccer365 в datetime для сортировки ближайших матчей."""
    now = now or datetime.now()
    text = str(status_text).strip()
    lowered = text.lower()

    if _is_live_status(text):
        return now

    if lowered in ("сегодня", "today"):
        return now.replace(hour=23, minute=59, second=0, microsecond=0)

    if lowered in ("завтра", "tomorrow"):
        day = now.date() + timedelta(days=1)
        return datetime.combine(day, datetime.min.time()).replace(hour=12, minute=0)

    time_only = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if time_only:
        hour, minute = int(time_only.group(1)), int(time_only.group(2))
        kickoff = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if kickoff < now - timedelta(minutes=15):
            kickoff += timedelta(days=1)
        return kickoff

    dated = re.match(
        r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?,?\s*(\d{1,2}):(\d{2})",
        text,
    )
    if dated:
        day, month = int(dated.group(1)), int(dated.group(2))
        year = int(dated.group(3)) if dated.group(3) else now.year
        hour, minute = int(dated.group(4)), int(dated.group(5))
        kickoff = datetime(year, month, day, hour, minute)
        if kickoff < now - timedelta(days=180):
            kickoff = kickoff.replace(year=year + 1)
        return kickoff

    return None


def _format_fixture_date(status_text, kickoff_dt=None):
    """Красиво форматирует дату/время матча для пользователя."""
    text = str(status_text).strip()
    if kickoff_dt and re.match(r"^\d{1,2}:\d{2}$", text):
        return f"Сегодня, {text}"
    if text.lower() in ("сегодня", "today") and kickoff_dt:
        return f"Сегодня, {kickoff_dt.strftime('%H:%M')}"
    return text


def _is_upcoming_fixture(status_text, home_goals, away_goals):
    if _is_live_status(status_text):
        return False
    return not _has_final_score(home_goals, away_goals)


def _parse_odds_value(raw):
    if raw is None:
        return None
    text = str(raw).strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value >= 1.0 else None

def _stat_for_team(stat_pair, is_home_team, missing="Нет данных"):
    if stat_pair is None:
        return missing
    home_val, away_val = stat_pair
    return home_val if is_home_team else away_val

# ==========================================
# ЭНДПОИНТ 1: Поиск через DuckDuckGo (ddgs)
# ==========================================
def search_teams(team_name):
    query = f"site:soccer365.ru/clubs/ {team_name}"
    teams = []

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=25))

            for res in results:
                url = res.get("href", "")
                title = res.get("title", "")

                if "soccer365.ru/clubs/" not in url:
                    continue

                team_id = _extract_club_id(url)
                if not team_id or any(t["id"] == team_id for t in teams):
                    continue

                exact_name = _clean_team_name(title)
                if not exact_name or len(exact_name) <= 2:
                    continue
                if _is_excluded_team(exact_name):
                    continue
                if not _is_relevant_team(exact_name, team_name):
                    continue

                teams.append({
                    "id": team_id,
                    "name": exact_name,
                })

                if len(teams) >= 5:
                    break
    except Exception as e:
        print(f"\n❌ Ошибка при поиске: {e}")

    return teams
# ==========================================
# БИЗНЕС-ЛОГИКА (Слой чистого парсинга)
# ==========================================
def parse_recent_fixtures(html_text, limit=5):
    """Только извлекает матчи из готового HTML-кода."""
    soup = BeautifulSoup(html_text, 'html.parser')
    matches = []
    game_links = soup.find_all('a', class_='game_link')

    for link in game_links:
        href = link.get('href')
        if href and '/games/' in href:
            fixture_id = href.strip('/').split('/')[-1]
            title = link.get('title', 'Матч')

            home_name = "Хозяева"
            away_name = "Гости"
            if " - " in title:
                parts = title.split(" - ")
                home_name = parts[0].strip()
                away_name = parts[1].strip()

            home_goals = "-"
            away_goals = "-"
            home_id = "0"
            away_id = "0"
            match_status = "Завершен"

            ht = link.find("div", class_="ht")
            at = link.find("div", class_="at")
            if ht and at:
                home_gls = ht.find("div", class_="gls")
                away_gls = at.find("div", class_="gls")
                if home_gls:
                    home_goals = home_gls.get_text(strip=True) or "-"
                if away_gls:
                    away_goals = away_gls.get_text(strip=True) or "-"
                home_id = _extract_team_id_from_img(ht.find("img"))
                away_id = _extract_team_id_from_img(at.find("img"))

            status_div = link.find("div", class_="status")
            if status_div:
                match_status = status_div.get_text(strip=True) or match_status

            matches.append({
                "fixture_id": fixture_id,
                "date": match_status,
                "home_name": home_name,
                "home_id": home_id,
                "away_name": away_name,
                "away_id": away_id,
                "home_goals": home_goals,
                "away_goals": away_goals
            })

        if len(matches) >= limit:
            break

    return matches

def parse_fixture_statistics(html_text):
    """Извлекает статистику матча: для каждой метрики пара (хозяева, гости)."""
    soup = BeautifulSoup(html_text, 'html.parser')
    stats_dict = _empty_stats()

    full_match_tab = soup.find('div', id='stat-tp0')
    search_area = full_match_tab if full_match_tab else soup
    stats_items = search_area.find_all('div', class_='stats_item')

    for item in stats_items:
        title_div = item.find('div', class_='stats_title')
        if not title_div:
            continue

        stat_key = _STAT_TITLE_MAP.get(title_div.text.strip())
        if not stat_key or stats_dict[stat_key] is not None:
            continue

        values = item.find_all('div', class_='stats_inf')
        if len(values) >= 2:
            stats_dict[stat_key] = (values[0].text.strip(), values[1].text.strip())

    return stats_dict

def parse_upcoming_fixtures(html_text, limit=5):
    """Извлекает будущие матчи из HTML-кода страницы клуба и сортирует по ближайшему старту."""
    soup = BeautifulSoup(html_text, "html.parser")
    matches = []
    now = datetime.now()
    game_links = soup.find_all("a", class_="game_link")

    for link in game_links:
        status_div = link.find("div", class_="status")
        if not status_div:
            continue

        status_text = status_div.get_text(strip=True)
        title = link.get("title", "Матч")

        home_name = "Хозяева"
        away_name = "Гости"
        if " - " in title:
            parts = title.split(" - ")
            home_name = parts[0].strip()
            away_name = parts[1].strip()

        home_goals = "-"
        away_goals = "-"
        home_id = "0"
        away_id = "0"
        ht = link.find("div", class_="ht")
        at = link.find("div", class_="at")
        if ht and at:
            home_gls = ht.find("div", class_="gls")
            away_gls = at.find("div", class_="gls")
            if home_gls:
                home_goals = home_gls.get_text(strip=True) or "-"
            if away_gls:
                away_goals = away_gls.get_text(strip=True) or "-"
            home_id = _extract_team_id_from_img(ht.find("img"))
            away_id = _extract_team_id_from_img(at.find("img"))

        if not _is_upcoming_fixture(status_text, home_goals, away_goals):
            continue

        fixture_id = link.get("dt-id")
        if not fixture_id:
            href = link.get("href", "")
            if "/games/" in href:
                fixture_id = href.strip("/").split("/")[-1]

        kickoff_dt = _parse_fixture_datetime(status_text, now=now)
        matches.append({
            "fixture_id": fixture_id,
            "date": _format_fixture_date(status_text, kickoff_dt),
            "status_raw": status_text,
            "kickoff_dt": kickoff_dt,
            "home_name": home_name,
            "home_id": home_id,
            "away_name": away_name,
            "away_id": away_id,
            "odds_1": "-",
            "odds_x": "-",
            "odds_2": "-",
        })

    matches.sort(
        key=lambda item: item["kickoff_dt"] or datetime.max.replace(tzinfo=None)
    )
    return matches[:limit]


def parse_fixture_odds(html_text):
    """Парсит линию букмекера (Винлайн и др.) со страницы матча на Soccer365."""
    soup = BeautifulSoup(html_text, "html.parser")
    bookmakers = []
    seen = set()

    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)

        if len(rows) < 2:
            continue

        header = [cell.strip().upper() for cell in rows[0]]
        if not {"1", "X", "2"}.issubset(set(header)):
            continue

        market_names = rows[0]
        for row in rows[1:]:
            if not row or not row[0]:
                continue

            bookmaker_name = row[0].strip()
            markets = {}
            for index in range(1, min(len(row), len(market_names))):
                market_name = market_names[index].strip()
                odds_value = _parse_odds_value(row[index])
                if not market_name or odds_value is None:
                    continue
                markets[market_name] = odds_value

            if not markets:
                continue

            key = (bookmaker_name, tuple(sorted(markets.items())))
            if key in seen:
                continue
            seen.add(key)
            bookmakers.append({
                "bookmaker": bookmaker_name,
                "markets": markets,
            })

    return {
        "source": "soccer365",
        "bookmakers": bookmakers,
    }


def _get_the_odds_api_key():
    global _the_odds_api_key
    if _the_odds_api_key is not None:
        return _the_odds_api_key

    config_path = Path(__file__).resolve().parent / "config.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as config_file:
            _the_odds_api_key = json.load(config_file).get("the_odds_api_key")
    else:
        _the_odds_api_key = ""

    return _the_odds_api_key


def _normalize_team_name(name):
    normalized = re.sub(r"\s+", " ", name.lower().strip())
    normalized = normalized.replace("ё", "е")
    return _TEAM_NAME_ALIASES.get(normalized, normalized)


def _team_tokens_match(left, right):
    left_norm = _normalize_team_name(left)
    right_norm = _normalize_team_name(right)
    if left_norm == right_norm:
        return True
    return left_norm in right_norm or right_norm in left_norm


def _event_matches_teams(event, home_name, away_name):
    event_home = event.get("home_team", "")
    event_away = event.get("away_team", "")
    direct = _team_tokens_match(event_home, home_name) and _team_tokens_match(event_away, away_name)
    reverse = _team_tokens_match(event_home, away_name) and _team_tokens_match(event_away, home_name)
    return direct or reverse


def _get_soccer_sport_keys():
    global _soccer_sport_keys
    if _soccer_sport_keys is not None:
        return _soccer_sport_keys

    api_key = _get_the_odds_api_key()
    if not api_key:
        _soccer_sport_keys = []
        return _soccer_sport_keys

    try:
        response = requests.get(
            f"{THE_ODDS_API_BASE}/sports",
            params={"apiKey": api_key},
            timeout=15,
        )
        response.raise_for_status()
        all_keys = [
            sport["key"]
            for sport in response.json()
            if sport.get("key", "").startswith("soccer_")
        ]
    except requests.exceptions.RequestException:
        _soccer_sport_keys = list(_INTERNATIONAL_SPORT_PRIORITY)
        return _soccer_sport_keys

    ordered = []
    for sport_key in _INTERNATIONAL_SPORT_PRIORITY:
        if sport_key in all_keys:
            ordered.append(sport_key)
    for sport_key in all_keys:
        if sport_key not in ordered:
            ordered.append(sport_key)

    _soccer_sport_keys = ordered
    return _soccer_sport_keys


def _parse_h2h_odds(event):
    home_team = event.get("home_team", "")
    away_team = event.get("away_team", "")
    odds_1 = odds_x = odds_2 = "-"

    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue

            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "")
                price = outcome.get("price")
                if price is None:
                    continue
                price_text = f"{float(price):.2f}".rstrip("0").rstrip(".")
                if name.lower() == "draw":
                    odds_x = price_text
                elif _team_tokens_match(name, home_team):
                    odds_1 = price_text
                elif _team_tokens_match(name, away_team):
                    odds_2 = price_text

            if odds_1 != "-" and odds_x != "-" and odds_2 != "-":
                return {
                    "odds_1": odds_1,
                    "odds_x": odds_x,
                    "odds_2": odds_2,
                }

    return {
        "odds_1": odds_1,
        "odds_x": odds_x,
        "odds_2": odds_2,
    }


def _event_involves_team(event, team_name):
    return (
        _team_tokens_match(event.get("home_team", ""), team_name)
        or _team_tokens_match(event.get("away_team", ""), team_name)
    )


def _format_api_date(iso_time):
    if not iso_time:
        return "-"
    try:
        normalized = iso_time.replace("Z", "+00:00")
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", normalized)
        if not match:
            return iso_time
        year, month, day, hour, minute = match.groups()
        return f"{day}.{month}, {hour}:{minute}"
    except ValueError:
        return iso_time


def _has_valid_odds(odds):
    return any(value != "-" for value in odds.values())


def _build_match_from_event(event):
    odds = _parse_h2h_odds(event)
    return {
        "home_name": event.get("home_team", ""),
        "away_name": event.get("away_team", ""),
        "date": _format_api_date(event.get("commence_time")),
        "odds_1": odds["odds_1"],
        "odds_x": odds["odds_x"],
        "odds_2": odds["odds_2"],
    }


def find_odds_for_teams(home_name, away_name, preferred_team=None):
    """Ищет коэффициенты 1X2 в The Odds API для матча или ближайшего матча команды."""
    if not ODDS_API_ENABLED:
        return None

    api_key = _get_the_odds_api_key()
    if not api_key:
        return None

    fallback_event = None

    for sport_key in _get_soccer_sport_keys():
        try:
            response = requests.get(
                f"{THE_ODDS_API_BASE}/sports/{sport_key}/odds",
                params={
                    "apiKey": api_key,
                    "regions": "eu",
                    "markets": "h2h",
                    "oddsFormat": "decimal",
                },
                timeout=15,
            )
            if response.status_code != 200:
                continue

            events = response.json()
            if not events:
                continue

            for event in events:
                odds = _parse_h2h_odds(event)
                if not _has_valid_odds(odds):
                    continue

                if _event_matches_teams(event, home_name, away_name):
                    return _build_match_from_event(event)

                if preferred_team and _event_involves_team(event, preferred_team):
                    if fallback_event is None or event.get("commence_time", "") < fallback_event.get("commence_time", ""):
                        fallback_event = event
        except requests.exceptions.RequestException:
            continue

    if fallback_event:
        return _build_match_from_event(fallback_event)

    return None


def get_match_odds(home_name, away_name, preferred_team=None):
    """Возвращает коэффициенты 1X2 через The Odds API."""
    if not ODDS_API_ENABLED:
        return {"odds_1": "-", "odds_x": "-", "odds_2": "-"}

    match = find_odds_for_teams(home_name, away_name, preferred_team=preferred_team)
    if not match:
        return {"odds_1": "-", "odds_x": "-", "odds_2": "-"}

    return {
        "odds_1": match["odds_1"],
        "odds_x": match["odds_x"],
        "odds_2": match["odds_2"],
    }


def _parse_all_h2h_odds(event):
    """Возвращает список коэффициентов 1X2 по каждому букмекеру события."""
    home_team = event.get("home_team", "")
    away_team = event.get("away_team", "")
    per_bookmaker = []

    for bookmaker in event.get("bookmakers", []):
        odds_1 = odds_x = odds_2 = None
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "")
                price = outcome.get("price")
                if price is None:
                    continue
                if name.lower() == "draw":
                    odds_x = float(price)
                elif _team_tokens_match(name, home_team):
                    odds_1 = float(price)
                elif _team_tokens_match(name, away_team):
                    odds_2 = float(price)

        if odds_1 and odds_x and odds_2:
            per_bookmaker.append({
                "bookmaker": bookmaker.get("title") or bookmaker.get("key") or "?",
                "odds_1": round(odds_1, 2),
                "odds_x": round(odds_x, 2),
                "odds_2": round(odds_2, 2),
            })

    return per_bookmaker


def _build_bookmaker_summary(event, per_bookmaker):
    count = len(per_bookmaker)
    avg_1 = round(sum(b["odds_1"] for b in per_bookmaker) / count, 2)
    avg_x = round(sum(b["odds_x"] for b in per_bookmaker) / count, 2)
    avg_2 = round(sum(b["odds_2"] for b in per_bookmaker) / count, 2)
    return {
        "home_name": event.get("home_team", ""),
        "away_name": event.get("away_team", ""),
        "date": _format_api_date(event.get("commence_time")),
        "bookmaker_count": count,
        "bookmakers": per_bookmaker,
        "avg_odds": {"odds_1": avg_1, "odds_x": avg_x, "odds_2": avg_2},
    }


def get_match_bookmaker_odds(home_name, away_name, preferred_team=None):
    """Возвращает коэффициенты 1X2 по нескольким букмекерам для матча.

    Вызывается осознанно в режиме ИИ-прогноза, поэтому работает независимо от
    флага ODDS_API_ENABLED (он отключает только автоматический показ коэффициентов).
    """
    api_key = _get_the_odds_api_key()
    if not api_key:
        return None

    fallback = None

    for sport_key in _get_soccer_sport_keys():
        try:
            response = requests.get(
                f"{THE_ODDS_API_BASE}/sports/{sport_key}/odds",
                params={
                    "apiKey": api_key,
                    "regions": "eu",
                    "markets": "h2h",
                    "oddsFormat": "decimal",
                },
                timeout=15,
            )
            if response.status_code != 200:
                continue

            events = response.json()
            for event in events or []:
                per_bookmaker = _parse_all_h2h_odds(event)
                if not per_bookmaker:
                    continue

                if _event_matches_teams(event, home_name, away_name):
                    return _build_bookmaker_summary(event, per_bookmaker)

                if preferred_team and fallback is None and _event_involves_team(event, preferred_team):
                    fallback = (event, per_bookmaker)
        except requests.exceptions.RequestException:
            continue

    if fallback:
        return _build_bookmaker_summary(*fallback)

    return None

# ==========================================
# ОРКЕСТРАТОРЫ (Связывают сеть и парсинг)
# ==========================================
def get_recent_fixtures(team_id, limit=5):
    limit = min(max(int(limit), 1), MAX_FIXTURE_LIMIT)
    url = f"https://soccer365.ru/clubs/{team_id}/&tab=result_last"
    html_text = fetch_html(url) # Вызываем нашего Курьера
    
    if not html_text:
        return []
        
    return parse_recent_fixtures(html_text, limit) # Передаем текст Повару

def get_fixture_statistics(fixture_id, is_home_team):
    url = f"https://soccer365.ru/games/{fixture_id}/"
    html_text = fetch_html(url)
    
    if not html_text:
        return {key: "Ошибка" for key in _STAT_KEYS}

    raw_stats = parse_fixture_statistics(html_text)
    stats = {
        key: _stat_for_team(raw_stats[key], is_home_team)
        for key in _STAT_KEYS
    }

    time.sleep(0.5) # Пауза защиты от бана
    return stats

def get_team_form_stats(team_id, limit=5):
    """Агрегирует статистику ('всё сразу') и результаты по последним матчам команды.

    Возвращает словарь со средними показателями, балансом В-Н-П, средними голами
    и списком последних результатов. Используется для ИИ-прогноза.
    """
    matches = get_recent_fixtures(team_id, limit=limit)
    if not matches:
        return None

    totals = {key: 0.0 for key in _STAT_KEYS}
    counts = {key: 0 for key in _STAT_KEYS}
    goals_for = 0.0
    goals_against = 0.0
    wins = draws = losses = 0
    counted_matches = 0
    recent_results = []

    for match in matches:
        is_home_team = str(team_id) == str(match["home_id"])
        stats = get_fixture_statistics(match["fixture_id"], is_home_team)

        for key in _STAT_KEYS:
            num = _stat_to_number(stats.get(key))
            if num is not None:
                totals[key] += num
                counts[key] += 1

        home_goals = _stat_to_number(match["home_goals"])
        away_goals = _stat_to_number(match["away_goals"])
        if home_goals is None or away_goals is None:
            continue

        team_goals = home_goals if is_home_team else away_goals
        opp_goals = away_goals if is_home_team else home_goals
        goals_for += team_goals
        goals_against += opp_goals
        counted_matches += 1

        if team_goals > opp_goals:
            wins += 1
            outcome = "В"
        elif team_goals == opp_goals:
            draws += 1
            outcome = "Н"
        else:
            losses += 1
            outcome = "П"

        opponent = match["away_name"] if is_home_team else match["home_name"]
        recent_results.append(f"{outcome} {int(team_goals)}:{int(opp_goals)} ({opponent})")

    averages = {
        key: round(totals[key] / counts[key], 1) if counts[key] else None
        for key in _STAT_KEYS
    }

    return {
        "matches_analyzed": len(matches),
        "averages": averages,
        "avg_goals_for": round(goals_for / counted_matches, 2) if counted_matches else None,
        "avg_goals_against": round(goals_against / counted_matches, 2) if counted_matches else None,
        "record": {"wins": wins, "draws": draws, "losses": losses},
        "recent_results": recent_results,
    }

def get_upcoming_fixtures(team_id, limit=3):
    url = f"https://soccer365.ru/clubs/{team_id}/"
    html_text = fetch_html(url)

    if not html_text:
        return []

    return parse_upcoming_fixtures(html_text, limit)


def get_nearest_upcoming_fixture(team_id):
    """Возвращает ближайший предстоящий матч команды (включая сегодняшний по времени)."""
    upcoming = get_upcoming_fixtures(team_id, limit=10)
    return upcoming[0] if upcoming else None


def parse_fixture_context(html_text):
    """Извлекает турнир и контекст матча со страницы Soccer365."""
    soup = BeautifulSoup(html_text, "html.parser")
    competition = None

    for header in soup.find_all(class_="block_header"):
        text = header.get_text(" ", strip=True)
        if not text:
            continue
        lowered = text.lower()
        if "коэфф" in lowered:
            continue
        if any(
            marker in lowered
            for marker in (
                "тур", "кубок", "лига", "чемпионат", "отбор", "финал",
                "сезон", "этап", "групп", "плей-офф", "play-off",
            )
        ) or re.search(r"\d{2}\.\d{2}\.\d{4}", text):
            competition = text
            break

    return {"competition": competition}


def get_fixture_context(fixture_id):
    if not fixture_id:
        return {}
    html_text = fetch_html(f"https://soccer365.ru/games/{fixture_id}/")
    if not html_text:
        return {}
    return parse_fixture_context(html_text)


def _extract_1x2_odds(odds_info):
    if not odds_info or not odds_info.get("bookmakers"):
        return None

    book = odds_info["bookmakers"][0]
    markets = book.get("markets", {})
    if isinstance(markets, dict) and "1" in markets:
        return {
            "home": markets.get("1"),
            "draw": markets.get("X"),
            "away": markets.get("2"),
            "bookmaker": book.get("bookmaker"),
        }

    if "odds_1" in book:
        return {
            "home": book.get("odds_1"),
            "draw": book.get("odds_x"),
            "away": book.get("odds_2"),
            "bookmaker": book.get("bookmaker"),
        }

    return None


def _compute_strength_index(form):
    """Индекс силы команды (1–10) по форме: атака, оборона, турнирная форма."""
    if not form:
        return None

    goals_for = form.get("avg_goals_for") or 0
    goals_against = form.get("avg_goals_against") or 0
    record = form.get("record") or {}
    played = sum(record.get(key, 0) for key in ("wins", "draws", "losses")) or 1
    points_per_game = (record.get("wins", 0) * 3 + record.get("draws", 0)) / played

    index = 5.0
    index += (goals_for - 1.3) * 1.1
    index -= (goals_against - 1.3) * 0.9
    index += (points_per_game - 1.4) * 1.3
    return round(max(1.0, min(10.0, index)), 1)


def _analyze_odds_balance(odds_info, home_name, away_name):
    extracted = _extract_1x2_odds(odds_info)
    if not extracted:
        return None

    home_odds = extracted.get("home")
    away_odds = extracted.get("away")
    draw_odds = extracted.get("draw")
    if not home_odds or not away_odds:
        return None

    favorite = home_name if home_odds < away_odds else away_name
    underdog = away_name if favorite == home_name else home_name
    fav_odds = min(home_odds, away_odds)
    dog_odds = max(home_odds, away_odds)
    gap = round(dog_odds / fav_odds, 2) if fav_odds else None

    if gap and gap >= 4:
        mismatch = "очень большой разрыв класса"
    elif gap and gap >= 2.5:
        mismatch = "явный фаворит"
    elif gap and gap >= 1.6:
        mismatch = "умеренное преимущество одной из сторон"
    else:
        mismatch = "равновесие / без явного фаворита"

    return {
        "bookmaker": extracted.get("bookmaker"),
        "home_odds": home_odds,
        "draw_odds": draw_odds,
        "away_odds": away_odds,
        "favorite": favorite,
        "underdog": underdog,
        "odds_gap": gap,
        "mismatch": mismatch,
    }


def _adjust_expected_goals(
    home_form,
    away_form,
    home_strength,
    away_strength,
    home_elo=None,
    away_elo=None,
    h2h=None,
):
    """Оценка голов с учётом обороны соперника, Elo и личных встреч."""
    home_attack = home_form.get("avg_goals_for") if home_form else None
    home_defense = home_form.get("avg_goals_against") if home_form else None
    away_attack = away_form.get("avg_goals_for") if away_form else None
    away_defense = away_form.get("avg_goals_against") if away_form else None

    if None in (home_attack, home_defense, away_attack, away_defense):
        return None

    league_avg = 1.3

    def defense_resistance(avg_conceded):
        return 0.45 + 0.55 * (league_avg / max(float(avg_conceded), 0.4))

    ratio = home_strength / away_strength if home_strength and away_strength else 1.0

    underdog_home = max(0.45, min(1.0, 0.4 + 0.6 * min(ratio, 1.0)))
    underdog_away = max(0.45, min(1.0, 0.4 + 0.6 * min(1 / ratio, 1.0) if ratio else 1.0))

    expected_home = home_attack * defense_resistance(away_defense) * underdog_home * 1.08
    expected_away = away_attack * defense_resistance(home_defense) * underdog_away

    if ratio >= 2.2:
        expected_away = min(expected_away, away_attack * 0.7)
    if ratio <= 0.45:
        expected_home = min(expected_home, home_attack * 0.7)

    if home_elo is not None and away_elo is not None:
        elo_diff = (home_elo + ELO_HOME_ADVANTAGE) - away_elo
        expected_home *= max(0.65, min(1.35, 1 + elo_diff / 900))
        expected_away *= max(0.65, min(1.35, 1 - elo_diff / 900))

    if h2h and h2h.get("count", 0) >= 3 and h2h.get("avg_total_goals") is not None:
        h2h_total = h2h["avg_total_goals"]
        form_total = expected_home + expected_away
        blended_total = form_total * 0.65 + h2h_total * 0.35
        if form_total > 0:
            scale = blended_total / form_total
            expected_home *= scale
            expected_away *= scale

    return {
        "home": round(expected_home, 2),
        "away": round(expected_away, 2),
        "total": round(expected_home + expected_away, 2),
    }


def _assess_match_importance(competition_text, odds_balance):
    text = (competition_text or "").lower()
    notes = []

    if any(word in text for word in ("товарищ", "friendly", "контрольн")):
        notes.append("товарищеский характер — возможны ротации и нетипичная мотивация")
    if any(word in text for word in ("финал", "полуфинал", "четвертьфинал", "1/4", "1/2")):
        notes.append("стадия плей-офф — повышенная ценность каждого эпизода")
    if any(word in text for word in ("отбор", "qualif", "квалиф")):
        notes.append("отборочный матч — результат критичен для турнирной задачи")
    if any(word in text for word in ("кубок", "лига", "чемпионат", "euro", "world", "наций")):
        notes.append("официальный турнир — ожидается стандартная мотивация")

    if odds_balance and odds_balance.get("odds_gap", 0) >= 3:
        notes.append(
            f"по линии явный фаворит ({odds_balance['favorite']}) — "
            f"аутсайдер ({odds_balance['underdog']}) может играть от обороны"
        )

    if not notes:
        notes.append("контекст турнира уточни по названию соревнования и мотивации команд")

    return notes


def _elo_expected_score(team_elo, opponent_elo, is_home):
    effective = team_elo + ELO_HOME_ADVANTAGE if is_home else team_elo - ELO_HOME_ADVANTAGE
    return 1 / (1 + 10 ** ((opponent_elo - effective) / 400))


def compute_team_elo(team_id, limit=ELO_HISTORY_LIMIT, opponent_elos=None):
    """Считает рейтинг Elo команды по последним завершённым матчам."""
    matches = get_recent_fixtures(team_id, limit=limit)
    if not matches:
        return None

    opponent_elos = opponent_elos or {}
    elo = ELO_START
    processed = 0

    for match in reversed(matches):
        is_home = str(team_id) == str(match["home_id"])
        home_goals = _stat_to_number(match["home_goals"])
        away_goals = _stat_to_number(match["away_goals"])
        if home_goals is None or away_goals is None:
            continue

        team_goals = home_goals if is_home else away_goals
        opp_goals = away_goals if is_home else home_goals

        if team_goals > opp_goals:
            actual = 1.0
        elif team_goals == opp_goals:
            actual = 0.5
        else:
            actual = 0.0

        opponent_id = str(match["away_id"] if is_home else match["home_id"])
        opponent_elo = opponent_elos.get(opponent_id, ELO_OPPONENT_BASE)
        expected = _elo_expected_score(elo, opponent_elo, is_home)
        elo += ELO_K * (actual - expected)
        processed += 1

    return {
        "elo": round(elo),
        "matches_used": processed,
    }


def compute_pair_elo(home_id, away_id, limit=ELO_HISTORY_LIMIT):
    """Elo обеих команд с уточнением, если они встречались в истории соперников."""
    if not home_id or not away_id:
        return None, None

    home_base = compute_team_elo(home_id, limit=limit)
    away_base = compute_team_elo(away_id, limit=limit)
    if not home_base or not away_base:
        return home_base, away_base

    home_refined = compute_team_elo(
        home_id,
        limit=limit,
        opponent_elos={str(away_id): away_base["elo"]},
    )
    away_refined = compute_team_elo(
        away_id,
        limit=limit,
        opponent_elos={str(home_id): home_base["elo"]},
    )
    return home_refined, away_refined


def _elo_match_probabilities(home_elo, away_elo):
    home_effective = home_elo + ELO_HOME_ADVANTAGE
    home_win = 1 / (1 + 10 ** ((away_elo - home_effective) / 400))
    away_win = 1 / (1 + 10 ** ((home_effective - away_elo) / 400))
    draw = max(0.08, min(0.34, 0.28 - abs(home_elo - away_elo) / 1200))
    total = home_win + draw + away_win
    return {
        "home_win_pct": round(home_win / total * 100, 1),
        "draw_pct": round(draw / total * 100, 1),
        "away_win_pct": round(away_win / total * 100, 1),
    }


def parse_head_to_head(html_text, perspective_home, perspective_away):
    """Парсит личные встречи с вкладки stats_games (там только H2H этих команд)."""
    soup = BeautifulSoup(html_text, "html.parser")
    matches = []

    for link in soup.find_all("a", class_="game_link"):
        title = link.get("title", "")
        if " - " not in title:
            continue

        match_home, match_away = [part.strip() for part in title.split(" - ", 1)]

        status_div = link.find("div", class_="status")
        date_text = status_div.get_text(strip=True) if status_div else "—"

        home_goals = away_goals = None
        ht = link.find("div", class_="ht")
        at = link.find("div", class_="at")
        if ht and at:
            home_gls = ht.find("div", class_="gls")
            away_gls = at.find("div", class_="gls")
            if home_gls and away_gls:
                home_goals = _stat_to_number(home_gls.get_text(strip=True))
                away_goals = _stat_to_number(away_gls.get_text(strip=True))

        if home_goals is None or away_goals is None:
            continue

        matches.append({
            "date": date_text,
            "match_home": match_home,
            "match_away": match_away,
            "home_goals": int(home_goals),
            "away_goals": int(away_goals),
        })

    if not matches:
        return None

    home_wins = draws = away_wins = 0
    total_goals = 0
    recent_lines = []

    for item in matches:
        total_goals += item["home_goals"] + item["away_goals"]

        if _team_tokens_match(item["match_home"], perspective_home):
            pg_home, pg_away = item["home_goals"], item["away_goals"]
        elif _team_tokens_match(item["match_away"], perspective_home):
            pg_home, pg_away = item["away_goals"], item["home_goals"]
        elif _team_tokens_match(item["match_home"], perspective_away):
            pg_home, pg_away = item["away_goals"], item["home_goals"]
        else:
            pg_home, pg_away = item["home_goals"], item["away_goals"]

        if pg_home > pg_away:
            home_wins += 1
            outcome = "В"
        elif pg_home == pg_away:
            draws += 1
            outcome = "Н"
        else:
            away_wins += 1
            outcome = "П"

        recent_lines.append(
            f"{outcome} {pg_home}:{pg_away} ({item['date']})"
        )

    count = len(matches)
    return {
        "count": count,
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "avg_total_goals": round(total_goals / count, 2),
        "recent_results": recent_lines[:5],
    }


def get_head_to_head(fixture_id, home_name, away_name):
    if not fixture_id:
        return None

    html_text = fetch_html(f"https://soccer365.ru/games/{fixture_id}/&tab=stats_games")
    if not html_text:
        return None

    return parse_head_to_head(html_text, home_name, away_name)


def build_match_intelligence(
    home_name,
    away_name,
    home_form,
    away_form,
    odds_info=None,
    fixture_id=None,
    home_id=None,
    away_id=None,
):
    """Собирает контекст матча: сила, Elo, H2H, скорректированные ожидания."""
    context = get_fixture_context(fixture_id) if fixture_id else {}
    home_strength = _compute_strength_index(home_form)
    away_strength = _compute_strength_index(away_form)
    odds_balance = _analyze_odds_balance(odds_info, home_name, away_name)

    home_elo_data, away_elo_data = compute_pair_elo(home_id, away_id)
    home_elo = home_elo_data["elo"] if home_elo_data else None
    away_elo = away_elo_data["elo"] if away_elo_data else None
    elo_probs = _elo_match_probabilities(home_elo, away_elo) if home_elo and away_elo else None

    h2h = get_head_to_head(fixture_id, home_name, away_name)

    expected_goals = _adjust_expected_goals(
        home_form,
        away_form,
        home_strength,
        away_strength,
        home_elo=home_elo,
        away_elo=away_elo,
        h2h=h2h,
    )

    naive_total = None
    if home_form and away_form:
        hf = home_form.get("avg_goals_for") or 0
        af = away_form.get("avg_goals_for") or 0
        naive_total = round(hf + af, 2)

    importance_notes = _assess_match_importance(context.get("competition"), odds_balance)

    if h2h and h2h["count"] >= 3:
        if h2h["home_wins"] >= h2h["away_wins"] + 2:
            importance_notes.append(
                f"в личных встречах {home_name} исторически доминирует "
                f"({h2h['home_wins']}-{h2h['draws']}-{h2h['away_wins']})"
            )
        elif h2h["away_wins"] >= h2h["home_wins"] + 2:
            importance_notes.append(
                f"в личных встречах {away_name} исторически доминирует "
                f"({h2h['home_wins']}-{h2h['draws']}-{h2h['away_wins']})"
            )
        else:
            importance_notes.append(
                f"личные встречи относительно равны ({h2h['home_wins']}-{h2h['draws']}-{h2h['away_wins']})"
            )

    strength_gap = None
    if home_strength is not None and away_strength is not None:
        strength_gap = round(home_strength - away_strength, 1)

    elo_gap = round(home_elo - away_elo, 0) if home_elo and away_elo else None

    return {
        "competition": context.get("competition"),
        "home_strength": home_strength,
        "away_strength": away_strength,
        "strength_gap": strength_gap,
        "home_elo": home_elo,
        "away_elo": away_elo,
        "elo_gap": elo_gap,
        "elo_probs": elo_probs,
        "head_to_head": h2h,
        "odds_balance": odds_balance,
        "expected_goals": expected_goals,
        "naive_total_goals": naive_total,
        "importance_notes": importance_notes,
    }


def get_fixture_betting_line(fixture_id, home_name=None, away_name=None, preferred_team=None):
    """Берёт линию букмекера со страницы матча на Soccer365 (Винлайн и др.).

    Если на странице матча линии нет — резервный запрос в The Odds API.
    """
    if fixture_id:
        html_text = fetch_html(f"https://soccer365.ru/games/{fixture_id}/")
        if html_text:
            odds = parse_fixture_odds(html_text)
            if odds.get("bookmakers"):
                odds["fixture_id"] = fixture_id
                return odds

    if home_name and away_name:
        api_odds = get_match_bookmaker_odds(home_name, away_name, preferred_team=preferred_team)
        if api_odds and api_odds.get("bookmakers"):
            api_odds["source"] = "the-odds-api"
            return api_odds

    return None


def get_next_match_with_odds(team_id, team_name=None):
    """Возвращает ближайший матч команды с коэффициентами 1X2."""
    upcoming = get_upcoming_fixtures(team_id, limit=1)
    if not upcoming:
        return None

    match = upcoming[0]
    if not ODDS_API_ENABLED:
        match.update({"odds_1": "-", "odds_x": "-", "odds_2": "-"})
        return match

    preferred_team = team_name or match["home_name"]
    api_match = find_odds_for_teams(
        match["home_name"],
        match["away_name"],
        preferred_team=preferred_team,
    )

    if api_match and _has_valid_odds(api_match):
        if not _event_matches_teams(
            {"home_team": api_match["home_name"], "away_team": api_match["away_name"]},
            match["home_name"],
            match["away_name"],
        ):
            match["date"] = api_match["date"]
            match["home_name"] = api_match["home_name"]
            match["away_name"] = api_match["away_name"]
            match["odds_source"] = "the-odds-api"
        match["odds_1"] = api_match["odds_1"]
        match["odds_x"] = api_match["odds_x"]
        match["odds_2"] = api_match["odds_2"]
    else:
        match.update({"odds_1": "-", "odds_x": "-", "odds_2": "-"})

    return match