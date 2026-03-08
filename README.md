# Criatons — Agente de Vendas IA

Agente conversacional de vendas para a vertical R1 (residência médica) da MedReview, powered by Claude.

## Stack

- **Python 3.14** + Flask
- **Anthropic Claude** (Sonnet 4) via API
- Frontend: HTML/CSS/JS vanilla

## Setup rápido

```bash
# 1. Clone e entre no projeto
git clone <repo-url> && cd criatons

# 2. Crie o ambiente virtual
python -m venv .venv
source .venv/bin/activate

# 3. Instale dependências
pip install -r requirements.txt

# 4. Configure a API key
cp .env.example .env
# Edite .env e coloque sua ANTHROPIC_API_KEY

# 5. Rode
python sandbox/app.py
```

Acesse `http://localhost:5000` no navegador.

## Estrutura

```
agents/sales/       → Lógica do agente + system prompt
core/               → Config, cliente LLM, memória de conversa
data/               → Ofertas, produtos, regras comerciais (JSON)
sandbox/            → Servidor Flask + UI de chat
```

## Endpoints

| Método | Rota       | Descrição                  |
|--------|------------|----------------------------|
| GET    | `/`        | Interface de chat           |
| POST   | `/chat`    | Envia mensagem ao agente    |
| POST   | `/reset`   | Reinicia conversa           |
| GET    | `/history` | Retorna histórico completo  |

## Configuração

Variáveis em `core/config.py`:

- `CLAUDE_MODEL` — modelo do Claude (default: claude-sonnet-4)
- `MAX_TOKENS` — limite de tokens por resposta (default: 400)
- `PORT` — porta do servidor (default: 5000)

Dados de negócio em `data/`:

- `offers.json` — planos e preços
- `product_info.json` — descrições e FAQ
- `commercial_rules.json` — regras de desconto e escalação
