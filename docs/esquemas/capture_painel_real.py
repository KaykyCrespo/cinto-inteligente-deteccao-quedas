from pathlib import Path
from time import sleep

from playwright.sync_api import sync_playwright

ROOT = Path(r"c:\Users\User\Documents\Repositório\cinto-inteligente-deteccao-quedas")
OUT = ROOT / "docs" / "IMAGENS" / "prints" / "originais"
OUT.mkdir(parents=True, exist_ok=True)


def screenshot_por_texto(page, texto, nome, padding=40):
    loc = page.locator(f"text={texto}").first
    if loc.count() == 0:
        return False
    loc.scroll_into_view_if_needed()
    sleep(1)
    box = loc.bounding_box()
    if not box:
        return False
    x = max(0, box["x"] - padding)
    y = max(0, box["y"] - padding)
    w = min(page.viewport_size["width"] - x, box["width"] + 2 * padding)
    h = min(page.viewport_size["height"] - y, 700)
    page.screenshot(path=str(OUT / f"{nome}.png"), clip={"x": x, "y": y, "width": w, "height": h})
    return True


def capturar_visao_completa(page, nome, scroll_y=250):
    page.set_viewport_size({"width": 1600, "height": 2200})
    page.evaluate(f"window.scrollTo(0, {scroll_y})")
    sleep(1.5)
    page.screenshot(path=str(OUT / f"{nome}.png"), full_page=True, animations="disabled")


def capturar_mapa_indoor(page, nome):
    page.locator("button[role='tab']", has_text="Detalhes").click()
    sleep(2)
    page.locator("text=Localização indoor").first.scroll_into_view_if_needed()
    sleep(1)
    page.evaluate("window.scrollTo(0, 900)")
    sleep(1)
    page.screenshot(path=str(OUT / f"{nome}.png"), full_page=True, animations="disabled")


def abrir_app(page):
    page.goto("http://localhost:8501", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("text=Monitoramento", timeout=60000)
    sleep(5)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
    abrir_app(page)

    # barra lateral
    page.locator('[data-testid="stSidebar"]').screenshot(path=str(OUT / "barra_lateral.png"), animations="disabled")

    # aba monitoramento
    page.locator("button[role='tab']", has_text="Monitoramento").click()
    sleep(2)
    capturar_visao_completa(page, "monitoramento_normal", scroll_y=280)

    # aba detalhes
    page.locator("button[role='tab']", has_text="Detalhes").click()
    sleep(2)
    page.locator("text=Status do Sistema").scroll_into_view_if_needed()
    sleep(1)
    capturar_visao_completa(page, "detalhes_status", scroll_y=320)

    capturar_mapa_indoor(page, "detalhes_mapa_indoor_ajustado")

    try:
        page.locator("text=Ambiente e posição das antenas").first.click()
    except Exception:
        pass
    sleep(1.5)
    capturar_visao_completa(page, "detalhes_mapa", scroll_y=360)

    # gráficos e exportação
    page.locator("text=Gráficos de Sinais").wait_for(timeout=20000)
    sleep(1.5)
    capturar_visao_completa(page, "detalhes_sinais_ecg", scroll_y=260)

    page.locator("text=Exportação de dados").wait_for(timeout=20000)
    sleep(1.5)
    capturar_visao_completa(page, "detalhes_exportacao", scroll_y=260)

    browser.close()

print(f"PNG salvos em {OUT}")
