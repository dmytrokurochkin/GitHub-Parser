#!/usr/bin/env bash
# deploy.sh: встановлення і оновлення бота на Debian однією командою.
#   ./deploy.sh                перший запуск: Docker, .env, сон ноутбука, запуск
#   ./deploy.sh                повторно: git pull і перезбірка контейнера, .env не чіпається
#   ./deploy.sh --reconfigure  змінити токени й ID у .env
#
# Усе тіло скрипта в main(): bash читає файл по ходу виконання, а git pull
# може його змінити. Функцію bash читає цілком до запуску.
set -euo pipefail

say() { printf '%s\n' "$*"; }

ask_yes() {
    local answer
    read -r -p "$1 [Y/n]: " answer
    # Лише латиниця: у локалі C кирилиця в [...] порівнюється побайтово,
    # а "ні" і "так" починаються з того самого байта
    [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
}

get_env() {
    [ -f .env ] || return 0
    KEY="$1" awk 'index($0, ENVIRON["KEY"] "=") == 1 { print substr($0, length(ENVIRON["KEY"]) + 2); exit }' .env
}

# Значення йде в awk через змінну оточення, а не аргументом:
# аргументи процесу видно всім у ps, а там токен
set_env() {
    (umask 077 && KEY="$1" VALUE="$2" awk '
        BEGIN { key = ENVIRON["KEY"]; value = ENVIRON["VALUE"]; done = 0 }
        index($0, key "=") == 1 { print key "=" value; done = 1; next }
        { print }
        END { if (!done) print key "=" value }
    ' .env > .env.tmp)
    # cat у наявний файл зберігає його права 600
    cat .env.tmp > .env
    rm -f .env.tmp
}

# prompt KEY "Питання" secret|plain required|optional
prompt() {
    local key=$1 text=$2 mode=$3 need=$4 value="" have hint=""
    have=$(get_env "$key")
    if [ -n "$have" ]; then
        hint=" (Enter: залишити поточне)"
    elif [ "$need" = optional ]; then
        hint=" (Enter: пропустити)"
    fi
    while true; do
        if [ "$mode" = secret ]; then
            read -r -s -p "$text$hint: " value
            echo
        else
            read -r -p "$text$hint: " value
        fi
        if [ -n "$value" ]; then
            set_env "$key" "$value"
            return
        fi
        if [ -n "$have" ] || [ "$need" = optional ]; then
            return
        fi
    done
}

configure() {
    if [ ! -f .env ]; then
        (umask 077 && cp .env.example .env)
    fi
    chmod 600 .env
    say ""
    say "📝 Налаштування .env"
    prompt BOT_TOKEN "🔑 BOT_TOKEN (від @BotFather)" secret required
    prompt CHANNEL_ID "📢 CHANNEL_ID (@username каналу або -100...)" plain required
    prompt ADMIN_ID "👤 ADMIN_ID (твій числовий ID, дізнатися в @userinfobot)" plain required
    prompt CHANNEL_LINK "🔗 CHANNEL_LINK (лише для приватного каналу: https://t.me/+...)" plain optional
    prompt GITHUB_TOKEN "🐙 GITHUB_TOKEN (токен без прав, ліміт 5000 запитів/год замість 60)" secret optional
    prompt LAPATHONIA_API_KEY "🤖 LAPATHONIA_API_KEY (описи українською через LLM)" secret optional
    say "✅ .env збережено (права 600). Решта налаштувань розкладу: nano .env"
}

disable_sleep() {
    local conf=/etc/systemd/logind.conf.d/github-parser-no-sleep.conf
    # Лише для ноутбука: є батарея або кришка
    if ! ls /sys/class/power_supply/BAT* >/dev/null 2>&1 && [ ! -d /proc/acpi/button/lid ]; then
        return
    fi
    if [ -f "$conf" ]; then
        return
    fi
    say ""
    if ! ask_yes "💻 Схоже, це ноутбук. Вимкнути сон (і при закритій кришці), щоб бот працював 24/7?"; then
        say "ℹ️ Сон не чіпаю. Якщо ноутбук засне, пости не вийдуть вчасно"
        return
    fi
    $SUDO mkdir -p /etc/systemd/logind.conf.d
    printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\nIdleAction=ignore\n' \
        | $SUDO tee "$conf" >/dev/null
    # Замасковані цілі сну діють одразу: навіть якщо щось спробує приспати систему,
    # вона не засне. Налаштування кришки logind прочитає після перезавантаження
    # (перезапуск systemd-logind наживо може обірвати графічну сесію)
    $SUDO systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null
    say "✅ Сон вимкнено. Повернути: sudo rm $conf && sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target"
}

check_time() {
    # Розклад іде за годинником сервера: годинник, що відстає, зсуває пости
    command -v timedatectl >/dev/null 2>&1 || return 0
    if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)" = "no" ]; then
        say "⏳ Годинник не синхронізований, вмикаю NTP..."
        $SUDO timedatectl set-ntp true 2>/dev/null \
            || say "⚠️ Не вдалося. Встанови синхронізацію: sudo apt install systemd-timesyncd"
    fi
}

main() {
    cd "$(dirname "$(readlink -f "$0")")"
    if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

    say "=================================================="
    say "🚀 GitHub Parser: розгортання в Docker"
    say "=================================================="

    if [ -d .git ]; then
        say "⏳ Оновлюю код з GitHub..."
        git pull --ff-only || say "⚠️ git pull не вдався, запускаю поточну версію"
    fi

    if ! command -v docker >/dev/null 2>&1; then
        say "⏳ Docker не знайдено, встановлюю (get.docker.com)..."
        if ! command -v curl >/dev/null 2>&1; then
            $SUDO apt-get update -q && $SUDO apt-get install -y -q curl
        fi
        curl -fsSL https://get.docker.com | $SUDO sh
        if [ -n "$SUDO" ]; then
            # Діє з наступного входу в систему; до того docker іде через sudo
            $SUDO usermod -aG docker "$USER" || true
        fi
    fi
    if docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="$SUDO docker"; fi
    if ! $DOCKER compose version >/dev/null 2>&1; then
        say "❌ Немає docker compose: sudo apt install docker-compose-plugin"
        exit 1
    fi

    if [ ! -f .env ] || [ "${1:-}" = "--reconfigure" ]; then
        configure
    else
        say "ℹ️ .env уже є, залишаю як є (змінити: ./deploy.sh --reconfigure)"
    fi

    disable_sleep
    check_time

    mkdir -p data
    say ""
    say "⏳ Збираю і запускаю контейнер..."
    $DOCKER compose up -d --build

    say ""
    say "=================================================="
    say "🎉 Бот запущено, перезапускається сам (restart: unless-stopped)"
    say "• Логи:      $DOCKER compose logs -f"
    say "• Зупинити:  $DOCKER compose down"
    say "• Оновити:   ./deploy.sh"
    say "• У Telegram бот надішле тобі повідомлення про старт"
    say "=================================================="
    sleep 5
    $DOCKER compose logs --tail 20
}

main "$@"
