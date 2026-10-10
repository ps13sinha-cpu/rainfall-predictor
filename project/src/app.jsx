// RIIS — App shell + router with Auto-Location & Live Search
const { useState: useState_a, useEffect: useEffect_a } = React;

function useHash(){
  const [h,setH] = useState_a(()=>location.hash || "#/dashboard");
  useEffect_a(()=>{
    const on = ()=>{ setH(location.hash || "#/dashboard"); try{localStorage.setItem("riis:route",location.hash)}catch(e){} };
    window.addEventListener("hashchange", on);
    // restore
    try{ const saved = localStorage.getItem("riis:route"); if(saved && !location.hash) location.hash = saved; }catch(e){}
    return ()=>window.removeEventListener("hashchange", on);
  },[]);
  return h;
}

function Clock(){
  const [t,setT] = useState_a(new Date());
  useEffect_a(()=>{ const i=setInterval(()=>setT(new Date()),1000); return ()=>clearInterval(i); },[]);
  const pad = n=>String(n).padStart(2,"0");
  const utcH = t.getUTCHours(), utcM = t.getUTCMinutes(), utcS = t.getUTCSeconds();
  let istM = utcM + 30; let istHrs = utcH + 5; if(istM>=60){istM-=60;istHrs+=1;} istHrs = istHrs%24;
  return (
    <div className="clock">
      <div className="t mono">{pad(istHrs)}:{pad(istM)}:{pad(utcS)} <span style={{color:"var(--text-lo)"}}>IST</span></div>
      <div className="z">{pad(utcH)}:{pad(utcM)}:{pad(utcS)} UTC</div>
    </div>
  );
}

function TopBar({ onOpenEmerg, riisUpdateCount }){
  const [query, setQuery] = useState_a("");
  
  const handleLocate = () => {
    // Forget the saved location and locate from this device (GPS first, IP guess only as a fallback)
    if (window.relocateFromDevice) window.relocateFromDevice();
    else if (window.fetchDeviceLocationAndWeather) window.fetchDeviceLocationAndWeather(true);
  };

  const handleSearchSubmit = (e) => {
    if (e.key === "Enter" || e.type === "click") {
      if (query.trim() && window.searchAndLoadLocation) {
        window.searchAndLoadLocation(query.trim());
      }
    }
  };

  const isLoading = window.RIIS?.locationLoading;
  const isDevice = window.RIIS?.isDeviceLocation;
  const hasError = window.RIIS?.locationError;

  return (
    <div className="topbar">
      <div className="crumb">RIIS <b>Rainfall Impact Intelligence</b></div>
      <div className="search" style={{ position: "relative" }}>
        <span className="ic" onClick={handleSearchSubmit} style={{ cursor: "pointer" }}>{Icon.search}</span>
        <input 
          placeholder="Search a place to view on the national map…"
          value={query}
          onChange={(e)=>setQuery(e.target.value)}
          onKeyDown={handleSearchSubmit}
        />
        {query && (
          <button 
            onClick={()=>setQuery("")}
            style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", color: "var(--text-lo)", cursor: "pointer", fontSize: 13 }}
          >✕</button>
        )}
      </div>
      <button 
        className={`iconbtn locate-btn ${isLoading ? 'loading' : ''} ${isDevice ? 'active' : ''}`}
        title={isLoading ? "Acquiring live coordinates..." : isDevice ? "Active device location" : "Use device location"}
        onClick={handleLocate}
        style={{ marginRight: 8 }}
      >
        {isLoading ? <span className="spinner-mini" /> : Icon.pin}
      </button>
      {hasError && (
        <span className="error-tooltip" title={hasError} style={{ color: "#EF4444", fontSize: 14, cursor: "help", marginRight: 8 }}>⚠️</span>
      )}
      <div className="status-chip">
        <span className="dot"/>ALL SYSTEMS NOMINAL · LIVE METRICS ACTIVE
      </div>
      <Clock/>
      <button className="iconbtn" title="Notifications">{Icon.bell}<span className="badge">{window.RIIS?.alerts?.length || 3}</span></button>
      <button className="iconbtn" title="Layers">{Icon.layer}</button>
      <button className="emergbtn" onClick={onOpenEmerg}>
        {Icon.siren}<span>EMERGENCY</span>
      </button>
    </div>
  );
}

function Rail({ active, go }){
  const navItems = [
    { id:"dashboard", label:"Dashboard",       ic:Icon.home,     hash:"#/dashboard" },
    { id:"map",       label:"India Map",       ic:Icon.map,      hash:"#/map" },
    { id:"city",      label:`City · ${window.RIIS?.location?.city || "Local"}`, ic:Icon.city, hash:"#/city" },
    { id:"explainable",label:"Explainable AI", ic:Icon.brain,    hash:"#/explainable" },
    { id:"timeline",  label:"Timeline",        ic:Icon.clock,    hash:"#/timeline" },
    { id:"simulate",  label:"Flood Simulator", ic:Icon.wave,     hash:"#/simulate" },
    { id:"routes",    label:"Safe Routes",     ic:Icon.map,      hash:"#/routes" },
    { id:"farmer",    label:"Farmer Advisory", ic:Icon.leaf,     hash:"#/farmer" },
    { id:"reservoir", label:"Reservoirs",      ic:Icon.droplet,  hash:"#/reservoir" },
    { id:"disaster",  label:"Disaster Ops",    ic:Icon.shield,   hash:"#/disaster" },
    { id:"alerts",    label:"Alerts",          ic:Icon.bell,     hash:"#/alerts" },
    { id:"community", label:"Community",       ic:Icon.users,    hash:"#/community" },
    { id:"history",   label:"Historical",      ic:Icon.chart,    hash:"#/history" },
    { id:"admin",     label:"Admin",           ic:Icon.gear,     hash:"#/admin" },
  ];

  return (
    <aside className="rail">
      <div className="logo" title="RIIS">R</div>
      <nav>
        {navItems.map(n=>(
          <a key={n.id} href={n.hash} className={"nav-item"+(active===n.id?" active":"")} onClick={(e)=>{e.preventDefault();go(n.hash);}}>
            {n.ic}
            <span className="tip">{n.label}</span>
          </a>
        ))}
      </nav>
      <div className="user" title="RIIS Operations Terminal">OP</div>
    </aside>
  );
}

