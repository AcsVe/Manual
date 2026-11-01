"""Licence for one computer: «EXPIRY:signature», where the signature is ECDSA P-256 over «FINGERPRINT|EXPIRY».

* The public key below is the same one the bell player uses, so the existing generator
  (bell_license_key_generator.py + license_private_key.pem, kept OUTSIDE this repository) issues the keys.
* The fingerprint is salted with «MANUAL-BUILDER|», so a bell or cheque key never unlocks this program and vice versa.
* Without a key the program runs as a trial for TRIAL_DAYS days, then exporting (PDF, Word, interactive copy) is locked; editing and viewing stay open.
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime

IS_WIN = sys.platform.startswith('win')
TRIAL_DAYS = 14
SALT = 'MANUAL-BUILDER|'

LICENSE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE9hskm3ufgTN+cmD+Vhzv2w6OIiuw
RL/YjNVP/aJaT05+91ZOAv634CJt812D8dP5TtfS6XpAeHRX8ALMi95b9Q==
-----END PUBLIC KEY-----"""
_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_A = _P - 3
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
      0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


def _ec_add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % _P == 0:
        return None
    if p == q:
        lam = (3 * p[0] * p[0] + _A) * pow(2 * p[1], -1, _P) % _P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, _P) % _P
    x = (lam * lam - p[0] - q[0]) % _P
    return x, (lam * (p[0] - x) - p[1]) % _P


def _ec_mul(k, p):
    r = None
    while k:
        if k & 1:
            r = _ec_add(r, p)
        p = _ec_add(p, p)
        k >>= 1
    return r


def _public_point(pem):
    import base64
    der = base64.b64decode(''.join(ln for ln in pem.strip().splitlines() if '-----' not in ln))
    raw = der[-65:]                                  # SubjectPublicKeyInfo ends with 04 || X || Y
    if raw[0] != 4:
        raise ValueError('bad public key')
    return int.from_bytes(raw[1:33], 'big'), int.from_bytes(raw[33:], 'big')


def _der_sig(sig):
    """ECDSA DER signature → (r, s)."""
    if len(sig) < 8 or sig[0] != 0x30:
        raise ValueError('bad signature')
    i = 2 if sig[1] < 0x80 else 2 + (sig[1] & 0x7f)
    out = []
    for _ in range(2):
        if sig[i] != 0x02:
            raise ValueError('bad signature')
        ln = sig[i + 1]
        out.append(int.from_bytes(sig[i + 2:i + 2 + ln], 'big'))
        i += 2 + ln
    return out[0], out[1]


def ecdsa_verify(message, signature, pem=None):
    try:
        r, s_ = _der_sig(signature)
        q = _public_point(pem or LICENSE_PUBLIC_KEY_PEM)
    except (ValueError, IndexError):
        return False
    if not (1 <= r < _N and 1 <= s_ < _N):
        return False
    z = int.from_bytes(hashlib.sha256(message).digest(), 'big')
    w = pow(s_, -1, _N)
    pt = _ec_add(_ec_mul(z * w % _N, _G), _ec_mul(r * w % _N, q))
    return pt is not None and pt[0] % _N == r


def check_license(key, fingerprint, today):
    """→ (valid, expired, 'PERMANENT' | 'YYYY-MM-DD' | None). Key format «EXP:signature» (EXP = YYYYMMDD or PERMANENT)."""
    import base64
    parts = (key or '').strip().split(':', 1)
    if len(parts) != 2:
        return False, False, None
    exp, sig = parts[0].strip().upper(), parts[1].strip()
    try:
        raw = base64.urlsafe_b64decode(sig + '=' * (-len(sig) % 4))
    except ValueError:
        return False, False, None
    if not ecdsa_verify(f'{fingerprint.strip().upper()}|{exp}'.encode(), raw):
        return False, False, None
    if exp == 'PERMANENT':
        return True, False, 'PERMANENT'
    try:
        d = datetime.strptime(exp, '%Y%m%d').date()
    except ValueError:
        return False, False, None
    return True, today > d, d.isoformat()



