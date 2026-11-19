/* Display old snapshot labels without changing record names, form values, or evidence. */
const opticalLegacyTerms=/翻面|换面|面朝外|固定 [AB] 面|固定蓬松 A 面|反馈加翻面|A 面固定时|朝向按日历/;
function opticalText(value){
 const text=String(value??'');
 if(!opticalLegacyTerms.test(text))return text;
 return text.replace(/朝向按日历/g,'季节光学切换').replace(/翻面[＋+]热阻反馈|反馈加翻面/g,'表面光学切换＋热阻调节')
  .replace(/翻面日历/g,'光学切换日历').replace(/季节翻面/g,'季节光学切换')
  .replace(/按(日历|参考日历)(?:翻面|换面)/g,'按$1切换表面光学参数')
  .replace(/翻面 ECA/g,'ECA 表面光学切换').replace(/材料翻面|翻面|换面/g,'表面光学切换')
  .replace(/固定蓬松 A 面/g,'固定蓬松、固定 A').replace(/固定 ([AB]) 面/g,'固定 $1')
  .replace(/固定 A[＋+]热阻反馈/g,'固定 A＋热阻调节')
  .replace(/A 面固定时的热阻反馈贡献/g,'固定 A 时的热阻调节贡献')
  .replace(/([AB]) 面朝外时间占比/g,'采用 $1 的时间占比')
  .replace(/([AB]) 面朝外/g,'固定 $1').replace(/制冷面朝外/g,'固定 A').replace(/供暖面朝外/g,'固定 B');
}
function opticalSearch(labels,query){
 const text=labels.filter(x=>x!=null).join(' ');
 const needle=query.toLocaleLowerCase();
 return text.toLocaleLowerCase().includes(needle)||opticalText(text).toLocaleLowerCase().includes(opticalText(query).toLocaleLowerCase());
}
(() => {
 const raw='pre,code,script,style,textarea,input,[contenteditable]:not([contenteditable="false"]),[data-verbatim],option:not([value])';
 const attributes=['title','aria-label'];
 const legacyAttributeSelector=attributes.flatMap(key=>['翻面','换面','面朝外','固定 A 面','固定 B 面','固定蓬松 A 面','A 面固定时','朝向按日历'].map(term=>'['+key+'*="'+term+'"]')).join(',');
 function label(text){
  // A file path/URL in a receipt can contain the original study name.
  if(!opticalLegacyTerms.test(text)||/[A-Za-z]:[\\/]|https?:\/\/|\.(?:epJSON|json|csv|md|zip|sql|epw|xlsx|html)\b/i.test(text))return text;
  return opticalText(text);
 }
 function textNode(node){
  if(!opticalLegacyTerms.test(node.data)||node.parentElement?.closest(raw))return;
  const changed=label(node.data);
  if(changed!==node.data)node.data=changed;
 }
 function updateAttributes(node){
  for(const key of attributes){
   const v=node.getAttribute(key);if(v){const changed=label(v);if(changed!==v)node.setAttribute(key,changed);}
  }
 }
 function visit(node){
  if(node.nodeType===Node.TEXT_NODE){textNode(node);return;}
  if(node.nodeType!==Node.ELEMENT_NODE||node.closest(raw))return;
  if(opticalLegacyTerms.test(node.textContent)){
   const walk=document.createTreeWalker(node,NodeFilter.SHOW_TEXT);
   while(walk.nextNode())textNode(walk.currentNode);
  }
  updateAttributes(node);
  for(const el of node.querySelectorAll(legacyAttributeSelector))if(!el.closest(raw))updateAttributes(el);
 }
 // Only added subtrees are scanned; the model, option values and download URLs stay original.
 const watcher=new MutationObserver(events=>{
  for(const e of events){
   if(e.type==='childList'){for(const n of e.addedNodes)if(n.isConnected)visit(n);}
   else if(e.type==='characterData')visit(e.target);
   else {
    const el=e.target,v=el.getAttribute(e.attributeName);
    if(v&&!el.closest(raw)){const next=label(v);if(next!==v)el.setAttribute(e.attributeName,next);}
   }
  }
 });
 watcher.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attributes});
})();
