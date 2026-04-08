# IONOS_SIM - RF ionospheric channel simulator based on an extended Watterson model for long and medium wave

This simulator alters audio signals as if they had reached a radio receiver at specific times of day/year via multiple propagation paths over long or medium wave according to ITU-R P.1407, ITU-R F.1487 and ITU-R P.368 (ground wave, sky wave). 

![UI1](https://github.com/radiolab81/IONOS_SIM/blob/main/www/mainui.jpg "main UI")

Various ITU test profiles are taken into account, as well as ground conductivity (ITU-R P.527), radiation angle, and transmitter power.

```python
ITU-R F.1487 profile lib 
ITU_PROFILES = [
    # --- MID LATITUDES ---
    {"name": "Mid Lat Quiet",      "delays": [0.0, 0.5, 1.0], "spread": 0.1},
    {"name": "Mid Lat Moderate",   "delays": [0.0, 1.0, 2.0], "spread": 0.5},
    {"name": "Mid Lat Disturbed",  "delays": [0.0, 2.0, 4.0], "spread": 1.0},

    # --- LOW LATITUDES ---
    {"name": "Low Lat Quiet",      "delays": [0.0, 0.5, 1.2], "spread": 0.5},
    {"name": "Low Lat Moderate",   "delays": [0.0, 2.0, 4.5], "spread": 1.5},
    {"name": "Low Lat Disturbed",  "delays": [0.0, 6.0, 9.0], "spread": 10.0},

    # --- HIGH LATITUDES ---
    {"name": "High Lat Quiet",     "delays": [0.0, 1.0, 2.5], "spread": 0.5},
    {"name": "High Lat Moderate",  "delays": [0.0, 3.0, 5.5], "spread": 10.0},
    {"name": "High Lat Disturbed", "delays": [0.0, 7.0, 10.5], "spread": 30.0},

    # --- (NVIS paths) ---
    {"name": "NVIS Quiet",         "delays": [0.0, 0.5, 0.8], "spread": 0.1},
    {"name": "NVIS Disturbed",     "delays": [0.0, 1.0, 1.5], "spread": 1.0},
    {"name": "Equatorial Flutter", "delays": [0.0, 0.8, 1.6], "spread": 20.0}
]

# Ground Conductivity (sigma) in S/m according to ITU-R P.527
SIGMA_TYPES = [
    ("Sea Water", 5.0),      # High Conductivity (Best for Groundwave)
    ("Wet Ground", 1e-2),    # Good Propagation
    ("Dry/Rocky", 1e-3),     # High Attenuation
    ("Urban/City", 1e-4)     # Maximum Ground Loss
]
```

There is a selection of different predefined transmitter locations relative to the receiver location.

```python
RECV_LOC = {"name": "Frankfurt/Main", "lat": "50.1109", "lon": "8.6821"}
SENDER_PRESETS = [
    # --- NORTH PATH ---
    {"name": "Bieblach (N-Nah)",    "lat": 50.91, "lon": 12.09, "sig_pref": 1, "desc": "Hessisch/Thüringisches Bergland (Feucht)"},
    {"name": "Kopenhagen (N-Mid)",  "lat": 55.67, "lon": 12.56, "sig_pref": 1, "desc": "Norddeutsche Tiefebene (Feucht)"},
    {"name": "Stockholm (N-Far)",   "lat": 59.32, "lon": 18.06, "sig_pref": 2, "desc": "Skandinavischer Schild (Trocken/Fels)"},

    # --- SOUTH PATH ---
    {"name": "Mühlacker (S-Nah)",   "lat": 48.94, "lon": 8.85,  "sig_pref": 1, "desc": "Südwestdeutsches Schichtstufenland (Feucht)"},
    {"name": "Mailand (S-Mid)",     "lat": 45.46, "lon": 9.18,  "sig_pref": 2, "desc": "Alpen-Massiv (Trocken/Fels)"},
    {"name": "Neapel (S-Far)",      "lat": 40.85, "lon": 14.26, "sig_pref": 1, "desc": "Apennin/Küstenebene (Feucht)"},

    # --- WEST/EAST-PATH ---
    {"name": "Luxemburg (W-Nah)",   "lat": 49.61, "lon": 6.13,  "sig_pref": 3, "desc": "Urbanes Gebiet / Minette (Stadt)"},
    {"name": "Prag (O-Mid)",        "lat": 50.07, "lon": 14.43, "sig_pref": 2, "desc": "Böhmische Masse (Trocken/Fels)"},
    {"name": "Bordeaux (W-Far)",    "lat": 44.83, "lon": -0.57, "sig_pref": 1, "desc": "Französisches Sedimentbecken (Feucht)"}
]
```

In addition to the inputs of the sound card installed in the system, WAV files or internet radio stations (stations.db, for example from the AMWaveSynth project https://github.com/radiolab81/AMWaveSynth) can also be used as source signals.


![UI2](https://github.com/radiolab81/IONOS_SIM/blob/main/www/mainui_sc_in.jpg "input soundcard")


![UI2](https://github.com/radiolab81/IONOS_SIM/blob/main/www/mainui_iradio.jpg "input internetradio")

The audio signal, modified by the ground and sky wave paths, can be output in various ways: soundout, WAV file

![UI3](https://github.com/radiolab81/IONOS_SIM/blob/main/www/mainui_sink.jpg "sink")

Simple AM ​​modulators for old historical radios, such as GFGF Konzertsender (https://www.radiomuseum.org/r/gfgf_konzertsender.html) or Le ModulAM (https://modulam.retrotechnique.org/); DDS-Heimsenderlein (https://www.radiomuseum.org/forum/gemeinschaftsprojekt_dds_heimsenderlein.html) and many others,
enable an even more realistic simulation purely at the audio level.

### Install

Installation is as easy as 1-2-3 on Debian 12/13-Linux systems. Simply use the Python package manager uv or the command sequence from install_ionos_env.sh to create a virtual Python environment.
From this environment, simply start "IONOS_SIM" with:

`uv run ionos_sim.py`
