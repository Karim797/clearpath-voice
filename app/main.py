from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .config import settings, validate_settings
from .db import init_db
from .security import verify_action_token
from .routers import admin, demo, events, tools, webhooks

@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_settings()
    init_db()
    yield


app = FastAPI(
    title="ClearPath Voice API",
    version="3.0.0",
    description="Bounded-action multilingual voice-agent backend for government applications returned for amendment.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:8000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(tools.router)
app.include_router(events.router)
app.include_router(admin.router)
app.include_router(demo.router)
app.include_router(webhooks.router)


@app.get("/demo-upload/{token}", response_class=HTMLResponse)
def demo_upload(token: str):
    payload = verify_action_token(token)
    if payload.get("action_type") != "upload_access":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="invalid_upload_token_scope")
    case_id = str(payload.get("case_id", ""))
    document_type = str(payload.get("document_type", "document")).replace("_", " ")
    return f"""
    <!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Secure upload demo</title>
    <style>body{{font-family:system-ui,sans-serif;max-width:620px;margin:60px auto;padding:0 20px;background:#08111f;color:#e7edf7}}.card{{background:#0d1829;border:1px solid #223149;border-radius:18px;padding:26px}}.muted{{color:#93a4bb}}code{{color:#b9c8ff}}</style></head>
    <body><div class='card'><h1>Secure upload route</h1><p>This signed demo route is valid only for the requested document and expires automatically.</p><p><b>Case:</b> <code>{case_id}</code></p><p><b>Requested document:</b> {document_type}</p><p class='muted'>Challenge prototype: a production pilot would hand this token to the authority's approved document-storage service rather than accepting documents in ClearPath.</p></div></body></html>
    """


