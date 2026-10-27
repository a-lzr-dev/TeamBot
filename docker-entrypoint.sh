#!/bin/sh
# Скрипт входа в контейнер с поддержкой миграций

set -e

echo "🚀 TeamBot Docker Entrypoint"
echo "============================"
echo ""

# Проверка, нужно ли выполнять миграции
if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
    echo "🔄 Running database migrations..."

    # Проверка наличия Alembic через Python-интерпретатор из venv
    # (shebang в /app/.venv/bin/alembic сломан, поэтому используем python -m)
    if /app/.venv/bin/python -c "import alembic" 2>/dev/null; then
        # Применение миграций через python -m alembic
        if /app/.venv/bin/python -m alembic upgrade head; then
            echo "✅ Migrations applied successfully"
        else
            echo "❌ Migrations failed!"
            if [ "${MIGRATIONS_REQUIRED:-true}" = "true" ]; then
                echo "   Migrations are required, exiting..."
                exit 1
            else
                echo "   ⚠️  Continuing despite migration failure (MIGRATIONS_REQUIRED=false)"
            fi
        fi
    else
        echo "⚠️  Alembic not found in Python environment, skipping migrations"
    fi
else
    echo "⏭️  Migrations skipped (SKIP_MIGRATIONS=true)"
fi

echo ""
echo "🚀 Starting application..."

# Запуск приложения через Python из venv
exec /app/.venv/bin/python run.py "$@"
