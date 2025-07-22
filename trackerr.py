from beem import Hive
from beem.account import Account
from beem.amount import Amount
import requests
import time
import json
import os
import threading

# Конфигурация
CONFIG = {
# Hive настройки
    "hive_account": "huobi-earn",
    "hive_state_file": "hive_tracker_state.json",
    
    # EOS настройки
    "eos_account": "binancentwrk",
    "eos_contract": "core.vaulta",
    "eos_api": "https://api.eosn.io",
    "eos_state_file": "vaulta_state.json",
    
    # Общие настройки
    "telegram_bot_token": "7569935826:AAFlO8QYdC4la1kk2JynlR64V3IH0QxphZI",
    "telegram_chat_ids": ["8018300484", "7858883785", '8133353887'],
    "check_interval": 30
    
    # API для получения цены VAULTA
    "vaulta_price_api": "https://api.coingecko.com/api/v3/simple/price?ids=vaulta&vs_currencies=usd"
}

# Инициализация Hive
hive = Hive()

def get_hive_price():
    """Получает текущую цену HIVE в USD"""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=hive&vs_currencies=usd"
        response = requests.get(url)
        return response.json()["hive"]["usd"]
    except:
        try:
            ticker = hive.get_ticker()
            return float(ticker["latest"]) / float(ticker["hive_btc"])
        except:
            return 0.0

def get_vaulta_price():
    """Получает текущую цену VAULTA в USD"""
    try:
        response = requests.get(CONFIG['vaulta_price_api'])
        response.raise_for_status()
        return response.json()["vaulta"]["usd"]
    except Exception as e:
        print(f"Ошибка получения цены VAULTA: {e}")
        return 0.0

def send_telegram_notification(message, chat_id):
    """Отправляет сообщение в Telegram"""
    url = f"https://api.telegram.org/bot{CONFIG['telegram_bot_token']}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

# ================== HIVE МОНИТОРИНГ ==================
def format_hive_amount(amount_str, hive_price):
    """Форматирует сумму HIVE с USD эквивалентом"""
    amount = Amount(amount_str)
    symbol = amount.symbol
    usd_value = amount.amount * hive_price if symbol == "HIVE" else amount.amount
    return f"{amount} (${usd_value:.2f})", amount.amount, symbol

def load_hive_state():
    """Загружает состояние мониторинга Hive"""
    if os.path.exists(CONFIG['hive_state_file']):
        try:
            with open(CONFIG['hive_state_file'], 'r') as f:
                return json.load(f)
        except:
            pass
    return {"last_id": -1, "last_timestamp": ""}

def save_hive_state(state):
    """Сохраняет состояние мониторинга Hive"""
    with open(CONFIG['hive_state_file'], 'w') as f:
        json.dump(state, f)

def monitor_hive_transactions():
    """Мониторинг транзакций Hive"""
    print("Запущен мониторинг Hive транзакций...")
    state = load_hive_state()
    last_id = state["last_id"]
    last_timestamp = state["last_timestamp"]
    
    while True:
        try:
            account = Account(CONFIG['hive_account'])
            current_hive_price = get_hive_price()
            
            # Получаем историю операций
            history = account.history_reverse(only_ops=["transfer"])
            
            # Обрабатываем новые операции
            for op in history:
                op_id = op["index"]
                op_timestamp = str(op["timestamp"])
                
                # Пропускаем уже обработанные операции
                if op_id <= last_id or op_timestamp <= last_timestamp:
                    continue
                
                # Определяем тип транзакции
                is_incoming = op["to"] == CONFIG['hive_account']
                tx_type = "входящая" if is_incoming else "исходящая"
                
                # Форматируем сумму
                amount_str, amount_num, symbol = format_hive_amount(op["amount"], current_hive_price)
                
                # Рассчитываем рекомендованную сумму только для входящих транзакций
                backup_section = ""
                if is_incoming:
                    backup_amount = amount_num * 1.03
                    backup_usd = backup_amount * (current_hive_price if symbol == "HIVE" else 1)
                    backup_str = f"{backup_amount:.3f} {symbol} (${backup_usd:.2f})"
                    backup_section = f"\n*Рекомендуемая сумма бека:*\n{backup_str}"
                
                # Формируем сообщение
                message = (
                    f"🔔 *Новая {tx_type} транзакция Hive!*\n\n"
                    f"• *Тип:* {'📥 ' if is_incoming else '📤 '}{tx_type}\n"
                    f"• *Сумма:* {amount_str}\n"
                    f"• *От:* `{op['from']}`\n"
                    f"• *Кому:* `{op['to']}`\n"
                    f"• *Мемо:* {op['memo'] or '🚫'}\n"
                    f"{backup_section}"
                )
                
                # Отправляем уведомление во все чаты
                for chat_id in CONFIG['telegram_chat_ids']:
                    send_telegram_notification(message, chat_id)
                
                # Обновляем состояние
                last_id = op_id
                last_timestamp = op_timestamp
                save_hive_state({"last_id": last_id, "last_timestamp": last_timestamp})
            
            time.sleep(CONFIG['check_interval'])
            
        except Exception as e:
            print(f"Ошибка мониторинга Hive: {e}")
            time.sleep(CONFIG['check_interval'] * 2)

