import os
import time
import requests
import sqlite3
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer

# Configurações do Telegram
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# Lista padrão de URLs para monitoramento
DEFAULT_URLS = [
    "https://a7xworld.com/products.json",
    "https://a7xworld.com/collections/new-merch/products.json",
    "https://a7xworld.com/collections/all/products.json",
    "https://a7xworld.com/collections/the-vault/products.json",
    "https://a7xworld.com/collections/bat-friday-23/products.json",
    "https://a7xworld.com/collections/vinyl-records/products.json"
]

URLS_ENV = os.environ.get("MONITOR_URLS")
URLS = [u.strip() for u in URLS_ENV.split(",")] if URLS_ENV else DEFAULT_URLS
DB_FILE = "/data/products.db"
INTERVALO = int(os.environ.get("CHECK_INTERVAL", "300"))

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            title TEXT,
            price TEXT,
            url TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_known_products():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM products")
    rows = cursor.fetchall()
    conn.close()
    return {row[0] for row in rows}

def save_products(products):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT OR IGNORE INTO products (id, title, price, url) VALUES (?, ?, ?, ?)",
        products
    )
    conn.commit()
    conn.close()

def send_telegram(message):
    telegram_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(telegram_url, json=payload)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERRO] Falha ao enviar telegram: {e}")

def monitor():
    print("[INFO] Iniciando monitoramento a7xworld.com...")
    init_db()
    
    conhecidos = get_known_products()
    primeira_vez = len(conhecidos) == 0
    if primeira_vez:
        print("[INFO] Banco de dados vazio. Inicializando com produtos atuais...")
        
    while True:
        try:
            novos_salvar = []
            alertas = []
            
            for url in URLS:
                print(f"[INFO] Buscando produtos em: {url}")
                
                # Extrair nome da coleção do link
                colecao = url.split("/collections/")[-1].split("/")[0] if "/collections/" in url else "geral"
                
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
                    "Referer": "https://a7xworld.com/",
                    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"Windows"',
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin"
                }
                
                try:
                    res = requests.get(url, headers=headers, timeout=15)
                    res.raise_for_status()
                    data = res.json()
                except Exception as req_err:
                    print(f"[ERRO] Falha ao ler {url}: {req_err}")
                    continue
                
                for p in data.get("products", []):
                    pid = str(p["id"])
                    title = p.get("title", "Sem título")
                    handle = p.get("handle", "")
                    prod_url = f"https://a7xworld.com/products/{handle}"
                    
                    price = "N/A"
                    variants = p.get("variants", [])
                    if variants:
                        price = variants[0].get("price", "N/A")
                    
                    if pid not in conhecidos:
                        novos_salvar.append((pid, title, price, prod_url))
                        conhecidos.add(pid)
                        if not primeira_vez:
                            alertas.append(
                                f"<b>🔥 NOVO PRODUTO DETECTADO!</b>\n\n"
                                f"<b>Nome:</b> {title}\n"
                                f"<b>Coleção:</b> {colecao.upper()}\n"
                                f"<b>Preço:</b> ${price}\n"
                                f"<b>Link:</b> {prod_url}"
                            )
            
            if novos_salvar:
                save_products(novos_salvar)
                print(f"[INFO] {len(novos_salvar)} novos produtos adicionados.")
                
            if alertas:
                for alerta in alertas:
                    send_telegram(alerta)
                    print(f"[INFO] Alerta enviado: {alerta.replace('\n', ' ')}")
            else:
                if not primeira_vez:
                    print("[INFO] Nenhum produto novo nas coleções.")
            
            if primeira_vez:
                primeira_vez = False
                print("[INFO] Inicialização concluída. Monitorando...")
                
        except Exception as e:
            print(f"[ERRO] Ocorreu uma falha geral no ciclo: {e}")
            
        time.sleep(INTERVALO)

# Servidor HTTP simples para Health Check do Railway
class HealthCheckHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        # Silenciar logs do Health Check para não poluir console
        return

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"[INFO] Servidor health check rodando na porta {port}")
    server.serve_forever()

if __name__ == "__main__":
    # Inicia health check em thread separada
    server_thread = threading.Thread(target=run_health_check_server, daemon=True)
    server_thread.start()
    
    # Inicia loop de monitoramento principal
    monitor()
