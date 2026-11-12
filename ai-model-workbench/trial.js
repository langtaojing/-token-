const byId = (id) => document.getElementById(id);
function selectSection(kind, name){const sectionAttr=kind==="admin"?"data-admin-section":"data-user-section";const buttonAttr=kind==="admin"?"data-admin-view":"data-view";document.querySelectorAll("["+sectionAttr+"]").forEach(el=>el.classList.toggle("trial-hidden",el.getAttribute(sectionAttr)!==name));document.querySelectorAll("["+buttonAttr+"]").forEach(el=>el.classList.toggle("active",el.getAttribute(buttonAttr)===name));if(kind==="admin"&&name==="network")loadNetworkHistory()}
document.querySelectorAll("[data-view]").forEach(button=>button.onclick=()=>selectSection("user",button.dataset.view));
document.querySelectorAll("[data-admin-view]").forEach(button=>button.onclick=()=>selectSection("admin",button.dataset.adminView));
async function api(path, options = {}) { const response = await fetch(path, { credentials: "include", headers: { "Content-Type": "application/json" }, ...options }); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || "请求失败"); return data; }
function setTab(register) { byId("login-form").classList.toggle("trial-hidden", register); byId("register-form").classList.toggle("trial-hidden", !register); byId("show-login").classList.toggle("active", !register); byId("show-register").classList.toggle("active", register); }
async function loadAdmin() { try { const data = await api("/api/admin/users"); byId("admin-panel").classList.remove("trial-hidden"); const container=byId("admin-users"); container.replaceChildren(); data.users.forEach(function(u){ const row=document.createElement("div"); row.className="admin-user"; const name=document.createElement("b"); name.textContent=u.username; const status=document.createElement("span"); status.textContent=u.role+" · "+(u.active?"启用":"停用"); const requests=document.createElement("input"); requests.type="number"; requests.min="1"; requests.max="1000"; requests.value=u.daily_requests; const tokens=document.createElement("input"); tokens.type="number"; tokens.min="1"; tokens.max="1000000"; tokens.value=u.daily_tokens; const save=document.createElement("button"); save.className="trial-btn secondary"; save.textContent="保存额度"; save.onclick=async()=>{try{await api("/api/admin/users/"+u.id,{method:"PATCH",body:JSON.stringify({daily_requests:Number(requests.value),daily_tokens:Number(tokens.value)})}); await loadAdmin()}catch(e){alert(e.message)}}; row.append(name,status,"请求",requests,"Token",tokens,save); if(u.role!=="admin"){const toggle=document.createElement("button"); toggle.className="trial-btn secondary"; toggle.textContent=u.active?"停用":"启用"; toggle.onclick=async()=>{try{await api("/api/admin/users/"+u.id,{method:"PATCH",body:JSON.stringify({daily_requests:Number(requests.value),daily_tokens:Number(tokens.value),active:!u.active})}); await loadAdmin()}catch(e){alert(e.message)}};row.append(toggle)} container.append(row) }) } catch { byId("admin-panel").classList.add("trial-hidden"); } }


byId("analyze-image-btn")?.addEventListener("click",async()=>{const input=byId("image-input");if(!input.files.length)return;const body=new FormData();body.append("file",input.files[0]);body.append("prompt",byId("image-prompt").value||"请分析这张图片，描述重要内容、文字和上下文。");const button=byId("analyze-image-btn");const result=byId("image-result");button.disabled=true;result.classList.remove("trial-hidden");result.textContent="图片分析中…";try{const r=await fetch("/api/analyze-image",{method:"POST",credentials:"include",body});const data=await r.json();if(!r.ok)throw Error(data.detail||"图片分析失败");result.textContent="【"+data.model+" · 图片分析】\nToken："+data.usage.total_tokens+" · 耗时："+data.latency_ms+"ms\n\n"+data.answer;await refreshSession()}catch(error){result.textContent="分析失败："+error.message}finally{button.disabled=false}});
async function loadFiles(){try{const data=await api("/api/files");const box=byId("file-list");box.replaceChildren();data.files.forEach(function(f){const row=document.createElement("div");row.className="file-row";const label=document.createElement("span");label.textContent=f.original_name+" · "+f.status+" · "+Math.ceil(f.size_bytes/1024)+" KB";const actions=document.createElement("span");if(["parsed"].includes(f.status)){const view=document.createElement("button");view.className="trial-btn secondary";view.textContent="解析文本";view.onclick=async()=>{const d=await api("/api/files/"+f.id+"/text");byId("result").textContent=d.text.slice(0,10000)};actions.append(view)}const del=document.createElement("button");del.className="trial-btn secondary";del.textContent="删除";del.onclick=async()=>{await api("/api/files/"+f.id,{method:"DELETE"});await loadFiles()};actions.append(del);row.append(label,actions);box.append(row)})}catch{} }
byId("template-select")?.addEventListener("change",function(){if(this.value)byId("prompt").value=this.value+"："+String.fromCharCode(10)+String.fromCharCode(10)});
byId("upload-btn")?.addEventListener("click",async()=>{const input=byId("file-input");if(!input.files.length)return;const data=new FormData();data.append("file",input.files[0]);const r=await fetch("/api/files",{method:"POST",credentials:"include",body:data});if(!r.ok){const e=await r.json().catch(()=>({detail:"上传失败"}));alert(e.detail||"上传失败");return}input.value="";await loadFiles()});

