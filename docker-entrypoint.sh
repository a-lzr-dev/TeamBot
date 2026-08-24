# Скрипт входа в контейнер с поддержкой миграций

set -e

echo "🚀 TeamBot Docker Entrypoint"
echo "============================"
echo ""

# Проверка, нужно ли выполнять миграции
if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
    echo "🔄 Running database migrations..."

    # Проверка наличия Alembic
    if command -v alembic >/dev/null 2>&1; then
        # Применение миграций с обработкой ошибок
        if alembic upgrade head; then
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
        echo "⚠️  Alembic not found, skipping migrations"
    fi
else
    echo "⏭️  Migrations skipped (SKIP_MIGRATIONS=true)"
fi

echo ""
echo "🚀 Starting application..."

# Запуск приложения с переданными аргументами
exec python run.py "$@"
