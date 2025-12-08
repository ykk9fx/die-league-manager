(async function(){
  try{
    const r = await fetch('/api/league');
    if(r.status===200){
      const span = document.getElementById('whoami');
      if(span) span.textContent = 'Signed in';
    }
  }catch{}
  document.getElementById('logoutBtn')?.addEventListener('click', async ()=>{
    await fetch('/api/auth/logout',{method:'POST'});
    location.href = '/static/index.html';
  });
})();