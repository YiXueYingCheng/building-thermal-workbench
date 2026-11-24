/* A receipt is valid only after the server checks the current files and registrations. */
class RecentViewReader {
 constructor(){this.entries=new Map();this.pending=new Map();}
 read(key,force,fetchView){
  const active=this.pending.get(key);
  if(active&&(!force||active.force))return active.promise;
  const previous=this.entries.get(key);
  const request={force};
  const promise=Promise.resolve().then(()=>fetchView(force?null:previous?.view_token)).then(receipt=>{
   const summary=receipt.summary??(receipt.view_token===previous?.view_token?previous?.summary:null);
   if(!summary)throw Error('缺少对应的已核验结果，请重新读取。');
   const view={...receipt,summary};
   if(this.pending.get(key)===request){
    this.entries.delete(key);
    if(view.view_token)this.entries.set(key,view);
    if(this.entries.size>3)this.entries.delete(this.entries.keys().next().value);
   }
   return view;
  }).catch(error=>{
   if(this.pending.get(key)===request)this.entries.delete(key);
   throw error;
  }).finally(()=>{if(this.pending.get(key)===request)this.pending.delete(key);});
  request.promise=promise;this.pending.set(key,request);return promise;
 }
}

// Share in-flight reads as well as finished snapshots. A failed read can be retried.
class DialogReads {
 constructor(limit){this.limit=limit;this.entries=new Map();}
 read(key,fetchValue,valid=()=>true){
  const saved=this.entries.get(key);
  if(saved && (!saved.ready || valid(saved.value))){
   this.entries.delete(key);this.entries.set(key,saved);
   return saved.promise;
  }
  const entry={ready:false};
  this.entries.set(key,entry);
  entry.promise=Promise.resolve().then(fetchValue).then(value=>{
   entry.value=value;entry.ready=true;
   for(const [id,item] of this.entries){
    if(this.entries.size<=this.limit)break;
    if(item.ready)this.entries.delete(id);
   }
   return value;
  }).catch(error=>{
   if(this.entries.get(key)===entry)this.entries.delete(key);
   throw error;
  });
  return entry.promise;
 }
}
