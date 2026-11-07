import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

export function validRequest(p) {
  return p && [p.latitude,p.longitude,p.accuracy].every(Number.isFinite) && Math.abs(p.latitude)<=90 && Math.abs(p.longitude)<=180 && p.accuracy>=0 && typeof p.speedtest==='boolean' && typeof p.firestore==='boolean';
}

export default function collectorPlugin() {
  let active=null;
  return {name:'local-laptop-collector',configureServer(server) {
    server.httpServer?.on('close',()=>active?.kill());
    server.middlewares.use('/api/collect',(req,res)=>{
      const reply=(status,value)=>{res.statusCode=status;res.setHeader('Content-Type','application/json');res.end(JSON.stringify(value));};
      if(req.method!=='POST')return reply(405,{error:'Use POST.'});
      const origin=req.headers.origin;
      if(!origin || origin!==`http://${req.headers.host}` || !/^localhost(:\d+)?$|^127\.0\.0\.1(:\d+)?$/.test(req.headers.host || ''))return reply(403,{error:'Local same-origin requests only.'});
      if(!req.headers['content-type']?.startsWith('application/json'))return reply(415,{error:'JSON required.'});
      if(active)return reply(409,{error:'A measurement is already running.'});
      let body='';let tooLarge=false;
      req.on('data',chunk=>{body+=chunk;if(body.length>4096){tooLarge=true;body='';}});
      req.on('end',()=>{
        let input;try{input=JSON.parse(body);}catch{return reply(400,{error:'Invalid JSON.'});}
        if(tooLarge||!validRequest(input))return reply(400,{error:'Invalid location or collection settings.'});
        if(active)return reply(409,{error:'A measurement is already running.'});
        const root=server.config.root;
        const venv=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
        const executable=process.env.PYTHON_EXECUTABLE || (existsSync(venv)?venv:process.platform==='win32'?'python':'python3');
        const child=spawn(executable,[path.join(root,'extractor/bridge.py')],{cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe']});
        active=child;let output='',finished=false;
        const finish=(status,value)=>{if(finished)return;finished=true;clearTimeout(timer);active=null;reply(status,value);};
        const timer=setTimeout(()=>{child.kill();finish(504,{error:'Extractor exceeded four minutes and was stopped.'});},240000);
        child.stdout.on('data',data=>{output=(output+data).slice(-100000);});
        child.stderr.on('data',()=>{});
        child.stdin.on('error',()=>{});
        child.on('error',()=>finish(503,{error:'Python could not start. Install Python and the requirements, or set PYTHON_EXECUTABLE.'}));
        child.on('close',code=>{
          if(code!==0)return finish(503,{error:'Extractor failed. Check Python, requirements.txt, and local Firebase credentials if upload is enabled.'});
          try{const line=output.split(/\r?\n/).findLast(l=>l.startsWith('BRIDGE_RESULT:'));finish(200,JSON.parse(line.slice(14)));}
          catch{finish(502,{error:'Extractor returned no valid result.'});}
        });
        child.stdin.end(JSON.stringify(input));
      });
    });
  }};
}
