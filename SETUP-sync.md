# Sincronização Fornecedor → Bling (serviço 24/7)

Worker que lê a API do seu fornecedor e mantém o estoque do Bling em dia,
sozinho, o dia inteiro. Estoque, criação de novos produtos e desativação
de itens sem estoque são automáticos; **preço entra na fila de aprovação**
(você aprova pelo Claude/MCP — ver projeto do `server.py`).

## Arquivos

```
bling-sync/
├── bling_client.py     # API do Bling (rate-limit + retry embutidos)
├── supplier_client.py  # >>> VOCÊ ADAPTA AQUI ao seu fornecedor <<<
├── state.py            # estado local (SQLite) — o diff
├── sync_worker.py      # o worker em si
├── server.py           # (opcional) MCP para aprovar preços via Claude
├── .env
└── bling_tokens.json   # criado na autorização OAuth (ver projeto anterior)
```

## 1. Adaptar ao seu fornecedor

Abra `supplier_client.py` e preencha o método `listar_catalogo()` com as
chamadas reais da API do seu fornecedor, convertendo a resposta para
`ProdutoFornecedor(sku, nome, preco, estoque, gtin, ...)`. É o único arquivo
que muda de fornecedor para fornecedor.

> Para eu te ajudar a preencher essa parte, me mande a documentação da API
> do seu fornecedor (ou um exemplo de resposta JSON e como autentica).

## 2. Descobrir o id do depósito do Bling

Estoque no Bling v3 é movimentação de depósito. Rode uma vez:

```bash
python3 -c "import bling_client as b; print(b.get_depositos())"
```

Pegue o `id` do depósito que você usa e coloque no `.env`.

## 3. Configurar o `.env`

```
# Bling
BLING_CLIENT_ID=...
BLING_CLIENT_SECRET=...
BLING_DEPOSITO_ID=1234561
BLING_SANDBOX=1            # COMECE em homologação
BLING_REQ_POR_SEG=2        # abaixo do teto de 3/s do Bling

# Fornecedor
FORNECEDOR_BASE_URL=https://api.seufornecedor.com
FORNECEDOR_API_KEY=...

# Comportamento do sync
SYNC_INTERVALO_MIN=10           # roda a cada 10 min
SYNC_AUTO_CRIAR=1               # cria produtos novos automaticamente
SYNC_DESATIVAR_SEM_ESTOQUE=1    # inativa quando zera estoque
MAX_VARIACAO_PCT=30             # anotado nas propostas de preço
```

## 4. Testar UM ciclo antes de soltar 24/7

```bash
pip install requests python-dotenv
python sync_worker.py --once
```

Confira o `sync.log`. Com `BLING_SANDBOX=1` nada acontece na sua conta real.
Quando estiver redondo, troque para `BLING_SANDBOX=0`.

## 5. Rodar 24/7

⚠️ Não rode no seu notebook. Use um VPS baratinho (qualquer VM de ~R$25/mês).

### Opção A — systemd (mais simples num VPS Linux)

Crie `/etc/systemd/system/bling-sync.service`:

```ini
[Unit]
Description=Sincronizacao Fornecedor -> Bling
After=network-online.target

[Service]
WorkingDirectory=/opt/bling-sync
ExecStart=/opt/bling-sync/.venv/bin/python sync_worker.py
Restart=always
RestartSec=15
EnvironmentFile=/opt/bling-sync/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bling-sync
journalctl -u bling-sync -f      # acompanhar os logs ao vivo
```

`Restart=always` faz o serviço subir sozinho se cair ou se o VPS reiniciar.

### Opção B — Docker

`Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir requests python-dotenv apscheduler
CMD ["python", "sync_worker.py"]
```

```bash
docker build -t bling-sync .
docker run -d --restart=always --env-file .env -v "$PWD":/app bling-sync
```

## 6. Observabilidade (não pule isto)

- `sync.log` registra cada ciclo e cada erro por SKU.
- `heartbeat.txt` guarda o timestamp do último ciclo OK. Monte um alerta
  externo (ex.: cron + curl pra um bot do Telegram) que te avisa se o
  heartbeat ficar velho — assim você descobre uma falha em minutos, não
  quando vender algo sem estoque.
- No `sync_worker.py` há um `TODO` marcando onde disparar o alerta quando
  os erros de um ciclo passarem de um limite.

## Como o preço se conecta ao Claude

Quando o preço muda no fornecedor, o worker NÃO altera o Bling — ele grava
uma proposta em `pending_changes.json`. Você revisa e aprova conversando com
o Claude (via `server.py`, o MCP do projeto anterior): "liste as alterações
pendentes" → "aplique as propostas X e Y". É a junção dos dois projetos.

## Limites que o código já respeita

- 3 req/s e 120k/dia do Bling → o cliente segura em 2/s e só manda o que mudou.
- Picos (600 req/10s) → throttle global evita encostar.
- 429 / 5xx → retry automático com backoff exponencial.
