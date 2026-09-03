function closeAddonIframe(){
  window.parent.postMessage({type:'Classroom',action:'closeIframe'}, '*');
}
function openGoogleLogin(url){
  window.open(url, '_blank', 'noopener=false');
}
