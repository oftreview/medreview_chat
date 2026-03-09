"""
=============================================================
BOTMAKER CONVERSATION EXTRACTOR
=============================================================
Script para extrair em massa todas as conversas da plataforma
Botmaker via API v2.0.

USO:
  1. Preencha suas credenciais no arquivo .env ou diretamente abaixo
  2. Acesse https://go.botmaker.com/apidocs/ e confirme os endpoints
  3. Rode: python botmaker_extractor.py

SAÍDA:
  - conversas_botmaker/conversas_completas.json  (todas as conversas)
  - conversas_botmaker/por_cliente/              (1 arquivo por cliente)
  - conversas_botmaker/resumo_extracao.json      (estatísticas)
=============================================================
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ============================================================
# CONFIGURAÇÃO - PREENCHA AQUI
# ============================================================

CONFIG = {
    # --- CREDENCIAIS ---
    # Pegue em: Botmaker > Configurações > API Botmaker > Credenciais
    "ACCESS_TOKEN": os.getenv("BOTMAKER_ACCESS_TOKEN", "SEU_TOKEN_AQUI"),

    # --- URL BASE DA API ---
    # Normalmente é essa. Confirme na documentação Swagger.
    "API_BASE_URL": "https://api.botmaker.com/v2.0",

    # --- ENDPOINTS ---
    # IMPORTANTE: Acesse https://go.botmaker.com/apidocs/ e confirme
    # os nomes exatos dos endpoints na sua conta. Os nomes abaixo
    # são os mais comuns, mas podem variar.
    "ENDPOINTS": {
        "customers": "/customers",          # Lista de clientes/contatos
        "messages": "/messages",            # Mensagens por conversa
        "conversations": "/conversations",  # Conversas (alternativo)
    },

    # --- FILTROS ---
    # Período de extração (None = sem limite)
    "DATA_INICIO": None,       # Ex: "2024-01-01T00:00:00.000Z"
    "DATA_FIM": None,          # Ex: "2026-03-09T23:59:59.000Z"

    # --- CONTROLE DE RATE LIMIT ---
    "DELAY_ENTRE_REQUESTS": 0.5,   # Segundos entre cada chamada
    "DELAY_ENTRE_CLIENTES": 1.0,   # Segundos entre cada cliente
    "MAX_RETRIES": 3,              # Tentativas em caso de erro
    "PAGE_SIZE": 100,              # Itens por página

    # --- SAÍDA ---
    "OUTPUT_DIR": "botmaker_pipeline/conversas_botmaker",
}

# ============================================================
# SETUP DE LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("botmaker_extracao.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# CLASSE PRINCIPAL
# ============================================================

class BotmakerExtractor:
    """Extrai conversas em massa da API Botmaker v2.0."""

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config["API_BASE_URL"].rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "access-token": config["ACCESS_TOKEN"],
            "Content-Type": "application/json",
        })
        self.output_dir = Path(config["OUTPUT_DIR"])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "por_cliente").mkdir(exist_ok=True)

        # Estatísticas
        self.stats = {
            "total_clientes": 0,
            "total_conversas": 0,
            "total_mensagens": 0,
            "erros": 0,
            "inicio_extracao": datetime.now().isoformat(),
        }

    # ----------------------------------------------------------
    # MÉTODOS DE REQUISIÇÃO
    # ----------------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
    ) -> Optional[dict]:
        """Faz uma requisição à API com retry automático."""
        url = f"{self.base_url}{endpoint}"

        for attempt in range(1, self.config["MAX_RETRIES"] + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    timeout=30,
                )

                if response.status_code == 200:
                    return response.json()

                elif response.status_code == 429:
                    # Rate limit atingido
                    wait_time = int(response.headers.get("Retry-After", 30))
                    logger.warning(
                        f"Rate limit! Aguardando {wait_time}s... "
                        f"(tentativa {attempt}/{self.config['MAX_RETRIES']})"
                    )
                    time.sleep(wait_time)

                elif response.status_code == 401:
                    logger.error("Token inválido ou expirado! Verifique suas credenciais.")
                    return None

                else:
                    logger.warning(
                        f"HTTP {response.status_code} em {endpoint} "
                        f"(tentativa {attempt}/{self.config['MAX_RETRIES']}): "
                        f"{response.text[:200]}"
                    )
                    time.sleep(2 ** attempt)

            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Erro de conexão (tentativa {attempt}/"
                    f"{self.config['MAX_RETRIES']}): {e}"
                )
                time.sleep(2 ** attempt)

        self.stats["erros"] += 1
        logger.error(f"Falha após {self.config['MAX_RETRIES']} tentativas em {endpoint}")
        return None

    def _get(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """Atalho para GET."""
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, data: Optional[dict] = None) -> Optional[dict]:
        """Atalho para POST."""
        return self._request("POST", endpoint, data=data)

    # ----------------------------------------------------------
    # PAGINAÇÃO GENÉRICA
    # ----------------------------------------------------------

    def _paginate(self, endpoint: str, params: Optional[dict] = None) -> list:
        """
        Itera por todas as páginas de um endpoint.

        NOTA: A Botmaker pode usar diferentes estratégias de paginação:
          - offset/limit
          - cursor/nextPageToken
          - page/pageSize

        Ajuste este método conforme a documentação da sua conta.
        """
        all_items = []
        params = params or {}
        params["limit"] = self.config["PAGE_SIZE"]
        offset = 0

        while True:
            params["offset"] = offset
            result = self._get(endpoint, params)

            if not result:
                break

            # Tenta extrair os itens da resposta
            # A chave pode variar: "data", "items", "results", "messages", etc.
            items = (
                result.get("data")
                or result.get("items")
                or result.get("results")
                or result.get("messages")
                or result.get("customers")
                or result.get("conversations")
                or (result if isinstance(result, list) else [])
            )

            if not items:
                break

            all_items.extend(items)
            logger.info(f"  ... {len(all_items)} itens coletados de {endpoint}")

            # Verifica se tem mais páginas
            # Opção 1: nextPageToken / cursor
            next_token = result.get("nextPageToken") or result.get("cursor")
            if next_token:
                params["pageToken"] = next_token
                params.pop("offset", None)
            # Opção 2: offset
            elif len(items) >= self.config["PAGE_SIZE"]:
                offset += self.config["PAGE_SIZE"]
            else:
                break  # Última página

            time.sleep(self.config["DELAY_ENTRE_REQUESTS"])

        return all_items

    # ----------------------------------------------------------
    # EXTRAÇÃO
    # ----------------------------------------------------------

    def extrair_clientes(self) -> list:
        """Busca todos os clientes/contatos."""
        logger.info("=" * 60)
        logger.info("ETAPA 1: Extraindo lista de clientes...")
        logger.info("=" * 60)

        endpoint = self.config["ENDPOINTS"]["customers"]
        params = {}

        if self.config["DATA_INICIO"]:
            params["fromDate"] = self.config["DATA_INICIO"]
        if self.config["DATA_FIM"]:
            params["toDate"] = self.config["DATA_FIM"]

        clientes = self._paginate(endpoint, params)
        self.stats["total_clientes"] = len(clientes)
        logger.info(f"Total de clientes encontrados: {len(clientes)}")

        return clientes

    def extrair_mensagens_cliente(self, customer_id: str) -> list:
        """Busca todas as mensagens de um cliente específico."""
        endpoint = self.config["ENDPOINTS"]["messages"]
        params = {"customerId": customer_id}

        if self.config["DATA_INICIO"]:
            params["fromDate"] = self.config["DATA_INICIO"]
        if self.config["DATA_FIM"]:
            params["toDate"] = self.config["DATA_FIM"]

        return self._paginate(endpoint, params)

    def extrair_conversas_direto(self) -> list:
        """
        Alternativa: busca conversas diretamente pelo endpoint
        /conversations (se disponível na sua conta).
        """
        logger.info("Tentando extração direta via /conversations...")
        endpoint = self.config["ENDPOINTS"]["conversations"]
        params = {}

        if self.config["DATA_INICIO"]:
            params["fromDate"] = self.config["DATA_INICIO"]
        if self.config["DATA_FIM"]:
            params["toDate"] = self.config["DATA_FIM"]

        return self._paginate(endpoint, params)

    # ----------------------------------------------------------
    # FLUXO PRINCIPAL
    # ----------------------------------------------------------

    def executar(self):
        """Executa a extração completa."""
        logger.info("=" * 60)
        logger.info("INICIANDO EXTRAÇÃO DE CONVERSAS BOTMAKER")
        logger.info(f"Horário: {datetime.now().isoformat()}")
        logger.info("=" * 60)

        todas_conversas = []

        # ----- ESTRATÉGIA 1: Via endpoint de conversas -----
        try:
            conversas_diretas = self.extrair_conversas_direto()
            if conversas_diretas:
                logger.info(
                    f"Encontradas {len(conversas_diretas)} conversas "
                    f"via endpoint direto!"
                )
                todas_conversas = conversas_diretas
                self.stats["total_conversas"] = len(conversas_diretas)
        except Exception as e:
            logger.info(f"Endpoint /conversations não disponível: {e}")
            logger.info("Usando estratégia alternativa (por cliente)...")

        # ----- ESTRATÉGIA 2: Cliente por cliente -----
        if not todas_conversas:
            clientes = self.extrair_clientes()

            if not clientes:
                logger.error(
                    "Nenhum cliente encontrado! Verifique:\n"
                    "  1. Seu access-token está correto?\n"
                    "  2. O endpoint de customers está correto?\n"
                    "  3. Acesse https://go.botmaker.com/apidocs/ "
                    "e confirme os nomes dos endpoints."
                )
                return

            logger.info("=" * 60)
            logger.info("ETAPA 2: Extraindo mensagens por cliente...")
            logger.info("=" * 60)

            for i, cliente in enumerate(clientes, 1):
                # O ID do cliente pode estar em diferentes campos
                customer_id = (
                    cliente.get("id")
                    or cliente.get("customerId")
                    or cliente.get("_id")
                    or cliente.get("chatPlatformContactId")
                    or ""
                )
                customer_name = (
                    cliente.get("name")
                    or cliente.get("firstName", "")
                    or cliente.get("displayName", "")
                    or "Sem nome"
                )

                if not customer_id:
                    logger.warning(f"Cliente sem ID, pulando: {cliente}")
                    continue

                logger.info(
                    f"[{i}/{len(clientes)}] Extraindo mensagens de: "
                    f"{customer_name} ({customer_id})"
                )

                mensagens = self.extrair_mensagens_cliente(customer_id)

                if mensagens:
                    conversa = {
                        "customer_id": customer_id,
                        "customer_name": customer_name,
                        "customer_data": cliente,
                        "mensagens": mensagens,
                        "total_mensagens": len(mensagens),
                        "extraido_em": datetime.now().isoformat(),
                    }
                    todas_conversas.append(conversa)
                    self.stats["total_mensagens"] += len(mensagens)
                    self.stats["total_conversas"] += 1

                    # Salva arquivo individual do cliente
                    safe_name = "".join(
                        c if c.isalnum() or c in "-_" else "_"
                        for c in customer_id
                    )
                    filepath = self.output_dir / "por_cliente" / f"{safe_name}.json"
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(conversa, f, ensure_ascii=False, indent=2)

                time.sleep(self.config["DELAY_ENTRE_CLIENTES"])

        # ----- SALVAR RESULTADOS -----
        logger.info("=" * 60)
        logger.info("ETAPA 3: Salvando resultados...")
        logger.info("=" * 60)

        # Arquivo principal com todas as conversas
        output_path = self.output_dir / "conversas_completas.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(todas_conversas, f, ensure_ascii=False, indent=2)
        logger.info(f"Conversas salvas em: {output_path}")

        # Estatísticas
        self.stats["fim_extracao"] = datetime.now().isoformat()
        stats_path = self.output_dir / "resumo_extracao.json"
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, ensure_ascii=False, indent=2)

        # Resumo final
        logger.info("=" * 60)
        logger.info("EXTRAÇÃO CONCLUÍDA!")
        logger.info(f"  Clientes processados: {self.stats['total_clientes']}")
        logger.info(f"  Conversas extraídas:  {self.stats['total_conversas']}")
        logger.info(f"  Mensagens totais:     {self.stats['total_mensagens']}")
        logger.info(f"  Erros:                {self.stats['erros']}")
        logger.info(f"  Arquivos salvos em:   {self.output_dir}/")
        logger.info("=" * 60)

        return todas_conversas


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    # Validação básica
    if CONFIG["ACCESS_TOKEN"] == "SEU_TOKEN_AQUI":
        print("\n" + "=" * 60)
        print("ATENÇÃO: Configure seu token antes de rodar!")
        print()
        print("PASSOS:")
        print("  1. Acesse https://go.botmaker.com/#/api")
        print("  2. Vá em Configurações > API Botmaker > Credenciais")
        print("  3. Copie seu access-token")
        print("  4. Cole na variável ACCESS_TOKEN no topo deste arquivo")
        print("     OU defina a variável de ambiente BOTMAKER_ACCESS_TOKEN")
        print()
        print("IMPORTANTE:")
        print("  Acesse https://go.botmaker.com/apidocs/ e confirme")
        print("  os nomes exatos dos endpoints antes de rodar.")
        print("=" * 60 + "\n")
    else:
        extractor = BotmakerExtractor(CONFIG)
        extractor.executar()
