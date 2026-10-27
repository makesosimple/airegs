"""Admin paneli — Open WebUI admin Bearer token ile korunur."""
from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.services.vector_store import get_client

router = APIRouter(prefix="/airegs-admin", tags=["admin"])

WEBUI_URL = os.environ.get("WEBUI_INTERNAL_URL", "http://127.0.0.1:3081")
WEBUI_DB = os.environ.get("WEBUI_DB_PATH", "/opt/ito-webui-data/webui.db")
bearer = HTTPBearer(auto_error=True)


def _webui_db() -> sqlite3.Connection:
    if not os.path.exists(WEBUI_DB):
        raise HTTPException(503, f"Open WebUI DB bulunamadı: {WEBUI_DB}")
    conn = sqlite3.connect(f"file:{WEBUI_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _ts(v) -> str:
    if not v:
        return ""
    try:
        return datetime.fromtimestamp(int(v)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _extract_qas(chat_json: str) -> list[dict]:
    try:
        ch = json.loads(chat_json or "{}")
    except Exception:
        return []
    inner = ch.get("chat", ch)
    msgs = inner.get("messages")
    if not msgs:
        hist = (inner.get("history") or {}).get("messages") or {}
        msgs = list(hist.values()) if isinstance(hist, dict) else hist
    if isinstance(msgs, dict):
        msgs = list(msgs.values())
    out = []
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        out.append({
            "role": m.get("role", ""),
            "content": m.get("content", ""),
            "timestamp": _ts(m.get("timestamp")),
        })
    return out


async def require_admin(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                f"{WEBUI_URL}/api/v1/auths/",
                headers={"Authorization": f"Bearer {creds.credentials}"},
            )
    except Exception as e:
        raise HTTPException(503, f"Auth service unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(401, "Geçersiz token")
    user = r.json()
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin yetkisi gerekli")
    return user


@router.get("/api/stats")
async def stats(_: dict = Depends(require_admin)):
    client = get_client()
    total = client.count(settings.collection_name).count
    by_type: dict[str, set] = defaultdict(set)
    chunks_by_type: dict[str, int] = defaultdict(int)
    offset = None
    while True:
        pts, offset = client.scroll(
            collection_name=settings.collection_name,
            limit=1000, offset=offset,
            with_payload=True, with_vectors=False,
        )
        for p in pts:
            t = p.payload.get("doc_type", "?")
            by_type[t].add(p.payload.get("document_id"))
            chunks_by_type[t] += 1
        if offset is None:
            break
    return {
        "total_chunks": total,
        "total_docs": sum(len(v) for v in by_type.values()),
        "by_type": [
            {"type": t, "docs": len(by_type[t]), "chunks": chunks_by_type[t]}
            for t in sorted(by_type)
        ],
    }


@router.get("/api/documents")
async def documents(
    doc_type: str | None = None,
    q: str | None = None,
    limit: int = 500,
    _: dict = Depends(require_admin),
):
    client = get_client()
    docs: dict[str, dict] = {}
    offset = None
    while True:
        pts, offset = client.scroll(
            collection_name=settings.collection_name,
            limit=1000, offset=offset,
            with_payload=True, with_vectors=False,
        )
        for p in pts:
            did = p.payload.get("document_id")
            if did in docs:
                docs[did]["chunks"] += 1
                continue
            t = p.payload.get("doc_type", "?")
            if doc_type and t != doc_type:
                continue
            title = p.payload.get("title", "")
            if q and q.lower() not in title.lower():
                continue
            docs[did] = {
                "id": did,
                "title": title,
                "doc_type": t,
                "url": p.payload.get("url", ""),
                "source": p.payload.get("source", ""),
                "date": p.payload.get("date", ""),
                "chunks": 1,
            }
        if offset is None:
            break
    items = sorted(docs.values(), key=lambda d: (d["doc_type"], d["title"]))
    return {"count": len(items), "items": items[:limit]}


@router.get("/api/documents/{doc_id}")
async def document_chunks(doc_id: str, _: dict = Depends(require_admin)):
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    client = get_client()
    pts, _off = client.scroll(
        collection_name=settings.collection_name,
        scroll_filter=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))]),
        limit=500,
        with_payload=True,
        with_vectors=False,
    )
    if not pts:
        raise HTTPException(404, "Doküman bulunamadı")
    first = pts[0].payload
    chunks = sorted(
        [{"index": p.payload.get("chunk_index", 0), "text": p.payload.get("text", "")} for p in pts],
        key=lambda c: c["index"],
    )
    return {
        "id": doc_id,
        "title": first.get("title", ""),
        "doc_type": first.get("doc_type", ""),
        "url": first.get("url", ""),
        "source": first.get("source", ""),
        "date": first.get("date", ""),
        "chunks": chunks,
    }


