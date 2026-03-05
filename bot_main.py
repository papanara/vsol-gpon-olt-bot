import telebot
import time
import logging
import os
import json
import threading
from dotenv import load_dotenv
from olt_snmp_core import OLTCore

# ==========================================
# SETUP LOGGING
# ==========================================
log_file_path = os.path.join(os.path.dirname(__file__), 'bot_error.log')
logging.basicConfig(
    filename=log_file_path,
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==========================================
# 1. KONFIGURASI — Baca dari file .env
# ==========================================
load_dotenv()
BOT_TOKEN      = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID  = int(os.getenv('ADMIN_CHAT_ID'))
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 60))   # default 60 detik
STATE_FILE     = os.path.join(os.path.dirname(__file__), 'onu_states.json')

if not BOT_TOKEN or not ADMIN_CHAT_ID:
    raise ValueError("BOT_TOKEN dan ADMIN_CHAT_ID wajib diisi di file .env")

# Inisialisasi Bot dan Engine
bot = telebot.TeleBot(BOT_TOKEN)
olt = OLTCore()

# ==========================================
# 2. STATE MANAGEMENT (Persist ke Disk)
# ==========================================
def load_states() -> dict:
    """Muat state ONU terakhir dari file JSON."""
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_states(states: dict):
    """Simpan state ONU ke file JSON."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(states, f, indent=2)
    except Exception as e:
        logger.error(f"Gagal menyimpan state: {e}", exc_info=True)

# State global + lock untuk thread safety
states_lock      = threading.Lock()
last_onu_states  = load_states()

# ==========================================
# 3. ALERT TOGGLE
# ==========================================
alert_enabled = True

# ==========================================
# 4. RATE LIMITING
# ==========================================
last_command_time: dict = {}
COOLDOWN_SECONDS = 5

def is_rate_limited(chat_id: int) -> bool:
    """Cegah spam command — cooldown 5 detik per user."""
    now = time.time()
    if chat_id in last_command_time:
        if now - last_command_time[chat_id] < COOLDOWN_SECONDS:
            return True
    last_command_time[chat_id] = now
    return False

# ==========================================
# 5. HELPER & KEAMANAN
# ==========================================
def is_authorized(message) -> bool:
    """Batasi akses hanya untuk admin."""
    return message.chat.id == ADMIN_CHAT_ID

# ==========================================
# 6. HANDLER PERINTAH MANUAL
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not is_authorized(message): return
    text = (
        "🤖 *OLT MONITORING BOT READY*\n\n"
        "📜 *Perintah Utama:*\n"
        "/info — Cek kesehatan sistem OLT\n"
        "/status — Ringkasan total ONU\n"
        "/all — Daftar ONU (tabel ringkas)\n"
        "/alert — Toggle notifikasi otomatis\n\n"
        "💡 *Tips:* Ketik angka ID (misal: `24`) untuk melihat detail ONU."
    )
    bot.reply_to(message, text, parse_mode='Markdown')


@bot.message_handler(commands=['info'])
def olt_info(message):
    if not is_authorized(message): return
    if is_rate_limited(message.chat.id): return
    bot.send_chat_action(message.chat.id, 'typing')

    data = olt.get_basic_info()
    if data:
        text = (
            "🏗 *SYSTEM INFORMATION*\n"
            "━━━━━━━━━━━━━━━\n"
            f"🏷 *Name:* `{data['name']}`\n"
            f"🌡 *Suhu:* `{data['temp']} °C`\n"
            f"📊 *CPU:* `{data['cpu']} %`\n"
            f"💾 *RAM:* `{data['mem']} %`\n"
            f"⏱ *Uptime:* `{data['uptime']}`\n"
            "━━━━━━━━━━━━━━━"
        )
    else:
        text = "❌ *Gagal mengambil data sistem.* Periksa koneksi ke OLT!"
    bot.reply_to(message, text, parse_mode='Markdown')


@bot.message_handler(commands=['status'])
def onu_status_summary(message):
    if not is_authorized(message): return
    if is_rate_limited(message.chat.id): return
    bot.send_chat_action(message.chat.id, 'typing')

    onus = olt.get_onu_information()
    if not onus:
        bot.reply_to(message, "❌ Gagal mengambil data ONU. OLT mungkin tidak responsif.")
        return

    online  = sum(1 for x in onus if x.get('status') == 'Online')
    dying   = sum(1 for x in onus if x.get('status') == 'Mati Listrik')
    los     = sum(1 for x in onus if x.get('status') == 'LOS (Putus)')
    offline = sum(1 for x in onus if x.get('status') == 'Offline')

    text = (
        "📊 *ONU STATUS SUMMARY*\n"
        "━━━━━━━━━━━━━━━\n"
        f"🟢 *Online:* `{online}`\n"
        f"🔌 *Mati Listrik:* `{dying}`\n"
        f"🔴 *LOS (Putus):* `{los}`\n"
        f"⚫ *Offline:* `{offline}`\n"
        f"📦 *Total ONU:* `{len(onus)}`"
    )
    bot.reply_to(message, text, parse_mode='Markdown')


@bot.message_handler(commands=['all'])
def list_all_onu(message):
    if not is_authorized(message): return
    if is_rate_limited(message.chat.id): return
    bot.send_chat_action(message.chat.id, 'typing')

    onus = olt.get_onu_information()
    if not onus:
        bot.reply_to(message, "❌ Gagal mengambil daftar ONU.")
        return

    # --- Kirim dalam chunks agar tidak melebihi batas 4096 karakter Telegram ---
    CHUNK_SIZE = 30
    chunks = [onus[i:i+CHUNK_SIZE] for i in range(0, len(onus), CHUNK_SIZE)]

    for idx, chunk in enumerate(chunks):
        header = "📋 *DAFTAR ONU (RINGKAS)*\n" if idx == 0 else ""
        body   = "```\nID | ST | NAMA\n-------------\n"
        for onu in chunk:
            st         = "ON" if onu.get('status') == 'Online' else \
                         "DG" if onu.get('status') == 'Mati Listrik' else "LS"
            name_short = onu.get('description', '?')[:10]
            body      += f"{onu['id']:<2} | {st:<2} | {name_short}\n"
        body += "```"

        footer = "\n_Ketik angka ID untuk detail_" if idx == len(chunks) - 1 else ""
        bot.send_message(message.chat.id, header + body + footer, parse_mode='Markdown')


@bot.message_handler(commands=['alert'])
def toggle_alert(message):
    if not is_authorized(message): return
    global alert_enabled
    alert_enabled = not alert_enabled
    status = "✅ *Aktif*" if alert_enabled else "🔕 *Nonaktif*"
    bot.reply_to(message, f"Notifikasi otomatis sekarang: {status}", parse_mode='Markdown')


@bot.message_handler(func=lambda message: message.text and message.text.isdigit())
def check_onu_by_id(message):
    """Tampilkan detail lengkap saat user mengetik angka ID ONU."""
    if not is_authorized(message): return
    if is_rate_limited(message.chat.id): return

    target_id = message.text
    onus = olt.get_onu_information()

    onu = next((x for x in onus if str(x['id']) == target_id), None)

    if onu:
        status_emoji = (
            "🟢" if onu.get('status') == 'Online' else
            "🔌" if onu.get('status') == 'Mati Listrik' else "🔴"
        )
        text = (
            f"{status_emoji} *DETAIL ONU ID {target_id}*\n"
            "━━━━━━━━━━━━━━━\n"
            f"👤 *Nama:* `{onu.get('description', 'N/A')}`\n"
            f"📡 *Status:* `{onu.get('status', 'N/A')}`\n"
            f"📶 *RX Power:* `{onu.get('rx', 'N/A')} dBm`\n"
            f"⏱ *Uptime:* `{onu.get('uptime', 'N/A')}`\n"
            "━━━━━━━━━━━━━━━"
        )
    else:
        text = f"❌ *ID {target_id} tidak ditemukan.*"

    bot.send_message(message.chat.id, text, parse_mode='Markdown')


# ==========================================
# 7. AUTO-ALERT + FLOOD GUARD
# ==========================================

# Berapa kali SNMP gagal berturut-turut sebelum dianggap OLT down
OLT_DOWN_THRESHOLD = 2

# Durasi stabilization window setelah OLT/jaringan pulih (detik).
# Selama window ini bot TIDAK kirim notif — beri waktu ONU naik kembali.
STABILIZATION_WINDOW = int(os.getenv('STABILIZATION_WINDOW', 300))  # default 5 menit

# Grace period per-ONU untuk status NON-KRITIS (detik).
# ONU harus konsisten dalam status bermasalah selama durasi ini sebelum notif dikirim.
# Berguna untuk: client pindah colokan, kedip listrik sebentar, dsb.
# Status LOS (Putus) TIDAK terkena grace period — langsung notif karena kabel putus.
POWER_GRACE_PERIOD = int(os.getenv('POWER_GRACE_PERIOD', 300))  # default 5 menit

# Status yang dianggap KRITIS → notif langsung tanpa grace period
IMMEDIATE_ALERT_STATUSES = {'LOS (Putus)'}

# ── Debounce tracker per-ONU ─────────────────────────────────────────────────
# Struktur: { onu_id: {'status': str, 'since': float, 'notified': bool} }
# - status  : status pending yang belum dinotifikasi
# - since   : timestamp pertama kali status ini terdeteksi
# - notified: sudah dikirim notif untuk status ini atau belum
pending_changes: dict = {}
pending_lock = threading.Lock()


def _try_send_alert(onu_id: str, old_st: str, new_st: str, name: str):
    """
    Kirim notif perubahan status ONU dengan logika berikut:
    - Status KRITIS (LOS)     → langsung notif
    - Status NON-KRITIS       → tunda sampai grace period terpenuhi
    - ONU kembali Online      → notif langsung + batalkan pending jika ada

    Return True jika notif dikirim, False jika masih dalam grace period.
    """
    now = time.time()

    # ── ONU kembali Online ────────────────────────────────────────────────────
    if new_st == 'Online':
        with pending_lock:
            entry = pending_changes.pop(onu_id, None)

        # Hanya notif "pulih" jika sebelumnya sudah pernah dikirim notif masalah,
        # atau status lama bukan Online (artinya memang ada perubahan nyata)
        if entry and entry.get('notified'):
            # Sudah notif masalah sebelumnya → kirim notif pulih
            _send_status_message(onu_id, name, entry['status'], new_st)
        elif not entry and old_st != 'Online':
            # Tidak ada pending (mungkin langsung dari LOS ke Online) → notif
            _send_status_message(onu_id, name, old_st, new_st)
        # Jika ada pending tapi belum notif → ONU balik Online dalam grace period
        # → tidak perlu notif sama sekali (client cuma pindah colokan sebentar)
        return True

    # ── Status KRITIS → notif langsung ───────────────────────────────────────
    if new_st in IMMEDIATE_ALERT_STATUSES:
        with pending_lock:
            pending_changes.pop(onu_id, None)  # hapus pending lain jika ada
            pending_changes[onu_id] = {'status': new_st, 'since': now, 'notified': True}
        _send_status_message(onu_id, name, old_st, new_st)
        return True

    # ── Status NON-KRITIS → cek grace period ─────────────────────────────────
    with pending_lock:
        entry = pending_changes.get(onu_id)

        if entry is None or entry['status'] != new_st:
            # Status baru pertama kali terdeteksi → mulai timer grace period
            pending_changes[onu_id] = {'status': new_st, 'since': now, 'notified': False}
            print(f"[Debounce] ONU {onu_id} ({name}): {old_st} → {new_st} "
                  f"(grace period {POWER_GRACE_PERIOD}s dimulai)")
            return False

        # Status sudah pending sebelumnya — cek apakah sudah melewati grace period
        elapsed = now - entry['since']
        if elapsed >= POWER_GRACE_PERIOD and not entry['notified']:
            entry['notified'] = True
            _send_status_message(onu_id, name, old_st, new_st, grace_elapsed=int(elapsed))
            return True

    return False


def _send_status_message(onu_id: str, name: str, old_st: str, new_st: str,
                         grace_elapsed: int = 0):
    """Format dan kirim notif Telegram untuk perubahan status ONU."""
    if not alert_enabled:
        return

    if new_st == 'Online':
        emoji = "🟢"
        extra = ""
    elif new_st == 'LOS (Putus)':
        emoji = "🔴"
        extra = "\n⚡ *Tindakan:* Cek kabel/splitter pelanggan."
    elif new_st == 'Mati Listrik':
        emoji = "🔌"
        mins  = grace_elapsed // 60
        extra = f"\n⏱ *Sudah mati:* ±{mins} menit" if grace_elapsed else ""
    else:
        emoji = "⚫"
        extra = ""

    text = (
        f"{emoji} *STATUS CHANGE*\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 *Nama:* `{name}`\n"
        f"🆔 *ID ONU:* `{onu_id}`\n"
        f"🔄 *Perubahan:* `{old_st}` ➔ `{new_st}`\n"
        f"⏰ *Waktu:* `{time.strftime('%H:%M:%S')}`"
        f"{extra}"
    )
    try:
        bot.send_message(ADMIN_CHAT_ID, text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Gagal kirim notif ONU {onu_id}: {e}", exc_info=True)


def background_monitor():
    """
    Monitor status ONU secara periodik.

    Empat skenario yang ditangani:
    ───────────────────────────────
    A) Client mati listrik sementara (< POWER_GRACE_PERIOD)
       → Tidak ada notif sama sekali jika ONU sudah kembali Online

    B) Client mati listrik permanen (> POWER_GRACE_PERIOD)
       → 1 notif "Mati Listrik" dengan info sudah berapa lama mati

    C) ONU LOS (kabel putus)
       → Notif langsung tanpa grace period (perlu tindakan segera)

    D) OLT restart atau mati lampu total
       → Stabilization window → silent re-sync → 1 notif ringkasan
    """
    global last_onu_states, alert_enabled

    consecutive_failures = 0
    olt_was_down         = False
    bot_fresh_start      = True  # Paksa stabilization window saat pertama start

    print("[Monitor] Background monitor started.")

    while True:
        try:
            current_onus = olt.get_onu_information()

            # ── OLT TIDAK RESPONSIF ──────────────────────────────────────────
            if not current_onus:
                consecutive_failures += 1
                print(f"[Monitor] Data ONU kosong (kegagalan ke-{consecutive_failures}).")

                if consecutive_failures >= OLT_DOWN_THRESHOLD and not olt_was_down:
                    olt_was_down    = True
                    bot_fresh_start = False
                    with pending_lock:
                        pending_changes.clear()  # buang semua pending saat OLT down
                    if alert_enabled:
                        bot.send_message(
                            ADMIN_CHAT_ID,
                            "🚨 *OLT TIDAK RESPONSIF*\n"
                            "━━━━━━━━━━━━━━━\n"
                            "SNMP walk gagal beberapa kali berturut-turut.\n"
                            "Kemungkinan OLT sedang restart atau koneksi terputus.\n"
                            f"⏰ *Waktu:* `{time.strftime('%H:%M:%S')}`",
                            parse_mode='Markdown'
                        )
                time.sleep(CHECK_INTERVAL)
                continue

            # ── STABILIZATION WINDOW (setelah OLT down atau bot baru start) ──
            if (olt_was_down or bot_fresh_start) and STABILIZATION_WINDOW > 0:
                reason = "OLT kembali online" if olt_was_down else "bot baru start"
                print(f"[Monitor] {reason}. Stabilization window {STABILIZATION_WINDOW}s...")

                if alert_enabled:
                    bot.send_message(
                        ADMIN_CHAT_ID,
                        "⏳ *JARINGAN PULIH — MENUNGGU STABIL*\n"
                        "━━━━━━━━━━━━━━━\n"
                        f"OLT responsif kembali.\n"
                        f"Monitoring ditahan selama *{STABILIZATION_WINDOW // 60} menit* "
                        f"agar ONU punya waktu naik kembali.\n"
                        f"⏰ *Waktu:* `{time.strftime('%H:%M:%S')}`",
                        parse_mode='Markdown'
                    )

                time.sleep(STABILIZATION_WINDOW)
                stable_onus = olt.get_onu_information()

                if stable_onus:
                    new_states = {str(o['id']): o.get('status') for o in stable_onus}
                    with states_lock:
                        last_onu_states = new_states
                        save_states(last_onu_states)

                    online_count  = sum(1 for s in new_states.values() if s == 'Online')
                    problem_count = len(new_states) - online_count
                    problem_note  = (
                        f"\n⚠️ *{problem_count} ONU* masih bermasalah — ketik /status untuk detail."
                        if problem_count > 0 else "\n✅ Semua ONU normal."
                    )

                    if alert_enabled:
                        bot.send_message(
                            ADMIN_CHAT_ID,
                            "✅ *MONITORING AKTIF KEMBALI*\n"
                            "━━━━━━━━━━━━━━━\n"
                            f"State {len(new_states)} ONU di-sync ulang.{problem_note}\n"
                            f"⏰ *Waktu:* `{time.strftime('%H:%M:%S')}`",
                            parse_mode='Markdown'
                        )
                else:
                    olt_was_down    = True
                    bot_fresh_start = False
                    time.sleep(CHECK_INTERVAL)
                    continue

                olt_was_down         = False
                bot_fresh_start      = False
                consecutive_failures = 0
                time.sleep(CHECK_INTERVAL)
                continue

            # ── MONITORING NORMAL ─────────────────────────────────────────────
            consecutive_failures = 0
            bot_fresh_start      = False

            with states_lock:
                for onu in current_onus:
                    oid_id     = str(onu['id'])
                    current_st = onu.get('status', 'Unknown')
                    name       = onu.get('description', f'ONU-{oid_id}')
                    old_st     = last_onu_states.get(oid_id)

                    if old_st is not None and old_st != current_st:
                        _try_send_alert(oid_id, old_st, current_st, name)
                    elif old_st == current_st and current_st not in ('Online', 'Unknown'):
                        # Status bermasalah masih sama → cek apakah grace period sudah lewat
                        _try_send_alert(oid_id, old_st, current_st, name)

                    last_onu_states[oid_id] = current_st

                save_states(last_onu_states)

        except Exception as e:
            logger.error(f"Background monitor error: {e}", exc_info=True)
            print(f"[Monitor] Error: {e}")

        time.sleep(CHECK_INTERVAL)


# ==========================================
# 8. ENTRY POINT
# ==========================================

if __name__ == '__main__':
    monitor_thread        = threading.Thread(target=background_monitor, name="OLTMonitor")
    monitor_thread.daemon = True
    monitor_thread.start()

    print("[Bot] Polling started...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
