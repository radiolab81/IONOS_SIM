import ephem, time, math, curses, os, random, subprocess, sys
import numpy as np
from noise import pnoise1
import os
import sounddevice as sd
import atexit

# --- CONFIGURATION ---
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

# Ground Conductivity (sigma) in S/m according to ITU-R P.527
SIGMA_TYPES = [
    ("Sea Water", 5.0),      # High Conductivity (Best for Groundwave)
    ("Wet Ground", 1e-2),    # Good Propagation
    ("Dry/Rocky", 1e-3),     # High Attenuation
    ("Urban/City", 1e-4)     # Maximum Ground Loss
]

FREQS = [153, 549, 1000, 1422, 1602]
POWERS = [1, 10, 50, 100, 500]

FS_IN, FS_OUT, CHUNK = 25000, 25000, 1024 

# ITU-R F.1487 profile lib 
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


# ITU-R P.372 - impulsive noise / sferics
SFERICS_CFG = [
     # --- (Pulse Frequency, Pulse Amplitude) ---
     (0, 0),  
     (0.000002, 1.5),    # 1: ITU-R P.372 LOW
     (0.00008,  2.8),    # 2: ETSI DRM TYPICAL
     (0.001,    5.5)     # 3: MIL-STD-188
]

class RadioEngine:
    def __init__(self):
        self.proc_in = None
        self.proc_out = None
        self.current_source = "Keine Quelle"

        #self.proc_in = subprocess.Popen(['ffmpeg', '-re', '-i', "https://47fm.ice.infomaniak.ch/47fm-80.aac", 
        #                                 '-af', 'lowpass=f=4500',
        #                                 '-f', 'f32le', '-ar', str(FS_IN), '-ac', '1', '-'], 
        #                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        #self.proc_out = subprocess.Popen(['ffmpeg', '-f', 's16le', '-ar', str(FS_OUT), '-ac', '1', '-i', '-', 
        #                                  '-f', 'alsa', 'default'], 
        #                                  stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

        self.set_output("DEFAULT", "default")

        self.t_total = 0.0
        self.iono_seed = random.random() * 10000
        self.agc_gain = 1.0
        self.noise_state = 0.0 + 0j
        self.lp_state = 1.0 
        self.iq_history = np.zeros(CHUNK * 2, dtype=complex)
        
        # allpass-filter coef for hilbert (phase-shifting)
        # replaces scipy.signal.hilbert by real time version
        self.z_real = np.zeros(4)
        self.z_imag = np.zeros(4)

        self.storm_mode = 0      
        self.sferic_timer = 0    
        self.sferic_amp = 0.0

    def cleanup(self):
        for p in [self.proc_in, self.proc_out]:
            if p:
                try:
                    # close pipes
                    if p.stdin: p.stdin.close()
                    if p.stdout: p.stdout.close()
                    p.terminate()  # friendly (SIGTERM)
                except:
                    pass
        
        # wait, check if still alife
        for p in [self.proc_in, self.proc_out]:
            if p and p.poll() is None:
                try:
                    p.wait(timeout=0.2)
                except:
                    try: p.kill() # the hard way (SIGKILL)
                    except: pass


    def set_source(self, source_type, path):
        # 1. terminate old input source
        if self.proc_in:
            try:
                self.proc_in.terminate()
                self.proc_in.wait(timeout=0.5)
            except:
                self.proc_in.kill()

        # 2. FFmpeg input-args 
        if source_type == "URL":
            inp = ['-re', '-i', path]
        elif source_type == "CARD":
            # for Debian/ALSA: 'default' or devicename
            inp = ['-f', 'alsa', '-i', path]
        elif source_type == "FILE":
            #inp = ['-re', '-i', path, '-stream_loop', '-1']
            inp = ['-stream_loop', '-1', '-re', '-i', path]
        else:
            return

        # 3. start new input stream (raw float output for physics)
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error'] + inp + [
            '-af', 'lowpass=f=4500',
            '-f', 'f32le', '-ar', str(FS_IN), '-ac', '1', '-'
        ]

        self.proc_in = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.current_source = path

        # 4. start output-process (ALSA) once, if not running
        # if not self.proc_out:
        #    self.proc_out = subprocess.Popen([
        #        'ffmpeg', '-hide_banner', '-loglevel', 'error',
        #        '-f', 'f32le', '-ar', str(FS_OUT), '-ac', '1', '-i', '-', 
        #        '-f', 'alsa', 'default'
        #    ], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def set_output(self, out_type="DEFAULT", target="default"):
        """ write data to sink """
        if self.proc_out:
            try:
                if self.proc_out.stdin:
                    self.proc_out.stdin.close()
                self.proc_out.terminate()
                self.proc_out.wait(timeout=0.2)
            except:
                self.proc_out.kill()

        # basic cmd: reading 25kHz mono from python pipe
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error',
               '-f', 's16le', '-ar', str(FS_OUT), '-ac', '1', '-i', '-']

        if out_type == "FILE":
            # FILE-MODE: 
            # stay for 25kHz mono, no add. filter needed
            cmd += ['-acodec', 'pcm_s16le', '-y', target]
        else:
            # SOUNDCARD-MODE:
            # pan filter for stereo output
            f_str = 'pan=stereo|c0=c0|c1=c0'
            device = target if target == "default" else f"plug:{target}"
            cmd += ['-af', f_str, '-f', 'alsa', device]

        self.proc_out = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)


    def continuous_hilbert(self, data):
        """create IQ-baseband without disturb."""
        # simple 90 deg. phase shifter (Analytic Signal)
        # real is delayed original signal, imag is hilbert answer
        # NumPy-vectorisation for phase shifting
        sig_iq = np.zeros(len(data), dtype=complex)
        # m-AM signal: carrier + audio
        am_real = 1.0 + 0.8 * data
        
        # baseband AM Signal simply S(t) = (1+m*a(t)).
        # IQ-equivalent in complex baseband is (1+m*a(t)) + 0j.
        # iono phase-rotation do the job
        sig_iq.real = am_real
        sig_iq.imag = 0.0 # baseband AM-TX doesnt need imag signal part 
        return sig_iq

    def process_hf_physics(self, v_f, t_speed, sun_elev, freq_khz, dist_km, profile):
        raw = self.proc_in.stdout.read(CHUNK * 4)
        if not raw: return
        audio = np.frombuffer(raw, dtype=np.float32)
        
        # 1. continuous IQ-generation (baseband AM)
        sig_iq = self.continuous_hilbert(audio)
        
        # Update delay-history
        self.iq_history = np.concatenate((self.iq_history[CHUNK:], sig_iq))
        self.t_total += CHUNK / FS_IN
        

        # --- scaling for physics ---
        total_v = sum(v_f) + 1e-9
        sc = 0.7 / total_v if total_v > 0.7 else 1.0


        # --- NOISE (atmospheric) ---
        white = (np.random.normal(0, 0.012, CHUNK) + 1j * np.random.normal(0, 0.012, CHUNK))
        pink = np.zeros(CHUNK, dtype=complex)
        
        if self.storm_mode == 0:
           # ORIGINAL-CODE (sferics off)
           for i in range(CHUNK):
            self.noise_state = 0.99 * self.noise_state + 0.01 * white[i]
            pink[i] = self.noise_state

        else: # --- sferics on ---
            p_strike, max_amp = SFERICS_CFG[self.storm_mode]
            
            is_lw = freq_khz < 300
            roll_off = 0.998 if is_lw else 0.993
            f_scale = 3.5 if is_lw else 1.0
            
            # sun elevation < 0, boost up sferics 
            night_boost = 1.8 if sun_elev < 0 else 1.0
   
            for i in range(CHUNK):
                self.noise_state = 0.99 * self.noise_state + 0.01 * white[i]
                pink[i] = self.noise_state
        
                w = pink[i] * sc

                if self.sferic_timer <= 0:
                    if random.random() < p_strike:
                        t_cfg = [0, (60, 200), (300, 900), (1000, 4500)]
                        t_min, t_max = t_cfg[self.storm_mode]
                        self.sferic_timer = random.randint(t_min, t_max)
                        # use sc, to stay ALWAYS on top of signal
                        self.sferic_amp = random.uniform(0.8, max_amp) * f_scale * sc * night_boost
                
                if self.sferic_timer > 0:
                    w += (random.gauss(0, self.sferic_amp) + 1j * random.gauss(0, self.sferic_amp))
                    self.sferic_timer -= 1
                
                self.noise_state = roll_off * self.noise_state + (1.0 - roll_off) * w
                pink[i] = self.noise_state



        # 2. MULTI-PATH (phase-continuous by history-buffer) according ITU profiles
        sig_total_iq = (v_f[0] * sc) * sig_iq
        slow_t = self.t_total * profile['spread'] * t_speed * 0.05
        fast_t = slow_t * 8.0

        for i in range(3):
            d_samples = int((profile['delays'][i] / 1000.0) * FS_IN)
            start_idx = CHUNK - d_samples
            sig_delayed = self.iq_history[start_idx : start_idx + CHUNK]
            
            n_main = pnoise1(slow_t + (i * 100.0) + self.iono_seed)
            n_turb = pnoise1(fast_t + (i * 50.0) + self.iono_seed) * 0.12
            total_n = n_main + n_turb

            # phase-rotation simulates interference 
            phase_rot = np.exp(1j * (4.5 * total_n))
            fading_amp = (1.0 + 0.4 * total_n)
            sig_total_iq += (v_f[i+1] * sc) * fading_amp * sig_delayed * phase_rot

        sig_total_iq += pink
        
        # --- DEMODULATION ---
        demod_raw = np.abs(sig_total_iq)
        
        # --- SAMPLE-BY-SAMPLE DC REMOVAL ---
        demod_filtered = np.zeros_like(demod_raw)
        for i in range(CHUNK):
            self.lp_state = 0.9995 * self.lp_state + 0.0005 * demod_raw[i]
            demod_filtered[i] = demod_raw[i] - self.lp_state

        # --- AGC ---
        current_peak = np.percentile(np.abs(demod_filtered), 97) + 1e-12
        target_gain = 0.55 / current_peak
        self.agc_gain += (min(150.0, target_gain) - self.agc_gain) * 0.02
        
        audio_out = demod_filtered * self.agc_gain
        
        # --- OUTPUT ---
        out_s16 = (np.clip(audio_out * 32767, -32767, 32767)).astype(np.int16)
        #self.proc_out.stdin.write(out_s16.tobytes())
        #self.proc_out.stdin.flush()
        if self.proc_out and self.proc_out.stdin:
            try:
                self.proc_out.stdin.write(out_s16.tobytes())
                self.proc_out.stdin.flush()
            except (BrokenPipeError, OSError):
                # when FFmpeg dies, python stays alive
                self.proc_out = None


