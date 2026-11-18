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
    parser = argparse.ArgumentParser(description="Orquestrador Diario Incremental WiNS Engenharia")
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Pula coleta nas fontes externas e roda apenas deduplicacao, classificacao de fases, dashboard e Excel",
    )
    args = parser.parse_args()

    if not args.skip_api:
        # 1. Portais e fontes preditivas incrementais (preservam decisores e obras existentes)
        run_step("coletar_convisao_obras.py")
        run_step("resolver_cnpjs_convisao_rapidfuzz.py")
        run_step("limpar_duplicidades_cnc.py")
        run_step("coletar_cimm_investimentos.py")
        run_step("coletar_ibama_sislic.py")
        run_step("coletar_mg_obras.py")
        run_step("coletar_bvmi_radar.py")

    # 2. Ingestao de retornos OpenBot (se houver novos registros)
    if os.path.exists(os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_convisao_cimm.csv")):
        run_step("ingerir_convisao_cimm_decisores.py")

    # 3. Sincronizacao final (todas_obras_consolidadas + fase_obra + campanha_por_decisor_unico + Dashboard + Excel)
    run_step("limpar_duplicidades_cnc.py")
    print("\nPipeline Diario WiNS Engenharia concluido com sucesso!")


if __name__ == "__main__":
    main()
