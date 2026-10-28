"""Drops the browser network mid-charge and checks it ends PENDIENTE -> resolved exactly once.

Usage: e2e_offline.py OUT_DIR URL/feria   (same fixtures as e2e_kiosk.py)
"""
import json
import sys
import time
import urllib.request

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

OUT, URL = sys.argv[1], sys.argv[2]
API = URL.replace('/feria', '/feria/api/v1')
options = Options()
for arg in ('--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars'):
    options.add_argument(arg)
d = webdriver.Chrome(options=options)
d.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width': 900, 'height': 700, 'deviceScaleFactor': 1, 'mobile': False})
d.execute_cdp_cmd('Network.enable', {})
d.implicitly_wait(5)


def net(offline):
    d.execute_cdp_cmd('Network.emulateNetworkConditions', {'offline': offline, 'latency': 0, 'downloadThroughput': -1, 'uploadThroughput': -1})


def click(act, **kw):
    d.find_element(By.CSS_SELECTOR, f'[data-act="{act}"]' + ''.join(f'[data-{k}="{v}"]' for k, v in kw.items())).click()


def text():
    return d.find_element(By.TAG_NAME, 'body').text.replace('\n', ' | ')


def api(path):
    try:
        with urllib.request.urlopen(API + path) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


try:
    d.get(URL)
    time.sleep(1)
    # 1) offline on the home screen
    net(True)
    time.sleep(4)
    big = d.find_elements(By.CSS_SELECTOR, '.big')
    print('OFFLINE banner visible:', d.find_element(By.ID, 'banner').is_displayed(), '| buttons disabled:', all(b.get_attribute('disabled') for b in big))
    d.save_screenshot(f'{OUT}/off_1_home.png')
    net(False)
    time.sleep(6)
    print('ONLINE again, banner hidden:', not d.find_element(By.ID, 'banner').is_displayed(),
          '| buttons enabled:', not any(b.get_attribute('disabled') for b in d.find_elements(By.CSS_SELECTOR, '.big')))

    # 2) the network drops between "confirm" and the server
    click('start', a='COBRAR')
    ActionChains(d).send_keys('stress01').send_keys(Keys.ENTER).perform()
    time.sleep(1)
    before = float(api('/contacts/lookup?code=STRESS01')[1]['balance'])
    for k in '2.5':
        click('key', k=k)
    net(True)
    click('confirm')
    time.sleep(3)
    inflight = json.loads(d.execute_script("return localStorage.getItem('feria_inflight')"))
    print('PENDING screen:', 'PENDIENTE DE CONFIRMAR' in text(), '| persisted before sending:', bool(inflight), '| approved shown:', 'COBRADO' in text())
    d.save_screenshot(f'{OUT}/off_2_pending.png')
    net(False)
    time.sleep(9)
    print('RESOLVED:', text())
    status, movement = api(f"/movements/{inflight['uuid']}")
    after = float(api('/contacts/lookup?code=STRESS01')[1]['balance'])
    print('server:', status, movement.get('status'), '| balance', before, '->', after, '| charged exactly once:', round(before - after, 2) == 2.5)
    print('inflight cleared:', d.execute_script("return localStorage.getItem('feria_inflight')") is None)
    d.save_screenshot(f'{OUT}/off_3_resolved.png')
finally:
    d.quit()
