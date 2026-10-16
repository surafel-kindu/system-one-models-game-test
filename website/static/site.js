'use strict';
document.querySelectorAll('.copy-button').forEach(button=>button.addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(button.parentElement.querySelector('code').textContent);button.textContent='Copied ✓';}
  catch{button.textContent='Select the command to copy';}
  setTimeout(()=>button.textContent='Copy',2500);
}));
