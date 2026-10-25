export let csrf='';
export function setCsrf(value:string){csrf=value;}
export async function api(path:string,method='GET',body?:unknown){
 const isForm=body instanceof FormData;
 const r=await fetch('/api/v1'+path,{method,credentials:'same-origin',headers:{...(isForm?{}:{'Content-Type':'application/json'}),'X-CSRF-Token':csrf},body:body===undefined?undefined:isForm?body:JSON.stringify(body)});
 if(!r.ok){let e;try{e=await r.json()}catch{e={detail:'Service unavailable'}}throw new Error(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail));}
 return r.status===204?{}:r.json();
}
export function download(path:string){window.open('/api/v1'+path,'_blank','noopener');}
