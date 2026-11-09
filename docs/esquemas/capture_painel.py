from pathlib import Path
from time import sleep
import json

from playwright.sync_api import sync_playwright

ROOT = Path(r"c:\Users\User\Documents\Repositório\cinto-inteligente-deteccao-quedas")
OUT_DIR = ROOT / "docs" / "IMAGENS" / "prints" / "originais"
OUT_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH = ROOT / "docs" / "esquemas" / "prints_anotacoes.json"

# Nome dos arquivos PNG esperados pelo manual.
NOMES = [
    "barra_lateral",
    "monitoramento_normal",
    "monitoramento_queda",
    "detalhes_status",
    "detalhes_mapa",
    "detalhes_sinais_ecg",
    "detalhes_exportacao",
]


def save_page(page, name):
    page.locator("main").screenshot(path=str(OUT_DIR / f"{name}.png"), animations="disabled")


def get_label_point(page, label):
    loc = page.locator(f"text={label}").first
    if loc.count() == 0:
        return None
    box = loc.bounding_box()
    if box is None:
        return None
    return {"x": int(box["x"] + box["width"] / 2), "y": int(box["y"] + box["height"] / 2)}


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
    page.goto("http://localhost:8501", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("text=Monitoramento", timeout=60000)
    sleep(6)

    # tela 1: barra lateral
    page.locator('[data-testid="stSidebar"]').screenshot(path=str(OUT_DIR / "barra_lateral.png"), animations="disabled")

    # tela 2: monitoramento normal
    page.get_by_role("tab", name="Monitoramento").click()
    sleep(2)
    page.locator("main").screenshot(path=str(OUT_DIR / "monitoramento_normal.png"), animations="disabled")

    # tela 3: monitoramento após queda - espera ação manual do usuário para simular queda
    # esta etapa fica pendente e não é executada automaticamente.

    # tela 4: detalhes status
    page.get_by_role("tab", name="Detalhes").click()
    sleep(2)
    page.locator("main").screenshot(path=str(OUT_DIR / "detalhes_status.png"), animations="disabled")

    # tela 5: mapa
    try:
        page.get_by_text("Ambiente e posição das antenas").first.click()
    except Exception:
        pass
    sleep(1.5)
    page.locator("main").screenshot(path=str(OUT_DIR / "detalhes_mapa.png"), animations="disabled")

    # tela 6: gráficos de sinais
    page.locator("text=Gráficos de Sinais").wait_for(timeout=20000)
    sleep(1)
    page.locator("main").screenshot(path=str(OUT_DIR / "detalhes_sinais_ecg.png"), animations="disabled")

    # tela 7: exportação
    page.locator("text=Exportação de dados").wait_for(timeout=20000)
    sleep(1)
    page.locator("main").screenshot(path=str(OUT_DIR / "detalhes_exportacao.png"), animations="disabled")

    # Produz JSON com marcações iniciais em pontos gerais para o passo de anotações.
    dados = {
        "barra_lateral": [
            {"numero": 1, "x": 120, "y": 110},
            {"numero": 2, "x": 120, "y": 240},
            {"numero": 3, "x": 120, "y": 350},
            {"numero": 4, "x": 120, "y": 480},
            {"numero": 5, "x": 120, "y": 610},
            {"numero": 6, "x": 120, "y": 760},
        ],
        "monitoramento_normal": [
            {"numero": 1, "x": 300, "y": 140},
            {"numero": 2, "x": 640, "y": 240},
            {"numero": 3, "x": 930, "y": 240},
            {"numero": 4, "x": 1100, "y": 240},
            {"numero": 5, "x": 1300, "y": 240},
            {"numero": 6, "x": 500, "y": 650},
            {"numero": 7, "x": 1200, "y": 680},
        ],
        "detalhes_status": [
            {"numero": 1, "x": 300, "y": 140},
            {"numero": 2, "x": 560, "y": 180},
            {"numero": 3, "x": 840, "y": 180},
            {"numero": 4, "x": 430, "y": 340},
            {"numero": 5, "x": 780, "y": 340},
            {"numero": 6, "x": 1160, "y": 340},
        ],
        "detalhes_mapa": [
            {"numero": 1, "x": 310, "y": 120},
            {"numero": 2, "x": 650, "y": 170},
            {"numero": 3, "x": 980, "y": 170},
            {"numero": 4, "x": 430, "y": 430},
            {"numero": 5, "x": 930, "y": 430},
            {"numero": 6, "x": 1200, "y": 530},
        ],
        "detalhes_sinais_ecg": [
            {"numero": 1, "x": 410, "y": 140},
            {"numero": 2, "x": 940, "y": 140},
            {"numero": 3, "x": 1180, "y": 460},
        ],
        "detalhes_exportacao": [
            {"numero": 1, "x": 260, "y": 200},
            {"numero": 2, "x": 760, "y": 200},
            {"numero": 3, "x": 1200, "y": 200},
        ],
    }
    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    browser.close()

print(f"Capturas salvas em: {OUT_DIR}")
print(f"JSON de marcações salvo em: {JSON_PATH}")
