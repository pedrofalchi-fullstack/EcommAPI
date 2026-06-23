<div align="center">

# 🛒 EcommAPI — Gestão de estoque 24/7 e Automação de E-commerce com Aprovação Humana

**Plataforma Python de automação para e-commerce** — sincroniza estoque entre o fornecedor e o ERP **Bling** em tempo real, propõe alterações de preço via **IA (Claude / Gemini)** sob revisão humana, e foi projetada para escalar até a automação completa de pedidos.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-4695EB?style=flat-square)](https://modelcontextprotocol.io/)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude-D97757?style=flat-square)](https://www.anthropic.com/)
[![Google](https://img.shields.io/badge/Google-Gemini-4285F4?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev/)
[![Bling](https://img.shields.io/badge/Bling-API%20v3-FFA500?style=flat-square)](https://developer.bling.com.br/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## 📑 Sumário

- [Sobre o Projeto](#-sobre-o-projeto)
- [Por que esse projeto existe](#-por-que-esse-projeto-existe)
- [Arquitetura](#-arquitetura)
- [Stack Tecnológica](#-stack-tecnológica)
- [Pontos Altos do Projeto](#-pontos-altos-do-projeto)
- [Fases do Projeto](#-fases-do-projeto)
- [Como Funciona — O Padrão Propor-Aprovar-Aplicar](#-como-funciona--o-padrão-propor-aprovar-aplicar)
- [Estrutura de Arquivos](#-estrutura-de-arquivos)
- [Segurança & Boas Práticas](#-segurança--boas-práticas)
- [Variáveis de Ambiente](#-variáveis-de-ambiente)
- [Como Rodar Localmente](#-como-rodar-localmente)
- [Conectando ao Claude](#-conectando-ao-claude)
- [Roadmap](#-roadmap)
- [Autor](#-autor)
- [Licença](#-licença)

---

## 🎯 Sobre o Projeto

**EcommAPI** é uma plataforma de automação de operações de e-commerce que conecta três sistemas que normalmente vivem isolados:

- A **API do fornecedor** (origem do catálogo e do estoque real)
- O **ERP Bling** (sistema de gestão central e fonte para o e-commerce)
- Uma **camada de IA** (Claude e Gemini, intercambiáveis) que analisa vendas e propõe otimizações

O sistema é construído sobre uma filosofia central: **a IA propõe, o humano aprova, e só então a mudança é aplicada**. Nada de _auto-pilot_ irresponsável — toda alteração de preço, descrição ou estoque passa por uma camada explícita de aprovação humana antes de tocar o Bling.

---

## 💡 Por que esse projeto existe

A motivação é concreta e mensurável: **substituir uma integração paga de terceiros** que conectava a API do fornecedor ao Bling de forma limitada, custosa e sem visibilidade.

Construir a própria integração trouxe três ganhos:

| Benefício | Impacto |
|---|---|
| 💰 **Economia direta** | Eliminação do custo mensal recorrente do serviço externo |
| 🔧 **Controle total** | Lógica de sincronização ajustada à realidade do negócio, sem caixa-preta |
| 🤖 **Extensibilidade com IA** | Camada de inteligência para análise de vendas e sugestões de preço — impossível com a ferramenta paga |

---

## 🏛 Arquitetura

```mermaid
flowchart LR
    Supplier[("🏭 API do<br/>Fornecedor")] -->|estoque / preço| Sync["⚙️ sync_worker.py<br/>(loop 24/7)"]
    Sync -->|diff incremental| State[("🗄️ SQLite<br/>state.db")]
    Sync -->|2 req/s + backoff| Bling[("🛒 Bling ERP<br/>(API v3)")]

    User([👤 Operador]) <-->|conversa| Claude["🧠 Claude / Gemini<br/>(brain.py)"]
    Claude -->|MCP tools| Server["🔌 server.py<br/>(MCP Server)"]
    Server -->|propostas| Pending[("📋 pending_<br/>changes.json")]
    User -->|aprovação| Pending
    Pending -->|aplicar| Bling

    Bling -->|webhook (Fase 3)| Future["🚀 fulfillment<br/>(futuro)"]
```

**Princípios de arquitetura:**

| Princípio | Implementação |
|---|---|
| **Human-in-the-loop** | Toda mudança passa por aprovação humana antes de ser aplicada |
| **Separação leitura/escrita** | Ferramentas de análise são livres; só uma ferramenta escreve no Bling |
| **Respeito a rate limits** | 2 req/s contra o Bling com _exponential backoff_ em erros 429/5xx |
| **Diff incremental** | SQLite local armazena estado; só itens que mudaram são enviados |
| **AI provider-agnostic** | `LLMProvider` abstrai Claude e Gemini — troca-se um pelo outro sem mexer no resto |
| **Audit trail completo** | Toda alteração aplicada fica registrada em `applied_log.jsonl` |

---

## 🛠 Stack Tecnológica

| Camada | Tecnologia | Uso |
|---|---|---|
| **Linguagem** | Python 3.11+ | Toda a base do projeto |
| **IA** | Anthropic Claude (SDK `anthropic`) | Provedor de LLM padrão |
| **IA** | Google Gemini (SDK `google-genai`) | Provedor de LLM alternativo (intercambiável) |
| **Protocolo** | MCP — Model Context Protocol | Conecta a IA ao Bling via ferramentas padronizadas |
| **ERP** | Bling API v3 | Sistema central (produtos, estoque, vendas, preços) |
| **Persistência** | SQLite | Estado local para diff incremental do sync |
| **Auth** | OAuth 2.0 | Autorização do Bling com refresh automático de token |
| **HTTP** | `requests` | Cliente HTTP com retry e backoff |
| **Config** | `python-dotenv` | Variáveis de ambiente |

---

## ⭐ Pontos Altos do Projeto

### 🛡 Padrão Propor → Aprovar → Aplicar
A IA **nunca** altera dados diretamente. Toda sugestão entra numa fila explícita (`pending_changes.json`) e só é aplicada quando o operador aprova por ID. É um _design pattern_ de segurança que evita o pesadelo clássico de "IA mudou o preço de mil produtos sozinha".

### 🔄 AI Provider-Agnostic
A camada `brain.py` define uma interface `LLMProvider` que abstrai Claude e Gemini. Trocar de provedor é uma linha de configuração — não uma refatoração. Isso protege o projeto de _vendor lock-in_ e permite escolher o melhor modelo para cada tipo de tarefa.

### ⚙️ Rate Limiting com Exponential Backoff
A API do Bling tem limites estritos (3 req/s, 120k/dia). O `sync_worker.py` opera deliberadamente abaixo do limite (2 req/s) e implementa _backoff_ exponencial em erros 429 e 5xx — uma demonstração de respeito a constraints externas e de robustez operacional.

### 📊 Diff Incremental Contra SQLite
Em vez de empurrar o catálogo inteiro do fornecedor para o Bling a cada ciclo, o worker mantém o estado anterior em SQLite e envia **apenas o que mudou**. Resultado: ordens de magnitude a menos de requisições, e respeito automático ao rate limit.

### 🔒 Trava de Variação Máxima
Mesmo com aprovação humana, uma trava de segurança (`MAX_VARIACAO_PCT`) impede mudanças bruscas de preço. Se a proposta exceder o limite configurado, ela é bloqueada antes mesmo de chegar na fila — proteção contra erros de digitação e respostas anômalas da IA.

---

## 🚦 Fases do Projeto

O projeto é organizado em três fases evolutivas, cada uma agregando capacidades à anterior.

### ✅ Fase 1 — Sincronização de Estoque _(em produção)_
Worker 24/7 que mantém o estoque do Bling em paridade com o catálogo do fornecedor. Operações de estoque seguem o modelo v3 do Bling (`POST /estoques` com tipo `B` para saldo absoluto), com matching por campo `codigo` (SKU).

### 🔧 Fase 2 — Aprovação de Preços e Métricas via MCP _(código completo)_
Servidor MCP (`server.py`) que expõe ao Claude (ou outro cliente MCP) ferramentas de análise e proposta:

- **Análise** (livre): `listar_produtos`, `analisar_vendas`, `produtos_sem_giro`
- **Proposta** (registra, não aplica): `propor_alteracao_preco`, `propor_alteracao_descricao`
- **Revisão** (somente leitura): `listar_alteracoes_pendentes`, `cancelar_proposta`
- **Aplicação** (a única que escreve): `aplicar_alteracoes_aprovadas`

Alterações de preço vindas do fornecedor também caem nessa fila — nada é aplicado automaticamente.

### 📋 Fase 3 — Fulfillment Automatizado via Webhooks _(planejado)_
Recebimento de eventos de pedido do Bling via webhook e criação automática do pedido na API do fornecedor. Requer:

- Endpoint público HTTPS (FastAPI)
- Idempotência por ID do evento (proteção contra retries duplicados)
- Fila inicial de aprovação manual antes de habilitar automação completa
- API do fornecedor com endpoint de criação de pedido

### 🌐 Integração Futura — Mercado Livre
O `brain.py` já é arquiteturalmente preparado para gerar sugestões de listings do Mercado Livre via API pública de _sellers_, mantendo o mesmo padrão de aprovação humana antes de aplicar qualquer mudança em anúncios.

---

## 🔄 Como Funciona — O Padrão Propor-Aprovar-Aplicar

```
1. Claude analisa vendas    ─►  propor_alteracao_preco  ─►  [proposta fica pendente]
                                                                      │
                                                                      ▼
2. Você revisa o diff       ◄────────────────────────────  pending_changes.json
                            │
                            ▼
3. Aplicar IDs aprovados    ─►  aplicar_alteracoes_aprovadas  ─►  escreve no Bling
                                                                      │
                                                                      ▼
                                                              applied_log.jsonl
```

**Exemplo de uso conversacional:**

> _"Liste as vendas dos últimos 30 dias, identifique os 5 produtos com menor giro e proponha um desconto de 10% em cada um."_

O Claude chama as ferramentas de análise, raciocina sobre os dados, e cria propostas — **sem tocar no Bling**. Você revisa:

> _"Aplique apenas as propostas abc123 e def456."_

Só então os dois preços específicos são alterados no ERP.

---

## 📂 Estrutura de Arquivos

```
EcommAPI/
├── sync_worker.py           # Worker 24/7 de sincronização de estoque (Fase 1)
├── server.py                # Servidor MCP para preços e métricas (Fase 2)
├── brain.py                 # Camada AI provider-agnostic (Claude / Gemini)
├── bling_client.py          # Cliente da API Bling v3 com OAuth + refresh
├── supplier_client.py       # Cliente da API do fornecedor
├── pricing.py               # Lógica de precificação e validações
├── state.py                 # Estado local em SQLite (diff incremental)
├── autorizar.py             # Script de autorização OAuth inicial
├── pricing_rules.example.json   # Template de regras de precificação
├── requirements.txt         # Dependências Python
├── SETUP-sync.md            # Guia detalhado de setup do worker
├── .env.example             # Template de variáveis de ambiente
└── .gitignore               # Proteção contra commits acidentais de segredos
```

---

## 🔒 Segurança & Boas Práticas

A segurança foi tratada como requisito de primeira classe, com múltiplas camadas:

- ✅ **Nenhuma credencial versionada** — `.env` e `bling_tokens.json` no `.gitignore` desde o primeiro commit
- ✅ **Aprovação humana obrigatória** — IA nunca escreve no Bling sem confirmação explícita por ID
- ✅ **Separação leitura/escrita** — apenas uma ferramenta tem permissão de escrita
- ✅ **Trava de variação máxima** — `MAX_VARIACAO_PCT` bloqueia mudanças bruscas mesmo se aprovadas
- ✅ **Audit trail completo** — toda alteração aplicada registrada em `applied_log.jsonl` com antes/depois
- ✅ **OAuth com refresh automático** — tokens nunca expostos no código, renovação transparente
- ✅ **Rate limiting respeitoso** — operação deliberadamente abaixo do limite com _backoff_ exponencial
- ✅ **Modo dry-run** — `SYNC_DRY_RUN=1` permite validar lógica sem tocar dados reais
- ✅ **Homologação primeiro** — `BLING_SANDBOX=1` para testes em ambiente isolado antes da produção

---

## 🔧 Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto a partir do `.env.example`. **Nunca commite valores reais.**

```env
# Bling — Credenciais OAuth
BLING_CLIENT_ID=<seu-client-id>
BLING_CLIENT_SECRET=<seu-client-secret>
BLING_DEPOSITO_ID=<id-do-deposito>

# Bling — Modo de operação
BLING_SANDBOX=1            # 1 = homologação, 0 = produção
MAX_VARIACAO_PCT=30        # Bloqueia variações de preço acima deste percentual
SYNC_DRY_RUN=0             # 1 = simula sem aplicar, 0 = aplica de verdade

# Fornecedor
SUPPLIER_API_URL=<url-da-api-do-fornecedor>
SUPPLIER_API_KEY=<sua-chave>

# Provedores de IA (escolha um ou ambos)
ANTHROPIC_API_KEY=<sua-chave-claude>
GEMINI_API_KEY=<sua-chave-gemini>
```

---

## ▶️ Como Rodar Localmente

**Pré-requisitos:** Python 3.11+ e conta no Bling com app criado.

### 1. Clonar e instalar dependências

```bash
git clone https://github.com/pedrofalchi-fullstack/EcommAPI.git
cd EcommAPI

# Criar e ativar ambiente virtual
python -m venv .venv
.\.venv\Scripts\activate          # Windows
# source .venv/bin/activate        # Linux/Mac

# Instalar dependências
pip install -r requirements.txt
```

### 2. Criar o app no Bling

No painel do Bling: **Preferências → Integrações → API → Criar aplicativo**. Anote o `client_id` e `client_secret`, e defina a _redirect URI_ (ex.: `http://localhost:8080/callback`).

### 3. Configurar variáveis de ambiente

```bash
cp .env.example .env   # e preencha com os valores reais
```

### 4. Autorizar o acesso ao Bling (uma vez só)

```bash
python autorizar.py
```

O script abre o navegador, você autoriza, e o `bling_tokens.json` é gerado automaticamente. O cliente passa a renovar tokens sozinho a partir daí.

### 5. Rodar o worker de sincronização (Fase 1)

```bash
python sync_worker.py
```

### 6. Rodar o servidor MCP (Fase 2)

```bash
mcp dev server.py
```

---

## 🧠 Conectando ao Claude

Com o servidor MCP rodando, é possível conectá-lo ao **Claude Desktop** ou ao **Claude Code**.

### Claude Desktop

Edite o arquivo de configuração de MCP servers e adicione (ajuste o caminho):

```json
{
  "mcpServers": {
    "ecommapi": {
      "command": "python",
      "args": ["C:/caminho/completo/EcommAPI/server.py"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add ecommapi python /caminho/completo/EcommAPI/server.py
```

Depois é só conversar com o Claude pedindo análises e propostas. Ele vai chamar as ferramentas, propor mudanças, e aguardar sua aprovação.

---

## 🔜 Roadmap

- [x] **Fase 1** — Worker de sincronização de estoque 24/7
- [x] **Fase 2** — Servidor MCP com aprovação humana de preços
- [x] Camada AI provider-agnostic (Claude + Gemini intercambiáveis)
- [x] Modo dry-run para validação sem efeitos colaterais
- [x] Audit trail completo de alterações
- [ ] **Fase 3** — Fulfillment automatizado via webhooks do Bling
- [ ] Endpoint público HTTPS (FastAPI) para receber eventos
- [ ] Integração com **Mercado Livre** (API pública de _sellers_)
- [ ] Relatório semanal automático cruzando vendas + giro
- [ ] Trava de margem mínima ao propor alterações de preço

---

## 👤 Autor

Desenvolvido por **Pedro Henrique Falchi**.

[![GitHub](https://img.shields.io/badge/GitHub-pedrofalchi--fullstack-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/pedrofalchi-fullstack)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Pedro%20Falchi-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/pedro-henrique-falchi-4ab4b937b)

---

## 📄 Licença

Este projeto está licenciado sob a **Licença MIT** — consulte o arquivo [`LICENSE`](LICENSE) para mais detalhes.

---

<div align="center">

_Construído com a filosofia de que IA aumenta humanos, não os substitui._ 🤖🤝

</div>
