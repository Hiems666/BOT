import football_api
import time

def run_diagnostics():
    print("=== ЗАПУСК ДИАГНОСТИКИ ПАРСЕРА ===")
    
    # Берем стабильную команду для теста
    test_team = "Аргентина" 

    # ---------------------------------------------------------
    # ШАГ 1: Проверка поисковика
    # ---------------------------------------------------------
    print(f"\n[Шаг 1] Тестируем поиск команды '{test_team}' через DDG...")
    teams = football_api.search_teams(test_team)
    
    if not teams:
        print("❌ ОШИБКА [ШАГ 1]: Поиск не дал результатов.")
        print("-> Возможные причины: DuckDuckGo заблокировал IP, либо изменился формат ссылок на Soccer365.")
        return
        
    print(f"✅ Поиск работает. Найдено команд: {len(teams)}")
    target_team = teams[0]
    team_id = target_team['id']
    print(f"-> Для дальнейшего теста выбрана: {target_team['name']} (ID: {team_id})")

    time.sleep(1) # Небольшая пауза, чтобы не спамить сайт

    # ---------------------------------------------------------
    # ШАГ 2: Проверка страницы профиля команды
    # ---------------------------------------------------------
    print(f"\n[Шаг 2] Тестируем загрузку истории матчей для ID {team_id}...")
    
    # Берем список с запасом, чтобы точно найти завершенный матч
    fixtures = football_api.get_recent_fixtures(team_id, limit=5)
    
    if not fixtures:
        print("❌ ОШИБКА [ШАГ 2]: Не удалось получить список матчей.")
        print("-> Возможные причины: Сбой сети (Курьер) или на сайте поменялся класс 'game_link'.")
        return
        
    print(f"✅ Матчи успешно найдены. Загружено: {len(fixtures)}")
    
    # ИЩЕМ ПЕРВЫЙ ЗАВЕРШЕННЫЙ МАТЧ (где счет не равен "-")
    target_fixture = None
    for fix in fixtures:
        if fix['home_goals'] != "-":
            target_fixture = fix
            break
            
    # Если вдруг все 5 матчей - будущие (редкость, но бывает), берем первый
    if not target_fixture:
        target_fixture = fixtures[0]

    fixture_id = target_fixture['fixture_id']
    print(f"-> Для парсинга статы выбран матч: {target_fixture['home_name']} {target_fixture['home_goals']}:{target_fixture['away_goals']} {target_fixture['away_name']} (ID: {fixture_id})")

    time.sleep(1)
    # ---------------------------------------------------------
    # ШАГ 3: Проверка детальной статистики
    # ---------------------------------------------------------
    print(f"\n[Шаг 3] Тестируем сбор статистики для матча ID {fixture_id}...")
    stats = football_api.get_fixture_statistics(fixture_id, is_home_team=True)
    
    if stats.get("Fouls") == "Ошибка":
        print("❌ ОШИБКА СЕТИ [ШАГ 3]: Не удалось скачать страницу матча.")
        return
        
    # Проверяем, не собрал ли парсер одни заглушки "Нет данных"
    if stats.get("Fouls") == "Нет данных" and stats.get("Offsides") == "Нет данных":
        print("⚠️ ВНИМАНИЕ [ШАГ 3]: Страница скачалась, но парсер ничего не нашел!")
        print("-> Причина: 100% изменился дизайн сайта. Проверь наличие вкладки 'stat-tp0' и классов 'stats_item'.")
    else:
        print("✅ Статистика успешно собрана:")
        for key, value in stats.items():
            print(f"   - {key}: {value}")

    print("\n=== ДИАГНОСТИКА УСПЕШНО ЗАВЕРШЕНА ===")

if __name__ == "__main__":
    run_diagnostics()