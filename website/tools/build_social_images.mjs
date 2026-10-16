#!/usr/bin/env node
// Optional asset-authoring utility. The Docker image serves the committed JPEGs.
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {dirname, join, resolve} from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const site=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(import.meta.url);
let sharp;
try { sharp=require('sharp'); }
catch { sharp=createRequire(join(site,'.social-tools','package.json'))('sharp'); }
const pages=JSON.parse(execFileSync('python3',['-c','import json; from presentation import PAGES; print(json.dumps(PAGES))'],{cwd:site,encoding:'utf8'}));
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const text=(x,y,s,size=22,color='#465043',weight=400)=>`<text x="${x}" y="${y}" fill="${color}" font-family="Arial,sans-serif" font-size="${size}" font-weight="${weight}">${esc(s)}</text>`;
function wrap(s,max){let lines=[],line='';for(const word of s.split(/\s+/)){if(line&&line.length+1+word.length>max){lines.push(line);line=word;}else line+=(line?' ':'')+word;}if(line)lines.push(line);return lines;}
const logo=(await readFile(join(site,'static/brand/logo-horizontal.png'))).toString('base64');
await mkdir(join(site,'static/social'),{recursive:true});
for(const [key,page] of Object.entries(pages)){
 const source=await readFile(join(site,'static/illustrations',key+'.svg'),'utf8');
 const illustration=source.slice(source.indexOf('>')+1,source.lastIndexOf('</svg>'));
 const description=wrap(page.description,49);
 if(description.length>4)throw new Error(`Shorten the description for ${key}: more than four social-card lines.`);
 let svg='<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630"><rect width="1200" height="630" fill="#E7E7E2"/>';
 svg+=[310,600,890].map(x=>`<path d="M${x} 0V630" stroke="#C5CABD"/>`).join('');
 svg+='<rect x="20" y="20" width="1160" height="590" rx="24" fill="none" stroke="#191D17" stroke-width="5"/>';
 svg+=`<svg x="61" y="62" width="342" height="83" viewBox="99 139 1993 484"><image width="2172" height="724" href="data:image/png;base64,${logo}"/></svg>`;
 svg+='<rect x="1100" y="73" width="19" height="19" fill="#FF6B1A"/>';
 svg+=text(64,197,'MODEL ARCADE LAB / '+(key==='home'?'EXPLORE':key.toUpperCase().replaceAll('-',' ')),17,'#465043',600);
 page.card_lines.forEach((label,i)=>{svg+=text(61,283+i*70,label,label.length<=14?52:43,'#191D17',800);});
 description.forEach((label,i)=>{svg+=text(65,407+i*31,label,22);});
 svg+=`<svg x="666" y="207" width="480" height="312" viewBox="0 0 800 520">${illustration}</svg>`;
 svg+='<path d="M63 536H1137" stroke="#ABB3A0"/>';
 svg+=text(65,576,'arcade.afroawi.com',25,'#191D17',700)+text(845,575,'SMALL MODELS. REAL DECISIONS.',14);
 svg+='</svg>';
 await sharp(Buffer.from(svg)).jpeg({quality:91,mozjpeg:true}).toFile(join(site,'static/social',key+'-v2.jpg'));
 console.log(key+'-v2.jpg: 1200 × 630');
}
