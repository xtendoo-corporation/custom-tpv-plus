"""Browser walk-through of the kiosk (needs selenium + chrome and a running server).

Usage: e2e_kiosk.py OUT_DIR URL/feria WIDTH HEIGHT TAG   (screenshots go to OUT_DIR)
Expects a contact "Estres" with card STRESS01 and a second customer "Estela Prueba" (card ESTELA01).
"""
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

OUT, URL, W, H, TAG = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
options = Options()
for arg in ('--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars'):
    options.add_argument(arg)
d = webdriver.Chrome(options=options)
d.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width': W, 'height': H, 'deviceScaleFactor': 1, 'mobile': W < 700})
d.implicitly_wait(5)


def shot(name):
    d.save_screenshot(f'{OUT}/{TAG}_{name}.png')


def click(act, **kw):
    d.find_element(By.CSS_SELECTOR, f'[data-act="{act}"]' + ''.join(f'[data-{k}="{v}"]' for k, v in kw.items())).click()


def text():
    return d.find_element(By.ID, 'app').text.replace('\n', ' | ')


def ask(action, who):
    click('start', a=action)
    d.find_element(By.ID, 'query').send_keys(who + Keys.ENTER)
    time.sleep(1.2)


try:
    d.get(URL)
    time.sleep(1)
    print('HOME:', text())
    shot('1_home')
    print('BIG BUTTONS:', [(b.size['width'], b.size['height']) for b in d.find_elements(By.CSS_SELECTOR, '.big')])
    click('start', a='SALDO')
    time.sleep(0.4)
    shot('2_cliente')
    print('QUERY FIELD FOCUSED:', d.switch_to.active_element == d.find_element(By.ID, 'query'))
    d.find_element(By.ID, 'query').send_keys('stress01' + Keys.ENTER)
    time.sleep(1.2)
    print('SALDO (card):', text())
    shot('3_saldo')
    click('home')
    ask('SALDO', 'estel')  # by name, a single match opens straight away
    print('SALDO (name):', text())
    click('home')
    ask('COBRAR', 'e')  # too short for a name search -> not found
    print('TOO SHORT:', text())
    click('home')
    d.find_element(By.CSS_SELECTOR, '[data-act="start"][data-a="COBRAR"]').click()
    d.find_element(By.ID, 'query').send_keys('est' + Keys.ENTER)
    time.sleep(1.2)
    print('AMBIGUOUS:', text())
    shot('4_elegir')
    click('home')
    ask('COBRAR', 'stress01')
    for k in '1.5':
        click('key', k=k)
    shot('5_importe')
    click('confirm')
    time.sleep(1.5)
    print('COBRO:', text())
    shot('6_resultado')
    click('home')
    ask('PEDIDOS', 'stress01')
    print('PEDIDOS:', text())
    click('home')
    ask('RECARGAR', 'stress01')
    for k in '20':
        click('key', k=k)
    click('confirm')
    time.sleep(1.5)
    print('RECARGA:', text())
    print('CONSOLE ERRORS:', [m for m in d.get_log('browser') if m['level'] == 'SEVERE'])
finally:
    d.quit()