# ================== EOS (VAULTA) МОНИТОРИНГ ==================
def load_eos_state():
    """Загружает состояние мониторинга EOS"""
    if os.path.exists(CONFIG['eos_state_file']):
        try:
            with open(CONFIG['eos_state_file'], 'r') as f:
                data = json.load(f)
                return data.get('last_global_sequence', 0)
        except:
            return 0
    return 0

def save_eos_state(sequence):
    """Сохраняет состояние мониторинга EOS"""
    with open(CONFIG['eos_state_file'], 'w') as f:
        json.dump({'last_global_sequence': sequence}, f)

def get_token_transfers():
    """Получает список транзакций токена VAULTA"""
    url = f"{CONFIG['eos_api']}/v2/history/get_actions"
    params = {
        "account": CONFIG['eos_account'],
        "filter": f"{CONFIG['eos_contract']}:transfer",
        "sort": "desc",
        "limit": 100
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json().get('actions', [])
    except Exception as e:
        print(f"Ошибка при получении EOS транзакций: {e}")
        return []

def parse_transfer_data(action):
    """Извлекает данные о переводе из действия"""
    try:
        act = action['act']
        data = act['data']
        return {
            'from': data['from'],
            'to': data['to'],
            'quantity': data['quantity'],
            'memo': data['memo'],
            'tx_id': action['trx_id'],
            'timestamp': action['timestamp'],
            'global_sequence': action['global_sequence'],
            'is_incoming': data['to'] == CONFIG['eos_account']
        }
    except KeyError:
        return None

def parse_quantity(quantity_str):
    """Разбирает строку количества (например: '100.0000 VAULT')"""
    try:
        amount, symbol = quantity_str.split()
        return float(amount), symbol
    except:
        return 0.0, "VAULT"

def monitor_eos_transactions():
    """Мониторинг транзакций EOS (VAULTA токен)"""
    print("Запущен мониторинг EOS транзакций (VAULTA)...")
    last_global_sequence = load_eos_state()
    
    while True:
        try:
            # Получаем текущую цену VAULTA
            vaulta_price = get_vaulta_price()
            transactions = get_token_transfers()
            new_sequence = last_global_sequence
            
            # Обрабатываем транзакции в обратном порядке (от старых к новым)
            for action in reversed(transactions):
                global_sequence = action['global_sequence']
                
                # Пропускаем уже обработанные транзакции
                if global_sequence <= last_global_sequence:
                    continue
                
                # Парсим данные транзакции
                tx_data = parse_transfer_data(action)
                if not tx_data:
                    continue
                
                # Разбираем количество и символ
                amount, symbol = parse_quantity(tx_data['quantity'])
                
                # Форматируем сумму с USD эквивалентом
                usd_value = amount * vaulta_price
                amount_str = f"{amount:.4f} {symbol} (${usd_value:.4f})"
                
                # Рассчитываем рекомендованную сумму для входящих транзакций
                backup_section = ""
                if tx_data['is_incoming']:
                    backup_amount = amount * 1.03
                    backup_usd = backup_amount * vaulta_price
                    backup_str = f"{backup_amount:.4f} {symbol} (${backup_usd:.4f})"
                    backup_section = f"\n*Рекомендуемая сумма бека:*\n{backup_str}"
                
                # Форматируем сообщение
                message = (
                    "🚀 *Новая транзакция VAULTA!*\n\n"
                    f"• *Тип:* {'📥 входящая' if tx_data['is_incoming'] else '📤 исходящая'}\n"
                    f"• *Транзакция:* [{tx_data['tx_id'][:12]}...](https://bloks.io/transaction/{tx_data['tx_id']})\n"
                    f"• *Время:* {tx_data['timestamp']}\n"
                    f"• *От:* `{tx_data['from']}`\n"
                    f"• *Кому:* `{tx_data['to']}`\n"
                    f"• *Количество:* {amount_str}\n"
                    f"• *Примечание:* {tx_data['memo'] or '🚫'}"
                    f"{backup_section}"
                )
                
                # Отправляем уведомление во все чаты
                for chat_id in CONFIG['telegram_chat_ids']:
                    send_telegram_notification(message, chat_id)
                
                print(f"Обнаружена новая транзакция VAULTA: {tx_data['tx_id']}")
                new_sequence = max(new_sequence, global_sequence)
            
            # Обновляем последний sequence
            if new_sequence > last_global_sequence:
                last_global_sequence = new_sequence
                save_eos_state(new_sequence)
        
        except Exception as e:
            print(f"Ошибка мониторинга EOS: {e}")
        
        time.sleep(CONFIG['check_interval'])

# ================== ЗАПУСК МОНИТОРИНГА ==================
if __name__ == "__main__":
    # Запускаем оба мониторинга в отдельных потоках
    hive_thread = threading.Thread(target=monitor_hive_transactions)
    eos_thread = threading.Thread(target=monitor_eos_transactions)
    
    hive_thread.daemon = True
    eos_thread.daemon = True
    
    hive_thread.start()
    eos_thread.start()
    
    print("Мониторинг запущен. Ожидание транзакций...")
    
    # Бесконечный цикл для поддержания работы потоков
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nМониторинг остановлен")