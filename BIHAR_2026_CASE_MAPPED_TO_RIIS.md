# Bihar Floods 2026, mapped to RIIS

Compiled 8 October 2026 from reporting through 7 October. The season is still active, so
figures will move. Where sources disagree, both are given.

---

## 1. What happened

### Wave one: early to mid September, the Ganga corridor

- The Ganga broke its all-time high flood levels at Gandhi Ghat in Patna on 6 September
  (50.57 m against the 2016 record of 50.52 m), at Pandarak the same day, and at Sultanganj in
  Bhagalpur on 8 September.
- Worst-hit districts: Patna, Bhagalpur, Saran, Vaishali, Begusarai, Katihar, Purnea, Buxar.
- Diara villages in Maner, Danapur, Raghopur and Panapur were cut off. Five drowning deaths in
  Patna district, five more in one Bhagalpur village, four of them children.
- A 20 m section of the Mahi embankment failed near Trilokchak in Saran on 5 September and a
  ring bund on the Daha breached at Imadpur Bind Toli. Twelve villages flooded from the Mahi alone.
- State count on 14 September: about 50 lakh people across 15 districts, 88 blocks,
  575 gram panchayats. 1,260 community kitchens, 13 relief camps.

### Wave two: late September to early October, the Gandak and north Bihar

- Heavy rain in Nepal's Gandak catchment pushed the Valmikinagar barrage discharge above
  5 lakh cusecs for several hours. The state's 30 September review called it the largest Nepal
  inflow on record.
- The Gandak hit 91.25 m at Bagaha on 1 October, above the 2024 record of 90.90 m.
- The Champaran embankment breached at four points within about ten hours: Khairatwa,
  Phuliyakhad, Bathuwaria and Golaghat. The Gandak ring embankment breached at Areraj in
  East Champaran. The Zamindari embankment was damaged at Sheetalpur in Gopalganj. Eight metres
  of the right Saran embankment subsided at Haizalpur, Maker block, and water spread into new
  parts of Saran on 2 October.
- Over 200 villages flooded across West Champaran, East Champaran, Gopalganj and Saran,
  spreading toward Muzaffarpur and Vaishali. State count on 7 October: nearly 10 lakh people
  in 169 gram panchayats across six districts.
- On 6 October the Gandak at Dumariaghat, the Ganga at Sultanganj and Hathidah, the Kosi at
  Birpur and Kursela, the Burhi Gandak at Khagaria, the Bagmati at Benibad and the Ghaghra at
  Darauli were all still above danger level.
- Ganga erosion on the Sahibganj to Maharajpur rail section forced a line closure and four
  train cancellations.

### The fact that matters most for RIIS

Bihar had a **35 percent rainfall deficit** this monsoon and still put four to five million
people under water. The rain that flooded Bihar fell in Nepal and Uttar Pradesh, on soils that
had dried out early and saturated late, and arrived through barrages and embankments that
failed. Experts quoted by Mongabay also point to Farakka barrage backwater slowing the Ganga's
drainage in the second half of the monsoon.

### The information gap

- Officials told Mongabay there had been no human deaths while district officers were
  confirming drownings.
- Official figures do not report farmland under water, crops lost, cattle dead, houses
  damaged or people missing, even though the state's own disaster SOP requires it.
- Relief camps were set up in towns, not in the villages that flooded. Families reported
  receiving 5 kg of flattened rice, two candles and 200 g of jaggery.
- The agriculture department will release crop damage figures only after water recedes.
  Megh Pyne Abhiyan's 2024 survey found average household losses of Rs 5.5 lakh against flat
  compensation paid months later.

---

## 2. Mapped to RIIS, component by component

| What Bihar showed | RIIS component | What RIIS does today | Gap for Bihar |
|---|---|---|---|
| Floods with a 35 percent rain deficit | Core thesis, slides 2 to 4 | The whole system is built on "rainfall is not impact". Local rain is one of ten factors, weighted 22 percent | Nothing. This is the strongest possible proof of the thesis |
| Upstream rain in Nepal drove the Gandak and Kosi | Upstream & Coastal factor, 8 percent weight | Reads reservoir levels for the nearest reservoir in the table and river proximity | No catchment-scale rain. Needs Open-Meteo rain for the Nepal Gandak and Kosi basins as an upstream feature, and barrage discharge as a live input |
| Valmikinagar above 5 lakh cusecs, Birpur rising | Reservoir live service | Scrapes CMWSSB and KSEB daily pages | Add the Bihar Water Resources Department flood bulletin and CWC gauge pages for Valmikinagar, Birpur, Dumariaghat, Gandhi Ghat. Same scraper pattern |
| Ganga broke all-time high flood levels | Historical factor, return period from 30 years of archive rain | Return period is computed on rainfall at the point | For riverine sites the return period must be on river stage, not local rain. CWC publishes historical HFL per gauge |
| Soils dried early, saturated late, then everything ran off | Hydrological factor, antecedent saturation | Pulls soil moisture at three depths and 3, 7, 30 day antecedent rain from Open-Meteo | Already covered. This is exactly the mechanism the saturation term models |
| Six embankment breaches in ten hours | Not modelled | Inundation model assumes water spreads from local ponding | Embankments are OSM `man_made=embankment` and `dyke` tags. A breach scenario needs a point source on the DEM, not a uniform ponding volume. Feasible: seed the priority flood fill from the breach cell |
| Diara villages cut off, relief camps in towns | Safe Routes, exposure factor | Scores roads by flood depth, routes around closures, counts people in the cell | Works as is for any site once the DEM and roads are fetched. The "destination cut off" response is exactly the diara case |
| Rail line closed by erosion | Not modelled | Roads only | Add OSM `railway=rail` segments to the same scoring, low effort |
| 1,000 acres of farmland lost in one Katihar village, no official count | Farmer advisory, flood history | Waterlogging risk per field from the ponding model, crop and stage aware | Add a post-event mode: record the modelled depth and duration per field as evidence for compensation claims. The data gap Mongabay describes is a product opportunity |
| Deaths denied centrally while confirmed locally | Community reports, system logs | Reports with upvotes and moderation feed the road layer | Extend reports to deaths, cattle and house damage with photo and timestamp, matching the state SOP's own requirement |
| No forecast of where water would arrive next | Inundation map, what-if scenarios | Any rainfall and duration at any point, mapped in seconds | For riverine floods the forcing is river stage, not rainfall. Add a stage-driven mode: set water surface to the gauge level instead of solving for ponding volume |
| Alerts went to 17 districts on alert mode | Alerting by district and ward risk class | Twilio, WhatsApp, Firebase, targeted by risk | Ready. Needs Bihar districts seeded and the river-stage mode above to make the risk class meaningful |

