import os
import requests
from datetime import datetime

from app.auth import get_headers
from app.config import (
    TIPO_JUST,
    TIPO_DESEN,
    RESULTADO,
    OPCAO_RES,
)

# ===========================================================
# API ENDPOINTS (loaded from .env)
# ===========================================================

URL_GET_MONITOR     = os.getenv("URL_GET_MONITOR")
URL_GET_NIVEL2      = os.getenv("URL_GET_NIVEL2")
URL_VALIDAR_FLUXO   = os.getenv("URL_VALIDAR_FLUXO")
URL_JUSTIFICAR      = os.getenv("URL_JUSTIFICAR")


# ===========================================================
# POST helper
# Centralized helper for POST requests with JSON payload
# ===========================================================

def post_json(url, body):
    """
    Sends a POST request with JSON body and default headers.
    Raises HTTP errors and always returns a dict.
    """
    r = requests.post(
        url,
        headers=get_headers(),
        json=body,
        timeout=40
    )
    r.raise_for_status()
    return r.json() if r.text.strip() else {}


# ===========================================================
# GET MONITOR
# Retrieves non-justified and non-compliant positions
# ===========================================================

def get_monitor():
    """
    Calls Monitor/get-monitor endpoint.

    Important parameters:
    - tipoFundo = 2  -> Liquids funds
    - tipoPosicao = 1
    - justificado = 1 -> Only NOT justified
    - enquadrado = 1  -> Only NOT compliant
    """
    body = {
        "cges": None,
        "idRegraList": None,
        "idGrupoList": None,
        "tipoFundo": 2,          # 2 FOR LIQUID FUNDS
        "tipoPosicao": 1,
        "justificado": 1,        # 1 = NOT justified, 0 = all
        "enquadrado": 1,         # 1 = NOT compliant, 0 = all
        "data": None,
        "porExecucao": True,
        "possuiDataPosicao": False,
        "idSistema": 1,
        "condominio": 3,
        "exclusividade": 3,
    }
    return post_json(URL_GET_MONITOR, body)


# ===========================================================
# GET LEVEL 2 DETAILS
# Retrieves detailed rule-level information for a CGE
# ===========================================================

def get_nivel2(cge, data_pos):
    """
    Calls Monitor/get-nivel2 for a specific CGE and position date.
    """
    body = {
        "cgePortfolio": cge,
        "idRegraList": None,
        "idGrupoList": None,
        "tipoFundo": 2,
        "tipoPosicao": 1,
        "exibirTodasRegras": False,
        "justificado": 1,
        "enquadrado": 1,
        "data": data_pos,
        "idSistema": 1,
    }
    return post_json(URL_GET_NIVEL2, body)


# ===========================================================
# GET PREVIOUS JUSTIFICATION (DM-1)
# Tries to reuse previous justification text and action plan
# ===========================================================

def get_justificativa_anterior(cge, data_pos, id_regra, explodida):
    """
    Returns:
        (dsJustificativa, planoAcao, idTipoJustificativa, idTipoDesenquadramento)

    Priority:
    1. DM-1 justification
    2. Delayed justification (fallback)
    """
    body = {
        "identificador": cge,
        "dataPosicao": data_pos,
        "tipoCalculo": "F",
        "regras": [
            {
                "idRegra": id_regra,
                "explodida": explodida
            }
        ],
    }

    try:
        r = requests.post(
            URL_VALIDAR_FLUXO,
            headers=get_headers(),
            json=body,
            timeout=40,
        )
        r.raise_for_status()
        data = r.json()

        prev = data.get("regrasJustificadasDMenos1", [])
        if prev:
            p = prev[0]
            return (
                p.get("dsJustificativa", ""),
                p.get("planoAcao", ""),
                p.get("idTipoJustificativa"),
                p.get("idTipoDesenquadramento"),
            )

        # Fallback: delayed justification
        return data.get("justificativaAtrasada", ""), "", None, None

    except Exception:
        return "", "", None, None


# ===========================================================
# JUSTIFY RULE
# Sends the final justification to the system
# ===========================================================

def justificar(guid, cge, data_pos, f, desc_ant, plano_acao_ant, usuario):
    """
    Sends justification payload using:
    - Previous justification text
    - Previous action plan
    - Fixed justification types from config
    """
    body = {
        "guidMensagem": guid,
        "identificador": cge,
        "tipoMonitor": "E",
        "dataPosicao": data_pos,
        "usuarioJustificativa": usuario,
        "regras": [
            {
                "idRegra": f["idRegra"],
                "nomeRegra": f.get("nomeRegra", ""),
                "explodida": bool(f.get("explodida")),
                "idTipoDesenquadramento": TIPO_DESEN,
                "idTipoJustificativa": TIPO_JUST,
                "dsJustificativa": desc_ant,
                "planoAcao": plano_acao_ant,
                "dtPrazoPlano": datetime.now().strftime("%Y-%m-%d"),
                "opcaoResultado": OPCAO_RES,
                "resultado": RESULTADO,
            }
        ],
    }

    r = requests.post(
        URL_JUSTIFICAR,
        headers=get_headers(),
        json=body,
        timeout=40,
    )
    return r.status_code, r.text[:300]
