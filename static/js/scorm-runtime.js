/* SCORM Classroom Bridge runtime: SCORM 1.2 + SCORM 2004 */
(function () {
  'use strict';
  const cfg = window.SCORM_BRIDGE_CONFIG || {};
  let state = Object.assign({}, cfg.initialState || {});
  let initialized = false;
  let terminated = false;
  let lastError = '0';
  let saveTimer = null;

  const errorStrings12 = {
    '0':'No error','101':'General exception','201':'Invalid argument error','202':'Element cannot have children',
    '203':'Element not an array - cannot have count','301':'Not initialized','401':'Not implemented error',
    '402':'Invalid set value, element is a keyword','403':'Element is read only','404':'Element is write only','405':'Incorrect data type'
  };
  const errorStrings2004 = {
    '0':'No error','101':'General exception','102':'General initialization failure','103':'Already initialized','104':'Content instance terminated',
    '111':'General termination failure','112':'Termination before initialization','113':'Termination after termination','122':'Retrieve data before initialization',
    '123':'Retrieve data after termination','132':'Store data before initialization','133':'Store data after termination','142':'Commit before initialization',
    '143':'Commit after termination','201':'General argument error','301':'General get failure','351':'General set failure','391':'General commit failure',
    '401':'Undefined data model element','402':'Unimplemented data model element','403':'Data model element value not initialized','404':'Data model element is read only',
    '405':'Data model element is write only','406':'Data model element type mismatch','407':'Data model element value out of range','408':'Data model dependency not established'
  };

  function setErr(code){ lastError = String(code); }
  function getValue(key){ return Object.prototype.hasOwnProperty.call(state,key) ? String(state[key]) : ''; }
  function setValue(key,value){ state[key] = String(value); setErr('0'); scheduleSave(); return 'true'; }
  function scheduleSave(){
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => persist(false), 800);
  }
  async function persist(finished){
    if (!cfg.stateUrl) return true;
    clearTimeout(saveTimer);
    try {
      const res = await fetch(cfg.stateUrl, {
        method:'POST', headers:{'Content-Type':'application/json'},
        credentials:'same-origin', keepalive:!!finished,
        body:JSON.stringify({state, finished:!!finished})
      });
      if (!res.ok) throw new Error('HTTP '+res.status);
      const data = await res.json();
      window.dispatchEvent(new CustomEvent('scormbridge:save',{detail:data}));
      return true;
    } catch (e) {
      console.error('SCORM Bridge save error', e);
      return false;
    }
  }

  const API12 = {
    LMSInitialize: function(){ if(initialized){setErr('101');return 'false';} initialized=true;terminated=false;setErr('0');return 'true'; },
    LMSFinish: function(){ if(!initialized){setErr('301');return 'false';} terminated=true;persist(true);setErr('0');return 'true'; },
    LMSGetValue: function(k){ if(!initialized){setErr('301');return '';} setErr('0');return getValue(k); },
    LMSSetValue: function(k,v){ if(!initialized){setErr('301');return 'false';} return setValue(k,v); },
    LMSCommit: function(){ if(!initialized){setErr('301');return 'false';} persist(false);setErr('0');return 'true'; },
    LMSGetLastError: function(){ return lastError; },
    LMSGetErrorString: function(c){ return errorStrings12[String(c)] || 'Unknown error'; },
    LMSGetDiagnostic: function(c){ return errorStrings12[String(c || lastError)] || ''; }
  };

  const API2004 = {
    Initialize: function(){ if(initialized){setErr('103');return 'false';} initialized=true;terminated=false;setErr('0');return 'true'; },
    Terminate: function(){ if(!initialized){setErr('112');return 'false';} if(terminated){setErr('113');return 'false';} terminated=true;persist(true);setErr('0');return 'true'; },
    GetValue: function(k){ if(!initialized){setErr('122');return '';} if(terminated){setErr('123');return '';} setErr('0');return getValue(k); },
    SetValue: function(k,v){ if(!initialized){setErr('132');return 'false';} if(terminated){setErr('133');return 'false';} return setValue(k,v); },
    Commit: function(){ if(!initialized){setErr('142');return 'false';} if(terminated){setErr('143');return 'false';} persist(false);setErr('0');return 'true'; },
    GetLastError: function(){ return lastError; },
    GetErrorString: function(c){ return errorStrings2004[String(c)] || 'Unknown error'; },
    GetDiagnostic: function(c){ return errorStrings2004[String(c || lastError)] || ''; }
  };

  // SCORM SCOs search window parents for these exact global names.
  window.API = API12;
  window.API_1484_11 = API2004;
  window.SCORMBridge = {
    getState:()=>Object.assign({},state),
    save:()=>persist(false),
    finish:()=>persist(true),
    set:(k,v)=>setValue(k,v)
  };

  window.addEventListener('pagehide', () => persist(false));
})();
