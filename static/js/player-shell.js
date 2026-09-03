(function(){
  const cfg = window.SCORM_BRIDGE_CONFIG || {};
  const banner = document.getElementById('integrity-banner');
  const focusCounter = document.getElementById('focus-counter');
  let fullscreenAsked = false;
  let handlingLoss = false;
  let forcedFinish = false;

  function goExit(){
    if (cfg.exitUrl) window.location.href = cfg.exitUrl;
    else history.back();
  }

  async function logEvent(type, payload){
    if (!cfg.eventUrl || handlingLoss || forcedFinish) return;
    handlingLoss = true;
    try {
      const r = await fetch(cfg.eventUrl, {method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({type,payload:payload||{}})});
      const d = await r.json();
      if (focusCounter) focusCounter.textContent = d.focus_losses;
      if (d.should_finish) {
        forcedFinish = true;
        if (banner) { banner.hidden=false; banner.textContent='Se ha alcanzado el límite de incidencias. El intento se cerrará y quedará registrado.'; }
        await window.SCORMBridge.finish();
        setTimeout(goExit, 900);
      }
    } catch(e){ console.warn(e); }
    finally { setTimeout(()=>{handlingLoss=false;},250); }
  }

  document.addEventListener('visibilitychange',()=>{
    if(document.visibilityState==='hidden') logEvent('hidden',{at:new Date().toISOString()});
  });
  window.addEventListener('blur',()=>logEvent('blur',{at:new Date().toISOString()}));

  async function requestFullscreen(){
    if(!cfg.fullscreen || fullscreenAsked) return;
    fullscreenAsked=true;
    try { if(document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen(); }
    catch(e) { console.info('Pantalla completa no concedida',e); }
  }
  document.addEventListener('click', requestFullscreen, {once:true});

  document.getElementById('btn-fullscreen')?.addEventListener('click',()=>{
    fullscreenAsked=false; requestFullscreen();
  });

  document.getElementById('btn-save-exit')?.addEventListener('click',async()=>{
    if(cfg.mode==='exam') {
      const ok = window.confirm('¿Quieres entregar el examen y finalizar este intento?');
      if(!ok) return;
      await window.SCORMBridge.finish();
    } else {
      await window.SCORMBridge.save();
    }
    if(document.fullscreenElement) { try{ await document.exitFullscreen(); }catch(e){} }
    goExit();
  });

  window.addEventListener('scormbridge:save',(ev)=>{
    const d=ev.detail||{};
    const score=document.getElementById('live-score');
    const status=document.getElementById('live-status');
    if(score && d.score!==null && d.score!==undefined) score.textContent=Number(d.score).toFixed(1)+'%';
    if(status && d.status) status.textContent=d.status;
  });
})();
