"""
=============================================================
BOTMAKER CONVERSATION ANALYZER
=============================================================
Script para analisar as conversas extraídas e gerar:
  1. Padrões de comportamento do agente de vendas
  2. Objeções mais comuns dos clientes
  3. Respostas mais eficazes
  4. Exemplos formatados para uso em prompts (few-shot)

USO:
  1. Rode primeiro o botmaker_extractor.py
  2. Depois rode: python botmaker_analyzer.py

SAÍDA:
  - analise_conversas/padroes_vendas.json
  - analise_conversas/exemplos_para_prompt.txt   ← direto no prompt
  - analise_conversas/relatorio_padroes.md
=============================================================
"""

import json
import re
from pathlib import Path
from datetime import datetime
from collections import Counter
from typing import Optional

# ============================================================
# CONFIGURAÇÃO
# ============================================================

CONFIG = {
    # Onde estão as conversas extraídas
    "INPUT_FILE": "botmaker_pipeline/conversas_botmaker/conversas_completas.json",

    # Pasta de saída da análise
    "OUTPUT_DIR": "botmaker_pipeline/analise_conversas",

    # Ajuste conforme o campo que identifica quem enviou a mensagem
    # Valores comuns: "bot", "agent", "human", "user", "customer"
    "SENDER_FIELD": "sender",         # Campo que indica o remetente
    "SENDER_BOT_VALUE": "bot",        # Valor quando é o bot falando
    "SENDER_AGENT_VALUE": "agent",    # Valor quando é atendente humano
    "SENDER_CUSTOMER_VALUE": "user",  # Valor quando é o cliente

    # Campo com o texto da mensagem
    "TEXT_FIELD": "text",             # Pode ser "content", "message", "body"

    # Campo com timestamp
    "TIMESTAMP_FIELD": "timestamp",   # Pode ser "createdAt", "date", "time"

    # Máximo de exemplos few-shot para o prompt
    "MAX_EXEMPLOS_PROMPT": 10,

    # Tamanho mínimo de conversa para ser considerado exemplo (nº de mensagens)
    "MIN_MENSAGENS_EXEMPLO": 4,
}

# ============================================================
# PALAVRAS-CHAVE PARA CLASSIFICAÇÃO
# ============================================================

PALAVRAS_COMPRA = [
    "quero comprar", "vou comprar", "fechar", "fechado", "confirmado",
    "pode enviar", "pode mandar", "pagamento", "pix", "boleto", "cartão",
    "pedido", "comprei", "adquirir", "contratar", "assinar", "sim, quero",
    "vamos", "bora", "aceito", "combinado", "ok pode",
]

PALAVRAS_OBJECAO = [
    "caro", "muito caro", "não tenho", "sem dinheiro", "não posso",
    "vou pensar", "deixa eu ver", "depois", "não sei", "talvez",
    "meu marido", "minha esposa", "preciso falar", "não tá no meu orçamento",
    "concorrente", "mais barato", "desconto", "não vejo valor",
    "não preciso", "já tenho", "não me interessa",
]

PALAVRAS_DUVIDA = [
    "como funciona", "o que é", "quanto custa", "qual o preço",
    "tem parcela", "como faço", "prazo", "entrega", "frete",
    "garantia", "devolução", "funciona para", "serve para",
    "diferença", "qual a diferença", "posso", "aceita",
]

# ============================================================
# CLASSE PRINCIPAL
# ============================================================

