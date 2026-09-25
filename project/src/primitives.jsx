// RIIS — primitives: icons, gauges, animations
const { useState, useEffect, useRef, useMemo } = React;

// -------- Icons (line, 1.5 stroke) --------
const Ic = ({ d, size=18, s=1.5, fill="none", ...p })=>(
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor" strokeWidth={s} strokeLinecap="round" strokeLinejoin="round" {...p}>{d}</svg>
);
const Icon = {
  home:    <Ic d={<><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/></>} />,
  map:     <Ic d={<><path d="M9 4l-6 2v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/></>} />,
  city:    <Ic d={<><path d="M3 21V8l6-4 6 4v13"/><path d="M15 21V12h6v9"/><path d="M6 12h.01M6 16h.01M9 12h.01M9 16h.01M12 12h.01M12 16h.01"/></>} />,
  brain:   <Ic d={<><path d="M12 4a3 3 0 00-3 3v10a3 3 0 006 0V7a3 3 0 00-3-3z"/><path d="M9 8a4 4 0 00-4 4 4 4 0 004 4"/><path d="M15 8a4 4 0 014 4 4 4 0 01-4 4"/></>} />,
  clock:   <Ic d={<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>} />,
  wave:    <Ic d={<><path d="M3 12s3-4 6-4 3 4 6 4 6-4 6-4"/><path d="M3 18s3-4 6-4 3 4 6 4 6-4 6-4"/></>} />,
  leaf:    <Ic d={<><path d="M5 20c8 0 14-6 14-14 0 0-6 0-10 4S5 20 5 20z"/><path d="M5 20l6-6"/></>} />,
  droplet: <Ic d={<><path d="M12 3l5 6a6 6 0 11-10 0l5-6z"/></>} />,
  shield:  <Ic d={<><path d="M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6l8-3z"/></>} />,
  bell:    <Ic d={<><path d="M6 8a6 6 0 1112 0c0 7 3 8 3 8H3s3-1 3-8z"/><path d="M10 21a2 2 0 004 0"/></>} />,
  users:   <Ic d={<><circle cx="9" cy="8" r="3"/><path d="M2 20a7 7 0 0114 0"/><circle cx="17" cy="8" r="2.5"/><path d="M22 18a5 5 0 00-6-5"/></>} />,
  chart:   <Ic d={<><path d="M3 20h18"/><path d="M6 16V9M11 16V5M16 16v-8M21 16v-4"/></>} />,
  gear:    <Ic d={<><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/></>} />,
  siren:   <Ic d={<><path d="M8 20V12a4 4 0 018 0v8"/><path d="M4 20h16"/><path d="M12 4V2M6 6L4 4M18 6l2-2"/></>} />,
  search:  <Ic d={<><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></>} />,
  send:    <Ic d={<><path d="M3 12l18-8-8 18-2-8-8-2z"/></>} />,
  bot:     <Ic d={<><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4"/><circle cx="9" cy="14" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="14" r="1" fill="currentColor" stroke="none"/></>} />,
  cloud:   <Ic d={<><path d="M17 18a4 4 0 000-8 6 6 0 00-11.7 1.5A3.5 3.5 0 006 18h11z"/></>} />,
  wind:    <Ic d={<><path d="M3 9h11a3 3 0 100-6"/><path d="M3 15h15a3 3 0 110 6"/><path d="M3 12h7"/></>} />,
  sun:     <Ic d={<><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></>} />,
  storm:   <Ic d={<><path d="M17 15a4 4 0 000-8 6 6 0 00-11.7 1.5A3.5 3.5 0 006 15h2"/><path d="M12 13l-3 5h3l-1 4 4-6h-3l1-3z"/></>} />,
  radar:   <Ic d={<><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><path d="M12 12l6-6"/></>} />,
  eye:     <Ic d={<><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></>} />,
  pin:     <Ic d={<><path d="M12 21s7-6 7-12a7 7 0 10-14 0c0 6 7 12 7 12z"/><circle cx="12" cy="9" r="2.5"/></>} />,
  plus:    <Ic d={<><path d="M12 5v14M5 12h14"/></>} />,
  minus:   <Ic d={<><path d="M5 12h14"/></>} />,
  layer:   <Ic d={<><path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5M3 17l9 5 9-5"/></>} />,
  hospital:<Ic d={<><rect x="4" y="6" width="16" height="14" rx="2"/><path d="M12 10v6M9 13h6"/></>} />,
  phone:   <Ic d={<><path d="M22 17v3a2 2 0 01-2 2 18 18 0 01-17-17 2 2 0 012-2h3l2 5-3 2a12 12 0 006 6l2-3 5 2z"/></>} />,
  fire:    <Ic d={<><path d="M12 3s-3 4-3 8a3 3 0 006 0 5 5 0 013 4c0 4-3 6-6 6s-6-2-6-6 6-8 6-12z"/></>} />,
  file:    <Ic d={<><path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9z"/><path d="M14 3v6h6"/></>} />,
  camera:  <Ic d={<><rect x="3" y="7" width="18" height="12" rx="2"/><circle cx="12" cy="13" r="4"/><path d="M8 7l2-3h4l2 3"/></>} />,
  arrow:   <Ic d={<><path d="M5 12h14M13 6l6 6-6 6"/></>} />,
  x:       <Ic d={<><path d="M6 6l12 12M18 6L6 18"/></>} />,
  flame:   <Ic d={<><path d="M12 3c1 5 6 6 6 12a6 6 0 01-12 0c0-3 2-4 2-7 2 2 2 5 4 5s0-8 0-10z"/></>} />,
  check:   <Ic d={<><path d="M5 13l4 4L19 7"/></>} />,
  play:    <Ic d={<><path d="M6 4l14 8-14 8V4z"/></>} />,
  pause:   <Ic d={<><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></>} />,
  route:   <Ic d={<><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M8 19h6a4 4 0 000-8H10a4 4 0 010-8h6"/></>} />
};
window.Ic = Ic; window.Icon = Icon;

// -------- Circular Gauge --------
function CircularGauge({ value, max=100, size=64, thickness=6, color, label, sublabel, className="" }){
  const r = (size - thickness)/2;
  const c = 2*Math.PI*r;
  const pct = Math.max(0, Math.min(1, value/max));
  const dash = c * pct;
  const cx = size/2;
  return (
    <div className={"gauge-comp "+className} style={{width:size,height:size,position:"relative"}}>
      <svg width={size} height={size}>
        <circle cx={cx} cy={cx} r={r} stroke="rgba(120,180,255,0.08)" strokeWidth={thickness} fill="none"/>
        <circle cx={cx} cy={cx} r={r} stroke={color||"var(--cyan)"} strokeWidth={thickness}
          fill="none" strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
          transform={`rotate(-90 ${cx} ${cx})`}
          style={{filter:`drop-shadow(0 0 6px ${color||"var(--cyan)"})`}}
        />
      </svg>
      <div style={{position:"absolute",inset:0,display:"grid",placeItems:"center",textAlign:"center",lineHeight:1}}>
        <div>
          <div style={{fontSize:size*.24,fontWeight:700,letterSpacing:"-0.02em"}} className="num">{label ?? Math.round(value)}</div>
          {sublabel && <div style={{fontSize:9,color:"var(--text-lo)",letterSpacing:".1em",marginTop:2}} className="mono">{sublabel}</div>}
        </div>
      </div>
    </div>
  );
}

// -------- Half-Ring Gauge (for risk / confidence) --------
function HalfGauge({ value, max=100, size=180, color, label, sub }){
  const r = size/2 - 12;
  const cx = size/2, cy = size*0.75;
  const start = Math.PI, end = 0;
  const pct = Math.max(0, Math.min(1, value/max));
  const ang = start + (end-start)*pct;
  const arc = (a1,a2)=>{
    const x1 = cx + r*Math.cos(a1), y1 = cy + r*Math.sin(a1);
    const x2 = cx + r*Math.cos(a2), y2 = cy + r*Math.sin(a2);
    const large = 0; const sweep = 1;
    return `M ${x1} ${y1} A ${r} ${r} 0 ${large} ${sweep} ${x2} ${y2}`;
  };
  return (
    <div style={{width:size,height:size*0.78,position:"relative"}}>
      <svg width={size} height={size*0.78}>
        <path d={arc(Math.PI, 0)} stroke="rgba(120,180,255,0.08)" strokeWidth="10" fill="none" strokeLinecap="round"/>
        <path d={arc(Math.PI, ang)} stroke={color||"var(--cyan)"} strokeWidth="10" fill="none" strokeLinecap="round"
          style={{filter:`drop-shadow(0 0 8px ${color||"var(--cyan)"})`}}/>
        {/* tick marks */}
        {Array.from({length:11}).map((_,i)=>{
          const a = Math.PI + i*(Math.PI/10);
          const x1 = cx + (r+6)*Math.cos(a), y1 = cy + (r+6)*Math.sin(a);
          const x2 = cx + (r+2)*Math.cos(a), y2 = cy + (r+2)*Math.sin(a);
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--text-lo)" strokeWidth="1" opacity=".5"/>;
        })}
      </svg>
      <div style={{position:"absolute",left:0,right:0,top:size*0.32,textAlign:"center"}}>
        <div style={{fontSize:size*.22,fontWeight:700,letterSpacing:"-0.02em",lineHeight:1}} className="num">{Math.round(value)}<span style={{fontSize:size*.10,color:"var(--text-lo)",marginLeft:2}}>{sub||""}</span></div>
        {label && <div className="k" style={{marginTop:6}}>{label}</div>}
      </div>
    </div>
  );
}

// -------- Sparkline --------
function Sparkline({ data, w=140, h=36, color="var(--cyan)", fill=true, dots=false }){
  const max = Math.max(...data), min = Math.min(...data);
  const rng = max - min || 1;
  const pts = data.map((v,i)=>[i*(w/(data.length-1)), h - ((v-min)/rng)*(h-4) - 2]);
  const path = pts.map((p,i)=>(i?"L":"M")+p[0].toFixed(1)+" "+p[1].toFixed(1)).join(" ");
  const area = path + ` L ${w} ${h} L 0 ${h} Z`;
  return (
    <svg width={w} height={h} style={{display:"block"}}>
      {fill && <path d={area} fill={color} opacity="0.12"/>}
      <path d={path} stroke={color} strokeWidth="1.5" fill="none"/>
      {dots && pts.map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r="2" fill={color}/>)}
    </svg>
  );
}

// -------- Radar with sweeping arm --------
function RadarSweep({ size=320, cityName="RADAR", stormDir="SW → NE", stormSpeed=14 }){
  const [angle,setAngle] = useState(0);
  useEffect(()=>{
    let raf; const start = performance.now();
    const tick = (t)=>{ setAngle(((t-start)/25)%360); raf=requestAnimationFrame(tick); };
    raf=requestAnimationFrame(tick);
    return ()=>cancelAnimationFrame(raf);
  },[]);
  const cx=size/2, cy=size/2;
  // Storm echo blobs (moving)
  const blobs = [
    {x:cx-40,y:cy-30,r:36,c:"#EF4444",o:0.45},
    {x:cx+20,y:cy-10,r:52,c:"#F97316",o:0.4},
    {x:cx-10,y:cy+40,r:44,c:"#F59E0B",o:0.3},
    {x:cx+50,y:cy+30,r:30,c:"#22D3EE",o:0.28},
  ];
  return (
    <svg width={size} height={size} style={{display:"block"}}>
      <defs>
        <radialGradient id="rgFade">
          <stop offset="0%" stopColor="#22D3EE" stopOpacity="0.15"/>
          <stop offset="100%" stopColor="#22D3EE" stopOpacity="0"/>
        </radialGradient>
        <linearGradient id="sweep" x1="0.5" y1="0.5" x2="1" y2="0.5">
          <stop offset="0%" stopColor="#22D3EE" stopOpacity="0"/>
          <stop offset="100%" stopColor="#22D3EE" stopOpacity="0.5"/>
        </linearGradient>
      </defs>
      <circle cx={cx} cy={cy} r={size/2-2} fill="url(#rgFade)"/>
      {/* rings */}
      {[1,2,3,4].map(i=>(
        <circle key={i} cx={cx} cy={cy} r={(size/2-4)*(i/4)} stroke="rgba(120,180,255,0.15)" strokeWidth="1" fill="none"/>
      ))}
      {/* crosshairs */}
      <line x1={cx} y1="2" x2={cx} y2={size-2} stroke="rgba(120,180,255,0.1)" strokeDasharray="2 4"/>
      <line x1="2" y1={cy} x2={size-2} y2={cy} stroke="rgba(120,180,255,0.1)" strokeDasharray="2 4"/>
      {/* Storm blobs */}
      <g filter="url(#f-blur)">
        {blobs.map((b,i)=>(
          <circle key={i} cx={b.x} cy={b.y} r={b.r} fill={b.c} opacity={b.o}
            style={{animation:`pulse 2s ${i*0.3}s infinite`}}/>
        ))}
      </g>
      {/* sweep */}
      <g transform={`rotate(${angle} ${cx} ${cy})`}>
        <path d={`M ${cx} ${cy} L ${cx + size/2} ${cy} A ${size/2} ${size/2} 0 0 0 ${cx + (size/2)*Math.cos(-Math.PI/3)} ${cy + (size/2)*Math.sin(-Math.PI/3)} Z`} fill="url(#sweep)"/>
        <line x1={cx} y1={cy} x2={cx + size/2 - 4} y2={cy} stroke="#22D3EE" strokeWidth="1.5" opacity="0.7"/>
      </g>
      {/* center dot + labels */}
      <circle cx={cx} cy={cy} r="4" fill="#22D3EE"/>
      <text x={cx+8} y={cy-6} fontSize="9" fill="#22D3EE" fontFamily="JetBrains Mono">{cityName || "RADAR"}</text>
      <text x="8" y="14" fontSize="9" fill="rgba(157,179,204,0.7)" fontFamily="JetBrains Mono">RANGE 250 KM</text>
      <text x={size-8} y="14" fontSize="9" fill="rgba(157,179,204,0.7)" fontFamily="JetBrains Mono" textAnchor="end">DOPPLER · LIVE</text>
      <text x="8" y={size-6} fontSize="9" fill="rgba(157,179,204,0.7)" fontFamily="JetBrains Mono">STORM {stormDir} · {stormSpeed} KM/H</text>
    </svg>
  );
}

// -------- Wind compass --------
function WindCompass({ dir=218, speed=24, size=64 }){
  const cx=size/2;
  return (
    <svg width={size} height={size}>
      <circle cx={cx} cy={cx} r={size/2-2} stroke="rgba(120,180,255,0.15)" strokeWidth="1" fill="none"/>
      <circle cx={cx} cy={cx} r={size/2-8} stroke="rgba(120,180,255,0.08)" strokeWidth="1" fill="none"/>
      {['N','E','S','W'].map((c,i)=>{
        const a = i*Math.PI/2 - Math.PI/2;
        const x = cx + (size/2-14)*Math.cos(a), y = cx + (size/2-14)*Math.sin(a);
        return <text key={c} x={x} y={y+3} fontSize="7" textAnchor="middle" fill="var(--text-lo)" fontFamily="JetBrains Mono">{c}</text>;
      })}
      <g transform={`rotate(${dir} ${cx} ${cx})`}>
        <path d={`M ${cx} 8 L ${cx-4} ${cx-2} L ${cx} ${cx-6} L ${cx+4} ${cx-2} Z`} fill="var(--cyan)"/>
        <line x1={cx} y1={cx+2} x2={cx} y2={size-8} stroke="var(--cyan)" strokeWidth="1" opacity=".4"/>
      </g>
    </svg>
  );
}

// -------- Rain animation (visual) --------
function RainCurtain({ intensity=0.7, w=280, h=240 }){
  const drops = useMemo(()=>{
    const n = Math.round(intensity*40);
    return Array.from({length:n},(_,i)=>({
      x: Math.random()*w,
      d: 0.6+Math.random()*0.6, // duration
      del: Math.random()*1.4,
      h: 12+Math.random()*20,
      o: 0.3+Math.random()*0.6
    }));
  },[intensity,w,h]);
  return (
    <div style={{position:"relative",width:w,height:h,overflow:"hidden"}}>
      {/* cloud */}
      <svg width={w} height={h} style={{position:"absolute",inset:0}}>
        <defs>
          <linearGradient id="cldG" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#334155"/><stop offset="100%" stopColor="#1e293b"/>
          </linearGradient>
        </defs>
        <ellipse cx={w*0.5} cy={h*0.28} rx={w*0.38} ry={h*0.14} fill="url(#cldG)" opacity="0.9"/>
        <ellipse cx={w*0.35} cy={h*0.24} rx={w*0.20} ry={h*0.11} fill="url(#cldG)" opacity="0.9"/>
        <ellipse cx={w*0.68} cy={h*0.22} rx={w*0.22} ry={h*0.10} fill="url(#cldG)" opacity="0.9"/>
        {/* Lightning */}
        <path d={`M ${w*0.52} ${h*0.42} L ${w*0.46} ${h*0.6} L ${w*0.5} ${h*0.6} L ${w*0.42} ${h*0.82}`}
          stroke="#FBBF24" strokeWidth="2" fill="none" opacity="0.9"
          style={{filter:"drop-shadow(0 0 6px #FBBF24)"}}/>
      </svg>
      {drops.map((d,i)=>(
        <div key={i} className="drop" style={{
          left: d.x, height: d.h, opacity: d.o,
          animationDuration: d.d+"s", animationDelay: d.del+"s",
          background:"linear-gradient(180deg,transparent,rgba(125,211,252,0.9))",
          position:"absolute", top:h*0.35, width:1,
          animationName:"raindrop", animationIterationCount:"infinite", animationTimingFunction:"linear"
        }}/>
      ))}
    </div>
  );
}

// -------- Risk color helper --------
function riskColor(cls){
  return { safe:"#10B981", mod:"#F59E0B", high:"#F97316", extreme:"#EF4444" }[cls] || "#22D3EE";
}
function riskLabel(cls){
  return { safe:"SAFE", mod:"MODERATE", high:"HIGH", extreme:"EXTREME" }[cls] || "";
}

Object.assign(window,{ CircularGauge, HalfGauge, Sparkline, RadarSweep, WindCompass, RainCurtain, riskColor, riskLabel });
