import subprocess
import sys

# Запускаем alembic с переданными аргументами
# Используем shell=True для правильной работы в Windows
result = subprocess.run(
    ["alembic"] + sys.argv[1:],
    shell=True,
    capture_output=False,
)
sys.exit(result.returncode)
