const API = {
  async json(url, opts={}){
    const res = await fetch(url, {...opts, headers:{'Content-Type':'application/json', ...(opts.headers||{})}});
    const text = await res.text();
    try{
      const data = text ? JSON.parse(text) : null;
      if(!res.ok) throw Object.assign(new Error(data?.error||res.statusText), {status:res.status, body:data});
      return data;
    }catch(e){
      if(!res.ok) throw Object.assign(new Error(text||res.statusText), {status:res.status});
      throw e;
    }
  },
  get(url){return this.json(url)},
  post(url, body){return this.json(url, {method:'POST', body:JSON.stringify(body)})},
  put(url, body){return this.json(url, {method:'PUT', body:JSON.stringify(body)})},
  del(url){return this.json(url, {method:'DELETE'})}
};
window.API = API;
