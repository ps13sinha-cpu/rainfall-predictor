// RIIS API Client — communicates with the FastAPI backend (port 8000)
(function() {
  // The backend runs independently of the static frontend.  Override this at
  // deployment time with `window.RIIS_API_BASE`, or save a URL in localStorage.
  // Port 8001 keeps the RIIS API clear of the common local port-8000 services.
  // start-riis.ps1 runs uvicorn on 8001; 8000 is kept as a fallback for a manually started backend.
  const EXPLICIT_BASE = window.RIIS_API_BASE || localStorage.getItem('riis_api_base');
  const CANDIDATE_BASES = ['http://127.0.0.1:8001', 'http://127.0.0.1:8000'];
  let API_BASE = (EXPLICIT_BASE || CANDIDATE_BASES[0]).replace(/\/$/, '');
  window.OPENWEATHER_API_KEY = window.OPENWEATHER_API_KEY || localStorage.getItem('openweather_api_key') || '';

  function apiFetch(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json', ...opts.headers };
    const token = localStorage.getItem('riis_token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return fetch(`${API_BASE}${path}`, { ...opts, headers })
      .then(r => {
        if (!r.ok) throw new Error(`API ${r.status}: ${r.statusText}`);
        return r.json();
      });
  }

  // Probe the candidate ports once so the UI finds the backend wherever it was started.
  const baseReady = EXPLICIT_BASE ? Promise.resolve(API_BASE) : (async () => {
    for (const base of CANDIDATE_BASES) {
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 2500);
        const r = await fetch(`${base}/api/health`, { signal: ctrl.signal });
        clearTimeout(t);
        if (r.ok) { API_BASE = base; break; }
      } catch (e) { /* try the next port */ }
    }
    window.RIIS_API.baseUrl = API_BASE;
    console.log('[RIIS] backend detected at', API_BASE);
    return API_BASE;
  })();

  // ── Districts ─────────────────────────────────────────────────────────────
  window.RIIS_API = {
    // Get all districts with live risk data from backend
    getDistricts() {
      return apiFetch('/api/districts/?limit=50');
    },

    // Get a single district with full weather data
    getDistrict(code) {
      const bc = code && !code.startsWith('IN-') ? 'IN-' + code : code;
      return apiFetch(`/api/districts/${bc}`);
    },

    // Get hourly forecast for a district
    getDistrictHourly(code) {
      const bc = code && !code.startsWith('IN-') ? 'IN-' + code : code;
      return apiFetch(`/api/districts/${bc}/hourly`);
    },

    // ── Weather ─────────────────────────────────────────────────────────────
    refreshWeather() {
      return apiFetch('/api/weather/refresh', { method: 'POST' });
    },

    refreshDistrict(code) {
      return apiFetch(`/api/weather/refresh/${code}`, { method: 'POST' });
    },

    // ── Reservoirs ──────────────────────────────────────────────────────────
    getReservoirs() {
      return apiFetch('/api/reservoirs/');
    },

    getReservoir(code) {
      return apiFetch(`/api/reservoirs/${code}`);
    },

    // Live feed status: when CMWSSB / KSEB were last fetched and which codes are live
    getReservoirStatus() {
      return apiFetch('/api/reservoirs/live/status');
    },

    // Fetch both daily reports now
    syncReservoirs() {
      return apiFetch('/api/reservoirs/sync', { method: 'POST' });
    },

    // Daily storage history (Chennai Metro Water reservoirs)
    getReservoirHistory(code, days = 14) {
      return apiFetch(`/api/reservoirs/${code}/history?days=${days}`);
    },

    updateReservoir(code, data) {
      return apiFetch(`/api/reservoirs/${code}`, {
        method: 'PUT',
        body: JSON.stringify(data)
      });
    },

    // ── Community Reports ───────────────────────────────────────────────────
    getReports(params = {}) {
      const qs = new URLSearchParams();
      if (params.status) qs.set('status', params.status);
      if (params.severity) qs.set('severity', params.severity);
      if (params.limit) qs.set('limit', String(params.limit));
      return apiFetch(`/api/reports/?${qs.toString()}`);
    },

    submitReport(data) {
      return apiFetch('/api/reports/', {
        method: 'POST',
        body: JSON.stringify(data)
      });
    },

    upvoteReport(id) {
      return apiFetch(`/api/reports/${id}/upvote`, { method: 'POST' });
    },

    moderateReport(id, action, note = '') {
      return apiFetch(`/api/reports/${id}/moderate?action=${action}&note=${encodeURIComponent(note)}`, {
        method: 'PUT'
      });
    },

    // Upload media for a report
    uploadMedia(file) {
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('riis_token');
      const headers = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      return fetch(`${API_BASE}/api/uploads/`, {
        method: 'POST',
        headers,
        body: formData
      }).then(r => r.json());
    },

    // ── Alerts ──────────────────────────────────────────────────────────────
    getAlerts(params = {}) {
      const qs = new URLSearchParams();
      if (params.active_only !== undefined) qs.set('active_only', String(params.active_only));
      if (params.severity) qs.set('severity', params.severity);
      return apiFetch(`/api/alerts/?${qs.toString()}`);
    },

    createAlert(data) {
      return apiFetch('/api/alerts/', {
        method: 'POST',
        body: JSON.stringify(data)
      });
    },

    deactivateAlert(id) {
      return apiFetch(`/api/alerts/${id}/deactivate`, { method: 'PUT' });
    },

    // Broadcast alert via SMS/WhatsApp/Push
    broadcastAlert(id, channels) {
      return apiFetch(`/api/alerts/${id}/broadcast`, {
        method: 'POST',
        body: JSON.stringify({ channels })
      });
    },

    // ── Auth ────────────────────────────────────────────────────────────────
    register(data) {
      return apiFetch('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify(data)
      });
    },

    login(username, password) {
      return apiFetch('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password })
      }).then(result => {
        if (result.access_token) {
          localStorage.setItem('riis_token', result.access_token);
          localStorage.setItem('riis_user', JSON.stringify(result.user));
        }
        return result;
      });
    },

    logout() {
      localStorage.removeItem('riis_token');
      localStorage.removeItem('riis_user');
    },

    getMe() {
      return apiFetch('/api/auth/me');
    },

    // ── ML / Predictions ────────────────────────────────────────────────────
    getPrediction(districtCode) {
      const bc = districtCode && !districtCode.startsWith('IN-') ? 'IN-' + districtCode : districtCode;
      return apiFetch(`/api/ml/predict/${bc}`);
    },

    getShapExplanations(districtCode) {
      const bc = districtCode && !districtCode.startsWith('IN-') ? 'IN-' + districtCode : districtCode;
      return apiFetch(`/api/ml/shap/${bc}`);
    },

    // Every tabular model's prediction for the district, side by side
    getPredictAll(districtCode) {
      const bc = districtCode && !districtCode.startsWith('IN-') ? 'IN-' + districtCode : districtCode;
      return apiFetch(`/api/ml/predict-all/${bc}`);
    },

    // Registry of all trained models with held-out metrics
    getModels() {
      return apiFetch('/api/ml/models');
    },

    getHistorical(districtCode, startDate, endDate) {
      const bc = districtCode && !districtCode.startsWith('IN-') ? 'IN-' + districtCode : districtCode;
      return apiFetch(`/api/historical/${bc}?start_date=${startDate}&end_date=${endDate}`);
    },

    ingestHistorical(districtCode, startDate, endDate) {
      const bc = districtCode && !districtCode.startsWith('IN-') ? 'IN-' + districtCode : districtCode;
      return apiFetch(`/api/historical/ingest/${bc}?start_date=${startDate}&end_date=${endDate}`, {
        method: 'POST'
      });
    },

    // ── Hyperlocal Impact Engine ────────────────────────────────────────────
    // Geospatial factors for a point: elevation, slope, water distance, soil, landuse
    getGeofactors(lat, lon, force = false) {
      return apiFetch(`/api/hyperlocal/geofactors?lat=${lat}&lon=${lon}${force ? '&force=true' : ''}`);
    },

    // DEM-driven flood extent (real elevation grid + depression filling)
    getInundation(params = {}) {
      const qs = new URLSearchParams();
      qs.set('lat', params.lat); qs.set('lon', params.lon);
      if (params.rainfall_mm != null) qs.set('rainfall_mm', params.rainfall_mm);
      if (params.duration_h != null) qs.set('duration_h', params.duration_h);
      if (params.intensity_mm_h != null) qs.set('intensity_mm_h', params.intensity_mm_h);
      return apiFetch(`/api/hyperlocal/inundation?${qs.toString()}`);
    },

    // Full ten-factor rainfall impact assessment for a hyperlocal point (engine v2)
    getHyperlocalImpact(params = {}) {
      const qs = new URLSearchParams();
      qs.set('lat', params.lat); qs.set('lon', params.lon);
      if (params.rainfall_mm != null) qs.set('rainfall_mm', params.rainfall_mm);
      if (params.duration_h != null) qs.set('duration_h', params.duration_h);
      if (params.intensity_mm_h != null) qs.set('intensity_mm_h', params.intensity_mm_h);
      if (params.pattern) qs.set('pattern', params.pattern);
      if (params.ml_score != null) qs.set('ml_score', params.ml_score);
      return apiFetch(`/api/hyperlocal/impact?${qs.toString()}`);
    },

    // Every raw input the engine uses (terrain, soil moisture, OSM, tide, reservoirs, flood history)
    getHyperlocalFactors(lat, lon) {
      return apiFetch(`/api/hyperlocal/factors?lat=${lat}&lon=${lon}`);
    },

    // ── Safe Routes ─────────────────────────────────────────────────────────
    getRoadSite(lat, lon, force = false) {
      return apiFetch(`/api/routes/site?lat=${lat}&lon=${lon}${force ? '&force=true' : ''}`);
    },

    // Road segments with flood status for a scenario (GeoJSON + most_affected)
    getRoads(params = {}) {
      const qs = new URLSearchParams();
      qs.set('lat', params.lat); qs.set('lon', params.lon);
      if (params.rainfall_mm != null) qs.set('rainfall_mm', params.rainfall_mm);
      if (params.duration_h != null) qs.set('duration_h', params.duration_h);
      if (params.intensity_mm_h != null) qs.set('intensity_mm_h', params.intensity_mm_h);
      if (params.mode) qs.set('mode', params.mode);
      return apiFetch(`/api/routes/roads?${qs.toString()}`);
    },

    // Safe route + normal route between two points
    getRoute(params = {}) {
      const qs = new URLSearchParams();
      qs.set('from_lat', params.from_lat); qs.set('from_lon', params.from_lon);
      qs.set('to_lat', params.to_lat); qs.set('to_lon', params.to_lon);
      if (params.rainfall_mm != null) qs.set('rainfall_mm', params.rainfall_mm);
      if (params.duration_h != null) qs.set('duration_h', params.duration_h);
      if (params.intensity_mm_h != null) qs.set('intensity_mm_h', params.intensity_mm_h);
      if (params.mode) qs.set('mode', params.mode);
      return apiFetch(`/api/routes/route?${qs.toString()}`);
    },

    geocode(q, lat, lon) {
      return apiFetch(`/api/routes/geocode?q=${encodeURIComponent(q)}&lat=${lat}&lon=${lon}`);
    },

    reverseGeocode(lat, lon) {
      return apiFetch(`/api/routes/reverse?lat=${lat}&lon=${lon}`);
    },

    postRoadReport(body) {
      return apiFetch('/api/routes/report', { method: 'POST', body: JSON.stringify(body) });
    },

    getRoadReports(lat, lon) {
      return apiFetch(`/api/routes/reports?lat=${lat}&lon=${lon}`);
    },

    getRoadModel() {
      return apiFetch('/api/routes/model');
    },

    // ── Stats ───────────────────────────────────────────────────────────────
    getStats() {
      return apiFetch('/api/stats');
    },

    getHealth() {
      return apiFetch('/api/health');
    }
  };

  // Auto-login check on load
  const savedUser = localStorage.getItem('riis_user');
  if (savedUser) {
    try { window.RIIS_API._user = JSON.parse(savedUser); } catch(e) {}
  }

  window.RIIS_API.baseUrl = API_BASE;
  window.RIIS_API.ready = baseReady;
  console.log('[RIIS] API client initialized — backend:', API_BASE);
})();
