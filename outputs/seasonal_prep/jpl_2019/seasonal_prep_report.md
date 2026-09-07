# JPL seasonal preparation report

Status: CONDITIONAL_PASS
Months: 2019-02, 2019-08, 2019-11

## Acquisition

| Month | Official | Probe requests | Local | UTC | Left | Right | Carry | Carry complete | Valid chunks | Expected chunks | Matched | Missing | Orphan |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 1288 | 1 | 1288 | 1288 | 6 | 6 | 1 | 1 | 28 | 28 | 1289 | 0 | 0 |
| 2019-08 | 1509 | 1 | 1509 | 1511 | 2 | 0 | 0 | 0 | 31 | 31 | 1509 | 0 | 0 |
| 2019-11 | 1353 | 1 | 1353 | 1355 | 2 | 0 | 1 | 1 | 30 | 30 | 1354 | 0 | 0 |

## Cleaning

Structural sessions retain verified connection/disconnection state and remain in coverage denominators when either branch is unavailable. Analyzable session counts require a cleaned branch with positive observed duration; raw container validity alone does not establish an observed trajectory.

| Month | Acquisition sessions | Structural retained | Current analyzable | Pilot analyzable | Coverage denominator | Whole current unavailable | Whole pilot unavailable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 1289 | 1289 | 1287 | 1287 | 1289 | 2 | 2 |
| 2019-08 | 1509 | 1509 | 1509 | 1509 | 1509 | 0 | 0 |
| 2019-11 | 1354 | 1354 | 1347 | 1347 | 1354 | 7 | 7 |

| Month | Invalid placeholders | Current-only invalid | Pilot-only invalid | Both invalid | Metadata checked | Metadata matched | Metadata anomalies |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 2 | 0 | 0 | 2 | 2 | 2 | 0 |
| 2019-08 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2019-11 | 6 | 0 | 0 | 6 | 6 | 6 | 0 |

| Month | Attempted | Cleaned | Sessions omitted | Current invalid rate | Pilot invalid rate | Current raw | Current usable | Current retained | Current retained rate | Pilot raw | Pilot usable | Pilot retained | Pilot retained rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 1289 | 1289 | 0 | 0.0015515903801396431 | 0.0015515903801396431 | 8622405 | 8581940 | 8581940 | 0.9953069938143708 | 8627675 | 8587196 | 8587196 | 0.9953082377349634 |
| 2019-08 | 1509 | 1509 | 0 | 0.0 | 0.0 | 9796237 | 9749362 | 9749362 | 0.9952149993921136 | 9795474 | 9748682 | 9748682 | 0.9952230999745393 |
| 2019-11 | 1354 | 1354 | 0 | 0.004431314623338257 | 0.004431314623338257 | 8172792 | 8132700 | 8128880 | 0.9946270503397125 | 8178756 | 8138853 | 8135035 | 0.9946543215129539 |

### Trajectory quarantine

| Month | Trajectory quarantine | Full-session quarantine | Current raw-container count | Current container-valid after quarantine | Pilot raw-container count | Pilot container-valid after quarantine | Quarantine in denominator | Raw retained | Sort repair | Timestamp shift s | Interpolation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 0 | 0 | 1287 | 1287 | 1287 | 1287 | true | true | false | 0 | false |
| 2019-08 | 0 | 0 | 1509 | 1509 | 1509 | 1509 | true | true | false | 0 | false |
| 2019-11 | 1 | 0 | 1348 | 1347 | 1348 | 1347 | true | true | false | 0 | false |

| Month | Current duplicate extras | Pilot duplicate extras | Current conflicts | Pilot conflicts | Boundary points | Boundary sessions | Boundary integral share | Current boundary +/-60 | Pilot boundary +/-60 | Current mode s | Pilot mode s | Current hold s | Pilot hold s | User-input truncation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 2 | 25 | 24 | 1 | 493 | 292 | 3.544160246045563e-05 | 3.0535288075837265e-05 | 0.003284316683863742 | 4 | 4 | 12 | 12 | true |
| 2019-08 | 21 | 94 | 79 | 0 | 5944 | 386 | 0.0013016831551920073 | 0.0011226339162866742 | 0.0031061760633986765 | 4 | 4 | 12 | 12 | true |
| 2019-11 | 59 | 262 | 189 | 3 | 4681 | 313 | 0.001390497003309783 | 0.001226366157962035 | 0.0030691622589650875 | 4 | 4 | 12 | 12 | true |

## Power semantics

This accounting correction grants no new kW-label authorization; the existing E208 and power-semantics gates remain authoritative.

