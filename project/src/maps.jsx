// RIIS — Live Maps: Leaflet.js + CartoDB Dark + RainViewer Radar
// Requires: Leaflet 1.9.4 loaded as global L in index.html

const { useRef: useRef_m, useEffect: useEffect_m, useState: useState_m } = React;

// ── Inject dark-theme overrides for Leaflet ──────────────────────────────────
const LEAFLET_DARK_CSS = `
  @keyframes riis-pulse-extreme {
    0%   { box-shadow: 0 0 0 0 rgba(239,68,68,0.7),  0 0 8px rgba(239,68,68,0.5); }
    70%  { box-shadow: 0 0 0 14px rgba(239,68,68,0), 0 0 8px rgba(239,68,68,0.5); }
    100% { box-shadow: 0 0 0 0 rgba(239,68,68,0),    0 0 8px rgba(239,68,68,0.5); }
  }
  @keyframes riis-pulse-high {
    0%   { box-shadow: 0 0 0 0 rgba(249,115,22,0.6),  0 0 8px rgba(249,115,22,0.4); }
    70%  { box-shadow: 0 0 0 12px rgba(249,115,22,0), 0 0 8px rgba(249,115,22,0.4); }
    100% { box-shadow: 0 0 0 0 rgba(249,115,22,0),    0 0 8px rgba(249,115,22,0.4); }
  }
  @keyframes riis-pulse-user {
    0%   { box-shadow: 0 0 0 0 rgba(34,211,238,0.8),  0 0 14px rgba(34,211,238,0.6); }
    70%  { box-shadow: 0 0 0 18px rgba(34,211,238,0), 0 0 14px rgba(34,211,238,0.6); }
    100% { box-shadow: 0 0 0 0 rgba(34,211,238,0),    0 0 14px rgba(34,211,238,0.6); }
  }
  .riis-dot { border-radius: 50%; cursor: pointer; transition: transform 0.15s ease; }
  .riis-dot:hover { transform: scale(1.45) !important; }
  .riis-dot.pulse-extreme { animation: riis-pulse-extreme 1.8s infinite; }
  .riis-dot.pulse-high    { animation: riis-pulse-high 2.2s infinite; }
  .riis-dot.pulse-user    { animation: riis-pulse-user 1.5s infinite; }
  .leaflet-tooltip.rv-tip {
    background: rgba(6,13,21,0.97) !important;
    border: 1px solid rgba(100,160,255,0.25) !important;
    color: #E8F1FF !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 10.5px !important;
    border-radius: 6px !important;
    padding: 5px 10px !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.7) !important;
    white-space: nowrap !important;
  }
  .leaflet-tooltip.rv-tip::before { display: none !important; }
  .leaflet-tile-pane {
    filter: brightness(0.65) invert(1) contrast(2.2) hue-rotate(200deg) saturate(0.4);
  }
  .leaflet-container { background: #060D15 !important; }
  .leaflet-control-attribution {
    background: rgba(6,13,21,0.85) !important;
    color: rgba(150,180,220,0.55) !important;
    font-size: 9px !important;
    border-radius: 4px 0 0 0 !important;
  }
  .leaflet-control-attribution a { color: #22D3EE !important; }
`;
function injectLeafletStyles() {
  if (document.getElementById('riis-lf-dark')) return;
  const s = document.createElement('style');
  s.id = 'riis-lf-dark';
  s.textContent = LEAFLET_DARK_CSS;
  document.head.appendChild(s);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const RISK_COL = { extreme: '#EF4444', high: '#F97316', mod: '#F59E0B', safe: '#10B981' };
const rCol = cls => RISK_COL[cls] || '#22D3EE';
const rLabel = cls => ({ extreme:'EXTREME', high:'HIGH', mod:'MODERATE', safe:'SAFE' })[cls] || (cls||'').toUpperCase();

async function fetchRadarLayer(opacity) {
  if (typeof L === 'undefined') return null;
  try {
    const res = await fetch('https://api.rainviewer.com/public/weather-maps.json');
    const data = await res.json();
    const frames = [...(data.radar?.past || []), ...(data.radar?.nowcast || [])];
    const latest = frames[frames.length - 1];
    if (!latest) return null;
    return L.tileLayer(
      `https://tilecache.rainviewer.com${latest.path}/256/{z}/{x}/{y}/2/1_1.png`,
      { opacity: opacity || 0.55, zIndex: 300, maxZoom: 22, maxNativeZoom: 19, attribution: '🌧 <a href="https://www.rainviewer.com">RainViewer</a>' }
    );
  } catch (e) {
    console.warn('[RIIS] RainViewer unavailable:', e.message);
    return null;
  }
}

function mkDot(color, size, pulseClass, selected, isUser) {
  if (typeof L === 'undefined') return null;
  return L.divIcon({
    className: '',
    html: `<div class="riis-dot ${pulseClass}" style="width:${size}px;height:${size}px;background:${color};border:${selected||isUser?'3px solid #fff':'2px solid '+color+'99'};box-shadow:0 0 ${isUser?14:7}px ${color}88;"></div>`,
    iconSize: [size, size],
    iconAnchor: [size/2, size/2]
  });
}

const MBT = { width:32,height:32,borderRadius:6,background:'rgba(6,13,21,0.9)',border:'1px solid rgba(100,160,255,0.2)',color:'var(--text-mid)',cursor:'pointer',display:'flex',alignItems:'center',justifyContent:'center',backdropFilter:'blur(8px)',transition:'all .15s',padding:0 };

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// INDIA NATIONAL RISK MAP — Leaflet + RainViewer
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function IndiaMap({ districts, onSelect, hover, setHover, selectedCode }) {
  const elRef    = useRef_m(null);
  const mapRef   = useRef_m(null);
  const radarRef = useRef_m(null);
  const mrkRef   = useRef_m({});
  const [showRadar, setShowRadar] = useState_m(true);
  const [radarTS,   setRadarTS]   = useState_m('');

  useEffect_m(() => {
    if (!elRef.current || mapRef.current || typeof L === 'undefined') return;
    injectLeafletStyles();
    const map = L.map(elRef.current, { 
      center:[21.5,80.0], 
      zoom:5, 
      zoomControl:false, 
      attributionControl:true, 
      minZoom:3, 
      maxZoom:22,
      scrollWheelZoom: true,
      doubleClickZoom: true,
      touchZoom: true
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
      maxNativeZoom: 19
    }).addTo(map);
    mapRef.current = map;
    fetchRadarLayer(0.55).then(layer => {
      if (!layer) return;
      layer.addTo(map);
      radarRef.current = layer;
      setRadarTS(new Date().toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'}));
    });
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  useEffect_m(() => {
    if (!mapRef.current || !radarRef.current) return;
    if (showRadar) radarRef.current.addTo(mapRef.current);
    else radarRef.current.remove();
  }, [showRadar]);

  useEffect_m(() => {
    const map = mapRef.current;
    if (!map || typeof L === 'undefined') return;
    Object.values(mrkRef.current).forEach(m => { try { m.remove(); } catch(e){} });
    mrkRef.current = {};
    districts.forEach(d => {
      if (d.lat == null || d.lon == null) return;
      const isUser = d.isUser || d.code === 'USER-LOC';
      const isSel  = selectedCode === d.code;
      const color  = isUser ? '#22D3EE' : rCol(d.class);
      const size   = isUser ? 20 : d.class==='extreme' ? 15 : d.class==='high' ? 13 : 10;
      const pulse  = isUser ? 'pulse-user' : d.class==='extreme' ? 'pulse-extreme' : d.class==='high' ? 'pulse-high' : '';
      const marker = L.marker([d.lat, d.lon], { icon: mkDot(color, size, pulse, isSel, isUser), zIndexOffset: isUser?2000:isSel?1000:0 })
        .addTo(map)
        .on('click', () => onSelect(d))
        .on('mouseover', e => setHover({...d, sx:e.originalEvent.clientX, sy:e.originalEvent.clientY}))
        .on('mouseout',  () => setHover(null));
      if (isUser || isSel) {
        marker.bindTooltip(isUser ? `📍 ${d.name}` : d.name, {
          permanent:true, direction:'top', offset:[0, -(size/2+6)], className:'rv-tip'
        }).openTooltip();
      }
      mrkRef.current[d.code] = marker;
    });
    const u = districts.find(d => d.isUser || d.code === 'USER-LOC');
    if (u && u.lat != null && mapRef.current) mapRef.current.flyTo([u.lat, u.lon], 8, {animate:true, duration:1.2});
  }, [districts, selectedCode]);

  const flyToUser = () => {
    const u = districts.find(d => d.isUser || d.code === 'USER-LOC');
    if (u && u.lat != null && mapRef.current) mapRef.current.flyTo([u.lat, u.lon], 9, {animate:true});
  };

  const refreshRadar = () => {
    const map = mapRef.current;
    if (!map) return;
    if (radarRef.current) { try { radarRef.current.remove(); } catch(e){} radarRef.current = null; }
    fetchRadarLayer(0.55).then(layer => {
      if (!layer) return;
      radarRef.current = layer;
      if (showRadar) layer.addTo(map);
      setRadarTS(new Date().toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'}));
    });
  };

  return (
    <div style={{position:'relative',width:'100%',height:500,borderRadius:12,overflow:'hidden',border:'1px solid var(--stroke)'}}>
      <div ref={elRef} style={{width:'100%',height:'100%'}} />

      {/* Top-right controls */}
      <div style={{position:'absolute',top:12,right:12,zIndex:1000,display:'flex',flexDirection:'column',gap:5}}>
        <button onClick={()=>mapRef.current?.zoomIn()}  style={MBT} title="Zoom in">{Icon.plus}</button>
        <button onClick={()=>mapRef.current?.zoomOut()} style={MBT} title="Zoom out">{Icon.minus}</button>
        <button onClick={()=>setShowRadar(r=>!r)} title="Toggle rain radar"
          style={{...MBT, background:showRadar?'rgba(34,211,238,0.18)':MBT.background, color:showRadar?'#22D3EE':'var(--text-mid)'}}>
          {Icon.layer}
        </button>
        <button onClick={flyToUser}    style={{...MBT, color:'#22D3EE'}} title="Go to my location">{Icon.pin}</button>
        <button onClick={refreshRadar} style={{...MBT, color:'#10B981'}} title="Refresh radar">{Icon.radar}</button>
      </div>

      {/* Top-left live badges */}
      <div style={{position:'absolute',top:12,left:12,zIndex:1000,display:'flex',gap:6,flexDirection:'column'}}>
        <div style={{background:'rgba(6,13,21,0.9)',borderRadius:6,padding:'5px 11px',border:'1px solid rgba(100,160,255,0.2)',backdropFilter:'blur(8px)',fontSize:10.5,display:'flex',alignItems:'center',gap:6}}>
          <span style={{width:6,height:6,borderRadius:'50%',background:'#10B981',boxShadow:'0 0 6px #10B981',display:'inline-block',flexShrink:0}}/>
          <span style={{color:'#E8F1FF',fontWeight:600,fontFamily:'JetBrains Mono'}}>LIVE · OpenStreetMap · {districts.filter(d=>d.lat!=null).length} DISTRICTS</span>
        </div>
        {showRadar && radarTS && (
          <div style={{background:'rgba(6,13,21,0.9)',borderRadius:6,padding:'4px 10px',border:'1px solid rgba(34,211,238,0.3)',backdropFilter:'blur(8px)',fontSize:10,display:'flex',alignItems:'center',gap:5}}>
            <span style={{color:'#22D3EE',fontSize:12}}>🌧</span>
            <span style={{color:'#22D3EE',fontFamily:'JetBrains Mono',fontWeight:600}}>RainViewer Live · {radarTS}</span>
          </div>
        )}
      </div>

      {/* Legend */}
      <div style={{position:'absolute',bottom:28,left:12,zIndex:1000,background:'rgba(6,13,21,0.92)',borderRadius:8,padding:'9px 14px',border:'1px solid rgba(100,160,255,0.18)',backdropFilter:'blur(10px)'}}>
        <div style={{fontSize:9.5,fontWeight:700,letterSpacing:'.12em',color:'var(--text-lo)',marginBottom:7,fontFamily:'JetBrains Mono'}}>RISK CLASS</div>
        {[['extreme','#EF4444','Extreme'],['high','#F97316','High'],['mod','#F59E0B','Moderate'],['safe','#10B981','Safe']].map(([,c,l])=>(
          <div key={l} style={{display:'flex',alignItems:'center',gap:7,fontSize:11,marginBottom:4}}>
            <span style={{width:9,height:9,borderRadius:'50%',background:c,boxShadow:`0 0 6px ${c}`,flexShrink:0}}/>
            <span style={{color:'var(--text-mid)'}}>{l}</span>
          </div>
        ))}
        <div style={{display:'flex',alignItems:'center',gap:7,fontSize:11,marginTop:7,paddingTop:7,borderTop:'1px solid rgba(100,160,255,0.12)'}}>
          <span style={{width:9,height:9,borderRadius:'50%',background:'#22D3EE',boxShadow:'0 0 8px #22D3EE',flexShrink:0}}/>
          <span style={{color:'#22D3EE'}}>Your Location</span>
        </div>
      </div>

      {/* Hover tooltip */}
      {hover && (
        <div style={{position:'fixed',left:hover.sx+16,top:hover.sy-14,zIndex:9999,pointerEvents:'none',background:'rgba(6,13,21,0.97)',border:`1px solid ${rCol(hover.class)}55`,borderRadius:8,padding:'9px 14px',backdropFilter:'blur(12px)',minWidth:160}}>
          <div style={{fontWeight:700,fontSize:13}}>{hover.name}</div>
          <div style={{fontSize:11,color:rCol(hover.class),marginTop:3}}>{rLabel(hover.class)} · Risk {hover.risk}</div>
          <div style={{fontSize:11,color:'var(--text-mid)',marginTop:2}}>Rain: {typeof hover.rain==='number'?hover.rain.toFixed(1):hover.rain} mm · Pop: {((hover.pop||0)/1e6).toFixed(2)}M</div>
          {(hover.isUser||hover.code==='USER-LOC') && <div style={{fontSize:10,color:'#22D3EE',marginTop:3}}>📍 Your live GPS location</div>}
        </div>
      )}
    </div>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// CITY / HYPERLOCAL MAP — Leaflet + RainViewer
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function ChennaiMap({ wards, onSelect, selected }) {
  const elRef  = useRef_m(null);
  const mapRef = useRef_m(null);
  const mrkRef = useRef_m({});

  useEffect_m(() => {
    if (!elRef.current || mapRef.current || typeof L === 'undefined') return;
    injectLeafletStyles();
    const lat = RIIS.location.lat || 13.0827;
    const lon = RIIS.location.lon || 80.2707;
    const map = L.map(elRef.current, { 
      center:[lat,lon], 
      zoom:13, 
      zoomControl:false, 
      attributionControl:true, 
      minZoom:3, 
      maxZoom:22,
      scrollWheelZoom: true,
      doubleClickZoom: true,
      touchZoom: true
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
      maxNativeZoom: 19
    }).addTo(map);
    mapRef.current = map;
    fetchRadarLayer(0.50).then(layer => { if (layer) layer.addTo(map); });
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  useEffect_m(() => {
    const map = mapRef.current;
    if (!map || typeof L === 'undefined') return;
    Object.values(mrkRef.current).forEach(m => { try { m.remove(); } catch(e){} });
    mrkRef.current = {};

    const lat = RIIS.location.lat || 13.0827;
    const lon = RIIS.location.lon || 80.2707;
    map.flyTo([lat, lon], 13, {animate:true, duration:0.8});

    // User pulsing pin
    const userIcon = L.divIcon({
      className: '',
      html: `<div class="riis-dot pulse-user" style="width:20px;height:20px;background:#22D3EE;border:3px solid #fff;box-shadow:0 0 18px #22D3EE88;"></div>`,
      iconSize:[20,20], iconAnchor:[10,10]
    });
    L.marker([lat, lon], {icon:userIcon, zIndexOffset:3000}).addTo(map)
      .bindTooltip(`📍 ${RIIS.location.city||'You'}`, {permanent:true, direction:'top', offset:[0,-14], className:'rv-tip'}).openTooltip();

    wards.forEach(w => {
      const wLat = w.lat != null ? w.lat : lat + (50 - w.y) * 0.0006;
      const wLon = w.lon != null ? w.lon : lon + (w.x - 50) * 0.0006;
      const isSel = selected?.id === w.id;
      const color = rCol(w.class);
      const size  = isSel ? 15 : 11;
      const pulse = w.class==='extreme'?'pulse-extreme':w.class==='high'?'pulse-high':'';
      const m = L.marker([wLat,wLon], {icon:mkDot(color,size,pulse,isSel,false), zIndexOffset:isSel?1000:0})
        .addTo(map)
        .on('click', ()=>onSelect(w))
        .bindTooltip(`${w.name} · ${rLabel(w.class)} · Risk ${w.risk}`, {direction:'top', className:'rv-tip'});
      if (isSel) m.openTooltip();
      mrkRef.current[w.id] = m;
    });
  }, [wards, selected]);

  const city = RIIS.location.city || 'Hyperlocal';
  return (
    <div style={{position:'relative',width:'100%',height:460,borderRadius:12,overflow:'hidden',border:'1px solid var(--stroke)'}}>
      <div ref={elRef} style={{width:'100%',height:'100%'}} />
      <div style={{position:'absolute',top:12,right:12,zIndex:1000,display:'flex',flexDirection:'column',gap:5}}>
        <button onClick={()=>mapRef.current?.zoomIn()}  style={MBT}>{Icon.plus}</button>
        <button onClick={()=>mapRef.current?.zoomOut()} style={MBT}>{Icon.minus}</button>
        <button onClick={()=>mapRef.current?.flyTo([RIIS.location.lat||13.0827,RIIS.location.lon||80.2707],14,{animate:true})}
          style={{...MBT,color:'#22D3EE'}} title="Re-center">{Icon.pin}</button>
      </div>
      <div style={{position:'absolute',top:12,left:12,zIndex:1000,background:'rgba(6,13,21,0.9)',borderRadius:6,padding:'5px 11px',border:'1px solid rgba(100,160,255,0.2)',backdropFilter:'blur(8px)',fontSize:10.5,display:'flex',alignItems:'center',gap:6}}>
        <span style={{width:6,height:6,borderRadius:'50%',background:'#10B981',boxShadow:'0 0 6px #10B981',display:'inline-block',flexShrink:0}}/>
        <span style={{color:'#E8F1FF',fontWeight:600,fontFamily:'JetBrains Mono'}}>LIVE · {city.toUpperCase()} · {wards.length} ZONES</span>
      </div>
      <div style={{position:'absolute',bottom:28,left:12,zIndex:1000,background:'rgba(6,13,21,0.92)',borderRadius:8,padding:'8px 12px',border:'1px solid rgba(34,211,238,0.2)',backdropFilter:'blur(10px)'}}>
        <div style={{color:'#22D3EE',fontFamily:'JetBrains Mono',fontWeight:700,fontSize:10.5}}>🌧 RainViewer · OpenStreetMap</div>
        <div style={{color:'var(--text-mid)',marginTop:3,fontSize:10.5}}>Hyperlocal GPS view · {city}</div>
      </div>
    </div>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// FLOOD SIMULATION MAP (SVG — kept as simulation canvas)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function FloodSimMap({ wards, intensity }) {
  const safeWards = wards || (window.RIIS && window.RIIS.chennaiWards) || [];
  const safeIntensity = intensity || 0;
  const W = 580, H = 400;
  const t = Math.min(1, safeIntensity / 100);
  const ROADS = [
    "M50,200 Q100,150 200,180 Q300,210 400,170 Q500,130 550,160",
    "M80,100 Q120,180 100,280 Q90,340 110,390",
    "M200,50 Q220,120 210,200 Q200,290 230,380",
    "M350,60 Q370,150 360,240 Q350,330 380,390",
    "M480,80 Q490,160 480,250 Q470,330 500,390",
    "M50,300 Q150,280 260,310 Q370,340 460,320 Q520,310 560,330"
  ];
  const BLDG = [
    {x:60,y:80,w:50,h:35},{x:130,y:70,w:40,h:30},{x:240,y:60,w:55,h:40},
    {x:310,y:75,w:45,h:35},{x:400,y:65,w:50,h:30},{x:470,y:80,w:40,h:40},
    {x:65,y:130,w:45,h:30},{x:150,y:120,w:50,h:35},{x:450,y:130,w:55,h:30},
    {x:80,y:220,w:40,h:35},{x:140,y:215,w:50,h:30},{x:270,y:225,w:45,h:30},
    {x:430,y:220,w:50,h:35},{x:500,y:215,w:45,h:30},{x:70,y:320,w:50,h:40},
    {x:170,y:330,w:45,h:35},{x:320,y:340,w:50,h:30},{x:420,y:330,w:45,h:35},{x:510,y:340,w:40,h:30}
  ];
  const waterLevel = H - (t * H * 0.55);
  const floodAlpha = t * 0.62;
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{borderRadius:12,overflow:'hidden',background:'#060D15'}}>
      <defs>
        <linearGradient id="terrain2" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#0D1A2E"/><stop offset="100%" stopColor="#060D15"/>
        </linearGradient>
        <linearGradient id="flood2" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={`rgba(34,130,230,${floodAlpha*0.6})`}/>
          <stop offset="100%" stopColor={`rgba(10,60,160,${floodAlpha})`}/>
        </linearGradient>
        <filter id="glow2"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>
      <rect width={W} height={H} fill="url(#terrain2)"/>
      {ROADS.map((d,i)=><path key={i} d={d} stroke={`rgba(70,100,140,${0.7-t*0.4})`} strokeWidth="5" fill="none" strokeLinecap="round"/>)}
      {ROADS.map((d,i)=><path key={`r${i}`} d={d} stroke={`rgba(90,130,180,${0.5-t*0.3})`} strokeWidth="1.5" fill="none" strokeLinecap="round"/>)}
      {BLDG.map((b,i)=>{
        const sub=Math.max(0,Math.min(1,(b.y+b.h-waterLevel)/b.h));
        return <g key={i}>
          <rect x={b.x} y={b.y} width={b.w} height={b.h} fill={`rgba(30,50,80,${0.85-sub*0.5})`} stroke="rgba(60,100,140,0.4)" strokeWidth="0.5" rx="1"/>
          {sub>0&&<rect x={b.x} y={Math.max(b.y,waterLevel)} width={b.w} height={b.h-Math.max(0,waterLevel-b.y)} fill="rgba(30,90,200,0.4)" rx="1"/>}
        </g>;
      })}
      {t>0&&<g>
        <rect x={0} y={waterLevel} width={W} height={H-waterLevel} fill="url(#flood2)"/>
        {[0,1,2,3,4].map(i=><ellipse key={i} cx={100+i*100} cy={waterLevel+6} rx={30+i*8} ry={4} fill="none" stroke="rgba(100,180,255,0.3)" strokeWidth="1"/>)}
        {(H-waterLevel)>30&&<text x={W-12} y={waterLevel+Math.min((H-waterLevel)/2,60)} textAnchor="end" fill="rgba(120,180,255,0.8)" fontSize="11" fontFamily="JetBrains Mono" fontWeight="600">~{(t*2.5).toFixed(1)}m depth</text>}
      </g>}
      {safeWards.map(w=>{
        const wx=(w.x/100)*W, wy=(w.y/100)*H;
        const col=rCol(w.class);
        const sub=wy>waterLevel;
        return <g key={w.id} filter="url(#glow2)">
          <circle cx={wx} cy={wy} r={sub?8:6} fill={sub?'rgba(30,90,200,0.6)':col} stroke={col} strokeWidth="1.5" opacity={sub?0.7:1}/>
          <text x={wx} y={wy-10} textAnchor="middle" fill={col} fontSize="9" fontFamily="JetBrains Mono" fontWeight="600">{(w.name||'').split(' ').pop()}</text>
        </g>;
      })}
      <g transform={`translate(16,${H-16})`}>
        <line x1="0" y1="0" x2="50" y2="0" stroke="rgba(150,180,220,0.5)" strokeWidth="1.5"/>
        <line x1="0" y1="-4" x2="0" y2="4" stroke="rgba(150,180,220,0.5)" strokeWidth="1"/>
        <line x1="50" y1="-4" x2="50" y2="4" stroke="rgba(150,180,220,0.5)" strokeWidth="1"/>
        <text x="25" y="-7" textAnchor="middle" fill="rgba(150,180,220,0.7)" fontSize="9" fontFamily="JetBrains Mono">500m</text>
      </g>
      {t===0&&<text x={W/2} y={H/2+6} textAnchor="middle" fill="rgba(100,140,180,0.4)" fontSize="13" fontFamily="JetBrains Mono">Move slider to simulate flood depth</text>}
    </svg>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// REAL DEM FLOOD MAP — Leaflet + backend inundation GeoJSON
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function depthColor(d) {
  if (d >= 1.5) return '#EF4444';
  if (d >= 0.8) return '#F97316';
  if (d >= 0.4) return '#F59E0B';
  if (d >= 0.15) return '#22D3EE';
  return '#3B82F6';
}

function RealFloodMap({ intensity, onResult }) {
  const elRef    = useRef_m(null);
  const mapRef   = useRef_m(null);
  const layerRef = useRef_m(null);
  const mkrRef   = useRef_m(null);
  const [meta, setMeta]   = useState_m(null);   // last backend response summary
  const [state, setState] = useState_m('loading'); // loading | ok | empty | error

  // One-time map init centred on the user's real location
  useEffect_m(() => {
    if (!elRef.current || mapRef.current || typeof L === 'undefined') return;
    injectLeafletStyles();
    const lat = (window.RIIS && window.RIIS.location.lat) || 12.82;
    const lon = (window.RIIS && window.RIIS.location.lon) || 80.04;
    const map = L.map(elRef.current, {
      center:[lat, lon], zoom:15, zoomControl:false,
      minZoom:3, maxZoom:19, scrollWheelZoom:true,
    });
    // OSM tiles (no API key) with an inverted filter to match the dark theme.
    // CARTO's dark tiles now bake an "API KEY REQUIRED" watermark without a key.
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map);
    map.getPane('tilePane').style.filter =
      'invert(1) hue-rotate(180deg) saturate(0.65) brightness(0.92) contrast(1.12)';
    mkrRef.current = L.circleMarker([lat, lon], {
      radius:7, color:'#fff', weight:2, fillColor:'#22D3EE', fillOpacity:1,
    }).addTo(map).bindTooltip(`📍 ${window.RIIS?.location?.city || 'You'}`, {direction:'top'});
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // Fetch real inundation whenever the intensity slider settles (debounced 600ms)
  useEffect_m(() => {
    if (!window.RIIS_API) return;
    let alive = true;
    const t = setTimeout(() => {
      const reqLat = window.RIIS.location.lat, reqLon = window.RIIS.location.lon;
      if (reqLat == null) return;
      setState('loading');
      window.RIIS_API.getInundation({
        lat: reqLat, lon: reqLon,
        rainfall_mm: Math.min(600, intensity * 3),
        duration_h: 3,
        intensity_mm_h: intensity,
      }).then(res => {
        if (!alive || !mapRef.current) return;
        if (Math.abs(window.RIIS.location.lat - reqLat) > 1e-6) return;

        if (layerRef.current) { layerRef.current.remove(); layerRef.current = null; }
        const n = res.geojson ? res.geojson.features.length : 0;
        if (n === 0) { setMeta(res); setState('empty'); if (onResult) onResult(res); return; }

        layerRef.current = L.geoJSON(res.geojson, {
          style: feat => {
            const d = feat.properties.max_depth_m;
            return { color: depthColor(d), weight: 1.5, fillColor: depthColor(d), fillOpacity: 0.55 };
          },
          onEachFeature: (feat, lyr) => {
            const p = feat.properties;
            lyr.bindPopup(
              `<b style="font-family:JetBrains Mono">${p.max_depth_m} m max depth</b><br/>`
              + `mean ${p.mean_depth_m} m · ${p.area_km2} km²<br/>`
              + `<span style="color:#8ab">DEM ponding polygon</span>`
            );
          },
        }).addTo(mapRef.current);
        setMeta(res);
        setState('ok');
        if (onResult) onResult(res);
      }).catch(e => { if (alive) { console.warn('[RIIS] inundation fetch failed:', e.message); setState('error'); } });
    }, 600);
    return () => { alive = false; clearTimeout(t); };
  }, [intensity, window.RIIS.location.lat]);

  // Keep marker in sync when location changes
  useEffect_m(() => {
    if (!mkrRef.current || !mapRef.current) return;
    const lat = window.RIIS.location.lat, lon = window.RIIS.location.lon;
    if (lat == null) return;
    mkrRef.current.setLatLng([lat, lon]);
    mapRef.current.setView([lat, lon], mapRef.current.getZoom());
  }, [window.RIIS.location.lat, window.RIIS.location.lon]);

  const boxStyle = { position:'relative', width:'100%', height:400, borderRadius:12, overflow:'hidden', background:'#060D15' };

  if (typeof L === 'undefined') {
    // Leaflet not loaded — schematic fallback
    return <FloodSimMap intensity={intensity}/>;
  }

  return (
    <div style={{position:'relative'}}>
      <div style={boxStyle} ref={elRef}/>
      {/* status + legend */}
      <div style={{position:'absolute', top:8, left:8, zIndex:500, pointerEvents:'none', display:'flex', flexDirection:'column', gap:4}}>
        {state==='loading' && (
          <span className="mono" style={{fontSize:10, background:'rgba(6,13,21,0.85)', border:'1px solid var(--stroke)', borderRadius:6, padding:'3px 8px', color:'var(--cyan)'}}>
            COMPUTING DEM FLOOD EXTENT…
          </span>
        )}
        {state==='error' && (
          <span className="mono" style={{fontSize:10, background:'rgba(6,13,21,0.85)', border:'1px solid #F97316', borderRadius:6, padding:'3px 8px', color:'#F97316'}}>
            BACKEND UNREACHABLE — SCHEMATIC VIEW
          </span>
        )}
        {state==='empty' && (
          <span className="mono" style={{fontSize:10, background:'rgba(6,13,21,0.85)', border:'1px solid var(--stroke)', borderRadius:6, padding:'3px 8px', color:'#10B981'}}>
            NO PONDING — DRAINAGE ABSORBS THIS EVENT
          </span>
        )}
        {state==='ok' && meta && (
          <span className="mono" style={{fontSize:10, background:'rgba(6,13,21,0.85)', border:'1px solid var(--stroke)', borderRadius:6, padding:'3px 8px', color:'var(--cyan)'}}>
            {meta.geojson.features.length} POLYGONS · {meta.stats.wet_area_km2} KM² · MAX {meta.stats.max_depth_m} M{meta.water.mode==='spilling' ? ' · SPILLING' : ''}
          </span>
        )}
      </div>
      {/* depth legend */}
      <div style={{position:'absolute', bottom:8, left:8, zIndex:500, pointerEvents:'none', background:'rgba(6,13,21,0.85)', border:'1px solid var(--stroke)', borderRadius:6, padding:'5px 8px', display:'flex', gap:8, alignItems:'center'}}>
        <span className="mono" style={{fontSize:9, color:'var(--text-lo)'}}>DEPTH</span>
        {[['#3B82F6','<0.15m'],['#22D3EE','0.15'],['#F59E0B','0.4'],['#F97316','0.8'],['#EF4444','1.5m+']].map(([col,lbl],i)=>(
          <span key={i} style={{display:'inline-flex', alignItems:'center', gap:3}}>
            <span style={{width:9,height:9,borderRadius:2,background:col}}/>
            <span className="mono" style={{fontSize:9,color:'var(--text-lo)'}}>{lbl}</span>
          </span>
        ))}
      </div>
      {/* DEM source badge */}
      <div style={{position:'absolute', bottom:8, right:8, zIndex:500, pointerEvents:'none', background:'rgba(6,13,21,0.85)', border:'1px solid var(--stroke)', borderRadius:6, padding:'3px 8px'}}>
        <span className="mono" style={{fontSize:9, color:'var(--text-lo)'}}>
          {meta ? `${meta.grid.res_m} M/PIXEL · ${meta.source.toUpperCase()}` : 'LOADING DEM…'}
        </span>
      </div>
      <div style={{position:'relative', marginTop:-4}}/>
    </div>
  );
}

// ── Safe Routes map ───────────────────────────────────────────────────────────
// Modelled on RealFloodMap: one Leaflet instance in a ref, inundation polygons
// under a roads layer coloured by flood status, safe + normal routes, draggable
// origin / destination pins, click-to-pick, legend and loading / error overlays.
const ROAD_STYLE = {
  open:        { color: '#6B7280', weight: 2,  opacity: 0.85 },
  caution:     { color: '#F59E0B', weight: 4,  opacity: 0.95 },
  closed_cars: { color: '#EF4444', weight: 5,  opacity: 1 },
  closed_all:  { color: '#7F1D1D', weight: 6,  opacity: 1 },
};
const ROAD_LABEL = { open: 'Open', caution: 'Caution', closed_cars: 'Closed to cars', closed_all: 'Closed to all' };

function pinIcon(color, letter) {
  return L.divIcon({
    className: '',
    html: `<div style="width:26px;height:26px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:${color};border:2px solid #fff;box-shadow:0 0 10px ${color}99;display:grid;place-items:center"><span style="transform:rotate(45deg);font:700 11px Inter,sans-serif;color:#061018">${letter}</span></div>`,
    iconSize: [26, 26], iconAnchor: [13, 26], popupAnchor: [0, -24],
  });
}

function SafeRouteMap({ origin, dest, scenario, mode, roads, routes, reports, picking, flashSegmentId,
                        state, onPick, onMoveOrigin, onMoveDest, onReport, onRetry }) {
  const elRef = useRef_m(null);
  const mapRef = useRef_m(null);
  const layers = useRef_m({ flood: null, roads: null, safe: null, safeCase: null, normal: null, origin: null, dest: null, reports: null, segs: {} });
  const cbRef = useRef_m({});
  cbRef.current = { onPick, onMoveOrigin, onMoveDest, onReport, picking };
  const [floodState, setFloodState] = useState_m('idle');

  // One-time init
  useEffect_m(() => {
    if (!elRef.current || mapRef.current || typeof L === 'undefined') return;
    injectLeafletStyles();
    const lat = (origin && origin.lat) || (window.RIIS && window.RIIS.location.lat) || 12.82;
    const lon = (origin && origin.lon) || (window.RIIS && window.RIIS.location.lon) || 80.04;
    const map = L.map(elRef.current, { center: [lat, lon], zoom: 15, zoomControl: false, minZoom: 3, maxZoom: 19, scrollWheelZoom: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom: 19,
    }).addTo(map);
    map.getPane('tilePane').style.filter = 'invert(1) hue-rotate(180deg) saturate(0.65) brightness(0.92) contrast(1.12)';
    map.createPane('floodPane'); map.getPane('floodPane').style.zIndex = 390;
    map.createPane('roadPane'); map.getPane('roadPane').style.zIndex = 420;
    map.createPane('routePane'); map.getPane('routePane').style.zIndex = 440;
    map.on('click', e => { const cb = cbRef.current; if (cb.picking && cb.onPick) cb.onPick(cb.picking, { lat: e.latlng.lat, lon: e.latlng.lng }); });
    // report buttons inside popups call back through this global
    window.__riisRoadReport = (segId, lat, lon, status) => {
      const cb = cbRef.current;
      const depthEl = document.getElementById(`riis-depth-${segId}`);
      const noteEl = document.getElementById(`riis-note-${segId}`);
      if (cb.onReport) cb.onReport({ segment_id: segId, lat, lon, status, depth_cm: depthEl && depthEl.value ? +depthEl.value : null, note: noteEl ? noteEl.value : '' });
      map.closePopup();
    };
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // Cursor while picking
  useEffect_m(() => { if (elRef.current) elRef.current.style.cursor = picking ? 'crosshair' : ''; }, [picking]);

  // Inundation polygons for the scenario (same engine as the simulator), translucent under the roads
  useEffect_m(() => {
    if (!window.RIIS_API || !origin || !mapRef.current) return;
    let alive = true;
    setFloodState('loading');
    const t = setTimeout(() => {
      window.RIIS_API.getInundation({ lat: origin.lat, lon: origin.lon, rainfall_mm: scenario.rainfall_mm, duration_h: scenario.duration_h })
        .then(res => {
          if (!alive || !mapRef.current) return;
          const Ls = layers.current;
          if (Ls.flood) { Ls.flood.remove(); Ls.flood = null; }
          if (res.geojson && res.geojson.features.length) {
            Ls.flood = L.geoJSON(res.geojson, { pane: 'floodPane', style: f => ({ color: '#3B82F6', weight: 1, fillColor: '#3B82F6', fillOpacity: 0.28 }) }).addTo(mapRef.current);
          }
          setFloodState('ok');
        }).catch(() => { if (alive) setFloodState('error'); });
    }, 400);
    return () => { alive = false; clearTimeout(t); };
  }, [origin && origin.lat, origin && origin.lon, scenario.rainfall_mm, scenario.duration_h]);

  // Roads layer
  useEffect_m(() => {
    const map = mapRef.current; if (!map) return;
    const Ls = layers.current;
    if (Ls.roads) { Ls.roads.remove(); Ls.roads = null; Ls.segs = {}; }
    if (!roads || !roads.features) return;
    Ls.roads = L.geoJSON(roads, {
      pane: 'roadPane',
      style: f => { const p = f.properties; const s = { ...(ROAD_STYLE[p.status] || ROAD_STYLE.open) }; if (p.tunnel) s.dashArray = '6 6'; return s; },
      onEachFeature: (f, lyr) => {
        const p = f.properties;
        Ls.segs[p.segment_id] = lyr;
        const nm = p.name || `${p.highway} road`;
        lyr.bindTooltip(`<b>${nm}</b><br/>${ROAD_LABEL[p.status] || p.status} · ${p.max_depth_m} m${p.tunnel ? ' · underpass' : ''}${p.bridge ? ' · bridge' : ''}`, { sticky: true });
        const [lon, lat] = f.geometry.coordinates[Math.floor(f.geometry.coordinates.length / 2)];
        lyr.bindPopup(
          `<div style="font-family:Inter,sans-serif;min-width:220px">
             <b>${nm}</b> <span style="color:#8ab">${p.highway}</span><br/>
             <span style="font-family:JetBrains Mono">${ROAD_LABEL[p.status] || p.status} · max ${p.max_depth_m} m · wet ${Math.round(p.wet_fraction * 100)}%</span><br/>
             <span style="color:#8ab;font-size:11px">HAND ${p.hand_m != null ? p.hand_m + ' m' : 'n/a'}${p.culvert_near ? ' · culvert nearby' : ''}${p.risk_ml != null ? ' · model risk ' + Math.round(p.risk_ml * 100) + '%' : ''} · source ${p.source}</span>
             <hr style="border:0;border-top:1px solid #345;margin:8px 0"/>
             <div style="font-size:11px;color:#8ab;margin-bottom:4px">Report the condition here (overrides the simulation for 6 h):</div>
             <input id="riis-depth-${p.segment_id}" type="number" placeholder="depth cm" style="width:70px;margin-right:4px"/>
             <input id="riis-note-${p.segment_id}" type="text" placeholder="note" style="width:120px"/>
             <div style="margin-top:6px;display:flex;gap:4px">
               <button onclick="window.__riisRoadReport(${p.segment_id},${lat},${lon},'open')" style="background:#10B981;border:0;color:#fff;padding:3px 8px;border-radius:4px;cursor:pointer">Open</button>
               <button onclick="window.__riisRoadReport(${p.segment_id},${lat},${lon},'caution')" style="background:#F59E0B;border:0;color:#fff;padding:3px 8px;border-radius:4px;cursor:pointer">Caution</button>
               <button onclick="window.__riisRoadReport(${p.segment_id},${lat},${lon},'closed')" style="background:#EF4444;border:0;color:#fff;padding:3px 8px;border-radius:4px;cursor:pointer">Closed</button>
             </div>
           </div>`);
      },
    }).addTo(map);
  }, [roads]);

  // Report markers
  useEffect_m(() => {
    const map = mapRef.current; if (!map) return;
    const Ls = layers.current;
    if (Ls.reports) { Ls.reports.remove(); Ls.reports = null; }
    if (!reports || !reports.length) return;
    Ls.reports = L.layerGroup(reports.map(r => L.circleMarker([r.lat, r.lon], { radius: 6, color: '#fff', weight: 1.5, fillColor: r.status === 'closed' ? '#EF4444' : r.status === 'caution' ? '#F59E0B' : '#10B981', fillOpacity: 0.95 })
      .bindTooltip(`Report: ${r.status}${r.depth_cm != null ? ' · ' + r.depth_cm + ' cm' : ''}${r.note ? ' · ' + r.note : ''}`))).addTo(map);
  }, [reports]);

  // Routes
  useEffect_m(() => {
    const map = mapRef.current; if (!map) return;
    const Ls = layers.current;
    ['safe', 'safeCase', 'normal'].forEach(k => { if (Ls[k]) { Ls[k].remove(); Ls[k] = null; } });
    if (!routes) return;
    const toLatLngs = g => g.coordinates.map(([lon, lat]) => [lat, lon]);
    const bounds = [];
    if (routes.normal_route && routes.normal_route.geojson) {
      const ll = toLatLngs(routes.normal_route.geojson);
      Ls.normal = L.polyline(ll, { pane: 'routePane', color: '#94A3B8', weight: 3, dashArray: '8 8', opacity: 0.9 }).addTo(map).bindTooltip('Normal shortest route');
      bounds.push(...ll);
    }
    if (routes.safe_route && routes.safe_route.geojson) {
      const ll = toLatLngs(routes.safe_route.geojson);
      Ls.safeCase = L.polyline(ll, { pane: 'routePane', color: '#fff', weight: 9, opacity: 0.7 }).addTo(map);
      Ls.safe = L.polyline(ll, { pane: 'routePane', color: '#22D3EE', weight: 6, opacity: 1 }).addTo(map).bindTooltip('Flood-aware safe route');
      bounds.push(...ll);
    }
    if (bounds.length) map.fitBounds(L.latLngBounds(bounds).pad(0.15), { animate: true });
  }, [routes]);

  // Origin / destination pins (draggable)
  useEffect_m(() => {
    const map = mapRef.current; if (!map) return;
    const Ls = layers.current;
    const sync = (key, pt, color, letter, cb) => {
      if (!pt) { if (Ls[key]) { Ls[key].remove(); Ls[key] = null; } return; }
      if (!Ls[key]) {
        Ls[key] = L.marker([pt.lat, pt.lon], { icon: pinIcon(color, letter), draggable: true, zIndexOffset: 1000 }).addTo(map);
        Ls[key].on('dragend', e => { const ll = e.target.getLatLng(); const fn = cbRef.current[cb]; if (fn) fn({ lat: ll.lat, lon: ll.lng }); });
      } else {
        Ls[key].setLatLng([pt.lat, pt.lon]);
      }
    };
    sync('origin', origin, '#10B981', 'A', 'onMoveOrigin');
    sync('dest', dest, '#EF4444', 'B', 'onMoveDest');
    if (origin && !dest && !routes) map.panTo([origin.lat, origin.lon]);
  }, [origin && origin.lat, origin && origin.lon, dest && dest.lat, dest && dest.lon]);

  // Flash a segment from the "most affected" list
  useEffect_m(() => {
    const map = mapRef.current; const lyr = flashSegmentId && layers.current.segs[flashSegmentId];
    if (!map || !lyr) return;
    const b = lyr.getBounds(); map.panTo(b.getCenter());
    const base = lyr.options; let n = 0;
    const iv = setInterval(() => { lyr.setStyle({ color: n % 2 ? base.color : '#22D3EE', weight: n % 2 ? base.weight : 9 }); if (++n > 6) { clearInterval(iv); lyr.setStyle({ color: base.color, weight: base.weight }); } }, 180);
    return () => clearInterval(iv);
  }, [flashSegmentId]);

  const boxStyle = { position: 'relative', width: '100%', height: 560, borderRadius: 12, overflow: 'hidden', background: '#060D15' };
  const chip = (txt, color) => <span className="mono" style={{ fontSize: 10, background: 'rgba(6,13,21,0.85)', border: '1px solid var(--stroke)', borderRadius: 6, padding: '3px 8px', color }}>{txt}</span>;
  if (typeof L === 'undefined') return <div style={boxStyle}><div style={{ padding: 20, color: 'var(--text-lo)' }}>Leaflet not loaded</div></div>;
  return (
    <div style={{ position: 'relative' }}>
      <div style={boxStyle} ref={elRef} />
      <div style={{ position: 'absolute', top: 8, left: 8, zIndex: 500, pointerEvents: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {picking && chip(`CLICK THE MAP TO SET ${picking === 'origin' ? 'ORIGIN' : 'DESTINATION'}`, '#F59E0B')}
        {state === 'loading' && chip('FETCHING ROADS · DEM · FLOOD STATUS…', 'var(--cyan)')}
        {floodState === 'loading' && chip('COMPUTING INUNDATION…', '#3B82F6')}
        {state === 'ok' && roads && chip(`${roads.features.length} SEGMENTS · ${Object.entries(roads.status_counts || {}).map(([k, v]) => `${v} ${k}`).join(' · ')}`, 'var(--text-mid)')}
      </div>
      {state === 'error' && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 600, display: 'grid', placeItems: 'center', background: 'rgba(6,13,21,0.6)' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: '#FCA5A5', marginBottom: 8 }}>Road data could not be loaded (Overpass may be rate-limiting).</div>
            <button className="btn primary" onClick={onRetry}>Retry</button>
          </div>
        </div>
      )}
      <div style={{ position: 'absolute', bottom: 10, left: 10, zIndex: 500, background: 'rgba(6,13,21,0.88)', border: '1px solid var(--stroke)', borderRadius: 8, padding: '8px 10px', fontSize: 10.5, color: 'var(--text-mid)', lineHeight: 1.7 }}>
        {Object.entries(ROAD_STYLE).map(([k, s]) => (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ width: 22, height: s.weight, background: s.color, display: 'inline-block', borderRadius: 2 }} />{ROAD_LABEL[k]}</div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ width: 22, height: 5, background: '#22D3EE', display: 'inline-block', borderRadius: 2, boxShadow: '0 0 0 2px #fff' }} />Safe route</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ width: 22, height: 0, borderTop: '3px dashed #94A3B8', display: 'inline-block' }} />Normal route</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ width: 22, height: 10, background: 'rgba(59,130,246,0.35)', border: '1px solid #3B82F6', display: 'inline-block' }} />Ponding (DEM)</div>
        <div style={{ color: 'var(--text-lo)' }}>dashed road = underpass · pins are draggable</div>
      </div>
    </div>
  );
}

Object.assign(window, { IndiaMap, ChennaiMap, FloodSimMap, RealFloodMap, SafeRouteMap });

