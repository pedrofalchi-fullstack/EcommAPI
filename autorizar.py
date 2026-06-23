"""
autorizar.py
Faz a autorização OAuth do Bling UMA vez e salva bling_tokens.json.
Roda em Windows/Mac/Linux. Depois disso, o refresh é automático.

Pré-requisitos no .env:
    BLING_CLIENT_ID=...
    BLING_CLIENT_SECRET=...
    BLING_REDIRECT_URI=http://localhost:8080/callback   (igual ao do app no Bling)
"""

import os
import json
import base64
import secrets
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["BLING_CLIENT_ID"]
CLIENT_SECRET = os.environ["BLING_CLIENT_SECRET"]
REDIRECT_URI = os.getenv("BLING_REDIRECT_URI", "http://localhost:8080/callback")

AUTH_URL = "https://www.bling.com.br/Api/v3/oauth/authorize"
TOKEN_URL = "https://api.bling.com.br/Api/v3/oauth/token"

state = secrets.token_urlsafe(8)
url = AUTH_URL + "?" + urlencode({
    "response_type": "code",
    "client_id": CLIENT_ID,
    "state": state,
    "redirect_uri": REDIRECT_URI,
})

print("\n1) Vou abrir o navegador para você autorizar o aplicativo.")
print("   Se não abrir, copie e cole esta URL no navegador:\n")
print("   " + url + "\n")
webbrowser.open(url)

print("2) Após autorizar, o navegador vai tentar abrir uma página que NÃO carrega")
print("   (isso é normal). Copie a URL INTEIRA da barra de endereços e cole aqui.\n")
resposta = input("Cole a URL de redirecionamento (ou só o code): ").strip()

# Aceita tanto a URL inteira quanto só o code.
if "code=" in resposta:
    code = parse_qs(urlparse(resposta).query).get("code", [None])[0]
else:
    code = resposta

if not code:
    raise SystemExit("Não consegui extrair o 'code'. Refaça o processo.")

basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
print("\n=== DEBUG ===")
print("CLIENT_ID:", CLIENT_ID)
print("REDIRECT_URI:", REDIRECT_URI)
print("CODE:", code)
print("TOKEN_URL:", TOKEN_URL)
print("==============\n")
resp = requests.post(
    TOKEN_URL,
    headers={
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    },
    data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    },
    timeout=30,
)

if resp.status_code != 200:
    raise SystemExit(f"Erro ao trocar o code: {resp.status_code}\n{resp.text}")

tokens = resp.json()
with open("bling_tokens.json", "w", encoding="utf-8") as f:
    json.dump(tokens, f, indent=2, ensure_ascii=False)

print("\n✓ Sucesso! bling_tokens.json criado.")
print("  Agora rode: python -c \"import bling_client as b; print(b.get_depositos())\"")
