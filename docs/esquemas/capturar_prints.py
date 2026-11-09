import json
from pathlib import Path
from time import sleep

from playwright.sync_api import sync_playwright

BASE = Path(r"c:\Users\User\Documents\Repositório\cinto-inteligente-deteccao-quedas")
OUT_ORIGINAIS = BASE / "docs" / "IMAGENS" / "prints" / "originais"
OUT_ORIGINAIS.mkdir(parents=True, exist_ok=True)
JSON_PATH = BASE / "docs" / "esquemas" / "prints_anotacoes.json"


def tag_bbox(page, text):
    locator = page.locator(f'text={text}').first
    if locator.count() == 0:
        return None
    box = locator.bounding_box()
    return None if box is None else {"x": int(box["x"] + box["width"] / 2), "y": int(box["y"] + box["height"] / 2)}


def salvar_captura(page, nome, seletor, marcacoes):
    locator = page.locator(seletor)
    locator.screenshot(path=str(OUT_ORIGINAIS / f"{nome}.png"), animations="disabled")
    marcacoes[nome] = [{"numero": n, "x": m["x"], "y": m["y"]} for n, m in enumerate(marcacoes.get(nome, []), start=1)]


def mover_para_monitoramento(page):
    page.goto("http://localhost:8501", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("text=Monitoramento", timeout=60000)
    page.wait_for_timeout(5000)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
    mover_para_monitoramento(page)

    anotacoes = {}

    sidebar = page.locator('[data-testid="stSidebar"]')
    sidebar.screenshot(path=str(OUT_ORIGINAIS / "barra_lateral.png"), animations="disabled")

    # pontos principais da barra lateral
    bbox = sidebar.bounding_box()
    cx, cy = bbox["x"] + bbox["width"] / 2, bbox["y"] + bbox["height"] / 2
    anotacoes["barra_lateral"] = [
        {"numero": 1, "x": int(cx), "y": int(bbox["y"] + 80)},
        {"numero": 2, "x": int(cx), "y": int(bbox["y"] + 170)},
        {"numero": 3, "x": int(cx), "y": int(bbox["y"] + 250)},
        {"numero": 4, "x": int(cx), "y": int(bbox["y"] + 380)},
        {"numero": 5, "x": int(cx), "y": int(bbox["y"] + 540)},
        {"numero": 6, "x": int(cx), "y": int(bbox["y"] + 620)},
        {"numero": 7, "x": int(cx), "y": int(bbox["y"] + 710)},
    ]

    # aba Monitoramento em estado normal
    page.get_by_role("tab", name="Monitoramento").click()
    page.wait_for_timeout(2000)
    page.locator('main').screenshot(path=str(OUT_ORIGINAIS / "monitoramento_normal.png"), animations="disabled")
    anotacoes["monitoramento_normal"] = [
        {"numero": 1, "x": 430, "y": 170},
        {"numero": 2, "x": 540, "y": 270},
        {"numero": 3, "x": 750, "y": 270},
        {"numero": 4, "x": 930, "y": 270},
        {"numero": 5, "x": 1120, "y": 270},
        {"numero": 6, "x": 450, "y": 610},
        {"numero": 7, "x": 1120, "y": 630},
    ]

    # aba Detalhes (status)
    page.get_by_role("tab", name="Detalhes").click()
    page.wait_for_timeout(2000)
    page.locator('main').screenshot(path=str(OUT_ORIGINAIS / "detalhes_status.png"), animations="disabled")
    anotacoes["detalhes_status"] = [
        {"numero": 1, "x": 520, "y": 170},
        {"numero": 2, "x": 830, "y": 220},
        {"numero": 3, "x": 1120, "y": 220},
        {"numero": 4, "x": 290, "y": 380},
        {"numero": 5, "x": 730, "y": 380},
        {"numero": 6, "x": 1150, "y": 380},
    ]

    # mapa: expande ambiente e posição das antenas
    expander = page.get_by_text("Ambiente e posição das antenas")
    if expander.count() > 0:
        expander.first.click()
    page.wait_for_timeout(1200)
    page.locator('main').screenshot(path=str(OUT_ORIGINAIS / "detalhes_mapa.png"), animations="disabled")
    anotacoes["detalhes_mapa"] = [
        {"numero": 1, "x": 340, "y": 160},
        {"numero": 2, "x": 860, "y": 180},
        {"numero": 3, "x": 1050, "y": 180},
        {"numero": 4, "x": 520, "y": 510},
        {"numero": 5, "x": 980, "y": 500},
        {"numero": 6, "x": 1210, "y": 560},
    ]

    # gráficos de sinais / ECG
    page.locator('text=Gráficos de Sinais').wait_for(timeout=10000)
    page.locator('main').screenshot(path=str(OUT_ORIGINAIS / "detalhes_sinais_ecg.png"), animations="disabled")
    anotacoes["detalhes_sinais_ecg"] = [
        {"numero": 1, "x": 400, "y": 170},
        {"numero": 2, "x": 995, "y": 170},
        {"numero": 3, "x": 1220, "y": 520},
    ]

    # exportação
    page.locator('text=Exportação de dados').wait_for(timeout=10000)
    page.locator('main').screenshot(path=str(OUT_ORIGINAIS / "detalhes_exportacao.png"), animations="disabled")
    anotacoes["detalhes_exportacao"] = [
        {"numero": 1, "x": 330, "y": 240},
        {"numero": 2, "x": 700, "y": 240},
        {"numero": 3, "x": 1030, "y": 240},
    ]

    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(anotacoes, f, ensure_ascii=False, indent=2)

    browser.close()

print(f"Imagens salvas em: {OUT_ORIGINAIS}")
print(f"JSON salvo em: {JSON_PATH}")
