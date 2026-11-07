import React, {useEffect,useRef,useState} from 'react';
import {nextBoundary} from './schedule.js';

export default function CollectionClock() {
  const [now,setNow]=useState(Date.now()),[enabled,setEnabled]=useState(false),[busy,setBusy]=useState(false);
  const [next,setNext]=useState(null),[status,setStatus]=useState('Collection is stopped.'),[last,setLast]=useState(null);
  const [speedtest,setSpeedtest]=useState(false),[firestore,setFirestore]=useState(false);
  const running=useRef(false),generation=useRef(0),deadline=useRef(null),active=useRef(false);
  const options=useRef({speedtest,firestore});options.current={speedtest,firestore};
  useEffect(()=>{const t=setInterval(()=>setNow(Date.now()),1000);return()=>{clearInterval(t);active.current=false;generation.current++;};},[]);
  async function run() {
    if(running.current)return;
    running.current=true;setBusy(true);const id=generation.current;
    try{
      if(!window.isSecureContext||!navigator.geolocation)throw Error('Location requires localhost/HTTPS and browser geolocation.');
      setStatus('Requesting fresh location…');
      const p=await new Promise((resolve,reject)=>navigator.geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:true,maximumAge:0,timeout:20000}));
      if(id!==generation.current)return;
      setStatus('Running the laptop extractor…');
      const result=await fetch('/api/collect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({latitude:p.coords.latitude,longitude:p.coords.longitude,accuracy:p.coords.accuracy,...options.current}),signal:AbortSignal.timeout(250000)});
      const data=await result.json();if(!result.ok)throw Error(data.error||'Collection failed.');
      if(id!==generation.current)return;
      setLast(data.record.measured_at);
      const warnings=data.record.errors?.length||0;
      setStatus(`Measurement saved locally${data.firestoreUploaded?' and uploaded to Firebase':''}. ${warnings?`${warnings} metric warning(s): ${data.record.errors.join('; ')}`:'Collection complete.'}${options.current.firestore&&!data.firestoreUploaded?' Firebase upload failed; local backup retained.':''}`);
    }catch(e){if(id===generation.current)setStatus(e.code===1?'Location permission denied. No measurement taken.':e.message||'Could not collect a measurement.');}
    finally{running.current=false;setBusy(false);}
  }
  useEffect(()=>{
    if(!enabled||now<deadline.current)return;
    deadline.current=nextBoundary(now);setNext(deadline.current);
    // One run after a suspended tab resumes; never replay missed intervals.
    if(!running.current)run();
  },[now,enabled]);
  function toggle(){
    if(enabled){active.current=false;generation.current++;setEnabled(false);setNext(null);setStatus('Schedule stopped. A measurement already submitted may finish locally.');}
    else{active.current=true;deadline.current=nextBoundary(Date.now());setNext(deadline.current);setEnabled(true);setStatus('Scheduled for the next five-minute clock boundary. Keep this app open.');}
  }
  return <section className="collection"><div className="section-title"><span>04</span><h2>Live collection</h2></div>
    <time className="live-clock" dateTime={new Date(now).toISOString()}>{new Date(now).toLocaleTimeString()}</time><div className="clock-zone">{Intl.DateTimeFormat().resolvedOptions().timeZone}</div>
    <p>Runs this laptop’s extractor at :00, :05, :10… while this app is open. Each run asks for a fresh location and saves locally.</p>
    <label className="control-row">Include download/upload test<input type="checkbox" checked={speedtest} onChange={e=>setSpeedtest(e.target.checked)}/></label><p>Speed tests use substantial bandwidth. Off by default.</p>
    <label className="control-row">Upload to Firebase<input type="checkbox" checked={firestore} onChange={e=>setFirestore(e.target.checked)}/></label><p>Requires local Firebase credentials. No keys go in the browser.</p>
    <div className="actions"><button onClick={toggle}>{enabled?'Stop schedule':'Start 5-minute schedule'}</button><button onClick={run} disabled={busy}>{busy?'Collecting…':'Collect now'}</button></div>
    {next&&<p>Next: {new Date(next).toLocaleTimeString()} · {Math.max(0,Math.ceil((next-now)/1000))}s</p>}
    <p role="status">{status}</p>{last&&<p>Last collected: {new Date(last).toLocaleTimeString()}</p>}
    <p>Collection feeds Firebase → LLM. It does not replace the map’s demo with unprocessed readings.</p>
  </section>;
}
