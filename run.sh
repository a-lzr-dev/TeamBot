# ============================================================
# TeamBot Run Script
# ============================================================
# Использование: ./run.sh [--mode full|api|tg|dev]
# ============================================================

set -e

# ============================================================
# Цвета для вывода
# ============================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================
# Функции логирования
# ============================================================
log_info() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_debug() {
    echo -e "${BLUE}🔍 $1${NC}"
}

log_header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
}

# ============================================================
# Проверка переменных окружения
# ============================================================
check_environment() {
    log_header "Проверка переменных окружения"
    
    # Обязательные переменные
    required_vars=(
        "BOT_TOKEN"
        "BOT_ID"
        "BOT_HASH"
        "DB_MAIN_USER"
        "DB_MAIN_PASSWORD"
        "DB_MAIN_HOST"
        "ADMIN_IDS"
        "SUPPORT_CHAT_ID"
        "SUPPORT_CHAT_TOPIC_IDS"
        "ENCRYPTION_SECRET"
    )
    
    missing_vars=()
    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            missing_vars+=("$var")
        fi
    done
    
    if [ ${#missing_vars[@]} -ne 0 ]; then
        log_error "Отсутствуют обязательные переменные окружения:"
        for var in "${missing_vars[@]}"; do
            echo "   - $var"
        done
        echo ""
        log_warn "Скопируйте .env.example в .env и заполните значения"
        exit 1
    fi
    
    log_info "Все обязательные переменные установлены"
    
    # Проверка формата ADMIN_IDS
    if ! [[ "$ADMIN_IDS" =~ ^\[.*\]$ ]]; then
        log_error "ADMIN_IDS должен быть в формате JSON массива: [1039799368]"
        exit 1
    fi
    
    # Проверка формата SUPPORT_CHAT_TOPIC_IDS
    if ! [[ "$SUPPORT_CHAT_TOPIC_IDS" =~ ^\{.*\}$ ]]; then
        log_error "SUPPORT_CHAT_TOPIC_IDS должен быть в формате JSON объекта: {\"Globus\":123,\"TeamBot\":456}"
        exit 1
    fi
    
    log_info "Все переменные прошли валидацию"
}

# ============================================================
# Проверка подключения к БД
# ============================================================
check_database() {
    log_header "Проверка подключения к БД"
    
    # Проверка основной БД (PostgreSQL)
    if [ -n "$DB_MAIN_HOST" ] && [ -n "$DB_MAIN_PORT" ]; then
        log_debug "Проверка PostgreSQL: $DB_MAIN_HOST:$DB_MAIN_PORT"
        
        # Используем python для проверки через asyncpg
        python3 -c "
import asyncio
import asyncpg
import sys

async def check_db():
    try:
        conn = await asyncpg.connect(
            host='${DB_MAIN_HOST}',
            port=${DB_MAIN_PORT},
            user='${DB_MAIN_USER}',
            password='${DB_MAIN_PASSWORD}',
            database='${DB_MAIN_NAME:-team_bot}'
        )
        await conn.close()
        return True
    except Exception as e:
        print(f'Ошибка подключения: {e}')
        return False

if not asyncio.run(check_db()):
    sys.exit(1)
" 2>/dev/null
        
        if [ $? -eq 0 ]; then
            log_info "PostgreSQL подключена успешно"
        else
            log_warn "Не удалось подключиться к PostgreSQL (продолжаем...)"
        fi
    fi
    
    # Проверка Avanpost (MSSQL) - если настроена
    if [ -n "$DB_AVANPOST_HOST" ] && [ -n "$DB_AVANPOST_PORT" ]; then
        log_debug "Проверка MSSQL: $DB_AVANPOST_HOST:$DB_AVANPOST_PORT"
        # Простая проверка через nc (netcat)
        if command -v nc &> /dev/null; then
            if nc -z "$DB_AVANPOST_HOST" "$DB_AVANPOST_PORT" 2>/dev/null; then
                log_info "MSSQL доступен"
            else
                log_warn "MSSQL недоступен (продолжаем...)"
            fi
        else
            log_warn "nc (netcat) не установлен, пропускаем проверку MSSQL"
        fi
    fi
}

# ============================================================
# Ожидание готовности БД
# ============================================================
wait_for_postgres() {
    log_header "Ожидание готовности PostgreSQL"
    
    local max_attempts=30
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        log_debug "Попытка $attempt/$max_attempts..."
        
        python3 -c "
import asyncio
import asyncpg

async def check():
    try:
        conn = await asyncpg.connect(
            host='${DB_MAIN_HOST}',
            port=${DB_MAIN_PORT},
            user='${DB_MAIN_USER}',
            password='${DB_MAIN_PASSWORD}',
            database='${DB_MAIN_NAME:-team_bot}'
        )
        await conn.close()
        return True
    except:
        return False

if not asyncio.run(check()):
    exit(1)
" 2>/dev/null
        
        if [ $? -eq 0 ]; then
            log_info "PostgreSQL готова к работе"
            return 0
        fi
        
        sleep 2
        attempt=$((attempt + 1))
    done
    
    log_warn "PostgreSQL не ответила за $max_attempts попыток, продолжаем..."
    return 0
}

# ============================================================
# Создание директорий
# ============================================================
create_directories() {
    log_header "Создание директорий"
    
    local dirs=(
        "${LOG_DIR:-/app/logs}"
        "${AUTOMATION_TEMP_DIR:-/app/temp/automation}"
    )
    
    for dir in "${dirs[@]}"; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir"
            log_info "Создана директория: $dir"
        else
            log_debug "Директория существует: $dir"
        fi
    done
}

# ============================================================
# Установка прав
# ============================================================
set_permissions() {
    log_header "Установка прав"
    
    # Если запущены от root
    if [ "$EUID" -eq 0 ]; then
        # Изменение владельца на botuser (если пользователь существует)
        if id "botuser" &>/dev/null; then
            chown -R botuser:botuser /app 2>/dev/null || true
            log_info "Права установлены для botuser"
        fi
    else
        log_debug "Запуск от непривилегированного пользователя"
    fi
}

# ============================================================
# Проверка Python окружения
# ============================================================
check_python() {
    log_header "Проверка Python окружения"
    
    # Проверка версии Python
    python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
    log_info "Python версия: $python_version"
    
    # Проверка наличия основных модулей
    local modules=(
        "aiogram"
        "fastapi"
        "sqlalchemy"
        "asyncpg"
        "telethon"
    )
    
    for module in "${modules[@]}"; do
        if python3 -c "import $module" 2>/dev/null; then
            log_debug "✅ $module установлен"
        else
            log_warn "⚠️  $module не установлен"
        fi
    done
}

# ============================================================
# Вывод информации о запуске
# ============================================================
print_banner() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}║   🚀  TeamBot Application Starting...                    ║${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}║   Mode:      ${YELLOW}${APP_MODE:-full}${GREEN}                                 ║${NC}"
    echo -e "${GREEN}║   API:       ${YELLOW}http://${API_HOST:-0.0.0.0}:${API_PORT:-8000}${GREEN}              ║${NC}"
    echo -e "${GREEN}║   Docs:      ${YELLOW}http://${API_HOST:-0.0.0.0}:${API_PORT:-8000}/api/docs${GREEN}    ║${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}║   Env:       ${YELLOW}${APP_ENV:-production}${GREEN}                              ║${NC}"
    echo -e "${GREEN}║   Debug:     ${YELLOW}${APP_DEBUG:-false}${GREEN}                              ║${NC}"
    echo -e "${GREEN}║   Log Level: ${YELLOW}${LOG_LEVEL:-INFO}${GREEN}                              ║${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║   📊 Database:                                           ║${NC}"
    echo -e "${GREEN}║     Main:     ${YELLOW}${DB_MAIN_HOST}:${DB_MAIN_PORT}/${DB_MAIN_NAME:-team_bot}${GREEN}          ║${NC}"
    if [ -n "$DB_AVANPOST_HOST" ]; then
        echo -e "${GREEN}║     Avanpost: ${YELLOW}${DB_AVANPOST_HOST}:${DB_AVANPOST_PORT}/${DB_AVANPOST_NAME:-avanpost}${GREEN}   ║${NC}"
    fi
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# ============================================================
# Основная функция
# ============================================================
main() {
    log_header "TeamBot Run Script"
    
    # Парсинг аргументов
    while [[ $# -gt 0 ]]; do
        case $1 in
            --mode)
                export APP_MODE="$2"
                shift 2
                ;;
            --host)
                export API_HOST="$2"
                shift 2
                ;;
            --port)
                export API_PORT="$2"
                shift 2
                ;;
            --debug)
                export APP_DEBUG=true
                export LOG_LEVEL=DEBUG
                shift
                ;;
            --help)
                echo "Использование: $0 [OPTIONS]"
                echo ""
                echo "Опции:"
                echo "  --mode MODE     Режим запуска (full|api|tg|dev)"
                echo "  --host HOST     Хост для API"
                echo "  --port PORT     Порт для API"
                echo "  --debug         Включить режим отладки"
                echo "  --help          Показать эту справку"
                exit 0
                ;;
            *)
                log_error "Неизвестная опция: $1"
                echo "Используйте --help для справки"
                exit 1
                ;;
        esac
    done
    
    # Установка значений по умолчанию
    export APP_MODE="${APP_MODE:-full}"
    export APP_ENV="${APP_ENV:-production}"
    export APP_DEBUG="${APP_DEBUG:-false}"
    export LOG_LEVEL="${LOG_LEVEL:-INFO}"
    export API_HOST="${API_HOST:-0.0.0.0}"
    export API_PORT="${API_PORT:-8000}"
    export DB_MAIN_NAME="${DB_MAIN_NAME:-team_bot}"
    export LOG_DIR="${LOG_DIR:-/app/logs}"
    export AUTOMATION_TEMP_DIR="${AUTOMATION_TEMP_DIR:-/app/temp/automation}"
    
    # Выполнение проверок
    check_environment
    create_directories
    set_permissions
    check_python
    
    # Ожидание БД (только не в dev режиме)
    if [ "$APP_MODE" != "dev" ] && [ "$APP_ENV" != "development" ]; then
        wait_for_postgres
    fi
    
    check_database
    
    # Вывод баннера
    print_banner
    
    # Запуск приложения
    log_info "Запуск приложения в режиме: $APP_MODE"
    echo ""
    
    exec python run.py --mode "$APP_MODE"
}

# ============================================================
# Обработка сигналов
# ============================================================
trap 'log_info "Получен сигнал остановки"; exit 0' SIGTERM SIGINT

# ============================================================
# Запуск
# ============================================================
main "$@"