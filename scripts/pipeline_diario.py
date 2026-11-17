import argparse
import os
import subprocess
import sys

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
SCRIPTS = os.path.join(BASE_DIR, "scripts")


def run_step(script_name: str):
    path = os.path.join(SCRIPTS, script_name)
    print(f"\n>>> Executando {script_name}...")
    subprocess.run([sys.executable, path], check=True)


def main():
    parser = argparse.ArgumentParser(description="Orquestrador Diario WiNS Engenharia")
    parser.add_argument("--skip-api", action="store_true", help="Pula coleta nas APIs externas e roda apenas consolidacao/otimizacao local")
    args = parser.parse_args()

    if not args.skip_api:
        run_step("captar_todas_fontes_2026_2027.py")
        run_step("resolver_cnpjs_aneel.py")
        run_step("enriquecer_qsa_brasilapi.py")
        run_step("varrer_whatsapp_sites.py")

    if os.path.exists(os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_privadas.csv")) or \
       os.path.exists(os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_publicas.csv")):
        run_step("ingerir_retorno_openbot.py")

    if os.path.exists(os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_lacunas.csv")):
        run_step("ingerir_lacunas_openbot.py")

    run_step("aplicar_otimizacoes_completas.py")
    run_step("gerar_dashboard_html.py")
    print("\nPipeline WiNS Engenharia concluido com sucesso!")


if __name__ == "__main__":
    main()