// Data licences require this on every screen (Open-Meteo CC BY 4.0, OSM ODbL, SoilGrids and IFI CC BY 4.0).
function AttributionFooter(){
  const link = { color:"var(--text-mid)", textDecoration:"underline", textDecorationColor:"var(--stroke-2)" };
  return (
    <footer className="attribution" style={{marginTop:"auto",padding:"10px 24px 12px",fontSize:10.5,lineHeight:1.7,color:"var(--text-lo)",borderTop:"1px solid var(--stroke)",background:"var(--bg-2)"}}>
      Weather data by <a href="https://open-meteo.com/" target="_blank" rel="noreferrer" style={link}>Open-Meteo.com</a> (CC BY 4.0)
      {" · "}Map data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" style={link}>OpenStreetMap contributors</a> (ODbL)
      {" · "}Soil data <a href="https://soilgrids.org/" target="_blank" rel="noreferrer" style={link}>ISRIC SoilGrids</a> (CC BY 4.0)
      {" · "}Flood history <a href="https://doi.org/10.5281/zenodo.4742142" target="_blank" rel="noreferrer" style={link}>India Flood Inventory</a> (CC BY 4.0)
      {" · "}Elevation SRTM via <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noreferrer" style={link}>AWS Terrain Tiles</a>
      {" · "}Forecast fallback <a href="https://api.met.no/" target="_blank" rel="noreferrer" style={link}>MET Norway</a> (CC BY 4.0)
    </footer>
  );
}

function App(){
  const hash = useHash();
  const active = (hash||"").replace("#/","").split("?")[0] || "dashboard";
  const [chatOpen, setChatOpen] = useState_a(false);
  const [emergOpen, setEmergOpen] = useState_a(false);
  const [riisUpdateCount, setRiisUpdateCount] = useState_a(0);
  
  useEffect_a(() => {
    window.triggerRiisUpdate = () => setRiisUpdateCount(prev => prev + 1);
    
    // Auto-fetch device location and live weather on startup
    if (window.fetchDeviceLocationAndWeather) {
      window.fetchDeviceLocationAndWeather();
    }

    // Fetch live weather for all districts on startup
    if (window.fetchDistrictsLiveData) {
      window.fetchDistrictsLiveData();
    }

    // Auto-refresh districts every 5 minutes
    const districtRefresh = setInterval(() => {
      if (window.fetchDistrictsLiveData) window.fetchDistrictsLiveData();
    }, 5 * 60 * 1000);

    return () => {
      delete window.triggerRiisUpdate;
      clearInterval(districtRefresh);
    };
  }, []);

  const go = (h)=>{ location.hash = h; };

  let screen;
  switch(active){
    case "dashboard":  screen = <DashboardScreen go={go}/>; break;
    case "map":        screen = <MapScreen go={go}/>; break;
    case "city":       screen = <CityScreen go={go}/>; break;
    case "explainable":screen = <ExplainableScreen/>; break;
    case "timeline":   screen = <TimelineScreen/>; break;
    case "simulate":   screen = <SimulateScreen/>; break;
    case "routes":     screen = <RoutesScreen/>; break;
    case "farmer":     screen = <FarmerScreen/>; break;
    case "reservoir":  screen = <ReservoirScreen/>; break;
    case "disaster":   screen = <DisasterScreen/>; break;
    case "alerts":     screen = <AlertsScreen/>; break;
    case "community":  screen = <CommunityScreen/>; break;
    case "history":    screen = <HistoryScreen/>; break;
    case "admin":      screen = <AdminScreen/>; break;
    default:           screen = <DashboardScreen go={go}/>;
  }

  return (
    <div className="app">
      <Rail active={active} go={go}/>
      <main className="main" data-screen-label={active}>
        <TopBar onOpenEmerg={()=>setEmergOpen(true)} riisUpdateCount={riisUpdateCount}/>
        {screen}
        <AttributionFooter/>
      </main>

      {/* Floating chat FAB */}
      {!chatOpen && !emergOpen && (
        <button className="chat-fab" onClick={()=>setChatOpen(true)} title="RIIS Assistant">
          {Icon.bot}
        </button>
      )}
      <ChatPanel open={chatOpen} onClose={()=>setChatOpen(false)}/>

      {emergOpen && <EmergencyOverlay onClose={()=>setEmergOpen(false)}/>}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
