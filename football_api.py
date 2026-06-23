import re
import requests
from bs4 import BeautifulSoup
import time
from ddgs import DDGS

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }

def _extract_club_id(url):
    match = re.search(r"/clubs/(\d+)", url)
    return match.group(1) if match else None

# ==========================================
# ЭНДПОИНТ 1: Поиск через DuckDuckGo (ddgs)
# ==========================================
def search_teams(team_name):
    print(f"\n[Дебаг] Ищем профиль '{team_name}'...")
    query = f"site:soccer365.ru/clubs/ {team_name}"
    teams = []

    try:
        print("[Дебаг] Отправляем запрос...")
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=10))
            print(f"[Дебаг] DuckDuckGo вернул {len(results)} результатов.")

            for res in results:
                url = res.get("href", "")
                title = res.get("title", "")
                print(f"[Дебаг] Найдена ссылка: {url}")

                if "soccer365.ru/clubs/" not in url:
                    continue

                team_id = _extract_club_id(url)
                if not team_id or any(t["id"] == team_id for t in teams):
                    continue

                exact_name = title.replace(" - Soccer365.ru", "").replace(" - Soccer365", "").strip()
                if not exact_name or len(exact_name) <= 2:
                    continue

                teams.append({
                    "id": team_id,
                    "name": exact_name,
                    "country": "Найдено DDG",
                })

                if len(teams) >= 5:
                    break
    except Exception as e:
        print(f"\n❌ Ошибка при поиске через DuckDuckGo: {e}")

    if not teams:
        print("\n[Дебаг] Итоговый список пуст.")

    return teams
# ==========================================
# ЭНДПОИНТ 2: Последние матчи команды (со счетом)
# ==========================================
def get_recent_fixtures(team_id, limit=5):
    url = f"https://soccer365.ru/clubs/{team_id}/"
    response = requests.get(url, headers=get_headers())
    soup = BeautifulSoup(response.text, 'html.parser')

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
            match_status = "Завершен"

            gls_divs = link.find_all("div", class_="gls")
            if len(gls_divs) >= 2:
                home_goals = gls_divs[0].get_text(strip=True)
                away_goals = gls_divs[1].get_text(strip=True)

            status_div = link.find("div", class_="status")
            if status_div:
                match_status = status_div.get_text(strip=True)

            matches.append({
                "fixture_id": fixture_id,
                "date": match_status,
                "home_name": home_name,
                "home_id": "0", 
                "away_name": away_name,
                "away_id": "0",
                "home_goals": home_goals,
                "away_goals": away_goals
            })

        if len(matches) >= limit:
            break

    return matches

# ==========================================
# ЭНДПОИНТ 3: Детальная статистика матча
# ==========================================
def get_fixture_statistics(fixture_id, is_home_team):
    url = f"https://soccer365.ru/games/{fixture_id}/"
    response = requests.get(url, headers=get_headers())
    soup = BeautifulSoup(response.text, 'html.parser')

    stats_dict = {"Fouls": "Нет данных", "Yellow cards": "Нет данных", "Shots on target": "Нет данных", "Offsides": "Нет данных"}

    # Ищем конкретный контейнер "Весь матч" (у него id="stat-tp0")
    full_match_tab = soup.find('div', id='stat-tp0')
    
    # Если сайт вдруг поменял дизайн, ищем по всей странице, 
    # но в приоритете именно вкладка "Весь матч"
    search_area = full_match_tab if full_match_tab else soup

    stats_items = search_area.find_all('div', class_='stats_item')
    
    for item in stats_items:
        title_div = item.find('div', class_='stats_title')
        if title_div:
            title = title_div.text.strip()
            
            # Ищем только нужные нам метрики
            if title in ["Фолы", "Желтые карточки", "Удары в створ", "Офсайды"]:
                values = item.find_all('div', class_='stats_inf')
                if len(values) >= 2:
                    home_val = values[0].text.strip()
                    away_val = values[1].text.strip()

                    # Формируем наглядный вывод
                    stat_str = f"{home_val} : {away_val} (Хозяева:Гости)"

                    # Добавляем проверку "Нет данных", чтобы парсер брал 
                    # только самое первое значение сверху страницы и не перезаписывал его
                    if title == "Фолы" and stats_dict["Fouls"] == "Нет данных":
                        stats_dict["Fouls"] = stat_str
                    elif title == "Желтые карточки" and stats_dict["Yellow cards"] == "Нет данных":
                        stats_dict["Yellow cards"] = stat_str
                    elif title == "Удары в створ" and stats_dict["Shots on target"] == "Нет данных":
                        stats_dict["Shots on target"] = stat_str
                    elif title == "Офсайды" and stats_dict["Offsides"] == "Нет данных":
                        stats_dict["Offsides"] = stat_str

    time.sleep(0.5) # Небольшая пауза, чтобы нас не забанили
    return stats_dict