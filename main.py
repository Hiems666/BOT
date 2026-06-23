import football_api


def run_analysis():
    team_input = input("\nВведи команду (на русском, например: Аргентина или Зенит): ").strip()

    teams = football_api.search_teams(team_input)

    if not teams:
        print("❌ Команда не найдена.")
        return

    print(f"\nНайдено несколько совпадений для '{team_input}'. Выбери нужную:")

    options_count = min(5, len(teams))
    for i, team in enumerate(teams[:options_count]):
        print(f"{i+1} - {team['name']} (Страна: {team['country']})")

    choice_idx = input(f"\nВведи номер нужной команды (1-{options_count}): ").strip()

    try:
        idx = int(choice_idx) - 1
        if idx < 0 or idx >= options_count:
            raise ValueError
        selected_team = teams[idx]
    except ValueError:
        print("❌ Неверный выбор.")
        return

    team_id = selected_team["id"]
    exact_name = selected_team["name"]

    print(f"\n✅ Ты выбрал: {exact_name} (ID: {team_id})")

    print("\nЧто именно ты хочешь проанализировать?")
    print("1 - Просто результаты (без детальной статистики)")
    print("2 - Только Фолы")
    print("3 - Только Желтые карточки")
    print("4 - Только Удары в створ")
    print("5 - Выгрузить всё сразу")

    choice = input("Выбери цифру (1-5): ").strip()
    limit_str = input("Сколько последних матчей показать? (Enter = 5): ")
    limit = int(limit_str) if limit_str.isdigit() else 5

    print("\nЗагружаю данные (это может занять пару секунд)...")

    matches = football_api.get_recent_fixtures(team_id, limit=limit)

    if not matches:
        print(f"\n⚠️ Нет завершенных матчей для {exact_name}.")
        return

    print("\n" + "-" * 50)
    for match in matches:
        fix_id = match["fixture_id"]
        date = match["date"]
        home = match["home_name"]
        away = match["away_name"]
        hg = match["home_goals"]
        ag = match["away_goals"]

        print(f"[{date}] {home} {hg}:{ag} {away}")

        if choice != "1":
            is_home_team = team_id == match["home_id"]
            stats = football_api.get_fixture_statistics(fix_id, is_home_team)

            if choice == "2":
                print(f"   🚩 Фолы ({exact_name}): {stats['Fouls']}")
            elif choice == "3":
                print(f"   🟨 Желтые карточки ({exact_name}): {stats['Yellow cards']}")
            elif choice == "4":
                print(f"   🎯 Удары в створ ({exact_name}): {stats['Shots on target']}")
            elif choice == "5":
                print(
                    f"   📊 Фолы: {stats['Fouls']} | ЖК: {stats['Yellow cards']} | "
                    f"Удары в створ: {stats['Shots on target']}"
                )

        print("-" * 50)


def main():
    print("\n" + "=" * 50)
    print("Менеджер Статистики")
    print("=" * 50)

    while True:
        run_analysis()

        action = input(
            "\nНажмите Enter для выхода из программы или N для нового запроса: "
        ).strip().lower()

        if action != "n":
            print("До встречи!")
            break

        print("\n" + "=" * 50)
        print("Новый запрос")
        print("=" * 50)


if __name__ == "__main__":
    main()
