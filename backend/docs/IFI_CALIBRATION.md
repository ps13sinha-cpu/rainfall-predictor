# Rainfall hazard calibration against the India Flood Inventory

Computed 2026-10-09. India Flood Inventory TN events (district, date, duration) joined to TNDMA Revenue-gauge district-day means 1991-2023 (unreported days = dry); flood day = day before through end of a recorded event; +/-4 day buffer excluded from negatives; rank AUC of rain totals and of the engine accumulation score; isotonic P(flood|1-day rain) rescaled to 0..100.

Events matched: 141 of 147 Tamil Nadu events since 1991. District-days: 395,630, flood days: 3,416 (base rate 0.0086).

## Discrimination (rank AUC, flood day vs other day)

| Feature | AUC |
|---|---|
| r1 | 0.7929 |
| r1max | 0.7829 |
| r3 | 0.8381 |
| r5 | 0.8479 |
| r7 | 0.8469 |
| acc_score | 0.8434 |
| acc_score_unscaled3 | 0.8381 |
| r3_plus_ant30 | 0.8447 |

## Observed flood rate inside each engine class (accumulation score only)

| Class | District-days | Flood days | Flood rate | Lift | Recall at floor |
|---|---|---|---|---|---|
| safe | 394,280 | 3160 | 0.008 | 0.9x | 1.0 |
| mod | 1,091 | 188 | 0.1723 | 20.0x | 0.075 |
| high | 232 | 62 | 0.2672 | 31.0x | 0.02 |
| extreme | 27 | 6 | 0.2222 | 25.7x | 0.002 |

## Flood rate above IMD thresholds

| 1-day rain >= | District-days | Flood rate |
|---|---|---|
| 64.5 mm | 1060 | 0.1877 |
| 115.6 mm | 233 | 0.2704 |
| 204.5 mm | 27 | 0.2222 |

## Calibrated accumulation curve (isotonic, rescaled to 100 at the maximum observed flood rate)

Hand-set: 0.0 mm -> 0.0, 64.5 mm -> 25.0, 115.6 mm -> 50.0, 204.5 mm -> 75.0, 350.0 mm -> 100.0

Calibrated: 0.0 mm -> 0.0, 0.0 mm -> 5.8, 0.2 mm -> 6.0, 0.2 mm -> 6.3, 0.4 mm -> 7.1, 0.5 mm -> 7.8, 0.6 mm -> 8.8, 1.1 mm -> 9.5, 1.7 mm -> 10.2, 2.1 mm -> 10.8, 2.4 mm -> 12.4, 2.7 mm -> 12.7, 4.1 mm -> 13.8, 4.6 mm -> 15.0, 6.3 mm -> 15.2, 7.1 mm -> 17.8, 8.9 mm -> 18.4, 10.1 mm -> 19.3, 11.4 mm -> 21.1, 13.0 mm -> 22.8, 14.9 mm -> 24.9, 17.4 mm -> 30.3, 20.7 mm -> 32.5, 25.5 mm -> 41.9, 33.6 mm -> 45.6, 64.6 mm -> 100.0

## Per-district flood propensity (top 12)

| District | Years | Flood days / decade | Heavy days / yr | Flood rate on heavy days |
|---|---|---|---|---|
| Chennai | 32.5 | 75.9 | 1.72 | 0.429 |
| Nagapattinam | 33.0 | 52.2 | 2.7 | 0.27 |
| Kanniyakumari | 32.9 | 44.4 | 1.49 | 0.224 |
| Tiruvannamalai | 32.7 | 44.0 | 0.98 | 0.156 |
| Villupuram | 32.7 | 43.2 | 0.7 | 0.217 |
| Coimbatore | 33.0 | 43.1 | 0.03 | 0.0 |
| Cuddalore | 33.0 | 41.8 | 2.09 | 0.333 |
| Thanjavur | 19.2 | 40.6 | 1.3 | 0.48 |
| Tirunelveli | 32.7 | 40.0 | 0.24 | 0.0 |
| Thoothukudi | 32.7 | 38.5 | 0.31 | 0.0 |
| Madurai | 26.7 | 37.1 | 0.15 | 0.25 |
| The Nilgiris | 33.0 | 37.0 | 0.36 | 0.167 |

## Scope

rainfall term only: the inventory is by district and day, so elevation, drainage and the other modifiers are not calibrated by this.

Unmatched inventory district names: Districts of Cauvery delta (1), Districts of Cauvery delta zone (1), Karaikal (1), Many districts of Tamil Nadu. (2), Many parts (1), Many parts of Tamil Nadu. (1), Nagarkoil (1), South Tripura (1)