async function loadDashboard(){
  const data=await api("/api/admin/metrics");const m=data.last_24h;const net=data.provider_network;
  const metrics=byId("admin-metrics");metrics.replaceChildren();
  for(const pair of [["活跃用户",data.active_users],["24小时调用",m.calls],["成功",m.success],["失败",m.failed],["Token",m.tokens],["平均延迟",m.avg_latency_ms===null?"—":m.avg_latency_ms+"ms"],["P95延迟",m.p95_latency_ms===null?"—":m.p95_latency_ms+"ms"],["延迟样本",m.latency_samples],["TCP探测失败率",net.probe_failure_rate_pct===null?"—":net.probe_failure_rate_pct+"%"]]){
    const card=document.createElement("div");card.className="metric-card";const label=document.createElement("small");label.textContent=pair[0];const value=document.createElement("strong");value.textContent=String(pair[1]);card.append(label,value);metrics.append(card)
  }
  const usage=byId("admin-usage");usage.replaceChildren();data.per_user_today.forEach(u=>{const row=document.createElement("div");row.className="usage-row";row.textContent=u.username+" · "+u.requests+"/"+u.daily_requests+" 次 · "+u.tokens+"/"+u.daily_tokens+" Token";usage.append(row)});
}
async function loadNetworkHistory(){try{const data=await api("/api/admin/network-history");const chart=byId("network-chart");const table=byId("network-table");chart.replaceChildren();table.replaceChildren();const rows=data.samples;const valid=rows.filter(r=>r.avg_connect_ms!==null);const max=Math.max(1,...valid.map(r=>r.avg_connect_ms));rows.forEach(r=>{const col=document.createElement("div");col.className="network-col";const bar=document.createElement("div");bar.className="network-bar";bar.style.height=(r.avg_connect_ms===null?4:Math.max(4,r.avg_connect_ms/max*160))+"px";bar.title=r.sampled_at+" · "+(r.avg_connect_ms===null?"失败":r.avg_connect_ms+"ms");col.append(bar);chart.append(col);const line=document.createElement("div");line.className="usage-row";line.textContent=new Date(r.sampled_at).toLocaleString("zh-CN")+" · 连接 "+(r.avg_connect_ms===null?"失败":r.avg_connect_ms+"ms")+" · "+r.failed+"/"+r.attempts+" 次探测失败";table.append(line)});if(!rows.length)table.textContent="暂无采样记录。"}catch(error){byId("network-table").textContent=error.message}}
async function loadPlans(){const data=await api("/api/plans");const box=byId("plan-list");box.replaceChildren();data.plans.forEach(plan=>{const card=document.createElement("div");card.className="plan-card";const title=document.createElement("h3");title.textContent=plan.name;const price=document.createElement("strong");price.textContent="¥"+plan.price_cny_month+" / 月";const detail=document.createElement("p");detail.textContent=plan.daily_requests+" 次/天 · "+plan.daily_tokens.toLocaleString()+" Token/天";const button=document.createElement("button");button.className="trial-btn secondary";button.textContent="申请订购";button.onclick=async()=>{try{const order=await api("/api/plan-orders",{method:"POST",body:JSON.stringify({plan_id:plan.id})});byId("plan-message").textContent=order.notice}catch(error){byId("plan-message").textContent=error.message}};card.append(title,price,detail,button);box.append(card)})}
async function loadOrders(){const data=await api("/api/admin/plan-orders");const box=byId("admin-orders");box.replaceChildren();data.orders.forEach(order=>{const row=document.createElement("div");row.className="usage-row";const label=document.createElement("span");label.textContent=order.username+" · "+order.plan_id+" · "+order.status;row.append(label);if(order.status==="pending"){for(const approve of [true,false]){const button=document.createElement("button");button.className="trial-btn secondary";button.textContent=approve?"批准":"拒绝";button.onclick=async()=>{await api("/api/admin/plan-orders/"+order.id+"/decision",{method:"POST",body:JSON.stringify({approve})});await loadOrders();await loadDashboard()};row.append(button)}}box.append(row)})}
async function refreshSession() { try { const data=await api("/api/me"); byId("login").classList.add("trial-hidden"); byId("workspace").classList.remove("trial-hidden"); byId("identity").textContent="已登录："+data.username+" · "+(data.role==="admin"?"管理员":"试用成员"); byId("usage").textContent="今日额度："+data.requests_used+"/"+data.daily_requests+" 次请求，"+data.tokens_used+"/"+data.daily_tokens+" Token"; await loadPlans(); if(data.role==="admin"){byId("admin-nav").classList.remove("trial-hidden");byId("admin-panel").prepend(byId("admin-nav"));await loadAdmin();await loadDashboard();await loadOrders()} await loadFiles(); } catch {} }
byId("show-login").onclick=()=>setTab(false); byId("show-register").onclick=()=>setTab(true);
byId("login-btn").onclick=async()=>{const message=byId("login-msg"),button=byId("login-btn");message.textContent="";button.disabled=true;try{await api("/api/login",{method:"POST",body:JSON.stringify({username:byId("username").value.trim(),password:byId("password").value})});await refreshSession()}catch(e){message.textContent=e.message}finally{button.disabled=false}};
byId("register-btn").onclick=async()=>{const message=byId("register-msg"),button=byId("register-btn");message.textContent="";button.disabled=true;try{await api("/api/register",{method:"POST",body:JSON.stringify({username:byId("reg-username").value.trim(),password:byId("reg-password").value,repeat:byId("reg-repeat").value})});await refreshSession()}catch(e){message.textContent=e.message}finally{button.disabled=false}};
byId("logout-btn").onclick=async()=>{await api("/api/logout",{method:"POST"});location.reload()};
byId("send-btn").onclick=async()=>{const prompt=byId("prompt").value.trim();if(!prompt)return;const mode=byId("chat-mode").value;const button=byId("send-btn");button.disabled=true;byId("result").textContent=mode==="deep"?"正在规划 → 执行 → 复查…":"正在生成回答…";try{const data=await api("/api/chat",{method:"POST",body:JSON.stringify({prompt,mode})});byId("result").textContent="【"+data.model+" · "+(mode==="deep"?"深度处理":"快速回答")+"】\n阶段："+(data.stages||[]).join(" → ")+"\nToken："+data.usage.total_tokens+" · 耗时："+data.latency_ms+"ms\n\n"+data.answer;await refreshSession()}catch(e){byId("result").textContent="请求失败："+e.message}finally{button.disabled=false}};refreshSession();
setInterval(()=>{if(!byId("admin-panel").classList.contains("trial-hidden")){if(!document.querySelector('[data-admin-section="network"]').classList.contains("trial-hidden"))loadNetworkHistory();else loadDashboard()}},30*60*1000);

