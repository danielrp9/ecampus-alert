import os
import json
import time
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

# --- CONFIGURAÇÕES ---
USER = os.getenv("ECAMPUS_USER")
PASS = os.getenv("ECAMPUS_PASS")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

URL_BASE = "https://ecampus.ufvjm.edu.br/"
URL_NOTAS = "https://ecampus.ufvjm.edu.br/index.php?module=ensino&action=main:quadronotasparciais"

def parse_avaliacoes(texto_bruto):
    """Transforma a string bruta em uma lista de dicionários (colunas)."""
    # Regex para capturar linhas que parecem avaliações (Nome Data Peso Aprov Nota)
    padrao = r"(.+?)\s+(\d{2}/\d{2}/\d{4})\s+(\d+[\d,]*%)\s*(\d+[\d,]*%)?\s*(\d+[\d,]*|--)"
    matches = re.findall(padrao, texto_bruto)
    
    avaliacoes = []
    for m in matches:
        avaliacoes.append({
            "nome": m[0].strip(),
            "data": m[1],
            "peso": m[2],
            "aprov": m[3] if m[3] else "--",
            "nota": m[4]
        })
    return avaliacoes

def extrair_resultado_parcial(texto):
    """Busca o valor do Resultado Parcial no texto."""
    match = re.search(r"Resultado Parcial:\s*(\d+[\d,]*|--)", texto)
    return match.group(1) if match else "--"

def enviar_email_html_estruturado(dados_atuais):
    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
    
    estilo = """
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            .materia-card { border: 1px solid #ccc; border-radius: 8px; margin-bottom: 25px; overflow: hidden; }
            .header-materia { background: #2c3e50; color: white; padding: 10px 15px; font-size: 18px; }
            table { width: 100%; border-collapse: collapse; background: white; }
            th { background: #ecf0f1; color: #2c3e50; text-align: left; padding: 8px; border-bottom: 2px solid #bdc3c7; }
            td { padding: 8px; border-bottom: 1px solid #eee; font-size: 13px; }
            .resumo { padding: 10px; background: #fdfdfd; font-weight: bold; border-top: 1px solid #ddd; }
            .sem-nota { padding: 20px; color: #888; text-align: center; }
        </style>
    """

    html_content = f"<html><head>{estilo}</head><body>"
    html_content += f"<h2>Relatório de Verificação de Lançamento de Notas - {agora}</h2>"

    for materia, texto in dados_atuais.items():
        avs = parse_avaliacoes(texto)
        res_parcial = extrair_resultado_parcial(texto)
        
        html_content += f'<div class="materia-card">'
        html_content += f'<div class="header-materia">{materia}</div>'
        
        if avs:
            html_content += """
            <table>
                <thead>
                    <tr>
                        <th>Avaliação</th>
                        <th>Data</th>
                        <th>Peso</th>
                        <th>Aprov.</th>
                        <th>Nota</th>
                    </tr>
                </thead>
                <tbody>
            """
            for a in avs:
                html_content += f"""
                    <tr>
                        <td>{a['nome']}</td>
                        <td>{a['data']}</td>
                        <td>{a['peso']}</td>
                        <td>{a['aprov']}</td>
                        <td style="color: blue; font-weight: bold;">{a['nota']}</td>
                    </tr>
                """
            html_content += "</tbody></table>"
        else:
            html_content += '<div class="sem-nota">Nenhuma avaliação lançada até o momento.</div>'
        
        html_content += f'<div class="resumo">Resultado Parcial Atual: {res_parcial}</div>'
        html_content += "</div>"

    html_content += "</body></html>"

    msg = MIMEMultipart()
    msg["Subject"] = f"🔔 Atualização de Notas no e-Campus - {agora}"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_USER
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        print("✅ E-mail estruturado enviado!")
    except Exception as e:
        print(f"❌ Erro no envio: {e}")

def extrair_notas():
    with sync_playwright() as p:
        # Mantido headless=True para rodar no GitHub
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            print("🚀 Iniciando captura...")
            page.goto(URL_BASE)
            page.fill("#uid", USER)
            page.fill("#pwd", PASS)
            page.keyboard.press("Enter")
            page.wait_for_url("**/index.php?module=**")
            
            page.goto(URL_NOTAS)
            page.wait_for_selector("#fullGrid")
            
            rows = page.locator("#fullGrid tbody tr.row1, #fullGrid tbody tr.row2").all()
            dados = {}

            for i, row in enumerate(rows):
                nome = row.locator("td").nth(5).inner_text().strip()
                row.locator("img[src*='plus.gif']").click()
                
                id_detalhe = f"#detail{i}"
                page.wait_for_selector(id_detalhe)
                time.sleep(1.5)
                
                texto_bruto = page.locator(id_detalhe).inner_text().strip()
                
                # --- CORREÇÃO: Limpeza do timestamp de atualização ---
                # Remove a linha que contém "Atualização detectada em..." para evitar falsos positivos
                texto_sanitizado = re.sub(r"Atualização detectada em.*", "", texto_bruto).strip()
                
                dados[nome] = texto_sanitizado
                print(f"   [Verificado] {nome}")

            browser.close()
            return dados
        except Exception as e:
            print(f"⚠️ Erro: {e}")
            browser.close()
            return None

def monitorar():
    print(f"--- Check: {datetime.now().strftime('%H:%M:%S')} ---")
    dados_atuais = extrair_notas()
    if not dados_atuais: return

    arquivo_db = "notas_anteriores.json"
    if os.path.exists(arquivo_db):
        with open(arquivo_db, "r", encoding="utf-8") as f:
            dados_anteriores = json.load(f)
    else:
        dados_anteriores = {}

    if dados_atuais != dados_anteriores:
        print("📢 Mudança real detectada! Enviando notificação...")
        enviar_email_html_estruturado(dados_atuais)
        with open(arquivo_db, "w", encoding="utf-8") as f:
            json.dump(dados_atuais, f, ensure_ascii=False, indent=4)
    else:
        print("😴 Sem novidades reais (apenas o timestamp mudou).")

if __name__ == "__main__":
    monitorar()