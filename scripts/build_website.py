"""Export a public website and demo from the same dashboard assets as the image."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'website'/'dist'
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
version=(ROOT/'VERSION').read_text().strip()
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'demo').mkdir(exist_ok=True)
for name in ('app.js','style.css'):
    shutil.copyfile(ROOT/'static'/name,OUT/'demo'/name)
shutil.copyfile(ROOT/'website'/'demo.js',OUT/'demo'/'demo.js')
html=(ROOT/'static'/'index.html').read_text().replace('href="/style.css"','href="/demo/style.css"').replace('<script src="/app.js" defer></script>','<script src="/demo/demo.js" defer></script><script src="/demo/app.js" defer></script>')
html=html.replace('<body>','<body class="demo"><div class="demo-banner">MOCK FLEET DEMO · Changes stay in this tab · <a href="/">About Protec</a> · '+version+'</div>').replace('Inventory prototype','Mock fleet demo')
(OUT/'demo'/'index.html').write_text(html)
with (OUT/'demo'/'style.css').open('a') as output: output.write('\n.demo-banner{position:sticky;top:0;z-index:50;background:#d4edb4;color:#173726;padding:10px;text-align:center;font-size:14px}.demo-banner a{color:inherit}.demo aside{top:42px}@media(max-width:800px){.demo aside{top:auto}}\n')
(OUT/'index.html').write_text((ROOT/'website'/'index.html').read_text().replace('<!--VERSION-->',version).replace('<!--REVISION-->',revision[:12]))
shutil.copyfile(ROOT/'website'/'site.css',OUT/'site.css')
manifest={'version':version,'revision':revision,'dashboard_sha256':hashlib.sha256((ROOT/'static'/'app.js').read_bytes()).hexdigest(),'mode':'mock-data-only'}
(OUT/'release.json').write_text(json.dumps(manifest)+'\n')
(OUT/'_headers').write_text('/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n  Content-Security-Policy: default-src \'self\'; connect-src \'none\'; frame-ancestors \'none\'; base-uri \'none\'; form-action \'self\'\n  Cache-Control: no-cache\n')
print(json.dumps(manifest))