/* ---------- 语音输入：浏览器本机采集 → 16 kHz 单声道 WAV → MiniMax asr-1.0 转写 ---------- */
(function () {
  const button = byId("mic-btn");
  const status = byId("voice-status");
  if (!button || !status) return;

  const MAX_SECONDS = 60;
  const TARGET_RATE = 16000;
  let recorder = null, stream = null, chunks = [], timer = null, seconds = 0, recording = false, busy = false;

  const pad = (n) => String(n).padStart(2, "0");
  const clock = (n) => pad(Math.floor(n / 60)) + ":" + pad(n % 60);
  const say = (text, tone) => { status.textContent = text; status.className = "trial-muted" + (tone ? " voice-" + tone : ""); };
  const supported = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder && (window.AudioContext || window.webkitAudioContext));

  function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const write = (offset, text) => { for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i)); };
    write(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); write(8, "WAVE");
    write(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    write(36, "data"); view.setUint32(40, samples.length * 2, true);
    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
      const sample = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
    return new Blob([view], { type: "audio/wav" });
  }

  async function toWav16k(blob) {
    const arrayBuffer = await blob.arrayBuffer();
    const Context = window.AudioContext || window.webkitAudioContext;
    const Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!Offline) throw new Error("browser-no-offline-audio");
    const context = new Context();
    let decoded;
    try { decoded = await context.decodeAudioData(arrayBuffer); } finally { context.close().catch(() => {}); }
    const frames = Math.max(1, Math.round(decoded.duration * TARGET_RATE));
    const offline = new Offline(1, frames, TARGET_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return encodeWav(rendered.getChannelData(0), TARGET_RATE);
  }

  function guessName(type) {
    if (!type) return "voice.webm";
    if (type.indexOf("wav") >= 0) return "voice.wav";
    if (type.indexOf("mp4") >= 0) return "voice.mp4";
    if (type.indexOf("ogg") >= 0) return "voice.ogg";
    return "voice.webm";
  }

  async function upload(blob, filename) {
    const form = new FormData();
    form.append("file", blob, filename);
    const response = await fetch("/api/speech-to-text", { method: "POST", credentials: "include", body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "语音识别失败");
    return data;
  }

  async function finish() {
    const raw = new Blob(chunks, { type: (recorder && recorder.mimeType) || "audio/webm" });
    chunks = [];
    busy = true;
    button.disabled = true;
    say("正在识别…", "busy");
    try {
      let payload = raw, filename = guessName(raw.type);
      try { payload = await toWav16k(raw); filename = "voice.wav"; } catch (error) { /* 浏览器转码失败时退回原始格式 */ }
      const data = await upload(payload, filename);
      const text = (data.text || "").trim();
      if (!text) { say("没有识别到语音内容，请靠近麦克风再试一次。", "error"); return; }
      byId("prompt").value = text;
      say("识别完成：" + text.length + " 字 · 耗时 " + data.latency_ms + "ms，已自动发送。", "ok");
      byId("send-btn").click();
    } catch (error) {
      say("语音识别失败：" + (error && error.message ? error.message : "请稍后重试"), "error");
    } finally {
      busy = false;
      button.disabled = false;
    }
  }

  function stop() {
    if (!recording) return;
    recording = false;
    if (timer) clearInterval(timer);
    try { if (recorder && recorder.state !== "inactive") recorder.stop(); } catch (error) { }
    if (stream) stream.getTracks().forEach((track) => track.stop());
    button.classList.remove("recording");
    button.textContent = "语音输入";
  }

  async function start() {
    if (busy || recording) return;
    if (!supported()) { say("当前浏览器不支持录音，请使用 Chrome、Edge 或 Safari。", "error"); return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (error) {
      say("无法使用麦克风：" + (error && error.name === "NotAllowedError" ? "权限被拒绝，请在地址栏允许麦克风后重试" : (error && error.message) || "未知错误"), "error");
      return;
    }
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4;codecs=mp4a.40.2", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];
    const mime = candidates.find((type) => { try { return MediaRecorder.isTypeSupported(type); } catch (error) { return false; } });
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    chunks = [];
    seconds = 0;
    recording = true;
    recorder.ondataavailable = (event) => { if (event.data && event.data.size) chunks.push(event.data); };
    recorder.onstop = () => { finish(); };
    recorder.start();
    button.classList.add("recording");
    button.textContent = "停止录音 00:00";
    say("正在录音…说完后再点一次按钮结束。", "busy");
    timer = setInterval(() => {
      seconds += 1;
      button.textContent = "停止录音 " + clock(seconds);
      if (seconds >= MAX_SECONDS) stop();
    }, 1000);
  }

  button.addEventListener("click", () => { if (recording) stop(); else start(); });
  window.addEventListener("pagehide", () => { if (timer) clearInterval(timer); if (stream) stream.getTracks().forEach((track) => track.stop()); });
})();
