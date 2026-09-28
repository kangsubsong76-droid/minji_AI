import asyncio
import json
import subprocess
import urllib.request
import websockets

async def test():
    edge_proc = subprocess.Popen([
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        '--headless=new',
        '--remote-debugging-port=9222',
        '--disable-gpu',
        'https://scribble-smirk-obedient.ngrok-free.dev'
    ])
    await asyncio.sleep(2)

    try:
        req = urllib.request.urlopen('http://127.0.0.1:9222/json')
        tabs = json.loads(req.read().decode())
        page_tab = [t for t in tabs if t.get('type') == 'page'][0]
        ws_url = page_tab['webSocketDebuggerUrl']

        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({'id': 1, 'method': 'Runtime.enable'}))

            # Click ngrok visit site button if present
            await ws.send(json.dumps({
                'id': 2,
                'method': 'Runtime.evaluate',
                'params': {
                    'expression': '''
                    (function() {
                        const btn = document.querySelector('button') || document.querySelector('a');
                        if (btn) btn.click();
                        return "Clicked: " + (btn ? btn.innerText : "none");
                    })()
                    ''',
                    'returnByValue': True
                }
            }))
            await asyncio.sleep(2)

            # Check minji app
            check_minji = {
                'id': 10,
                'method': 'Runtime.evaluate',
                'params': {
                    'expression': '''
                    (function() {
                        const pwBtn = document.querySelector('.pw-btn');
                        const faceIdBtn = document.getElementById('faceIdBtn');
                        const pwInput = document.getElementById('pwInput');
                        const pwGate = document.getElementById('pwGate');
                        const bioHint = document.getElementById('bioDeviceHint');
                        return {
                            title: document.title,
                            hasPwBtn: !!pwBtn,
                            hasFaceIdBtn: !!faceIdBtn,
                            faceIdBtnText: document.getElementById('faceIdBtnText')?.innerText,
                            bioHint: bioHint?.innerText,
                            typeof_checkPw: typeof window.checkPw,
                            typeof_handleFaceIdClick: typeof window.handleFaceIdClick,
                            pwInputValue: pwInput ? pwInput.value : null,
                            pwGateHidden: pwGate ? pwGate.classList.contains('hidden') : null
                        };
                    })()
                    ''',
                    'returnByValue': True
                }
            }
            await ws.send(json.dumps(check_minji))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get('id') == 10:
                    print('MINJI LIVE STATE:', json.dumps(msg['result']['result']['value'], indent=2))
                    break

            # Now test clicking the password button!
            click_pw = {
                'id': 11,
                'method': 'Runtime.evaluate',
                'params': {
                    'expression': '''
                    (function() {
                        const btn = document.querySelector('.pw-btn');
                        btn.click();
                        const pwGate = document.getElementById('pwGate');
                        return {
                            hiddenAfterClick: pwGate.classList.contains('hidden'),
                            displayStyle: pwGate.style.display,
                            authStored: localStorage.getItem('minji_auth')
                        };
                    })()
                    ''',
                    'returnByValue': True
                }
            }
            await ws.send(json.dumps(click_pw))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get('id') == 11:
                    print('LIVE CLICK RESULT:', msg['result']['result']['value'])
                    break
    finally:
        edge_proc.terminate()

asyncio.run(test())