@app.get("/demo", response_class=HTMLResponse)
def demo_dashboard():
    return r"""
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>ClearPath Evidence Console</title><style>
    :root{color-scheme:dark}*{box-sizing:border-box}body{font-family:Inter,ui-sans-serif,system-ui,sans-serif;margin:0;background:#08111f;color:#e7edf7}
    main{max-width:1180px;margin:0 auto;padding:34px 20px 64px}.top{display:flex;gap:18px;justify-content:space-between;align-items:end;flex-wrap:wrap}
    h1{margin:.2rem 0;font-size:clamp(28px,4vw,46px);letter-spacing:-.04em}.muted{color:#93a4bb}.pill{display:inline-block;border:1px solid #2b3a52;border-radius:999px;padding:6px 10px;font-size:12px;color:#b8c6da}
    .grid{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:18px;margin-top:24px}.panel{background:#0d1829;border:1px solid #223149;border-radius:18px;padding:18px;min-width:0}
    .cases{display:grid;gap:10px}.case{width:100%;text-align:left;background:#101d31;color:inherit;border:1px solid #263750;border-radius:13px;padding:14px;cursor:pointer}.case:hover,.case.active{border-color:#6f86a8;background:#14233a}
    .row{display:flex;justify-content:space-between;gap:12px;align-items:start}.code{font:12px ui-monospace,SFMono-Regular,monospace;color:#9fb4d1;overflow-wrap:anywhere}.status{font-size:11px;border:1px solid #32445f;border-radius:999px;padding:4px 8px;white-space:nowrap}
    pre{white-space:pre-wrap;word-break:break-word;font:12px/1.55 ui-monospace,SFMono-Regular,monospace;background:#07101c;border-radius:12px;padding:14px;max-height:430px;overflow:auto}.audit{margin-top:18px}.event{border-left:2px solid #526b8d;padding:4px 0 14px 14px;margin-left:5px}.event b{font-size:13px}.event small{display:block;color:#8ea1ba;margin-top:4px}
    .ok{color:#8ad7a0}.bad{color:#ffb2b2}button.verify{border:1px solid #39506e;background:#14233a;color:#e7edf7;padding:10px 12px;border-radius:10px;cursor:pointer}
    @media(max-width:800px){.grid{grid-template-columns:1fr}}
    </style></head><body><main>
      <div class='top'><div><span class='pill'>Synthetic challenge data</span><h1>Evidence Console</h1><div class='muted'>Inspect case scope, status and the checkpointed audit-integrity trail.</div></div><button class='verify' id='verify'>Verify audit chain</button></div>
      <div id='chain' class='muted' aria-live='polite' style='margin-top:12px'></div>
      <div class='grid'><section class='panel'><h2>Demo cases</h2><div id='cases' class='cases'></div></section><section class='panel'><h2>Selected case</h2><pre id='detail'>Choose a case.</pre></section></div>
      <section class='panel audit'><h2>Audit events</h2><div id='audit' class='muted'>Choose a case.</div></section>
    </main><script>
    const casesEl=document.getElementById('cases'), detail=document.getElementById('detail'), audit=document.getElementById('audit'), chain=document.getElementById('chain');
    const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
    async function loadCases(){const rows=await fetch('/demo-api/cases').then(r=>r.json());casesEl.innerHTML='';rows.forEach((c,i)=>{const b=document.createElement('button');b.className='case';b.innerHTML=`<div class="row"><div><strong>${esc(c.id)}</strong><div class="code">${esc(c.rejection_code)}</div></div><span class="status">${esc(c.status)}</span></div><div class="muted" style="margin-top:8px">${esc(c.contact_role)} · ${esc(c.preferred_language)} · deadline ${esc(c.correction_deadline)}</div>`;b.addEventListener('click',()=>selectCase(c.id,b));casesEl.appendChild(b);if(i===0)selectCase(c.id,b);});}
    async function selectCase(id,b){document.querySelectorAll('.case').forEach(x=>x.classList.remove('active'));b.classList.add('active');const [c,e]=await Promise.all([fetch(`/demo-api/cases/${encodeURIComponent(id)}`).then(r=>r.json()),fetch(`/demo-api/audit?case_id=${encodeURIComponent(id)}`).then(r=>r.json())]);detail.textContent=JSON.stringify(c,null,2);audit.innerHTML=e.length?e.map(x=>`<div class="event"><b>${esc(x.event_type)} · ${esc(x.outcome)}</b><small>${esc(x.timestamp)} · actor ${esc(x.actor)}</small><div class="code">${esc(JSON.stringify(x.details))}</div></div>`).join(''):'No audit events yet.';}
    document.getElementById('verify').addEventListener('click',async()=>{const x=await fetch('/demo-api/audit/verify').then(r=>r.json());chain.innerHTML=x.valid?`<span class="ok">✓ Audit chain valid</span> · ${x.events_checked} events checked`:`<span class="bad">✕ Audit chain failed</span> at event ${x.events_checked}`;});
    loadCases().catch(e=>{casesEl.textContent='Failed to load demo data.';console.error(e)});
    </script></body></html>
    """


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>ClearPath Voice</title><style>
    body{font-family:Inter,system-ui,sans-serif;max-width:920px;margin:50px auto;padding:0 20px;background:#0b1220;color:#e8eef8}
    .tag{display:inline-block;padding:6px 10px;border:1px solid #334155;border-radius:999px;color:#a5b4fc;margin-right:8px}
    .card{background:#111a2c;border:1px solid #25304a;border-radius:18px;padding:24px;margin:20px 0}a{color:#93c5fd}code{color:#c4b5fd}
    </style></head><body>
    <span class='tag'>ElevenLabs-ready</span><span class='tag'>Arabic + English</span><span class='tag'>Bounded actions</span>
    <h1>ClearPath Voice</h1><p>A voice recovery layer for government applications held up by correctable errors.</p>
    <div class='card'><h2>Safety invariant</h2><p>The agent can explain and correct only the exact rejection item. It has no approve/reject/cancel/start-application capability.</p></div>
    <div class='card'><h2>Demo endpoints</h2><p><a href='/docs'>Interactive API docs</a> · <a href='/demo'>Evidence console</a> · <a href='/demo-api/cases'>Sanitized cases</a> · <a href='/demo-api/audit/verify'>Verify audit integrity</a></p></div>
    </body></html>
    """