| Month | Status | E208 authorized | Pinned commit | Pinned formula | Mapping rate | Minimum kWh | Minimum coverage | Eligible | Retained | Retained rate | Voltage Q1 | Voltage median | Voltage Q3 | Voltage IQR | MdAPE | P90 APE | Aggregate relative error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | KW_RECONSTRUCTION_CANDIDATE | false | 14e723b11339e56ca3afd2bf4969f9e4bc8c2623 | E_208_kWh=208*ampere_hours/1000 | 1.0 | 0.5 | 0.9 | 1289 | 1208 | 0.9371605896043445 | 202.96523304643932 | 204.60849148138112 | 206.3852258980197 | 3.419992851580389 | 0.01783290960658708 | 0.03452497537642209 | 0.012671694114568548 |
| 2019-08 | KW_RECONSTRUCTION_CANDIDATE | false | 14e723b11339e56ca3afd2bf4969f9e4bc8c2623 | E_208_kWh=208*ampere_hours/1000 | 1.0 | 0.5 | 0.9 | 1509 | 1418 | 0.9396951623591783 | 202.20479756878726 | 204.0083715267089 | 206.35871350182026 | 4.153915933033005 | 0.021752629612152248 | 0.04051788089281101 | 0.016798426177806733 |
| 2019-11 | CURRENT_PROXY_ONLY | false | 14e723b11339e56ca3afd2bf4969f9e4bc8c2623 | E_208_kWh=208*ampere_hours/1000 | 1.0 | 0.5 | 0.9 | 1354 | 1075 | 0.7939438700147711 | 203.49776290829868 | 205.53753252176148 | 208.37696938810404 | 4.879206479805362 | 0.01724061534934028 | 0.037698012433495826 | 0.00892301009195581 |

## 15-minute

A bin with any positive-duration overlap with a wholly unobserved current session is excluded from station-current targets, even when coverage is at least 90%. Coverage-only counts are reported separately from final target-valid counts. Observed current partial sums remain diagnostic and unavailable current is not replaced by zero. Pilot-only missingness does not reject an otherwise valid current target.

| Month | Known-incomplete current bins | Known-incomplete pilot bins | Coverage-only 80 | Coverage-only 90 | Coverage-only 95 | Excluded despite coverage 80 | Excluded despite coverage 90 | Excluded despite coverage 95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 36 | 36 | 2610 | 2604 | 2602 | 0 | 0 | 0 |
| 2019-08 | 0 | 0 | 2960 | 2954 | 2943 | 0 | 0 | 0 |
| 2019-11 | 45 | 45 | 2768 | 2762 | 2755 | 1 | 0 | 0 |

| Month | Bins | Final valid 80 | Final valid 90 | Final valid 95 | Valid 80 rate | Valid 90 rate | Valid 95 rate | Missing 80 rate | Missing 90 rate | Missing 95 rate | Longest missing | Peak current | Max ramp | DST extra bins | Integral status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 2688 | 2610 | 2604 | 2602 | 0.9709821428571429 | 0.96875 | 0.9680059523809523 | 0.029017857142857095 | 0.03125 | 0.03199404761904767 | 36 | 765.5 | 328.314 | 0 | PASS |
| 2019-08 | 2976 | 2960 | 2954 | 2943 | 0.9946236559139785 | 0.9926075268817204 | 0.9889112903225806 | 0.005376344086021501 | 0.007392473118279619 | 0.011088709677419373 | 9 | 755.8 | 253.44233333 | 0 | PASS |
| 2019-11 | 2884 | 2767 | 2762 | 2755 | 0.9594313453536755 | 0.9576976421636616 | 0.9552704576976422 | 0.04056865464632453 | 0.0423023578363384 | 0.044729542302357816 | 32 | 754.9 | 183.18933333 | 4 | PASS |

| Month | Weekday bins | Weekday valid | Weekday mean | Weekday median | Weekend bins | Weekend valid | Weekend mean | Weekend median |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 1920 | 1895 | 189.52683571 | 44.89988889 | 768 | 709 | 7.89767717 | 0.0 |
| 2019-08 | 2112 | 2094 | 195.05122424 | 93.88922222 | 864 | 860 | 5.21839922 | 0.0 |
| 2019-11 | 2016 | 1912 | 183.61415202 | 60.45577778 | 868 | 850 | 18.13469595 | 0.0 |

## M1-M3

All future-label horizons use corrected target validity. Active charging counts are observed lower bounds; unknown current is not evidence that a connected session is inactive. Missing current, pilot and cumulative-current state retain their missingness masks; offline anomaly reasons do not enter online features.

