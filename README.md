# Bling × Claude — Agente de e-commerce com aprovação humana

Conecta o Claude ao seu Bling (API v3) para **analisar vendas e propor
alterações de preço**, mas com você no controle: o Claude **propõe**, você
**aprova**, e só então a mudança é **aplicada**.

## Como funciona (duas fases)

```
Claude analisa vendas  ─► propor_alteracao_preco ─► [proposta fica pendente]
                                                          │
você revisa o diff ◄──────────────────────────────────────┘
        │
        └─► aplicar_alteracoes_aprovadas(["abc123", ...]) ─► escreve no Bling
```

Nenhuma ferramenta de leitura altera dados. A **única** ferramenta que muda
preço é `aplicar_alteracoes_aprovadas`, e ela só toca nos IDs que você passar.

## 0. Onde colocar os arquivos (VS Code)

O VS Code é só o EDITOR — os arquivos vivem numa pasta no seu disco.
Crie uma pasta para o projeto e jogue os 3 arquivos juntos lá dentro
(precisam estar na MESMA pasta, porque `server.py` faz `import bling_client`):

```
bling-claude/
├── server.py
├── bling_client.py
├── README.md
├── .env                  # você cria (veja passo 4)
├── bling_tokens.json     # criado na autorização inicial (passo 3)
├── pending_changes.json  # criado sozinho ao propor mudanças
└── applied_log.jsonl     # criado sozinho ao aplicar mudanças
```

No VS Code: **File → Open Folder** → escolha a pasta `bling-claude`.
Use o terminal integrado (**Terminal → New Terminal**) para rodar os comandos
abaixo. Dica: crie um ambiente virtual antes (`python3 -m venv .venv` e ative).

## 1. Instalar

```bash
pip install "mcp[cli]" requests python-dotenv
```

## 2. Criar o app no Bling e pegar credenciais

1. No Bling: **Preferências → Integrações → API** → crie um aplicativo.
2. Anote o `client_id` e `client_secret`.
3. Defina uma **redirect URI** (ex.: `http://localhost:8080/callback`).

## 3. Autorização inicial (uma vez só)

Abra no navegador (troque CLIENT_ID e REDIRECT):

```
https://api.bling.com.br/Api/v3/oauth/authorize?response_type=code&client_id=CLIENT_ID&state=teste123&redirect_uri=REDIRECT
```

Autorize. O Bling te devolve um `code` na URL de redirect.
⚠️ Esse `code` expira em ~1 minuto — troque-o por tokens já:

```bash
python3 - <<'PY'
import base64, requests, json, os
CID="SEU_CLIENT_ID"; SEC="SEU_CLIENT_SECRET"; CODE="O_CODE_DA_URL"
b = base64.b64encode(f"{CID}:{SEC}".encode()).decode()
r = requests.post("https://api.bling.com.br/Api/v3/oauth/token",
    headers={"Authorization": f"Basic {b}",
             "Content-Type":"application/x-www-form-urlencoded"},
    data={"grant_type":"authorization_code","code":CODE})
open("bling_tokens.json","w").write(json.dumps(r.json(), indent=2))
print(r.status_code, r.text[:200])
PY
```

Isso cria `bling_tokens.json`. A partir daí o cliente renova o token sozinho.

## 4. Configurar o `.env`

```
BLING_CLIENT_ID=...
BLING_CLIENT_SECRET=...
BLING_SANDBOX=1          # COMECE em homologação! Troque para 0 só quando confiar.
MAX_VARIACAO_PCT=30      # bloqueia variações de preço acima disso
```

## 5. Testar

```bash
mcp dev server.py
```

Peça ao inspector para listar produtos. Se vierem dados, está conectado.

## 6. Conectar ao Claude

No **Claude Desktop**, edite o arquivo de configuração de MCP servers e
adicione (ajuste os caminhos):

```json
{
  "mcpServers": {
    "bling": {
      "command": "python3",
      "args": ["/caminho/completo/server.py"]
    }
  }
}
```

No **Claude Code**, use `claude mcp add` apontando para o mesmo comando.

Depois é só conversar:
> "Liste as vendas dos últimos 30 dias, identifique os 5 produtos com menor
> giro e proponha um desconto de 10% em cada um."

O Claude vai chamar `listar_vendas`, raciocinar, e criar **propostas**.
Você revisa com `listar_alteracoes_pendentes` e aprova as que quiser:
> "Aplique as propostas abc123 e def456."

## Camadas de segurança já embutidas

- **Sandbox primeiro** (`BLING_SANDBOX=1`) — teste sem mexer em dados reais.
- **Duas fases** — propor ≠ aplicar.
- **Trava de variação** — `MAX_VARIACAO_PCT` bloqueia mudanças bruscas.
- **Auditoria** — todo preço aplicado fica em `applied_log.jsonl` (antes/depois).

## Ferramentas disponíveis para o Claude

Leitura/análise (rodam livres): `listar_produtos`, `buscar_produto`,
`listar_vendas`, `analisar_vendas` (campeões + margem), `produtos_sem_giro`
(encalhados com estoque).

Propor (só registram, não aplicam): `propor_alteracao_preco`,
`propor_alteracao_descricao`.

Revisar/aplicar: `listar_alteracoes_pendentes`, `cancelar_proposta`,
`aplicar_alteracoes_aprovadas` (a única que escreve no Bling).

## Próximos passos sugeridos

- Relatório semanal automático cruzando `analisar_vendas` + `produtos_sem_giro`.
- Trava extra: exigir margem mínima ao propor preço (rejeitar se cair abaixo).
- Estender o `precoCusto` para custos compostos, se você usar kits/variações.
