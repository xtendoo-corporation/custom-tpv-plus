"""Browser walk-through of the cash desk (selenium + chrome, running server).

Usage: e2e_cash.py URL/feria OUT_DIR
Uses the customer "Estela Prueba" (card ESTELA01) to put known cash into the drawer.
"""
import json
import sys
import time
import urllib.request
import uuid

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

URL, OUT = sys.argv[1], sys.argv[2]
API = URL.replace('/feria', '/feria/api/v1')


def api(method, path, body=None):
    request = urllib.request.Request(
        API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


ok = True


def check(name, passed, detail=''):
    global ok
    ok &= bool(passed)
    print(f'[{"OK" if passed else "FAIL"}] {name} {detail}')


# known starting point: empty period, then 50 of recargas and a 10 cobro (which moves no cash)
_, base = api('GET', '/cash')
api('POST', '/cash', {'uuid': str(uuid.uuid4()), 'kind': 'close', 'counted': base['expected'], 'kept': '0'})
api('POST', '/movements', {'uuid': str(uuid.uuid4()), 'code_used': 'ESTELA01', 'type': 'RECARGAR', 'amount': '50.00', 'payment_method': 'cash'})
api('POST', '/movements', {'uuid': str(uuid.uuid4()), 'code_used': 'ESTELA01', 'type': 'RECARGAR', 'amount': '30.00', 'payment_method': 'card'})  # card: never in the drawer
api('POST', '/movements', {'uuid': str(uuid.uuid4()), 'code_used': 'ESTELA01', 'type': 'COBRAR', 'amount': '10.00'})

options = Options()
for arg in ('--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars'):
    options.add_argument(arg)
d = webdriver.Chrome(options=options)
d.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width': 420, 'height': 800, 'deviceScaleFactor': 1, 'mobile': True})
d.execute_cdp_cmd('Network.enable', {})
d.implicitly_wait(5)


def text():
    return d.find_element(By.TAG_NAME, 'body').text.replace('\n', ' | ')


def click(act, **kw):
    d.find_element(By.CSS_SELECTOR, f'[data-act="{act}"]' + ''.join(f'[data-{k}="{v}"]' for k, v in kw.items())).click()


def type_amount(digits):
    for ch in digits:
        click('key', k=ch)


def net(offline):
    d.execute_cdp_cmd('Network.emulateNetworkConditions', {'offline': offline, 'latency': 0, 'downloadThroughput': -1, 'uploadThroughput': -1})


try:
    d.get(URL)
    time.sleep(1.5)
    tiles = d.find_elements(By.CSS_SELECTOR, '.home .tile')
    check('Caja is the fourth tile of the home screen', len(tiles) == 4 and 'Caja' in tiles[3].text, [t.text.split('\n')[0] for t in tiles])
    check('the header no longer has a cash button', not d.find_elements(By.CSS_SELECTOR, '.bar .cashbtn'))
    d.save_screenshot(f'{OUT}/cash_1_home.png')

    click('cash')
    time.sleep(1)
    screen = text()
    check('shows the cash that should be in the drawer (cash recargas only: 50, not the 30 paid by card)', '50,00' in screen and 'Recargas en efectivo' in screen and 'con tarjeta' in screen.lower() and '30,00' in screen, screen[:150])
    d.save_screenshot(f'{OUT}/cash_2_summary.png')

    # count: 49 -> missing 1
    click('cash-count')
    type_amount('49')
    check('live difference while counting', 'Faltan 1,00' in text(), text()[:140])
    d.save_screenshot(f'{OUT}/cash_3_count.png')
    click('cash-save-count')
    time.sleep(1.5)
    check('a count is saved and shown', 'RECUENTO GUARDADO' in text() and 'Faltan 1,00' in text())
    click('home')

    # close: count 50 exactly, leave 20 for tomorrow
    click('cash')
    time.sleep(1)
    check('a count does not start a new period', '50,00' in text())
    click('cash-count')
    type_amount('50')
    check('cuadra', 'La caja cuadra' in text())
    click('cash-to-keep')
    type_amount('60')
    click('cash-review')
    check('cannot leave more than counted', 'No puedes dejar más de lo contado' in text(), text()[:160])
    click('back'); click('back')
    type_amount('20')
    d.save_screenshot(f'{OUT}/cash_4_keep.png')
    click('cash-review')
    screen = text()
    check('review shows what stays and what is withdrawn', 'Dejas para mañana' in screen and '20,00' in screen and '30,00' in screen, screen[:200])
    d.save_screenshot(f'{OUT}/cash_5_confirm.png')

    # the network drops while confirming: the cierre must still be stored exactly once
    net(True)
    click('cash-confirm')
    time.sleep(3)
    check('offline while closing: pending, nothing shown as done', 'PENDIENTE' in text() and 'CAJA CERRADA' not in text())
    net(False)
    time.sleep(8)
    screen = text()
    check('after the network is back: CAJA CERRADA', 'CAJA CERRADA' in screen and 'Dejas para mañana: 20,00' in screen, screen[:200])
    d.save_screenshot(f'{OUT}/cash_6_closed.png')
    click('home')

    _, after = api('GET', '/cash')
    check('next day starts with the 20 that were left', after['opening_float'] == '20.00' and after['expected'] == '20.00'
          and after['recharges'] == '0.00', json.dumps({k: after[k] for k in ('opening_float', 'recharges', 'expected')}))
    check('stored in the log', after['last_close'] and after['last_close']['kept'] == '20.00')
    print('CONSOLE ERRORS:', [m['message'][:120] for m in d.get_log('browser') if m['level'] == 'SEVERE'])
finally:
    d.quit()

print('RESULT:', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