---

## 3. What RIIS would have shown, had it been running in Bihar

1. **Early August:** antecedent rain and soil moisture at Open-Meteo grid points across north
   Bihar rising sharply after the dry June. Hydrological factor climbing while the
   meteorological factor stayed low. The impact score diverging from the rainfall alert.
2. **Early September:** Ganga gauge levels (if ingested) approaching HFL at Gandhi Ghat and
   Pandarak. Historical factor on river stage at a 1 in 10 year or rarer return period.
   Exposure factor high for Patna's diara panchayats.
3. **29 to 30 September:** Nepal catchment rain (Open-Meteo at Gandak basin points) and
   Valmikinagar discharge both spiking. Upstream factor at maximum. Safe Routes in West
   Champaran and Saran showing roads closing toward the embankments.
4. **1 October onward:** breach-seeded inundation runs for Khairatwa, Areraj, Haizalpur,
   showing which villages fill first and how deep, and which roads out remain open.
5. **Throughout:** per-field modelled depth and duration logged, so that when the agriculture
   department finally assesses losses, farmers have a dated record.

---

## 4. What to add to Bihar-proof RIIS, in order

| Change | Effort | Why first |
|---|---|---|
| Seed Bihar districts and the Gandak, Kosi, Ganga gauge sites | Hours | Everything else needs sites |
| Scrape CWC and Bihar WRD gauge and barrage pages into the reservoir table | One day | Riverine floods are driven by stage and discharge, not local rain |
| Upstream rain feature: Open-Meteo at Nepal catchment points, 24 to 72 hour sums | One day | The single biggest missing driver this year |
| Stage-driven inundation mode: water surface set from gauge level | One day | Turns the existing DEM model into a riverine tool |
| Breach-seeded inundation: priority flood from a chosen breach cell | One to two days | Six breaches in ten hours is the Bihar failure mode |
| Rail segments in Safe Routes | Hours | Sahibganj closure |
| Post-event evidence log per field and household | Two days | The compensation gap is documented and unfilled |

---

## 5. One slide for the deck

**Title:** Bihar 2026: four million flooded with a 35 percent rain deficit

**Left column, what happened:**
- Ganga above all-time high at Patna and Bhagalpur, 6 to 8 September
- Nepal inflow above 5 lakh cusecs, Gandak record at Bagaha, 1 October
- Six embankment breaches in ten hours, 200 villages flooded
- 50 lakh people, 15 districts, no official crop or cattle count

**Right column, what it proves:**
- Rainfall at the point is not the hazard. Upstream rain, saturation and failed
  infrastructure are
- Alerts by district reached 17 districts and still nobody knew which village filled next
- The information gap after the flood is as costly as the flood

**Bottom line:** RIIS already models saturation, exposure, roads and ponding. For Bihar it
needs river stage and upstream rain as inputs, and a breach mode. All free data, about a week.

---

## Sources

- Mongabay India, floods despite rainfall deficit: https://india.mongabay.com/2026/09/floods-affect-millions-despite-rainfall-deficit/
- The Watchers, 8 September: https://watchers.news/2026/09/08/five-dead-as-bihar-floods-affect-more-than-3-4-million-ganga-exceeds-previous-highest-levels/
- The Watchers, 7 October: https://watchers.news/2026/10/07/nearly-1-million-affected-by-floods-in-bihar-rivers-remain-above-danger-level-india/
- Daijiworld, Gandak record and breaches, 1 October: https://daijiworld.com/news/newsDisplay?newsID=1328211
- Telangana Today, Gandak enters Saran, 2 October: https://telanganatoday.com/bihar-floods-gandak-breaches-embankments-enters-new-areas-of-saran
- Tech Times, Ganga high-water marks: https://www.techtimes.com/articles/327077/20260909/bihar-floods-displace-four-million-ganga-breaks-all-time-high-water-marks.htm
- Patna Press, Kosi barrage discharge: https://patnapress.com/2-15-lakh-cusec-water-released-from-kosi-barrage-as-heavy-rain-in-nepal-raises-flood-concerns-in-bihar/
- Patna Press, BUIDCO monsoon plan: https://patnapress.com/patna-monsoon-waterlogging-buidco-drainage-pumping-stations-2026/
- Madhyamam, 13 districts: https://madhyamamonline.com/india/bihar-floods-kill-20-leave-27-mn-people-reeling-across-13-districts-1552707
