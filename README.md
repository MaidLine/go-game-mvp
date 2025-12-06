# Go Game — MVP

Простая реализация веб-приложения "Игра Го" с FastAPI (бэкенд), SQLite (БД) и адаптивным HTML/JS фронтендом.

## Требования
- Python 3.10+ (рекомендую 3.11)
- pip

## Установка и запуск локально (для новичка)
1. Скопируйте репозиторий в папку `go-game-mvp`.
2. Откройте терминал (Command Prompt / PowerShell на Windows, Terminal на macOS/Linux) и перейдите в папку проекта:
   ```bash
   cd path/to/go-game-mvp
3.	Создайте виртуальное окружение и активируйте его:
o	Windows:
 	python -m venv venv
.\venv\Scripts\Activate.ps1
 	либо (Command Prompt):
 	venv\\Scripts\\activate.bat
o	macOS / Linux:
 	python3 -m venv venv
source venv/bin/activate
4.	Установите зависимости:
 	pip install -r requirements.txt
5.	Запустите приложение:
 	uvicorn main:app --reload
6.	Откройте браузер и перейдите по адресу http://127.0.0.1:8000/ — страница фронтенда загрузится автоматически.
