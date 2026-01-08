# ===========================================================
# main.py
# Automatic justification (Type 1 – Asset) + consolidated email
# ===========================================================

import os
import re
from datetime import datetime
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()

from app.config import (
    TIPO_JUST,
    TIPO_DESEN,
    RESULTADO,
    OPCAO_RES,
    WHITELIST,
)

from app.api import (
    get_monitor,
    get_nivel2,
    get_justificativa_anterior,
    justificar,
)

import requests  # still used ONLY for email sending (to be isolated later)


# ===========================================================
# MAIN FLOW
# ===========================================================

# Step 0 — Retrieve monitor (non-justified & non-compliant)
monitor = get_monitor()

# Step 1 — Collect Level 2 only for CGEs present in whitelist
nivel2_list = []

for m in monitor:
    cge = m["codCgePortfolio"]
    if cge not in WHITELIST:
        continue

    nivel2_list.extend(
        get_nivel2(cge, m["dataPosicao"])
    )

# Flatten whitelist rules
regras_whitelist = {r for rules in WHITELIST.values() for r in rules}

# Filter only whitelisted rules
filtrados = [
    x for x in nivel2_list
    if x["idRegra"] in regras_whitelist
]


# ===========================================================
# STEP 1 — JUSTIFICATION
# ===========================================================

bloqueados_tipo = []
justificados = []

for f in filtrados:
    guid = f["guidMensagem"]

    # Find original monitor entry
    m = next(
        (z for z in monitor if z["guidMensagem"] == guid),
        None
    )
    if not m:
        continue

    cge = m["codCgePortfolio"]
    data_pos = m["dataPosicao"]
    explodida = bool(f.get("explodida"))

    # Retrieve previous (D-1) justification
    (
        desc_ant,
        plano_acao_ant,
        tipo_jus_ant,
        tipo_desen_ant
    ) = get_justificativa_anterior(
        cge,
        data_pos,
        f["idRegra"],
        explodida
    )

    # Skip if same rule appears exploded and non-exploded in same guid
    variantes = {
        x.get("guidMensagemRegra")
        for x in filtrados
        if x.get("guidMensagem") == guid
        and x.get("idRegra") == f.get("idRegra")
    }

    if len(variantes) > 1:
        bloqueados_tipo.append({
            "cge": cge,
            "idRegra": f["idRegra"],
            "reason": "Exploded and non-exploded rule on same day"
        })
        print(f"[SKIP] CGE {cge} | Rule {f['idRegra']} | Mixed explosion")
        continue

    # Skip new cycle (no previous justification)
    if tipo_jus_ant is None and tipo_desen_ant is None:
        bloqueados_tipo.append({
            "cge": cge,
            "idRegra": f["idRegra"],
            "reason": "New cycle after re-compliance"
        })
        print(f"[SKIP] CGE {cge} | Rule {f['idRegra']} | New cycle")
        continue

    # Validate justification / non-compliance type consistency
    try:
        if (
            int(tipo_jus_ant) != TIPO_JUST
            or int(tipo_desen_ant) != TIPO_DESEN
        ):
            bloqueados_tipo.append({
                "cge": cge,
                "idRegra": f["idRegra"],
                "previous_tipo_jus": tipo_jus_ant,
                "previous_tipo_desen": tipo_desen_ant,
                "current_tipo_jus": TIPO_JUST,
                "current_tipo_desen": TIPO_DESEN,
            })
            print(f"[SKIP] CGE {cge} | Rule {f['idRegra']} | Type mismatch")
            continue

    except (TypeError, ValueError):
        bloqueados_tipo.append({
            "cge": cge,
            "idRegra": f["idRegra"],
            "previous_tipo_jus": tipo_jus_ant,
            "previous_tipo_desen": tipo_desen_ant,
            "current_tipo_jus": TIPO_JUST,
            "current_tipo_desen": TIPO_DESEN,
        })
        print(f"[SKIP] CGE {cge} | Rule {f['idRegra']} | Invalid type")
        continue

    # Send justification
    status, ret = justificar(
        guid,
        cge,
        data_pos,
        f,
        desc_ant,
        plano_acao_ant,
        usuario=os.getenv("USUARIO"),
    )

    if status == 200:
        justificados.append(f)

    print(f"[{status}] Justified CGE {cge} | Rule {f['idRegra']}")


