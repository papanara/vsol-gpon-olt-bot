# OLT Monitoring Bot (VSOL GPON V1600GS)

Bot Telegram untuk memantau status OLT VSOL GPON 1 PON (V1600GS) secara real-time. Bot ini memberikan notifikasi otomatis jika terdapat perubahan status pada ONU (Online, LOS, Mati Listrik) dan menyediakan ringkasan status melalui perintah Telegram.

## ✨ Fitur Utama

- 🚀 **Real-time Monitoring**: Memantau status seluruh ONU pada PON port.
- 🔔 **Smart Notifications**: Notifikasi otomatis jika ONU LOS (Putus) atau Mati Listrik.
- 🛡️ **Flood Guard & Grace Period**: Mencegah banjir notifikasi saat OLT restart atau client hanya pindah colokan sebentar.
- 📊 **Status Summary**: Ringkasan total ONU (Online, LOS, Mati, Offline).
- 🌡️ **System Info**: Cek kesehatan OLT (Suhu, CPU, RAM, Uptime).
- 🔐 **Admin Only**: Akses bot dibatasi hanya untuk chat ID admin yang terdaftar.

## 🛠️ Persyaratan

- Python 3.8+
- OLT VSOL GPON (V1600GS atau seri serupa yang mendukung OID standar VSOL).
- SNMP enabled pada OLT.
- Bot Token dari [@BotFather](https://t.me/BotFather).

## 📦 Instalasi

1. **Clone repositori ini:**
   ```bash
   git clone <repository-url>
   cd oltbot
   ```

2. **Install dependensi:**
   ```bash
   pip install -r requirements.txt
   ```
   *(Pastikan Anda memiliki library `easysnmp`. Di Linux mungkin perlu install `libsnmp-dev`)*.

3. **Konfigurasi Environment:**
   Salin `env.example` menjadi `.env` dan lengkapi datanya:
   ```bash
   cp env.example .env
   ```
   Edit file `.env`:
   - `BOT_TOKEN`: Token bot Telegram Anda.
   - `ADMIN_CHAT_ID`: ID Telegram Anda.
   - `OLT_IP`: Alamat IP OLT VSOL Anda.
   - `OLT_COMMUNITY`: SNMP Community string (biasanya `public`).
   - `CHECK_INTERVAL`: Interval pengecekan (detik).

## 🚀 Cara Menjalankan

Jalankan skrip utama:
```bash
python bot_main.py
```

## 📜 Perintah Bot

- `/info` — Menampilkan informasi kesehatan OLT.
- `/status` — Ringkasan jumlah ONU berdasarkan status.
- `/all` — Menampilkan daftar seluruh ONU (ID | Status | Nama).
- `/alert` — Mengaktifkan/menonaktifkan notifikasi otomatis.
- `[ID]` — Kirim angka ID ONU untuk melihat detail lengkap (contoh: `24`).

## ⚠️ Keamanan

- **JANGAN** pernah menyebarkan file `.env` yang berisi token bot Anda.
- Selalu gunakan `.gitignore` untuk mencegah file sensitif ter-upload ke publik.

---
Dikembangkan untuk monitoring jaringan GPON yang efisien.
