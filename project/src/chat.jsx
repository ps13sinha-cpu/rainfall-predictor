// RIIS — AI Chat Assistant with Live Weather Grounding
const { useState: useState_ch, useRef: useRef_ch, useEffect: useEffect_ch } = React;

function getDynamicBotResponse(q) {
  const s = q.toLowerCase();
  const l = RIIS.location;
  const w = RIIS.live;
  const p = RIIS.prediction;
  const city = l.city || "your location";

  if (s.includes("flood") || s.includes("waterlog") || s.includes("safe")) {
    if (p.rainfall_mm > 25) {
      return {
        text: `**Yes — ${city} has an elevated flood risk today (${RIIS.riskIndex}/100, ${riskLabel(RIIS.riskClass)}).** Expected 6-hour rainfall is ${p.rainfall_mm}mm with peak rate ${p.peak_intensity}mm/hr. Low-lying corridors may experience water accumulation. Move vehicles to higher elevation.`,
        cite: `Live ConvLSTM · Risk Index ${RIIS.riskIndex} · ${city}`
      };
    } else if (p.rainfall_mm > 5) {
      return {
        text: `**Moderate localized risk in ${city}.** Predicted rainfall is ${p.rainfall_mm} mm in next 6h with risk index at ${RIIS.riskIndex}/100. Drainage load is normal, but watch low underpasses.`,
        cite: `Live Sensor Feed · ${city}`
      };
    } else {
      return {
        text: `**No flood risk in ${city} today.** Predicted 6-hour precipitation is ${p.rainfall_mm} mm. Barometric pressure is ${w.pressure} hPa (${w.pressureTrend}) with good drainage capacity.`,
        cite: `Live Metrics · ${city} · Status SAFE`
      };
    }
  }

  if (s.includes("irrigat") || s.includes("water") || s.includes("farm") || s.includes("crop")) {
    if (p.rainfall_mm > 15) {
      return {
        text: `**Do not irrigate today in ${city}.** ${p.rainfall_mm}mm precipitation is forecast. Field capacity will be replenished naturally. Delay supplemental irrigation for 48 hours.`,
        cite: `Crop AI · Live Forecast · ${city}`
      };
    } else {
      return {
        text: `**Standard irrigation is recommended in ${city}.** Only ${p.rainfall_mm}mm rainfall forecast. Soil moisture retention is moderate with ambient temperature ${w.temperature.toFixed(1)}°C and ${w.humidity}% humidity.`,
        cite: `Crop AI · Optimal Window · ${city}`
      };
    }
  }

  if (s.includes("rain") || s.includes("weather") || s.includes("temp") || s.includes("forecast")) {
    return {
      text: `**${p.intensity} in ${city}.** Current temperature is ${w.temperature.toFixed(1)}°C (${w.weatherDesc}), humidity is ${w.humidity}%, and pressure is ${w.pressure} hPa. Predicted 6-hour rainfall is **${p.rainfall_mm} mm** with rain onset **${p.startsInText}**. Wind is blowing from ${w.windDirLabel} at ${w.windSpeed} km/h (gusts ${w.windGusts} km/h).`,
      cite: `Open-Meteo Live · ${w.weatherDesc} · Confidence ${p.confidence}%`
    };
  }

  if (s.includes("road") || s.includes("traffic") || s.includes("transit")) {
    if (p.rainfall_mm > 20) {
      return {
        text: `**Traffic slowdowns and wet pavement in ${city}.** Rain onset in ${p.startsInText}. Visibility is currently ${w.visibility} km (${w.visibilityStatus}). Allow additional travel time and exercise caution.`,
        cite: `Transit Vector · Live Visibility ${w.visibility}km`
      };
    } else {
      return {
        text: `**All major transit corridors in ${city} are operating normally.** Visibility is ${w.visibility} km with no severe waterlogging alerts. Surface wind is ${w.windSpeed} km/h.`,
        cite: `Live Transit Vector · ${city}`
      };
    }
  }

  if (s.includes("reservoir") || s.includes("dam") || s.includes("inflow")) {
    return {
      text: `**Catchment inflow in regional reservoirs is estimated at ${RIIS.impacts.find(i=>i.id==='res')?.value || 14} m³/s.** Live rainfall trajectory shows ${p.rainfall_mm} mm over the next 6-hour window. Storage and spillway gates remain in normal operating configuration.`,
      cite: `Hydrology SCADA · Live Precipitation Integration`
    };
  }

  return {
    text: `I'm tracking live meteorological metrics for **${city}** (${l.lat.toFixed(3)}°N, ${l.lon.toFixed(3)}°E). Ask me:\n\n• Will my area flood today?\n• Is rain expected in ${city}?\n• Should I irrigate crops?\n• What is the current air quality & weather?\n• Traffic & road conditions?`,
    cite: `RIIS Live Assistant · ${city}`
  };
}

function ChatPanel({ open, onClose }){
  const l = RIIS.location;
  const [msgs, setMsgs] = useState_ch([
    { who:"bot", text:`👋 Hi — I'm your RIIS Live Assistant. I am monitoring live weather and flood risk for **${l.city || "your location"}**. Ask me anything!`, cite:`Live · ${l.city || "Online"}` }
  ]);
  const [input, setInput] = useState_ch("");
  const bodyRef = useRef_ch();
  useEffect_ch(()=>{ if(bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight; },[msgs,open]);

  const send = (t)=>{
    const q = t ?? input;
    if(!q.trim()) return;
    setInput("");
    setMsgs(m=>[...m, { who:"user", text:q }]);
    setTimeout(()=>{
      const r = getDynamicBotResponse(q);
      setMsgs(m=>[...m, { who:"bot", text:r.text, cite:r.cite }]);
    },400);
  };

  if(!open) return null;
  return (
    <div className="chat-panel">
      <div className="chat-hd">
        <div className="av">{Icon.bot}</div>
        <div style={{flex:1}}>
          <div className="name">RIIS Live Assistant</div>
          <div className="st"><span className="d"/>Live · {l.city}</div>
        </div>
        <button className="iconbtn" onClick={onClose} style={{width:30,height:30}}>{Icon.x}</button>
      </div>
      <div className="chat-body" ref={bodyRef}>
        {msgs.map((m,i)=>(
          <div key={i} className={"msg "+m.who}>
            {m.text.split("\n").map((l,j)=>(
              <div key={j} dangerouslySetInnerHTML={{__html: l
                .replace(/\*\*(.+?)\*\*/g,'<b style="color:#7DD3FC">$1</b>')
                .replace(/^• /,'• ')
              }}/>
            ))}
            {m.cite && <div className="cite">↳ {m.cite}</div>}
          </div>
        ))}
      </div>
      <div className="suggests">
        {[`Will ${l.city} flood today?`,`Is rain expected?`,`Should I irrigate?`,`What is the current weather?`].map((s,i)=>(
          <span key={i} className="s" onClick={()=>send(s)}>{s}</span>
        ))}
      </div>
      <div className="chat-input">
        <input placeholder="Ask about rainfall, flood risk, roads..." value={input}
          onChange={e=>setInput(e.target.value)}
          onKeyDown={e=>e.key==="Enter"&&send()}/>
        <button onClick={()=>send()}>{Icon.send}</button>
      </div>
    </div>
  );
}

window.ChatPanel = ChatPanel;