@router.get("/api/users")
async def list_users(_: dict = Depends(require_admin)):
    with _webui_db() as c:
        rows = c.execute(
            "SELECT id,name,email,role,created_at,last_active_at FROM user ORDER BY created_at DESC"
        ).fetchall()
        chat_counts = {r["user_id"]: r["n"] for r in c.execute(
            "SELECT user_id, COUNT(*) as n FROM chat GROUP BY user_id"
        ).fetchall()}
    items = [{
        "id": r["id"], "name": r["name"], "email": r["email"], "role": r["role"],
        "created": _ts(r["created_at"]),
        "last_active": _ts(r["last_active_at"]) if "last_active_at" in r.keys() else "",
        "chats": chat_counts.get(r["id"], 0),
    } for r in rows]
    return {"count": len(items), "items": items}


@router.get("/api/chats")
async def list_chats(
    user_id: str | None = None,
    q: str | None = None,
    limit: int = 200,
    _: dict = Depends(require_admin),
):
    sql = "SELECT c.id, c.user_id, c.title, c.created_at, c.updated_at, u.name FROM chat c LEFT JOIN user u ON u.id=c.user_id"
    params: list = []
    where = []
    if user_id:
        where.append("c.user_id=?"); params.append(user_id)
    if q:
        where.append("c.title LIKE ?"); params.append(f"%{q}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    params.append(limit)
    with _webui_db() as c:
        rows = c.execute(sql, params).fetchall()
    return {"count": len(rows), "items": [{
        "id": r["id"], "user_id": r["user_id"], "user_name": r["name"] or "?",
        "title": r["title"], "created": _ts(r["created_at"]), "updated": _ts(r["updated_at"]),
    } for r in rows]}


@router.get("/api/chats/{chat_id}")
async def chat_detail(chat_id: str, _: dict = Depends(require_admin)):
    with _webui_db() as c:
        r = c.execute(
            "SELECT c.id,c.title,c.created_at,c.chat,u.name,u.email FROM chat c LEFT JOIN user u ON u.id=c.user_id WHERE c.id=?",
            (chat_id,),
        ).fetchone()
    if not r:
        raise HTTPException(404, "Sohbet bulunamadı")
    return {
        "id": r["id"], "title": r["title"], "created": _ts(r["created_at"]),
        "user_name": r["name"] or "?", "user_email": r["email"] or "",
        "messages": _extract_qas(r["chat"]),
    }


@router.get("/api/feedback")
async def list_feedback(_: dict = Depends(require_admin)):
    with _webui_db() as c:
        rows = c.execute(
            "SELECT f.id,f.user_id,f.type,f.data,f.meta,f.created_at,u.name,u.email "
            "FROM feedback f LEFT JOIN user u ON u.id=f.user_id ORDER BY f.created_at DESC"
        ).fetchall()
    items = []
    for r in rows:
        try:
            data = json.loads(r["data"] or "{}")
        except Exception:
            data = {}
        try:
            meta = json.loads(r["meta"] or "{}")
        except Exception:
            meta = {}
        rating = data.get("rating")
        items.append({
            "id": r["id"],
            "created": _ts(r["created_at"]),
            "user_name": r["name"] or "?",
            "user_email": r["email"] or "",
            "rating": "👍" if rating == 1 else "👎" if rating == -1 else "—",
            "reason": data.get("reason", ""),
            "comment": data.get("comment", ""),
            "model_id": data.get("model_id", ""),
            "chat_id": meta.get("chat_id", ""),
            "message_id": meta.get("message_id", ""),
        })
    return {"count": len(items), "items": items}


@router.get("/", response_class=HTMLResponse)
async def admin_page():
    return HTMLResponse(ADMIN_HTML)


ADMIN_HTML = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>İTO Asistan — Veri Paneli</title>
<style>
  :root { --fg:#1a1a1a; --bg:#fafafa; --mut:#666; --line:#ddd; --accent:#0a7cff; }
  body { font-family: system-ui,-apple-system,Segoe UI,Roboto,sans-serif; margin:0; background:var(--bg); color:var(--fg); }
  header { padding:12px 20px; background:#fff; border-bottom:1px solid var(--line); display:flex; gap:12px; align-items:center; }
  header h1 { margin:0; font-size:16px; font-weight:600; }
  header .spacer { flex:1; }
  header .user { color:var(--mut); font-size:13px; }
  .wrap { display:grid; grid-template-columns: 320px 1fr; gap:0; height: calc(100vh - 53px); }
  .sidebar { border-right:1px solid var(--line); background:#fff; overflow:auto; padding:12px; }
  .main { overflow:auto; padding:20px; }
  .stat { padding:10px; border:1px solid var(--line); border-radius:6px; margin-bottom:8px; cursor:pointer; background:#fff; }
  .stat.active { border-color:var(--accent); background:#eef5ff; }
  .stat .t { font-weight:600; }
  .stat .n { color:var(--mut); font-size:12px; }
  input[type=text] { width:100%; padding:8px 10px; border:1px solid var(--line); border-radius:6px; box-sizing:border-box; font-size:14px; }
  table { width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:6px; overflow:hidden; }
  th,td { padding:8px 12px; text-align:left; border-bottom:1px solid var(--line); font-size:13px; vertical-align:top; }
  th { background:#f2f2f2; font-weight:600; position:sticky; top:0; }
  tr.doc:hover { background:#fafbfd; cursor:pointer; }
  .type-badge { display:inline-block; padding:2px 6px; background:#e8eef7; border-radius:3px; font-size:11px; color:#345; }
  .chunk { background:#fff; border:1px solid var(--line); border-radius:6px; padding:12px; margin-bottom:10px; font-size:13px; white-space:pre-wrap; }
  .chunk .idx { color:var(--mut); font-size:11px; margin-bottom:6px; }
  .btn { background:var(--accent); color:#fff; border:0; padding:8px 14px; border-radius:6px; cursor:pointer; font-size:13px; }
  .btn.alt { background:#eee; color:#333; }
  .tab { background:transparent; border:0; padding:8px 12px; font-size:13px; color:var(--mut); cursor:pointer; border-bottom:2px solid transparent; }
  .tab.active { color:var(--accent); border-bottom-color:var(--accent); font-weight:600; }
  .msg-user { background:#eef5ff; border-left:3px solid var(--accent); padding:10px 12px; margin:8px 0; border-radius:4px; white-space:pre-wrap; font-size:13px; }
  .msg-asst { background:#fff; border:1px solid var(--line); padding:10px 12px; margin:8px 0; border-radius:4px; white-space:pre-wrap; font-size:13px; }
  .msg-meta { color:var(--mut); font-size:11px; margin-bottom:4px; }
  a { color:var(--accent); text-decoration:none; }
  a:hover { text-decoration:underline; }
  #login { max-width:400px; margin:80px auto; background:#fff; padding:24px; border:1px solid var(--line); border-radius:8px; }
  #login h2 { margin:0 0 12px; font-size:18px; }
  #login p { color:var(--mut); font-size:13px; margin:0 0 16px; }
  #login input { margin-bottom:12px; }
  .err { color:#c00; font-size:13px; margin-top:8px; }
  .mut { color:var(--mut); }
</style>
</head>
<body>
<div id="login">
  <h2>Giriş</h2>
  <p>Open WebUI API anahtarınızı girin. (Ayarlar → Hesap → API Anahtarları)</p>
  <input type="password" id="token" placeholder="sk-...">
  <button class="btn" onclick="login()">Giriş</button>
  <div id="loginErr" class="err"></div>
</div>
<div id="app" style="display:none">
  <header>
    <h1>İTO Asistan · Veri Paneli</h1>
    <nav style="display:flex;gap:4px;margin-left:24px">
      <button class="tab" data-tab="docs" onclick="switchTab('docs')">Dokümanlar</button>
      <button class="tab" data-tab="users" onclick="switchTab('users')">Kullanıcılar</button>
      <button class="tab" data-tab="chats" onclick="switchTab('chats')">Sohbetler</button>
      <button class="tab" data-tab="feedback" onclick="switchTab('feedback')">Geri Bildirimler</button>
    </nav>
    <div class="spacer"></div>
    <span class="user" id="userInfo"></span>
    <button class="btn alt" onclick="logout()">Çıkış</button>
  </header>
  <div class="wrap" id="docsView">
    <aside class="sidebar">
      <div id="stats"></div>
      <div style="margin-top:16px">
        <input type="text" id="q" placeholder="Başlık ara…" oninput="debouncedSearch()">
      </div>
    </aside>
    <main class="main" id="main">
      <div class="mut">Yükleniyor…</div>
    </main>
  </div>
  <main class="main" id="genericView" style="display:none; height: calc(100vh - 53px); overflow:auto">
    <div class="mut">Yükleniyor…</div>
  </main>
</div>
<script>
const TOKEN_KEY = 'airegs_admin_token';
let state = { token: localStorage.getItem(TOKEN_KEY) || '', type: null, q: '', stats: null };

async function api(path) {
  const r = await fetch(path, { headers: { Authorization: 'Bearer ' + state.token } });
  if (r.status === 401 || r.status === 403) { logout(); throw new Error('auth'); }
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

function logout() { localStorage.removeItem(TOKEN_KEY); location.reload(); }

async function login() {
  const t = document.getElementById('token').value.trim();
  if (!t) return;
  state.token = t;
  try {
    const s = await api('api/stats');
    localStorage.setItem(TOKEN_KEY, t);
    state.stats = s;
    showApp();
  } catch (e) {
    document.getElementById('loginErr').textContent = 'Geçersiz token veya admin değilsiniz.';
  }
}

async function showApp() {
  document.getElementById('login').style.display = 'none';
  document.getElementById('app').style.display = 'block';
  switchTab('docs');
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab===name));
  const docsView = document.getElementById('docsView');
  const gen = document.getElementById('genericView');
  if (name==='docs') {
    docsView.style.display = 'grid'; gen.style.display = 'none';
    if (!state.stats) api('api/stats').then(s => { state.stats=s; renderStats(); loadDocs(); });
    else { renderStats(); loadDocs(); }
    return;
  }
  docsView.style.display = 'none'; gen.style.display = 'block';
  gen.innerHTML = '<div class="mut">Yükleniyor…</div>';
  if (name==='users') loadUsers();
  else if (name==='chats') loadChats();
  else if (name==='feedback') loadFeedback();
}

async function loadUsers() {
  const d = await api('api/users');
  const gen = document.getElementById('genericView');
  let html = '<div class="mut" style="margin-bottom:10px">' + d.count + ' kullanıcı</div>';
  html += '<table><thead><tr><th>Ad</th><th>E-posta</th><th>Rol</th><th>Sohbet</th><th>Kayıt</th></tr></thead><tbody>';
  for (const u of d.items) {
    html += '<tr><td>' + esc(u.name) + '</td><td>' + esc(u.email) + '</td><td><span class="type-badge">' + esc(u.role) + '</span></td>';
    html += '<td><a href="#" onclick="filterChats(\'' + u.id + '\',\'' + esc(u.name).replace(/\'/g,"\\\\\'") + '\');return false">' + u.chats + '</a></td>';
    html += '<td>' + esc(u.created) + '</td></tr>';
  }
  html += '</tbody></table>';
  gen.innerHTML = html;
}

function filterChats(uid, name) {
  state.chatFilter = { user_id: uid, name };
  switchTab('chats');
}

async function loadChats() {
  const gen = document.getElementById('genericView');
  const params = new URLSearchParams();
  if (state.chatFilter && state.chatFilter.user_id) params.set('user_id', state.chatFilter.user_id);
  const d = await api('api/chats' + (params.toString() ? '?' + params : ''));
  let html = '';
  if (state.chatFilter && state.chatFilter.user_id) {
    html += '<div style="margin-bottom:10px"><button class="btn alt" onclick="state.chatFilter=null;loadChats()">← Tüm sohbetler</button> <span class="mut">Filtre: ' + esc(state.chatFilter.name) + '</span></div>';
  }
  html += '<div class="mut" style="margin-bottom:10px">' + d.count + ' sohbet</div>';
  html += '<table><thead><tr><th>Tarih</th><th>Kullanıcı</th><th>Başlık</th></tr></thead><tbody>';
  for (const ch of d.items) {
    html += '<tr class="doc" onclick="openChat(\'' + ch.id + '\')"><td>' + esc(ch.created) + '</td><td>' + esc(ch.user_name) + '</td><td>' + esc(ch.title) + '</td></tr>';
  }
  html += '</tbody></table>';
  gen.innerHTML = html;
}

async function openChat(id) {
  const gen = document.getElementById('genericView');
  gen.innerHTML = '<div class="mut">Yükleniyor…</div>';
  const d = await api('api/chats/' + id);
  let html = '<button class="btn alt" onclick="loadChats()">← Geri</button>';
  html += '<h2 style="margin:16px 0 4px">' + esc(d.title) + '</h2>';
  html += '<div class="mut" style="margin-bottom:16px">' + esc(d.user_name) + ' · ' + esc(d.user_email) + ' · ' + esc(d.created) + '</div>';
  for (const m of d.messages) {
    const cls = m.role === 'user' ? 'msg-user' : 'msg-asst';
    html += '<div class="' + cls + '"><div class="msg-meta">' + esc(m.role) + (m.timestamp ? ' · ' + esc(m.timestamp) : '') + '</div>' + esc(m.content) + '</div>';
  }
  gen.innerHTML = html;
}

async function loadFeedback() {
  const d = await api('api/feedback');
  const gen = document.getElementById('genericView');
  let html = '<div class="mut" style="margin-bottom:10px">' + d.count + ' geri bildirim</div>';
  html += '<table><thead><tr><th>Tarih</th><th>Kullanıcı</th><th></th><th>Sebep</th><th>Yorum</th><th>Model</th><th>Sohbet</th></tr></thead><tbody>';
  for (const f of d.items) {
    const chatLink = f.chat_id ? '<a href="#" onclick="openChat(\'' + f.chat_id + '\');return false">aç ↗</a>' : '';
    html += '<tr><td>' + esc(f.created) + '</td><td>' + esc(f.user_name) + '</td><td style="font-size:16px">' + f.rating + '</td><td>' + esc(f.reason) + '</td><td>' + esc(f.comment) + '</td><td>' + esc(f.model_id) + '</td><td>' + chatLink + '</td></tr>';
  }
  html += '</tbody></table>';
  gen.innerHTML = html;
}

function renderStats() {
  const el = document.getElementById('stats');
  const total = state.stats.total_docs + ' doküman · ' + state.stats.total_chunks + ' chunk';
  let html = '<div class="stat ' + (state.type===null?'active':'') + '" onclick="filterType(null)"><div class="t">Tümü</div><div class="n">' + total + '</div></div>';
  for (const b of state.stats.by_type) {
    html += '<div class="stat ' + (state.type===b.type?'active':'') + '" onclick="filterType(\'' + b.type + '\')"><div class="t">' + b.type + '</div><div class="n">' + b.docs + ' doküman · ' + b.chunks + ' chunk</div></div>';
  }
  el.innerHTML = html;
}

function filterType(t) { state.type = t; renderStats(); loadDocs(); }

let searchTimer;
function debouncedSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = document.getElementById('q').value; loadDocs(); }, 250);
}

async function loadDocs() {
  const m = document.getElementById('main');
  m.innerHTML = '<div class="mut">Yükleniyor…</div>';
  const params = new URLSearchParams();
  if (state.type) params.set('doc_type', state.type);
  if (state.q) params.set('q', state.q);
  const data = await api('api/documents?' + params);
  let html = '<div class="mut" style="margin-bottom:10px">' + data.count + ' doküman</div>';
  html += '<table><thead><tr><th>Başlık</th><th>Tür</th><th>Chunk</th><th>Kaynak</th></tr></thead><tbody>';
  for (const d of data.items) {
    const url = d.url ? '<a href="' + d.url + '" target="_blank" onclick="event.stopPropagation()">↗</a>' : '';
    html += '<tr class="doc" onclick="openDoc(\'' + d.id + '\')"><td>' + esc(d.title) + '</td><td><span class="type-badge">' + d.doc_type + '</span></td><td>' + d.chunks + '</td><td>' + url + '</td></tr>';
  }
  html += '</tbody></table>';
  m.innerHTML = html;
}

async function openDoc(id) {
  const m = document.getElementById('main');
  m.innerHTML = '<div class="mut">Yükleniyor…</div>';
  const d = await api('api/documents/' + id);
  let html = '<button class="btn alt" onclick="loadDocs()">← Geri</button>';
  html += '<h2 style="margin:16px 0 4px">' + esc(d.title) + '</h2>';
  html += '<div class="mut" style="margin-bottom:16px">';
  html += '<span class="type-badge">' + d.doc_type + '</span> · ' + d.chunks.length + ' chunk';
  if (d.url) html += ' · <a href="' + d.url + '" target="_blank">Kaynak ↗</a>';
  html += '</div>';
  for (const c of d.chunks) {
    html += '<div class="chunk"><div class="idx">Chunk #' + c.index + '</div>' + esc(c.text) + '</div>';
  }
  m.innerHTML = html;
}

function esc(s) { return (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function userShow(u) { document.getElementById('userInfo').textContent = u; }

if (state.token) { showApp().catch(()=>{ document.getElementById('login').style.display='block'; document.getElementById('app').style.display='none'; }); }
</script>
</body>
</html>
"""
