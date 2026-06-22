import requests
import json
import sys

def load_token(filename="config.json"):
    """Читает только секретный токен из конфигурации"""
    try:
        with open(filename, "r", encoding="utf-8") as file:
            config = json.load(file)
            return config["api_token"]
    except FileNotFoundError:
        print("Ошибка: Файл config.json не найден!")
        sys.exit(1)
    except KeyError:
        print("Ошибка: В файле config.json нет ключа 'api_token'!")
        sys.exit(1)

def get_interactive_team_form():
    api_token = load_token()
    
    print("\n" + "="*40)
    print("⚽ АНАЛИЗАТОР ФУТБОЛЬНОЙ СТАТИСТИКИ ⚽")
    print("="*40)
    
    # Интерактивный запрос ID команды
    team_id_str = input("\nВведи ID команды (например, 764 для Бразилии): ")
    
    # Валидация: проверяем, что ввели именно число
    if not team_id_str.isdigit():
        print("Ошибка ввода: ID должен состоять только из цифр. Запусти скрипт заново.")
        return
        
    team_id = int(team_id_str)
    
    # Интерактивный запрос количества матчей
    limit_str = input("Сколько последних матчей показать? (Нажми Enter, чтобы оставить 5): ")
    
    # Если пользователь ничего не ввел (нажал Enter), ставим 5 по умолчанию
    if limit_str == "":
        limit = 5
    elif limit_str.isdigit():
        limit = int(limit_str)
    else:
        print("Неверный ввод количества. Будет показано 5 матчей.")
        limit = 5

    # Формируем запрос к API
    url = f"https://api.football-data.org/v4/teams/{team_id}/matches/"
    headers = {
        "X-Auth-Token": api_token
    }
    querystring = {
        "status": "FINISHED",
        "limit": limit
    }
    
    print(f"\nЗапрашиваем данные с сервера...")
    response = requests.get(url, headers=headers, params=querystring)
    
    if response.status_code == 200:
        data = response.json()
        matches = data.get('matches', [])
        
        print(f"\n✅ Результат: Найдено {len(matches)} последних матчей")
        print("-" * 40)
        
        for match in matches:
            home_team = match['homeTeam']['name']
            away_team = match['awayTeam']['name']
            home_score = match['score']['fullTime']['home']
            away_score = match['score']['fullTime']['away']
            date = match['utcDate'][:10] 
            
            print(f"[{date}] {home_team} {home_score}:{away_score} {away_team}")
            
        print("-" * 40 + "\n")
    else:
        print(f"Ошибка сервера: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    get_interactive_team_form()