| Month | Scheduled | Formal | Labels 15 | Labels 240 | M1 | M2 | M3 | M1 width | M2 width | M3 width | M1 encoded | M2 encoded | M3 encoded | Leakage violations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 2577 | 2388 | 2493 | 2493 | 2388 | 2388 | 2388 | 96 | 6 | 11 | 195 | 204 | 391 | 0 |
| 2019-08 | 2865 | 2784 | 2843 | 2843 | 2784 | 2784 | 2784 | 96 | 6 | 11 | 195 | 204 | 391 | 0 |
| 2019-11 | 2773 | 2517 | 2651 | 2651 | 2517 | 2517 | 2517 | 96 | 6 | 11 | 195 | 204 | 391 | 0 |

| Month | M1 history missing | M2 current missing | M2 pilot sum missing | M2 pilot mean missing | M3 current missing | M3 recent mean missing | M3 recent peak missing | M3 pilot missing | M3 departure missing | M3 energy missing | Feature whitelist |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 0.02590208 | 0.01088777 | 0.01088777 | 0.01088777 | 0.0022648 | 0.0001192 | 0.0001192 | 0.0022648 | 0.03951486 | 0.03951486 | PASS |
| 2019-08 | 0.00723255 | 0.00933908 | 0.00933908 | 0.00933908 | 0.00269376 | 0.00015393 | 0.00015393 | 0.00261679 | 0.02506478 | 0.02506478 | PASS |
| 2019-11 | 0.03514021 | 0.00476758 | 0.00397298 | 0.00397298 | 0.00898286 | 0.00024185 | 0.00024185 | 0.00487148 | 0.02788143 | 0.02788143 | PASS |

## Security

Aggregate-only evidence: YES
Raw inventories unchanged: YES
Network access: NO
Training executed: NO
M4 generated: NO
Config SHA256: ee5aa65322df108c837fe4a4fea49e30f1ec412f8ceb46dcd31e23336ef898b5
Code commit: 6ded3bdd810a8115ea5b8a51091de71fab894a03
2019-02 metadata source SHA256: bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
2019-02 metadata record SHA256: 62f8d00dead0b0f6ebc8f22083904076b42a82a7ae420d17f258bcdd982a9a66
2019-02 official reference SHA256: 2a6916f4d7c5272f3ec178bdfb2ab69d90e6117cafd77bf9375ef219e1938fef
2019-02 raw SHA256: 70a0a6178d39607045a0e048b119ef391fa7a6be96261020a2896e6a4d8742a0
2019-02 processed SHA256: 59eff11bd56ab09a80f26f20a5472a1463953e2c0e680aa270510ef04dd64604
2019-02 snapshot SHA256: 3583a639a36f9994138cf66f367af1a9096efccfa785328439d4b8c967d6209f
2019-08 metadata source SHA256: bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
2019-08 metadata record SHA256: 62f8d00dead0b0f6ebc8f22083904076b42a82a7ae420d17f258bcdd982a9a66
2019-08 official reference SHA256: d277233d62fca3665e263ee68d580b827d169313bbb50a64ea8c3a071aa4916d
2019-08 raw SHA256: 06b16066eeba18ef33ae0eb26a348111b316d213a8f9be88e9c9067059140f10
2019-08 processed SHA256: d938230d57a52b8728580f94737d469be47589c33d98be6aa9a15f5e75a78abb
2019-08 snapshot SHA256: 50dd7ce3f6f21fa66bc0b520201f88e6ddf061185f040424a87e8b327770cc11
2019-11 metadata source SHA256: bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
2019-11 metadata record SHA256: 62f8d00dead0b0f6ebc8f22083904076b42a82a7ae420d17f258bcdd982a9a66
2019-11 official reference SHA256: 692c3e304ceef3f42a786cf44337e4828c32cdc319bda6a816c34e2fbf695314
2019-11 raw SHA256: 77e7b261d488aec79a5d21648fbe1a9825b60cb1df65658de797fc2b404007f3
2019-11 processed SHA256: 097457efc566eeab1a79acb76d7ec2fca38f4dc35e1018687d45fc6bbd53c8b9
2019-11 snapshot SHA256: dc043e8b630b7bc5fa630b38345a4599b242f951ef242a45bcd62ea79f706ca9

## Decision

| Month | Preparation status | Power status | Leakage status | User-input truncation ready |
| --- | --- | --- | --- | --- |
| 2019-02 | PASS | KW_RECONSTRUCTION_CANDIDATE | PASS | true |
| 2019-08 | PASS | KW_RECONSTRUCTION_CANDIDATE | PASS | true |
| 2019-11 | PASS_WITH_TRAJECTORY_QUARANTINE | CURRENT_PROXY_ONLY | PASS | true |
