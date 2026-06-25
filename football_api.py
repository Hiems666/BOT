import re
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