# --- (physic-engine) ---
def get_itu_physics(dist_km, p_kw, freq_khz, sigma_val):
    f_mhz, e0 = freq_khz / 1000.0, 300000.0 * math.sqrt(p_kw)
    x = 18000.0 * sigma_val / f_mhz
    p_num = (math.pi * dist_km / (80.0 * f_mhz**2)) * (1.0 / x)
    a_g = (2.0 + 0.3 * p_num) / (2.0 + p_num + 0.6 * p_num**2)
    h_loss = math.exp(-(dist_km - 120) / (40.0 / f_mhz)) if dist_km > 120 else 1.0
    e_g = (e0 / dist_km) * a_g * h_loss
    h_e = 110.0
    alpha = math.degrees(math.atan(h_e / (dist_km / 2.0)))
    ant_gain = math.pow(math.cos(math.radians(alpha)), 2.8) if alpha < 75 else 0.0
    s_p = 2 * math.sqrt((dist_km/2)**2 + h_e**2)
    e_s = (e0 / s_p) * 0.45 * ant_gain * math.pow(10, -(0.0016 * s_p) / 20.0)
    return e_g, e_s, alpha

def calculate_distance(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2, dl = math.radians(float(lat1)), math.radians(float(lat2)), math.radians(float(lon2)-float(lon1))
    return 2 * r * math.asin(math.sqrt(math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2))

# Terminal user interface
def tui_menu(stdscr, items, title):
    h, w = stdscr.getmaxyx()
    win_h, win_w = min(len(items) + 4, h - 6), 70
    win = curses.newwin(win_h, win_w, (h - win_h) // 2, (w - win_w) // 2)
    win.keypad(1)
    win.box()
    win.timeout(-1) # UI blocks simulation for short period
    win.addstr(0, 2, f" {title} ", curses.A_BOLD)
    
    idx, offset = 0, 0
    while True:
        visible_rows = win_h - 4
        for i in range(visible_rows):
            curr = i + offset
            if curr < len(items):
                style = curses.A_REVERSE if curr == idx else curses.A_NORMAL
                # prepare UI-String (name or if dict Key 'name')
                label = items[curr]['name'] if isinstance(items[curr], dict) else str(items[curr])
                win.addstr(i + 2, 2, f" {label[:win_w-6]:<{win_w-6}} ", style)
        win.refresh()
        k = win.getch()
        if k == curses.KEY_UP and idx > 0:
            idx -= 1
            if idx < offset: offset -= 1
        elif k == curses.KEY_DOWN and idx < len(items) - 1:
            idx += 1
            if idx >= offset + visible_rows: offset += 1
        elif k in [10, 13, curses.KEY_ENTER]: return items[idx]
        elif k == 27: return None # ESC

def load_stations(filename="stations.db"):
    """ load channel list for source: internetradio from stations.db (Name,URL) """
    stations = []
    if not os.path.exists(filename):
        # Fallback, if no stations.db is available
        return [{"name": "47FM-80s (Fallback)", "url": "https://47fm.ice.infomaniak.ch/47fm-80.aac"}]
    
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "," in line:
                    name, url = line.split(",", 1)
                    stations.append({"name": name.strip(), "url": url.strip()})
    except Exception:
        return [{"name": "error reading station database", "url": ""}]
    
    return stations if stations else [{"name": "list empty", "url": ""}]


def draw_rect(stdscr, x, y, w, h, title=""):
    """ drawing a frame, check if terminal is to small """
    max_y, max_x = stdscr.getmaxyx()
    
    if y + h > max_y or x + w > max_x or h < 2 or w < 2:
        return # no frame possible

    try:
        stdscr.attron(curses.A_BOLD)
        # draw lines
        stdscr.vline(y + 1, x, curses.ACS_VLINE, h - 2)           # left
        stdscr.vline(y + 1, x + w - 1, curses.ACS_VLINE, h - 2)   # right
        stdscr.hline(y, x + 1, curses.ACS_HLINE, w - 2)           # top
        stdscr.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2)   # buttom
        
        # draw corners
        stdscr.addch(y, x, curses.ACS_ULCORNER)
        stdscr.addch(y, x + w - 1, curses.ACS_URCORNER)
        stdscr.addch(y + h - 1, x, curses.ACS_LLCORNER)
        stdscr.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        
        if title:
            # short frame title if to long
            clean_title = f" {title[:w-4]} "
            stdscr.addstr(y, x + 2, clean_title)
        stdscr.attroff(curses.A_BOLD)
    except curses.error:
        pass

def draw_ui(stdscr):
    engine = RadioEngine()
    atexit.register(engine.cleanup)
    engine.set_source("URL", "https://47fm.ice.infomaniak.ch/47fm-80.aac") 
    p_idx, s_idx, sig_idx, f_idx, t_speed, iono_curr = 4, 1, 1, 2, 1.0, 0.0001
    curses.curs_set(0); stdscr.nodelay(1); stdscr.timeout(5); last_t = time.time()

    sim_time_base = ephem.now() 
    t_off_seconds = 0.0

    itu_idx = 1 # start with ITU Moderate profile 1
    
    while True:
        # get actual ITU profile
        prof = ITU_PROFILES[itu_idx]

        dt = time.time() - last_t; last_t = time.time()
        sender, sigma_tuple = SENDER_PRESETS[s_idx], SIGMA_TYPES[sig_idx]
        sigma_name, sigma_val = sigma_tuple
        dist = calculate_distance(RECV_LOC["lat"], RECV_LOC["lon"], sender["lat"], sender["lon"])

        t_off_seconds += dt * t_speed
        obs = ephem.Observer(); obs.lat, obs.lon = RECV_LOC["lat"], RECV_LOC["lon"]
        obs.date = sim_time_base + (t_off_seconds / 86400.0)
        sun = ephem.Sun(); sun.compute(obs); elev = math.degrees(sun.alt)
        
        eg_uv, es_uv, alpha = get_itu_physics(dist, POWERS[p_idx], FREQS[f_idx], sigma_val)
        
        f_factor = (1000.0 / FREQS[f_idx])**2
        d_loss_db = max(0, elev + 5) * 4.2 * f_factor if elev > -10 else 0
        d_vis = math.pow(10, -d_loss_db/20.0)
        iono_target = 1.0 / (1.0 + math.exp((elev + 5.0) / 2.5))
        iono_curr += (iono_target - iono_curr) * 0.02

        v_f = [eg_uv/12000.0, 
               (es_uv*d_vis*iono_curr/12000.0)*0.8, 
               (es_uv*d_vis*iono_curr/12000.0)*0.5, 
               (es_uv*d_vis*iono_curr/12000.0)*0.2]
        
        engine.process_hf_physics(v_f, t_speed, elev, FREQS[f_idx], dist, prof)

        stdscr.erase()
        stdscr.addstr(1, 1, f"AM-IONOSPHERIC-CHANNEL-SIMULATOR                                                                   ", curses.A_REVERSE)
        draw_rect(stdscr,0,3,100,6,'Simulator settings');
        stdscr.addstr(4, 2, f"TX loc: {s_idx+1}. {sender['name']} ({dist:.1f} km to RX loc.)")
        stdscr.addstr(5, 2, f"PARAM:  {POWERS[p_idx]} kW | {FREQS[f_idx]} kHz | ground conductivity: {sigma_name}", curses.A_BOLD)
        stdscr.addstr(7, 2, f"TIME:   {ephem.localtime(obs.date).strftime('%H:%M:%S')} | SUN: {elev:6.2f}° | ANG: {alpha:4.1f}°")

        # --- table header ---
        stdscr.addstr(10, 2, f"{'Path':<12} | {'uV/m':>8} | {'%':>7} | {'Delay':>7} | {'P-Offset':>6} | {'Doppler':>8} | {'Signal':<22}", curses.A_BOLD |  curses.A_UNDERLINE)
        stdscr.addstr(11, 2, "-" * 90)      

        tw = sum(v_f) + 1e-9
        labels = ["Groundwave", "E-Layer Sky", "F-Layer Sky", "Ionoscatter"]
        d_vals = [eg_uv, es_uv*d_vis*iono_curr*0.8, es_uv*d_vis*iono_curr*0.5, es_uv*d_vis*iono_curr*0.2]
        
        # --- UI-calculations: Delay, Phase, Doppler (without physic-engine) ---
        delays = [0.0]
        phases = [0.0]
        dopplers = [0.0]
        
        # sync simulation time to engine
        slow_t = engine.t_total * prof['spread'] * t_speed * 0.05
        fast_t = slow_t * 8.0
        
        for i in range(3):
            delays.append(prof['delays'][i])
            
            # 1. actual phase shift
            n_main = pnoise1(slow_t + (i * 100.0) + engine.iono_seed)
            n_turb = pnoise1(fast_t + (i * 50.0) + engine.iono_seed) * 0.12
            total_n = n_main + n_turb

            phase_rad = 4.5 * total_n
            phase_deg = math.degrees(phase_rad) % 360.0
            
            if phase_deg > 180.0: 
                phase_deg -= 360.0

            phases.append(phase_deg)
            
            # 2. actual dopplerfreq (df = d_phi / dt)
            dt_sim = 0.01 # look 10ms ahead
            slow_t_next = (engine.t_total + dt_sim) * prof['spread'] * t_speed * 0.05
            fast_t_next = slow_t_next * 8.0
            
            n_main_next = pnoise1(slow_t_next + (i * 100.0) + engine.iono_seed)
            n_turb_next = pnoise1(fast_t_next + (i * 50.0) + engine.iono_seed) * 0.12
            phase_rad_next = 4.5 * (n_main_next + n_turb_next)
            
            doppler_hz = ((phase_rad_next - phase_rad) / dt_sim) / (2 * math.pi)
            dopplers.append(doppler_hz)

        draw_rect(stdscr,0,9,100,10,'Results');
        # --- print result rows ---
        for i, val in enumerate(d_vals):
            perc = (v_f[i] / tw) * 100
            bar = "█" * int(min(20, (v_f[i] * 20 * 2)))
            
            row = f"{labels[i]:<12} | {val:>8.2f} | {perc:>6.1f}% | {delays[i]:>4.1f} ms | {phases[i]:>+7.0f}° | {dopplers[i]:>5.2f} Hz | [{bar:<20}]"
            stdscr.addstr(11+i, 2, row)
            #stdscr.clrtoeol()

        stdscr.addstr(16, 2, f"AGC: {engine.agc_gain:.1f}x | IONO: {iono_curr*100:4.1f}% | D-LAYER: {d_loss_db:>4.1f} dB | SPEED: {t_speed}x")
        stdscr.addstr(17, 2, f" ITU PROFILE: {prof['name']:<18} | DO-SPREAD: {prof['spread']:>4.1f} Hz ", curses.A_REVERSE)
        
        # controls
        draw_rect(stdscr,0,19,100,6,'Controls');
        sferic_labels = [
            "OFF",                              # 0
            "ITU-R P.372 (Quiet/Rural)",        # 1 (0.000002 / 1.5)
            "ETSI DRM (Typical Case)",          # 2 (0.00008  / 2.8)
            "MIL-STD-188 (Worst Case)"          # 3 (0.001    / 5.5)
        ]
        sferic_text = sferic_labels[engine.storm_mode]
        stdscr.addstr(20, 2, "[1-9] TX presets        [G] ground conductivity  [W] TX Frequency  [L] TX Power  [P] Profile")
        stdscr.addstr(21, 2, "[I] src: Internetradio  [C] src: Soundcard       [O] src: File     [B/T] Time    [F/S] Speed")
        stdscr.addstr(22, 2, f"[U] Select sink         [M] SFERICS: {sferic_text:<10}                         ")
        stdscr.addstr(23, 2, "[R] Reset               [Q] Quit")
  

        key = stdscr.getch()
        if key == ord('q'): break
        elif ord('1') <= key <= ord('9'):
            s_idx = key - ord('1')
            sender = SENDER_PRESETS[s_idx]
            # sync groud conductivity to tx/rx path, see SENDER_PRESETS in CONFIG
            sig_idx = sender.get("sig_pref", sig_idx) 
            dist = calculate_distance(RECV_LOC["lat"], RECV_LOC["lon"], sender["lat"], sender["lon"])

        elif key == ord('i'):
            stations = load_stations() 
            choice = tui_menu(stdscr, stations, "STATION-LIST")
            if choice: engine.set_source("URL", choice['url'])
            
        elif key == ord('c'):
            devices = [{"name": d['name'], "id": i} for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]
            choice = tui_menu(stdscr, devices, "AUDIO-INPUT")
            if choice: engine.set_source("CARD", choice['name'])
            
        elif key == ord('o'):
            f_path = os.path.abspath(".")
            while True:
                raw_items = sorted(os.listdir(f_path))
                filtered_items = [
                    f for f in raw_items 
                    if os.path.isdir(os.path.join(f_path, f)) or f.lower().endswith(".wav")
                ]
                
                items = [{"name": ".. [BACK]"}] + [{"name": f} for f in filtered_items]
                choice = tui_menu(stdscr, items, f"WAV-BROWSER: {f_path}")
                
                if not choice: break
                
                full_p = os.path.normpath(os.path.join(f_path, choice['name']))
                if choice['name'] == ".. [BACK]":
                    new_path = os.path.dirname(f_path)
                    if new_path != f_path: f_path = new_path
                elif os.path.isdir(full_p):
                    f_path = full_p
                else:
                    engine.set_source("FILE", full_p)
                    break

        elif key in [ord('m'), ord('M')]: engine.storm_mode = (engine.storm_mode + 1) % 4
        elif key == ord('p'): itu_idx = (itu_idx + 1) % len(ITU_PROFILES)
        elif key == ord('g'): sig_idx = (sig_idx + 1) % len(SIGMA_TYPES)
        elif key == ord('w'): f_idx = (f_idx + 1) % len(FREQS)
        elif key == ord('l'): p_idx = (p_idx + 1) % len(POWERS)
        elif key in [ord('f'), ord('F')]: t_speed *= 2.0
        elif key in [ord('s'), ord('S')]: t_speed = max(0.125, t_speed / 2.0)
        elif key == ord('t'): t_off_seconds += 1800
        elif key == ord('b'): t_off_seconds -= 1800
        elif key == ord('r'): t_speed, t_off_seconds, sim_time_base = 1.0, 0.0, ephem.now()
        elif key in [ord('u'), ord('U')]:
            out_menu = [
                {"name": "1. Default-output (System Default)", "type": "DEFAULT", "target": "default"},
                {"name": "2. Select soundcard...", "type": "CARD_MENU"},
                {"name": "3. Write to wav file...", "type": "FILE_PROMPT"}
            ]
            choice = tui_menu(stdscr, out_menu, "AUDIO-OUTPUT")
            
            if choice:
                if choice["type"] == "CARD_MENU":
                    # find all outputs (for name target)
                    devices = sd.query_devices()
                    out_list = [{"name": f"{i}: {d['name']}", "target": d['name'], "type": "CARD"} 
                                for i, d in enumerate(devices) if d['max_output_channels'] > 0]
                    
                    dev_choice = tui_menu(stdscr, out_list, "SELECT DEVICE")
                    if dev_choice:
                        engine.set_output(out_type="CARD", target=dev_choice["target"])

                elif choice["type"] == "FILE_PROMPT":
                    # 1. non-blocking mode off to get user input
                    stdscr.nodelay(0) 
                    curses.curs_set(1) # Cursor on
                    curses.echo()      # Cursor visible
                    
                    # 2. input field for file name
                    stdscr.move(curses.LINES - 1, 0)
                    stdscr.clrtoeol()
                    stdscr.addstr(curses.LINES - 1, 2, "FILENAME: ", curses.A_BOLD | curses.A_REVERSE)
                    stdscr.refresh()

                    # 3. wait for filename 
                    try:
                        fname_bin = stdscr.getstr(curses.LINES - 1, 22)
                        fname = fname_bin.decode('utf-8').strip()
                    except:
                        fname = ""

                    # 4. back to simulation mode
                    curses.noecho()
                    curses.curs_set(0)
                    stdscr.nodelay(1) # Non-Blocking on for simulation mode
                    
                    # 5. no file, just use recording.wav ; no .wav ?
                    if not fname:
                        fname = "recording.wav"
                    if not fname.lower().endswith(".wav"):
                        fname += ".wav"
                        
                    engine.set_output(out_type="FILE", target=fname)
                    
                    # small feedback
                    stdscr.move(curses.LINES - 1, 0)
                    stdscr.clrtoeol()
                    stdscr.addstr(curses.LINES - 1, 2, f"-> recording started: {fname}", curses.A_BOLD)
                    stdscr.refresh()
                    time.sleep(1.2)

                elif choice["type"] == "DEFAULT":
                    engine.set_output(out_type="DEFAULT", target="default")

        stdscr.refresh()



if __name__ == "__main__":
    try:
        curses.wrapper(draw_ui)
    except KeyboardInterrupt:
        # nothing , wrapper cleanup 
        pass
