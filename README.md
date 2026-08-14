# TeamBot

## Быстрый старт

### 1. Настройка окружения

```bash
# Клонирование репозитория
git clone <your-repo>
cd TeamBot

# Создание виртуального окружения
python -m venv .venv
source .venv/bin/activate  # или .venv\Scripts\activate

# Установка зависимостей
pip install -e .
pre-commit install