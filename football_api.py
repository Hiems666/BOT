import json
import re
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
THE_ODDS_API_BASE = "https://api.the-odds-api.com/v4"

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
    """Извлекает будущие матчи из HTML-кода страницы клуба."""
    soup = BeautifulSoup(html_text, "html.parser")
    matches = []
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
        ht = link.find("div", class_="ht")
        at = link.find("div", class_="at")
        if ht and at:
            home_gls = ht.find("div", class_="gls")
            away_gls = at.find("div", class_="gls")
            if home_gls:
                home_goals = home_gls.get_text(strip=True) or "-"
            if away_gls:
                away_goals = away_gls.get_text(strip=True) or "-"

        if home_goals != "-" or away_goals != "-":
            continue

        fixture_id = link.get("dt-id")
        if not fixture_id:
            href = link.get("href", "")
            if "/games/" in href:
                fixture_id = href.strip("/").split("/")[-1]

        matches.append({
            "fixture_id": fixture_id,
            "date": status_text,
            "home_name": home_name,
            "away_name": away_name,
            "odds_1": "-",
            "odds_x": "-",
            "odds_2": "-",
        })

        if len(matches) >= limit:
            break

    return matches


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
    match = find_odds_for_teams(home_name, away_name, preferred_team=preferred_team)
    if not match:
        return {"odds_1": "-", "odds_x": "-", "odds_2": "-"}

    return {
        "odds_1": match["odds_1"],
        "odds_x": match["odds_x"],
        "odds_2": match["odds_2"],
    }

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

def get_upcoming_fixtures(team_id, limit=3):
    url = f"https://soccer365.ru/clubs/{team_id}/"
    html_text = fetch_html(url)

    if not html_text:
        return []

    return parse_upcoming_fixtures(html_text, limit)


def get_next_match_with_odds(team_id, team_name=None):
    """Возвращает ближайший матч команды с коэффициентами 1X2."""
    upcoming = get_upcoming_fixtures(team_id, limit=1)
    if not upcoming:
        return None

    match = upcoming[0]
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