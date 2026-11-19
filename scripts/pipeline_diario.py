import argparse
import os
import subprocess
import sys
from datetime import datetime

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
SCRIPTS = os.path.join(BASE_DIR, "scripts")


def run_step(script_name: str):
    path = os.path.join(SCRIPTS, script_name)
    print(f"\n>>> Executando {script_name}...")
    subprocess.run([sys.executable, path], check=True)


def git_publish():
    print("\n>>> Publicando atualizacao do Dashboard no GitHub/Render...")
    subprocess.run(["git", "-C", BASE_DIR, "add", "Dashboard/wins_engenharia_validacao.html", "Dashboard/data/wins_data.js", "README_PROJETO.md"], check=True)
    status = subprocess.run(["git", "-C", BASE_DIR, "status", "--porcelain"], capture_output=True, text=True, check=True)
    if not status.stdout.strip():
        print("Nenhuma mudanca pendente para commit.")
        return
    msg = f"chore(pipeline): atualizacao diaria automatica ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    subprocess.run(["git", "-C", BASE_DIR, "commit", "-m", msg], check=True)
    subprocess.run(["git", "-C", BASE_DIR, "push", "origin", "main"], check=True)
    print("Push para origin/main concluido.")


def main():
    parser = argparse.ArgumentParser(description="Orquestrador Diario Incremental WiNS Engenharia")
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Pula coleta nas fontes externas e roda apenas higiene, scoring, alertas de fase, dashboard e Excel",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Inclui coleta das fontes oficiais (ANEEL/BNDES/PNCP) e higiene completa de telefones/LinkedIn",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Faz git commit e git push do Dashboard atualizado para acionar deploy no Render",
    )
    args = parser.parse_args()

    if not args.skip_api:
        # 1. Fontes oficiais incrementais (BNDES, ANEEL SIGA, ANEEL Transmissao SIGET, PNCP, ObrasGov, Recife)
        run_step("coletar_oficiais_incremental.py")
        run_step("coletar_aneel_siget_transmissao.py")
        # 2. Portais e fontes preditivas incrementais (preservam decisores e obras existentes)
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

    # 3. Higiene e recuperacao incremental de QSA/emails/canais
    run_step("enriquecer_qsa_novas_obras.py")
    run_step("mapear_dominios_verificados.py")
    if args.full:
        run_step("higienizar_linkedin_banco.py")
        run_step("normalizar_telefones_libphonenumber.py")

    # 4. Sincronizacao final (dedup + fase_obra + score_prioridade + alertas_mudanca_fase + Dashboard + Excel)
    run_step("limpar_duplicidades_cnc.py")

    if args.publish:
        git_publish()

    print("\nPipeline Diario WiNS Engenharia concluido com sucesso!")


if __name__ == "__main__":
    main()
