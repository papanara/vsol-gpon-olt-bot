from easysnmp import Session
import re
import logging

logger = logging.getLogger(__name__)

class OLTCore:
    def __init__(self, ip, community):
        self.ip = ip
        self.community = community
        self.status_map = {
            '2': 'LOS (Putus)',
            '3': 'Online',
            '4': 'Mati Listrik',
            '6': 'Offline'
        }

    def _create_session(self):
        """Membuat sesi SNMP v2c"""
        return Session(hostname=self.ip, community=self.community, version=2)

    def get_basic_info(self):
        """
        Mengambil Informasi Dasar OLT:
        1. System Name, 2. Memory Usage, 3. CPU Usage, 4. Temperature, 5. Uptime
        Returns None jika OLT tidak bisa dihubungi.
        """
        try:
            session = self._create_session()
            oids = {
                'name':   '.1.3.6.1.2.1.1.5.0',
                'temp':   '.1.3.6.1.4.1.37950.1.1.5.10.13.1.1.2.1',
                'mem':    '.1.3.6.1.4.1.37950.1.1.5.10.13.1.1.4.1',
                'cpu':    '.1.3.6.1.4.1.37950.1.1.5.10.13.1.1.5.1',
                'uptime': '.1.3.6.1.4.1.37950.1.1.5.10.12.5.8.0'
            }

            results = {}
            for key, oid in oids.items():
                raw_val = session.get(oid).value
                if key in ['cpu', 'mem', 'temp'] and raw_val != 'NOSUCHINSTANCE':
                    try:
                        results[key] = f"{float(raw_val):.1f}"
                    except Exception:
                        results[key] = raw_val
                else:
                    results[key] = raw_val if raw_val != 'NOSUCHINSTANCE' else "N/A"

            return results

        except Exception as e:
            # Catat error tapi jangan crash — caller akan terima None
            logger.error(f"get_basic_info failed: {e}", exc_info=True)
            return None

    def get_onu_information(self, pon_port=1):
        """
        Mengambil Informasi Seluruh ONU pada PON port tertentu.
        Returns list kosong [] jika OLT tidak bisa dihubungi.

        Parameter:
            pon_port (int): Nomor PON port yang ingin di-query (default: 1)
        """
        try:
            session = self._create_session()
            p = pon_port  # shorthand

            phases    = session.walk(f'.1.3.6.1.4.1.37950.1.1.6.1.1.1.1.5.{p}')
            names     = session.walk(f'.1.3.6.1.4.1.37950.1.1.6.1.1.4.1.24.{p}')
            rx_powers = session.walk(f'.1.3.6.1.4.1.37950.1.1.6.1.1.3.1.7.{p}')
            uptimes   = session.walk(f'.1.3.6.1.4.1.37950.1.1.6.1.1.4.1.20.{p}')

            # Jika walk kembali kosong, berarti OLT tidak responsif
            if not phases:
                logger.warning(f"SNMP walk kosong pada PON port {pon_port} — OLT mungkin tidak responsif.")
                return []

            onu_data = {}
            def get_idx(oid): return oid.split('.')[-1]

            for ph in phases:
                idx = get_idx(ph.oid)
                onu_data[idx] = {'status': self.status_map.get(ph.value, 'Unknown')}

            for n in names:
                idx = get_idx(n.oid)
                if idx in onu_data:
                    onu_data[idx]['description'] = n.value

            for r in rx_powers:
                idx = get_idx(r.oid)
                if idx in onu_data:
                    onu_data[idx]['rx'] = r.value if r.value != '0.00' else "-inf"

            for u in uptimes:
                idx = get_idx(u.oid)
                if idx in onu_data:
                    onu_data[idx]['uptime'] = self._parse_onu_uptime(u.value)

            return [
                {'id': i, **onu_data[i]}
                for i in sorted(onu_data.keys(), key=int)
            ]

        except Exception as e:
            logger.error(f"get_onu_information (port {pon_port}) failed: {e}", exc_info=True)
            return []

    def _parse_onu_uptime(self, uptime_str):
        """Helper: konversi '1574691 s' → '18d 5h 24m'"""
        if not uptime_str or uptime_str == "N/A":
            return "OFFLINE"
        try:
            seconds = int(re.search(r'\d+', uptime_str).group())
            d = seconds // 86400
            h = (seconds % 86400) // 3600
            m = (seconds % 3600) // 60
            parts = []
            if d > 0: parts.append(f"{d}d")
            if h > 0: parts.append(f"{h}h")
            if m > 0: parts.append(f"{m}m")
            return " ".join(parts) if parts else "< 1m"
        except Exception:
            return uptime_str