def _run_quiet(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return (r.stdout or '').strip()
    except Exception:   # noqa: BLE001
        return ''


_BAD = ('', 'none', 'to be filled by o.e.m.', 'default string', 'not applicable', 'n/a', '0')


def machine_fingerprint(cache_dir=None):
    """16 characters tied to this computer: motherboard serial → Windows MachineGuid → network card."""
    raw = ''
    if IS_WIN:
        raw = _run_quiet(['powershell', '-NoProfile', '-Command',
                          '(Get-CimInstance -ClassName Win32_BaseBoard).SerialNumber'])
        if raw.strip().lower() in _BAD:
            lines = [ln.strip() for ln in _run_quiet(['wmic', 'baseboard', 'get', 'serialnumber']).splitlines()
                     if ln.strip() and 'serialnumber' not in ln.lower()]
            raw = lines[0] if lines else ''
        if raw.strip().lower() in _BAD:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography') as k:
                    raw = 'guid:' + winreg.QueryValueEx(k, 'MachineGuid')[0]
            except OSError:
                raw = ''
    elif os.path.isfile('/etc/machine-id'):
        raw = 'mid:' + open('/etc/machine-id').read().strip()
    cache = os.path.join(cache_dir, 'fingerprint.txt') if cache_dir else None
    if raw:
        fp = hashlib.sha256((SALT + raw).encode()).hexdigest()[:16].upper()
    else:
        if cache and os.path.isfile(cache):
            return open(cache, encoding='utf-8').read().strip()
        import uuid
        fp = hashlib.sha256((SALT + 'mac:' + str(uuid.getnode())).encode()).hexdigest()[:16].upper()
    if cache:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache, 'w', encoding='utf-8') as f:
                f.write(fp)
        except OSError:
            pass
    return fp


class LicenseState:
    """What the program may do now. ``mode``: 'licensed' | 'trial' | 'expired' | 'trial_over'."""

    def __init__(self, mode, expires=None, days_left=None, fingerprint=''):
        self.mode, self.expires, self.days_left, self.fingerprint = mode, expires, days_left, fingerprint

    @property
    def can_export(self):
        return self.mode in ('licensed', 'trial')

    def describe(self, L):
        if self.mode == 'licensed':
            return (L('مرخّص دائماً', 'Licensed — permanent') if self.expires == 'PERMANENT'
                    else L(f'مرخّص حتى {self.expires} (باقٍ {self.days_left} يوماً)',
                           f'Licensed until {self.expires} ({self.days_left} days left)'))
        if self.mode == 'trial':
            return L(f'نسخة تجريبية — باقٍ {self.days_left} يوماً', f'Trial — {self.days_left} days left')
        if self.mode == 'expired':
            return L(f'انتهى الترخيص في {self.expires} — التصدير متوقف', f'Licence expired on {self.expires} — exporting is locked')
        return L('انتهت الفترة التجريبية — التصدير متوقف', 'The trial is over — exporting is locked')


def _use_registry():
    return IS_WIN and not os.environ.get('MANUAL_TEST')    # tests never touch the build machine's registry


def _trial_start(data_dir, today=None):
    """First run date, kept in the data folder and (on Windows) the registry, so deleting one does not reset it."""
    stamp = os.path.join(data_dir, '.first_run')
    found = []
    try:
        found.append(date.fromisoformat(open(stamp, encoding='utf-8').read().strip()))
    except (OSError, ValueError):
        pass
    if _use_registry():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\ManualBuilder') as k:
                found.append(date.fromisoformat(winreg.QueryValueEx(k, 'FirstRun')[0]))
        except (OSError, ValueError):
            pass
    start = min(found) if found else (today or date.today())
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(stamp, 'w', encoding='utf-8') as f:
            f.write(start.isoformat())
    except OSError:
        pass
    if _use_registry():
        try:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\ManualBuilder') as k:
                winreg.SetValueEx(k, 'FirstRun', 0, winreg.REG_SZ, start.isoformat())
        except OSError:
            pass
    return start


def license_file(data_dir):
    return os.path.join(data_dir, 'license.json')


def save_key(data_dir, key):
    os.makedirs(data_dir, exist_ok=True)
    with open(license_file(data_dir), 'w', encoding='utf-8') as f:
        json.dump({'key': key.strip(), 'saved': datetime.now().isoformat(timespec='seconds')}, f)


def current_state(data_dir, today=None, fingerprint=None):
    today = today or date.today()
    fp = fingerprint or machine_fingerprint(data_dir)
    key = ''
    try:
        key = json.load(open(license_file(data_dir), encoding='utf-8')).get('key', '')
    except (OSError, ValueError):
        pass
    if key:
        ok, expired, exp = check_license(key, fp, today)
        if ok and not expired:
            left = None if exp == 'PERMANENT' else (date.fromisoformat(exp) - today).days
            return LicenseState('licensed', exp, left, fp)
        if ok and expired:
            return LicenseState('expired', exp, 0, fp)
    start = _trial_start(data_dir, today)
    left = TRIAL_DAYS - (today - start).days
    return LicenseState('trial' if left > 0 else 'trial_over', None, max(left, 0), fp)
