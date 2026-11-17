import csv
import os
import requests
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
IN_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "telefones_para_validar_evolution.csv")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "telefones_validados_evolution.csv")

# Preencha com os dados do seu Evolution Manager ou via variaveis de ambiente:
EVOLUTION_URL = os.getenv("EVOLUTION_URL", "http://localhost:8080").rstrip("/")
EVOLUTION_APIKEY = os.getenv("EVOLUTION_APIKEY", "SUA_API_KEY_AQUI")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "SUA_INSTANCIA_AQUI")


def main():
    if EVOLUTION_APIKEY == "SUA_API_KEY_AQUI" or EVOLUTION_INSTANCE == "SUA_INSTANCIA_AQUI":
        print("Configure EVOLUTION_URL, EVOLUTION_APIKEY e EVOLUTION_INSTANCE antes de rodar.")
        return

    with open(IN_CSV, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    numbers = [r["whatsapp_jids_input"] for r in rows]
    endpoint = f"{EVOLUTION_URL}/chat/whatsappNumbers/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_APIKEY, "Content-Type": "application/json"}

    validated = []
    batch_size = 50
    for i in range(0, len(numbers), batch_size):
        batch = numbers[i:i + batch_size]
        resp = requests.post(endpoint, json={"numbers": batch}, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"Erro HTTP {resp.status_code}: {resp.text[:200]}")
            break
        for item in resp.json():
            validated.append({
                "numero_enviado": item.get("number") or "",
                "existe_whatsapp": item.get("exists", False),
                "jid": item.get("jid") or "",
            })

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["numero_enviado", "existe_whatsapp", "jid"])
        w.writeheader()
        w.writerows(validated)

    ativos = sum(1 for x in validated if x["existe_whatsapp"])
    print(f"Validados {len(validated)} numeros | Com WhatsApp ativo: {ativos}")


if __name__ == "__main__":
    main()
