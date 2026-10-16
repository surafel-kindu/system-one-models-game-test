'use strict';
const form=document.querySelector('#suggestion-form');
form.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!form.reportValidity())return;
  form.querySelectorAll('[aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));
  form.querySelectorAll('.field-error').forEach(el=>el.textContent='');
  const error=document.querySelector('#form-error'),button=form.querySelector('button[type=submit]'),label=button.textContent;
  error.textContent='';button.disabled=true;button.textContent='Saving suggestion…';
  try{
    const data=Object.fromEntries(new FormData(form));
    const response=await fetch('/submit',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token':data.csrf},body:JSON.stringify(data)});
    const result=await response.json();
    if(!response.ok){
      for(const [key,message] of Object.entries(result.errors||{})){
        const field=form.elements.namedItem(key),hint=document.getElementById('error-'+key);
        if(hint)hint.textContent=message;
        if(field instanceof HTMLElement)field.setAttribute('aria-invalid','true');
      }
      throw new Error(result.error||'Your suggestion could not be saved. Please try again.');
    }
    form.hidden=true;
    document.querySelector('#receipt-reference').textContent=result.reference;
    document.querySelector('#receipt-issue').href=result.issue_url;
    const receipt=document.querySelector('#submission-receipt');receipt.hidden=false;receipt.focus();
  }catch(reason){error.textContent=reason.message||'Connection failed. Your fields are still here; please try again.';const first=form.querySelector('[aria-invalid=true]');if(first)first.focus();}
  finally{button.disabled=false;button.textContent=label;}
});