# ===========================================================
# STEP 2 — CONSOLIDATED EMAIL (unchanged logic)
# ===========================================================

URL_RECUPERAR_EMAIL = os.getenv("URL_RECUPERAR_EMAIL")
URL_DCK = os.getenv("URL_DCK")

grupos = defaultdict(list)

for f in justificados:
    grupos[f["guidMensagem"]].append(f)

for guid_msg, regras in grupos.items():

    m = next(
        (z for z in monitor if z["guidMensagem"] == guid_msg),
        None
    )
    if not m:
        continue

    cge = m["codCgePortfolio"]
    data_pos = m["dataPosicao"]

    regras_payload = [
        {"idRegra": r["idRegra"], "resultado": RESULTADO}
        for r in regras
    ]

    body_email = {
        "guidMensagem": guid_msg,
        "identificador": cge,
        "tipoMonitor": "E",
        "dataPosicao": data_pos,
        "idTipoJustificativa": TIPO_JUST,
        "idTipoDesenquadramento": TIPO_DESEN,
        "regras": regras_payload,
    }

    # Retrieve email content
    r_email = requests.post(
        URL_RECUPERAR_EMAIL,
        json=body_email,
        timeout=60,
    )
    r_email.raise_for_status()
    email_data = r_email.json()

    # =======================================================
    # TEST EMAIL PAYLOAD (SAFE)
    # =======================================================

    payload = {
        "emailFrom": "***",
        "emailTo": "***",
        "emailCc": "",
        "emailBcc": "",
        "subject": email_data.get("subject", "(no subject)"),
        "body": email_data.get("body", ""),
        "assinatura": {
            "nome": "Enquadramento Team",
            "email": "sh-enquadramento@btgpactual.com",
            "setor": "Risk & Compliance",
            "telefone": "(11) 1234-5678",
        },
        "anexos": [
            {
                "conteudo": a.get("conteudo", ""),
                "nome": a.get("nome", "attachment.xlsx"),
            }
            for a in email_data.get("anexos", [])
            if a.get("conteudo")
        ],
        "nomeSistema": 0,
    }


    # =======================================================
    # OFFICIAL EMAIL PAYLOAD (PRODUCTION)
    # =======================================================
    # payload = {
    #     "emailFrom": "***",
    #     "emailTo": email_data.get("to", ""),
    #     "emailCc": email_data.get("cc", ""),
    #     "emailBcc": email_data.get("bcc", ""),
    #     "subject": email_data.get("subject", ""),
    #     "body": email_data.get("body", ""),
    #     "assinatura": {
    #         "nome": "Enquadramento Team",
    #         "email": "***",
    #         "setor": "Risk & Compliance",
    #         "telefone": "***",
    #     },
    #     "anexos": [
    #         {
    #             "conteudo": a["conteudo"],
    #             "nome": a["nome"],
    #         }
    #         for a in email_data.get("anexos", [])
    #         if a.get("conteudo")
    #     ],
    #     "nomeSistema": 0,
    # }



    # Format decimal percentages inside email body
    def fmt(match):
        v = float(match.group())
        return f"{v * 100:.2f}%"

    payload["body"] = re.sub(
        r"\b0\.\d+\b",
        fmt,
        payload["body"],
    )

    # Send email
    r_send = requests.post(
        URL_DCK,
        json=payload,
        timeout=60,
    )

    print(
        f"[EMAIL {r_send.status_code}] "
        f"CGE {cge} | {len(regras)} rules | guid {guid_msg}"
    )
