import requests
from bs4 import BeautifulSoup

def test_soccer365_stats():
    # Ссылка на матч с твоего скриншота
    url = "https://soccer365.ru/games/2192385/"
    
    # Притворяемся браузером
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    print("Скачиваю страницу матча...")
    response = requests.get(url, headers=headers)
    
    # Загружаем HTML-код страницы в парсер BeautifulSoup
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Находим ВСЕ блоки с классом stats_item
    stats_items = soup.find_all('div', class_='stats_item')
    
    print("\n--- Результаты выгрузки ---")
    for item in stats_items:
        # Ищем название (Фолы, Удары и т.д.) внутри блока
        title_div = item.find('div', class_='stats_title')
        
        if title_div:
            title = title_div.text.strip()
            
            # Нам нужны только конкретные метрики
            if title in ["Фолы", "Желтые карточки", "Удары в створ"]:
                # Находим обе цифры (левую и правую)
                values = item.find_all('div', class_='stats_inf')
                
                if len(values) >= 2:
                    home_val = values[0].text.strip()
                    away_val = values[1].text.strip()
                    print(f"{title}: Новая Зеландия ({home_val}) - Египет ({away_val})")

if __name__ == "__main__":
    test_soccer365_stats()