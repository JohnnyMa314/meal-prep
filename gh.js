// gh.js — save source files straight to GitHub from the browser.
//
// Writing to the repo needs a GitHub token. You create it yourself and paste it
// here; it is stored ONLY in this browser's localStorage on this device, is never
// sent anywhere except api.github.com, and you can clear or revoke it any time.
//
// Make one at: github.com/settings/personal-access-tokens  (Fine-grained token)
//   Repository access : Only select repositories -> meal-prep
//   Permissions       : Repository permissions -> Contents -> Read and write
// Nothing else. That token can touch this one repo and nothing else in your account.
//
// A save commits the changed src/*.json files. The Build workflow then recompiles
// data.json + grocery.json, validates them, and commits the result — so the app
// and the iOS widget pick the change up on their own within a minute or so.

const GH = {
  repo: "JohnnyMa314/meal-prep",
  branch: "main",
  KEY: "mp1::ghtoken",

  token() { try { return localStorage.getItem(this.KEY) || ""; } catch (e) { return ""; } },
  setToken(t) { try { localStorage.setItem(this.KEY, t.trim()); } catch (e) {} },
  clearToken() { try { localStorage.removeItem(this.KEY); } catch (e) {} },
  hasToken() { return !!this.token(); },

  _b64(str) {                                   // unicode-safe base64
    const bytes = new TextEncoder().encode(str);
    let bin = "";
    bytes.forEach(b => { bin += String.fromCharCode(b); });
    return btoa(bin);
  },

  async _api(path, opts = {}) {
    const res = await fetch(`https://api.github.com/repos/${this.repo}/${path}`, {
      ...opts,
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${this.token()}`,
        "X-GitHub-Api-Version": "2022-11-28",
        ...(opts.headers || {})
      }
    });
    return res;
  },

  async _sha(path) {
    const res = await this._api(`contents/${path}?ref=${this.branch}`);
    if (res.status === 404) return null;              // new file
    if (!res.ok) throw new Error(await this._msg(res));
    return (await res.json()).sha;
  },

  async _msg(res) {
    let d = {};
    try { d = await res.json(); } catch (e) {}
    if (res.status === 401) return "Token rejected (401). It may be expired or mistyped.";
    if (res.status === 403) return "Forbidden (403). The token likely lacks Contents: read and write on this repo.";
    if (res.status === 404) return "Not found (404). Check the token has access to this repository.";
    return `${res.status} ${d.message || res.statusText}`;
  },

  // files: { "src/week.json": "<contents>", ... }
  async save(files, message) {
    if (!this.hasToken()) throw new Error("No token set.");
    const done = [];
    for (const [path, content] of Object.entries(files)) {
      let sha = await this._sha(path);
      let res = await this._put(path, content, message, sha);
      if (res.status === 409) {                        // someone else moved it — retry once
        sha = await this._sha(path);
        res = await this._put(path, content, message, sha);
      }
      if (!res.ok) throw new Error(`${path}: ${await this._msg(res)}`);
      done.push(path);
    }
    return done;
  },

  _put(path, content, message, sha) {
    return this._api(`contents/${path}`, {
      method: "PUT",
      body: JSON.stringify({
        message, branch: this.branch, content: this._b64(content),
        ...(sha ? { sha } : {})
      })
    });
  },

  async runsUrl() { return `https://github.com/${this.repo}/actions`; },

  // ---- UI -------------------------------------------------------------
  // mount: element to append the button to
  // getFiles: () => ({path: contents}) — called at save time
  // opts: { label, message, onSaved }
  mount(mountEl, getFiles, opts = {}) {
    const btn = document.createElement("button");
    btn.textContent = opts.label || "Save to GitHub";
    btn.className = opts.className || "primary";
    const gear = document.createElement("button");
    gear.textContent = "⚙";
    gear.title = "GitHub token settings";
    gear.style.padding = "8px 10px";

    const status = document.createElement("span");
    status.style.cssText = "font-size:.74rem;font-weight:600;margin-left:2px";

    const say = (msg, color) => { status.textContent = msg; status.style.color = color || "var(--muted)"; };

    btn.onclick = async () => {
      if (!this.hasToken()) return this.tokenPanel(() => btn.click());
      const files = getFiles();
      if (!files || !Object.keys(files).length) return say("nothing changed", "var(--muted)");
      btn.disabled = true; say("saving…");
      try {
        const done = await this.save(files, opts.message || "Update meal plan from the web UI");
        say(`✓ saved ${done.length} file${done.length === 1 ? "" : "s"} — rebuilding…`, "var(--ok)");
        if (opts.onSaved) opts.onSaved(done);
        setTimeout(() => say("✓ saved · app updates in ~1 min", "var(--ok)"), 4000);
      } catch (e) {
        say("✕ " + (e.message || e), "var(--bad)");
      } finally { btn.disabled = false; }
    };
    gear.onclick = () => this.tokenPanel();

    mountEl.appendChild(btn);
    mountEl.appendChild(gear);
    mountEl.appendChild(status);
    return { btn, say };
  },

  tokenPanel(after) {
    const back = document.createElement("div");
    back.style.cssText = "position:fixed;inset:0;background:rgba(32,31,26,.45);z-index:99;display:grid;place-items:center;padding:16px";
    const has = this.hasToken();
    back.innerHTML = `<div style="background:var(--card);border:1px solid var(--line);border-radius:14px;max-width:560px;width:100%;padding:18px;font-size:.88rem">
      <h3 style="margin:0 0 8px;font-size:1rem">GitHub token</h3>
      <p style="color:var(--muted);line-height:1.5;margin:0 0 10px">
        Saving commits to <b>${this.repo}</b>. Create a <b>fine-grained</b> token with access to
        <b>only this repository</b> and <b>Contents: Read and write</b> — nothing else.
        It is stored in this browser only and never leaves your device except to call api.github.com.
      </p>
      <p style="margin:0 0 10px"><a href="https://github.com/settings/personal-access-tokens" target="_blank" rel="noopener"
         style="color:var(--him);font-weight:600">Create a token ↗</a></p>
      <input id="ghTok" type="password" placeholder="${has ? "•••••••• (a token is saved)" : "github_pat_…"}"
        style="width:100%;font:inherit;font-family:var(--num);font-size:.8rem;padding:9px;border:1px solid var(--line);border-radius:9px;background:var(--paper);color:var(--ink)">
      <div id="ghErr" style="color:var(--bad);font-size:.78rem;margin-top:6px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;flex-wrap:wrap">
        ${has ? '<button id="ghClear" style="color:var(--bad)">Remove saved token</button>' : ""}
        <button id="ghCancel">Cancel</button>
        <button id="ghSave" class="primary">Check &amp; save token</button>
      </div></div>`;
    document.body.appendChild(back);
    const close = () => back.remove();
    back.onclick = e => { if (e.target === back) close(); };
    back.querySelector("#ghCancel").onclick = close;
    const clr = back.querySelector("#ghClear");
    if (clr) clr.onclick = () => { this.clearToken(); close(); };
    back.querySelector("#ghSave").onclick = async () => {
      const v = back.querySelector("#ghTok").value.trim();
      const err = back.querySelector("#ghErr");
      if (!v) { err.textContent = "Paste a token first."; return; }
      this.setToken(v);
      err.style.color = "var(--muted)"; err.textContent = "checking…";
      const res = await this._api(`contents/src/week.json?ref=${this.branch}`);
      if (!res.ok) { err.style.color = "var(--bad)"; err.textContent = await this._msg(res); this.clearToken(); return; }
      close();
      if (after) after();
    };
    setTimeout(() => back.querySelector("#ghTok").focus(), 30);
  }
};