class BotmakerAnalyzer:

    def __init__(self, config: dict):
        self.config = config
        self.output_dir = Path(config["OUTPUT_DIR"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def carregar_conversas(self) -> list:
        """Carrega o JSON de conversas extraídas."""
        filepath = Path(self.config["INPUT_FILE"])
        if not filepath.exists():
            print(f"Arquivo não encontrado: {filepath}")
            print("Rode primeiro o botmaker_extractor.py")
            return []

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def _get_mensagens(self, conversa: dict) -> list:
        """Extrai a lista de mensagens de uma conversa."""
        return (
            conversa.get("mensagens")
            or conversa.get("messages")
            or conversa.get("items")
            or []
        )

    def _get_texto(self, mensagem: dict) -> str:
        """Extrai o texto de uma mensagem."""
        return str(
            mensagem.get(self.config["TEXT_FIELD"])
            or mensagem.get("text")
            or mensagem.get("content")
            or mensagem.get("message")
            or mensagem.get("body")
            or ""
        ).strip()

    def _get_sender(self, mensagem: dict) -> str:
        """Identifica quem enviou a mensagem."""
        return str(
            mensagem.get(self.config["SENDER_FIELD"])
            or mensagem.get("sender")
            or mensagem.get("from")
            or mensagem.get("role")
            or "desconhecido"
        ).lower()

    def _is_bot(self, sender: str) -> bool:
        return sender in [
            self.config["SENDER_BOT_VALUE"],
            self.config["SENDER_AGENT_VALUE"],
            "bot", "agent", "assistant", "atendente",
        ]

    def _classificar_conversa(self, mensagens: list) -> dict:
        """Classifica o tipo e resultado de uma conversa."""
        todos_textos = " ".join(
            self._get_texto(m).lower() for m in mensagens
        )

        resultado = "indefinido"
        for palavra in PALAVRAS_COMPRA:
            if palavra in todos_textos:
                resultado = "converteu"
                break

        tipo = "geral"
        if any(p in todos_textos for p in PALAVRAS_DUVIDA):
            tipo = "duvida_produto"
        if any(p in todos_textos for p in PALAVRAS_OBJECAO):
            tipo = "teve_objecao"
        if resultado == "converteu":
            tipo = "venda_concluida"

        objecoes = [
            p for p in PALAVRAS_OBJECAO if p in todos_textos
        ]

        return {
            "resultado": resultado,
            "tipo": tipo,
            "objecoes_detectadas": objecoes,
        }

    # ----------------------------------------------------------
    # ANÁLISE PRINCIPAL
    # ----------------------------------------------------------

    def analisar(self, conversas: list) -> dict:
        """Analisa todas as conversas e extrai padrões."""
        print(f"Analisando {len(conversas)} conversas...")

        padroes = {
            "total_conversas": len(conversas),
            "vendas_concluidas": 0,
            "conversas_com_objecao": 0,
            "objecoes_mais_comuns": [],
            "perguntas_mais_comuns": [],
            "respostas_mais_eficazes": [],
            "exemplos_para_prompt": [],
        }

        todas_objecoes = []
        todas_perguntas = []
        exemplos_venda = []
        exemplos_objecao_contornada = []

        for conversa in conversas:
            mensagens = self._get_mensagens(conversa)
            if not mensagens:
                continue

            classificacao = self._classificar_conversa(mensagens)

            if classificacao["resultado"] == "converteu":
                padroes["vendas_concluidas"] += 1
                exemplos_venda.append({
                    "conversa": conversa,
                    "mensagens": mensagens,
                    "classificacao": classificacao,
                })

            if classificacao["objecoes_detectadas"]:
                padroes["conversas_com_objecao"] += 1
                todas_objecoes.extend(classificacao["objecoes_detectadas"])
                if classificacao["resultado"] == "converteu":
                    exemplos_objecao_contornada.append({
                        "conversa": conversa,
                        "mensagens": mensagens,
                        "objecoes": classificacao["objecoes_detectadas"],
                    })

            # Coleta perguntas dos clientes
            for msg in mensagens:
                texto = self._get_texto(msg)
                sender = self._get_sender(msg)
                if not self._is_bot(sender) and "?" in texto:
                    todas_perguntas.append(texto[:200])

        # Objeções mais comuns
        counter_objecoes = Counter(todas_objecoes)
        padroes["objecoes_mais_comuns"] = [
            {"objecao": ob, "ocorrencias": cnt}
            for ob, cnt in counter_objecoes.most_common(15)
        ]

        # Perguntas mais comuns (simplificado)
        padroes["perguntas_mais_comuns"] = self._agrupar_perguntas(
            todas_perguntas
        )

        # Exemplos para o prompt (conversas de vendas concluídas)
        padroes["exemplos_para_prompt"] = self._preparar_exemplos_prompt(
            exemplos_venda,
            exemplos_objecao_contornada,
        )

        # Taxa de conversão
        if padroes["total_conversas"] > 0:
            taxa = (padroes["vendas_concluidas"] / padroes["total_conversas"]) * 100
            padroes["taxa_conversao_percentual"] = round(taxa, 2)

        return padroes

    def _agrupar_perguntas(self, perguntas: list) -> list:
        """Retorna as perguntas mais frequentes (por similaridade básica)."""
        grupos = {}
        for p in perguntas:
            # Normaliza: lowercase, sem pontuação dupla
            chave = re.sub(r"\s+", " ", p.lower().strip())[:80]
            grupos[chave] = grupos.get(chave, 0) + 1

        ordenadas = sorted(grupos.items(), key=lambda x: x[1], reverse=True)
        return [
            {"pergunta": p, "ocorrencias": c}
            for p, c in ordenadas[:20]
        ]

    def _preparar_exemplos_prompt(
        self,
        exemplos_venda: list,
        exemplos_objecao: list,
    ) -> list:
        """
        Formata conversas reais como exemplos few-shot para usar no prompt
        do agente de vendas.
        """
        exemplos = []
        max_ex = self.config["MAX_EXEMPLOS_PROMPT"]
        min_msgs = self.config["MIN_MENSAGENS_EXEMPLO"]

        # Prioriza conversas com objeção contornada (mais valiosas)
        fontes = exemplos_objecao[:max_ex // 2] + exemplos_venda[:max_ex]

        for item in fontes[:max_ex]:
            mensagens = item["mensagens"]
            if len(mensagens) < min_msgs:
                continue

            dialogo = []
            for msg in mensagens[:20]:  # Limita tamanho
                texto = self._get_texto(msg)
                sender = self._get_sender(msg)
                if not texto:
                    continue

                papel = "Agente" if self._is_bot(sender) else "Cliente"
                dialogo.append(f"{papel}: {texto}")

            if len(dialogo) >= min_msgs:
                exemplos.append({
                    "tipo": item.get("classificacao", {}).get("tipo", "venda"),
                    "objecoes": item.get("objecoes", []),
                    "dialogo": dialogo,
                    "dialogo_texto": "\n".join(dialogo),
                })

        return exemplos

    # ----------------------------------------------------------
    # GERAÇÃO DOS ARQUIVOS DE SAÍDA
    # ----------------------------------------------------------

    def gerar_exemplos_prompt(self, padroes: dict) -> str:
        """
        Gera um arquivo .txt com os exemplos prontos para colar no
        prompt do agente de vendas.
        """
        exemplos = padroes.get("exemplos_para_prompt", [])
        linhas = []
        linhas.append("=" * 70)
        linhas.append("EXEMPLOS REAIS DE CONVERSAS DE VENDA")
        linhas.append("(Cole esses exemplos no prompt do seu agente)")
        linhas.append("=" * 70)
        linhas.append("")

        for i, ex in enumerate(exemplos, 1):
            tipo = ex.get("tipo", "")
            objecoes = ex.get("objecoes", [])

            linhas.append(f"--- EXEMPLO {i} [{tipo.upper()}] ---")
            if objecoes:
                linhas.append(f"(Objeções contornadas: {', '.join(objecoes)})")
            linhas.append("")
            linhas.append(ex["dialogo_texto"])
            linhas.append("")

        if not exemplos:
            linhas.append(
                "Nenhum exemplo gerado ainda.\n"
                "Rode o extrator e certifique-se de que há conversas com venda."
            )

        return "\n".join(linhas)

    def gerar_relatorio_md(self, padroes: dict) -> str:
        """Gera um relatório em Markdown com os padrões encontrados."""
        linhas = []
        linhas.append("# Relatório de Padrões — Conversas Botmaker")
        linhas.append(f"\n_Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}_\n")

        linhas.append("## Resumo Geral\n")
        linhas.append(f"- **Total de conversas analisadas:** {padroes['total_conversas']}")
        linhas.append(f"- **Vendas concluídas:** {padroes['vendas_concluidas']}")
        linhas.append(f"- **Conversas com objeção:** {padroes['conversas_com_objecao']}")
        taxa = padroes.get("taxa_conversao_percentual", 0)
        linhas.append(f"- **Taxa de conversão estimada:** {taxa}%")

        linhas.append("\n## Objeções Mais Comuns\n")
        for item in padroes["objecoes_mais_comuns"]:
            linhas.append(
                f"- **\"{item['objecao']}\"** — {item['ocorrencias']} ocorrências"
            )

        linhas.append("\n## Perguntas Frequentes dos Clientes\n")
        for item in padroes["perguntas_mais_comuns"][:10]:
            linhas.append(
                f"- \"{item['pergunta']}\" ({item['ocorrencias']}x)"
            )

        linhas.append("\n## Exemplos de Conversas Gerados\n")
        n = len(padroes.get("exemplos_para_prompt", []))
        linhas.append(
            f"{n} exemplos foram formatados para uso no prompt do agente. "
            f"Veja o arquivo `exemplos_para_prompt.txt`."
        )

        linhas.append("\n## Como Usar no Prompt do Agente\n")
        linhas.append(
            "Cole os exemplos do arquivo `exemplos_para_prompt.txt` "
            "no seu prompt principal, numa seção como:\n"
        )
        linhas.append("```")
        linhas.append("Abaixo estão exemplos reais de conversas de venda bem-sucedidas.")
        linhas.append("Use esses padrões como referência para suas respostas:\n")
        linhas.append("--- EXEMPLO 1 ---")
        linhas.append("Cliente: [pergunta]")
        linhas.append("Agente: [resposta eficaz]")
        linhas.append("...")
        linhas.append("```")

        return "\n".join(linhas)

    # ----------------------------------------------------------
    # FLUXO PRINCIPAL
    # ----------------------------------------------------------

    def executar(self):
        """Executa a análise completa."""
        conversas = self.carregar_conversas()
        if not conversas:
            return

        padroes = self.analisar(conversas)

        # Salva padrões em JSON
        padroes_path = self.output_dir / "padroes_vendas.json"
        with open(padroes_path, "w", encoding="utf-8") as f:
            json.dump(padroes, f, ensure_ascii=False, indent=2)
        print(f"Padrões salvos em: {padroes_path}")

        # Salva exemplos para o prompt
        exemplos_txt = self.gerar_exemplos_prompt(padroes)
        exemplos_path = self.output_dir / "exemplos_para_prompt.txt"
        with open(exemplos_path, "w", encoding="utf-8") as f:
            f.write(exemplos_txt)
        print(f"Exemplos para prompt salvos em: {exemplos_path}")

        # Salva relatório Markdown
        relatorio_md = self.gerar_relatorio_md(padroes)
        relatorio_path = self.output_dir / "relatorio_padroes.md"
        with open(relatorio_path, "w", encoding="utf-8") as f:
            f.write(relatorio_md)
        print(f"Relatório salvo em: {relatorio_path}")

        # Resumo no terminal
        print("\n" + "=" * 60)
        print("ANÁLISE CONCLUÍDA!")
        print(f"  Total de conversas: {padroes['total_conversas']}")
        print(f"  Vendas concluídas:  {padroes['vendas_concluidas']}")
        print(f"  Taxa de conversão:  {padroes.get('taxa_conversao_percentual', 0)}%")
        print(f"  Exemplos gerados:   {len(padroes.get('exemplos_para_prompt', []))}")
        print(f"\nObjeções mais comuns:")
        for item in padroes["objecoes_mais_comuns"][:5]:
            print(f"  - \"{item['objecao']}\" ({item['ocorrencias']}x)")
        print("=" * 60)


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    analyzer = BotmakerAnalyzer(CONFIG)
    analyzer.executar()
