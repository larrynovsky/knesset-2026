#!/usr/bin/env python3
"""Рендер UI для решений по преемственности партий.

Узкий контракт: build_ballot_lineage считает, этот файл рисует. Сети не трогает,
запускается на MacBook. Вход — criteria/ballot_lineage_draft.json.

Первое место в проекте, где ивритский текст попадает в HTML, поэтому здесь же
впервые применяется дисциплина R-B (WSTG-CLNT-01): данные уезжают в страницу
ОДНИМ куском JSON в <script type="application/json">, а не интерполяцией в
разметку; рендерит их textContent, не innerHTML. Экранирование живёт в одном
месте — функции esc() и в клиентском el().
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "criteria" / "ballot_lineage_draft.json"
OUT = ROOT / "report" / "lineage_ui.html"

CSS = """
:root{--bg:#faf9f7;--card:#fff;--ink:#1c1917;--mut:#78716c;--line:#e7e5e4;
--acc:#0f766e;--warn:#b45309;--warnbg:#fffbeb;--ok:#166534;--okbg:#f0fdf4}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:24px 20px 80px}
h1{font-size:22px;margin:0 0 6px} .sub{color:var(--mut);font-size:14px;margin-bottom:20px}
.bar{position:sticky;top:0;background:var(--bg);padding:12px 0;border-bottom:1px solid var(--line);
z-index:10;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.pill{background:var(--card);border:1px solid var(--line);border-radius:99px;padding:5px 12px;font-size:13px}
.pill b{color:var(--acc)}
button{font:inherit;padding:7px 14px;border-radius:8px;border:1px solid var(--line);
background:var(--card);cursor:pointer}
button:hover{border-color:var(--acc)} button.pri{background:var(--acc);color:#fff;border-color:var(--acc)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:14px 0;overflow:hidden}
.card>summary{padding:14px 18px;cursor:pointer;display:flex;align-items:center;gap:12px;
list-style:none;font-weight:600}
.card>summary::-webkit-details-marker{display:none}
.card>summary::before{content:"▸";color:var(--mut);transition:.15s}
.card[open]>summary::before{transform:rotate(90deg)}
.he{direction:rtl;unicode-bidi:isolate;font-size:15px}
.tag{margin-inline-start:auto;font-size:12px;padding:3px 9px;border-radius:99px;font-weight:500}
.tag.done{background:var(--okbg);color:var(--ok)} .tag.q{background:var(--warnbg);color:var(--warn)}
.body{padding:4px 18px 18px;border-top:1px solid var(--line)}
.step{display:flex;gap:10px;padding:7px 0;align-items:baseline;font-size:14px;color:var(--mut)}
.step .k{min-width:34px;font-variant-numeric:tabular-nums;font-size:12px}
.q{background:var(--warnbg);border:1px solid #fde68a;border-radius:10px;padding:12px 14px;margin:10px 0}
.q h4{margin:0 0 8px;font-size:14px;color:var(--warn)}
label.opt{display:flex;gap:10px;align-items:baseline;padding:7px 8px;border-radius:8px;cursor:pointer}
label.opt:hover{background:#fff}
label.opt input{margin-top:3px}
.meta{color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
textarea{width:100%;height:240px;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--card)}
.hide{display:none}
"""

JS = """
const D = JSON.parse(document.getElementById('data').textContent);
const dec = {};
const el = (t,c,txt)=>{const e=document.createElement(t); if(c)e.className=c;
  if(txt!==undefined) e.textContent = txt; return e;};

function heb(s){const e=el('span','he'); e.textContent=s; return e;}

function render(){
  const root = document.getElementById('list'); root.innerHTML='';
  const onlyQ = document.getElementById('onlyq').checked;
  D.chains.forEach((c,ci)=>{
    const qs = c.chain.filter(s=>s.step==='ВОПРОС');
    if(onlyQ && !qs.length) return;
    const d = el('details','card'); if(qs.length) d.open = false;
    const s = el('summary');
    s.appendChild(heb(c.anchor));
    const tag = el('span', 'tag ' + (qs.length?'q':'done'),
      qs.length ? qs.length+' вопр.' : 'решено машиной');
    s.appendChild(tag); d.appendChild(s);
    const b = el('div','body');
    c.chain.forEach((st,si)=>{
      if(st.step==='ВОПРОС'){
        const q = el('div','q');
        q.appendChild(el('h4',null,'Кнессет '+st.knesset+' — кто предшественник?'));
        (st.alternatives||[]).forEach(a=>{
          const l = el('label','opt');
          const r = el('input'); r.type='radio'; r.name='q'+ci+'_'+si; r.value=a.id;
          r.onchange=()=>{dec[ci+'_'+si]={anchor:c.anchor,knesset:st.knesset,
            choice_id:a.id,choice:a.name}; upd();};
          l.appendChild(r); l.appendChild(heb(a.name));
          l.appendChild(el('span','meta','перешло '+a.shared+' · всего '+a.mks+' · ov '+a.overlap));
          q.appendChild(l);
        });
        const l2 = el('label','opt');
        const r2 = el('input'); r2.type='radio'; r2.name='q'+ci+'_'+si; r2.value='CUT';
        r2.onchange=()=>{dec[ci+'_'+si]={anchor:c.anchor,knesset:st.knesset,
          choice_id:'CUT',choice:'линия обрывается здесь'}; upd();};
        l2.appendChild(r2); l2.appendChild(el('span',null,'линия обрывается — дальше другая партия'));
        q.appendChild(l2);
        b.appendChild(q);
      } else {
        const row = el('div','step');
        row.appendChild(el('span','k','к'+st.knesset));
        if(st.name) row.appendChild(heb(st.name));
        const bits=[]; if(st.mks!==undefined) bits.push(st.mks+' деп.');
        if(st.overlap!==undefined) bits.push('ov '+st.overlap);
        bits.push(st.step);
        row.appendChild(el('span','meta',bits.join(' · ')));
        b.appendChild(row);
      }
    });
    d.appendChild(b); root.appendChild(d);
  });
  upd();
}

function upd(){
  let total=0; D.chains.forEach(c=>total+=c.chain.filter(s=>s.step==='ВОПРОС').length);
  const n=Object.keys(dec).length;
  document.getElementById('cnt').innerHTML='решено <b>'+n+'</b> из '+total;
  const lines=['# решения по преемственности — вставить в criteria/party_lineage.yaml',
               'decisions:'];
  Object.values(dec).forEach(d=>{
    lines.push('  - anchor: "'+d.anchor.replace(/"/g,'\\\\"')+'"');
    lines.push('    at_knesset: '+d.knesset);
    lines.push('    choice_id: '+d.choice_id);
    lines.push('    choice: "'+String(d.choice).replace(/"/g,'\\\\"')+'"');
  });
  document.getElementById('out').value = lines.join('\\n');
}

document.getElementById('onlyq').onchange = render;
document.getElementById('copy').onclick = async ()=>{
  const t=document.getElementById('out');
  try{ await navigator.clipboard.writeText(t.value); }catch(e){ t.select(); document.execCommand('copy'); }
  const b=document.getElementById('copy'); const o=b.textContent;
  b.textContent='скопировано'; setTimeout(()=>b.textContent=o,1200);
};
render();
"""


def main() -> int:
    if not SRC.exists():
        print(f"нет {SRC} — сначала build_ballot_lineage.py", file=sys.stderr)
        return 1
    data = json.loads(SRC.read_text(encoding="utf-8"))
    total_q = sum(1 for c in data["chains"] for s in c["chain"] if s["step"] == "ВОПРОС")
    # Данные уезжают одним куском JSON, не интерполяцией в разметку (R-B).
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    html = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Преемственность партий — решения</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>Преемственность партий: {len(data['chains'])} цепочек, {total_q} вопросов</h1>
<div class="sub">Для каждой партии 25-го Кнессета машина прошла назад по каденциям.
Шаги без пометки разрешены автоматически. Жёлтые блоки — где нужно твоё решение.
Внизу — готовый текст решений, скопировать и прислать мне.</div>
<div class="bar">
  <span class="pill" id="cnt"></span>
  <label class="pill"><input type="checkbox" id="onlyq"> только с вопросами</label>
  <button class="pri" id="copy">скопировать решения</button>
</div>
<div id="list"></div>
<h3 style="margin-top:32px">Решения</h3>
<textarea id="out" readonly></textarea>
</div>
<script id="data" type="application/json">{blob}</script>
<script>{JS}</script></body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"{OUT}  ({len(html)//1024} КБ, вопросов {total_q})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
