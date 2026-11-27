# ==============================================================================
# dataset_finale.py
# RoboCupJunior Rescue - Smiley Victims Dataset Collector (OpenMV AE3 -> PC)
# ==============================================================================
# Script completo per acquisire il dataset delle Smiley Victims dalla scheda
# OpenMV AE3 e salvare le immagini PNG direttamente sul PC nella cartella:
#   C:\Users\crist\Documents\RoboCup_Maze_2027_MastriCostruttori\RoboCup_Maze_2027_MastriCostruttori\visione_openmv\Dataset png\
#
# COME AVVIARLO:
#   1. Disconnetti la OpenMV AE3 dall'estensione OpenMV di VS Code / OpenMV IDE
#      (la porta COM deve essere libera).
#   2. Installa le dipendenze sul PC (una sola volta):
#        pip install openmv pillow pyserial
#   3. Esegui questo file con Python sul PC:
#        python dataset_finale.py
#
# STRUTTURA CARTELLE (Windows non consente ':' e '|' nei nomi di cartelle):
#   Dataset png\happy\    <- ":)"  (happy face   / unharmed state)
#   Dataset png\neutral\  <- ":|"  (neutral face / stable state)
#   Dataset png\sad\      <- ":("  (sad face     / harmed state)
#   Dentro ciascuna cartella i file sono salvati come: 1.png, 2.png, 3.png, ...
#   riprendendo sempre dal numero successivo senza sovrascrivere nulla.
#
# COMANDI NELLA FINESTRA ANTEPRIMA:
#   - Tasti 1 / 2 / 3 : seleziona la classe attiva -> :) / :| / :(
#   - SPAZIO          : scatta subito una foto manuale
#   - P               : pausa / riprendi il timer automatico da 5 secondi
#   - Q o ESC         : chiudi il programma in sicurezza
#
# PROMEMORIA REGOLAMENTO ROBOCUPJUNIOR RESCUE (Sez. 4.4.6 - Victims):
#   - Posizionare le faccine su un muro (NON su ostacoli, rampe, gradini,
#     dossi o piastrelle colorate vietate).
#   - Altezza minima: 7 cm da terra.
#   - Diametro: 4 cm, colore a contrasto con il muro, sporgenza massima: 3 mm.
#   - Le faccine possono essere ruotate: varia rotazione, distanza, angolazione
#     e illuminazione tra uno scatto e l'altro.
# ==============================================================================

import os
import sys
import time
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

try:
    from openmv.camera import Camera
except ImportError:
    try:
        from openmv import Camera
    except ImportError:
        print("[ERRORE] Pacchetto 'openmv' non trovato nel Python del PC.")
        print("Esegui prima:  pip install openmv pillow pyserial")
        sys.exit(1)

try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None

# ==============================================================================
# CONFIGURAZIONE
# ==============================================================================

# Cartella di destinazione esatta sul PC
OUTPUT_DIR = (
    r"C:\Users\crist\Documents\RoboCup_Maze_2027_MastriCostruttori"
    r"\RoboCup_Maze_2027_MastriCostruttori\visione_openmv\Dataset png"
)

# Classe iniziale attiva: scegli tra ":)", ":|", ":("
ACTIVE_FOLDER = ":)"

# Porta seriale della OpenMV AE3:
# None = rilevamento automatico, oppure specifica es. "COM3"
SERIAL_PORT = None

# Intervallo di scatto automatico (secondi)
CAPTURE_INTERVAL_SEC = 5.0

# Se False (CONSIGLIATO), l'overlay/timer appare SOLO nell'anteprima live
# e le immagini PNG salvate restano pulite.
DRAW_HUD_ON_SAVED_IMAGE = False

# Risoluzione del sensore OpenMV AE3 ("QVGA" = 320x240, "VGA" = 640x480)
CAMERA_FRAMESIZE = "QVGA"

# Ingrandimento finestra anteprima live sul PC (es. 2 -> 640x480 per QVGA)
PREVIEW_SCALE = 2

# Durata indicatore visivo verde di conferma scatto (secondi)
CAPTURE_FLASH_SEC = 0.7

# ==============================================================================
# MAPPATURA CLASSI E SCRIPT EMBEDDED PER OPENMV AE3
# ==============================================================================

CLASS_TO_FOLDER = {
    ":)": "happy",
    ":|": "neutral",
    ":(": "sad",
}

CLASS_DESCRIPTIONS = {
    ":)": "happy face (unharmed)",
    ":|": "neutral face (stable)",
    ":(": "sad face (harmed)",
}

# Codice MicroPython inviato ed eseguito sulla OpenMV AE3
DEVICE_SCRIPT = f"""
try:
    import csi
    cam = csi.CSI()
    cam.reset()
    cam.pixformat(csi.RGB565)
    cam.framesize(getattr(csi, "{CAMERA_FRAMESIZE}"))
    def snap():
        return cam.snapshot()
except Exception:
    import sensor
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(getattr(sensor, "{CAMERA_FRAMESIZE}"))
    sensor.skip_frames(time=1000)
    def snap():
        return sensor.snapshot()

while True:
    snap()
"""

# ==============================================================================
# UTILITY FILESYSTEM E PORTA SERIALE
# ==============================================================================


def find_openmv_port():
    """Individua automaticamente la porta COM della OpenMV AE3 su Windows."""
    if SERIAL_PORT:
        return SERIAL_PORT

    if list_ports is None:
        raise RuntimeError(
            "Impossibile cercare le porte COM (manca pyserial). "
            "Imposta SERIAL_PORT = 'COMx' in cima allo script."
        )

    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError(
            "Nessuna porta COM trovata. Collega la OpenMV AE3 via USB "
            "e disconnettila da VS Code OpenMV / OpenMV IDE."
        )

    # VID noti per OpenMV / ST / Alif
    known_vids = {0x1209, 0x0483, 0x37C5}
    for p in ports:
        desc = (p.description or "").lower()
        manu = (p.manufacturer or "").lower()
        if "openmv" in desc or "openmv" in manu or (p.vid in known_vids):
            print(f"[USB] OpenMV rilevata su {p.device} ({p.description})")
            return p.device

    if len(ports) == 1:
        p = ports[0]
        print(f"[USB] Uso unica porta disponibile: {p.device} ({p.description})")
        return p.device

    print("[USB] Porte COM rilevate:")
    for idx, p in enumerate(ports, start=1):
        print(f"  {idx}. {p.device} - {p.description}")
    raise RuntimeError(
        "Piu' porte COM presenti: imposta SERIAL_PORT = 'COMx' in cima al file."
    )


def ensure_dataset_dirs():
    """Crea la cartella principale `Dataset png` e le 3 sottocartelle."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for folder_name in CLASS_TO_FOLDER.values():
        os.makedirs(os.path.join(OUTPUT_DIR, folder_name), exist_ok=True)
    return OUTPUT_DIR


def scan_existing_pngs(folder_path):
    """Restituisce (conteggio_png, prossimo_indice) senza sovrascrivere file."""
    max_idx = 0
    count = 0
    for name in os.listdir(folder_path):
        if name.lower().endswith(".png"):
            count += 1
            stem = name[:-4]
            if stem.isdigit():
                idx = int(stem)
                if idx > max_idx:
                    max_idx = idx
    return count, max_idx + 1


def count_all_classes():
    """Restituisce il conteggio PNG di ciascuna delle 3 cartelle."""
    totals = {}
    for smiley, folder_name in CLASS_TO_FOLDER.items():
        path = os.path.join(OUTPUT_DIR, folder_name)
        cnt, _ = scan_existing_pngs(path)
        totals[smiley] = cnt
    return totals


def draw_hud(
    pil_img,
    active_smiley,
    folder_name,
    counts_by_class,
    remaining_sec,
    interval_sec,
    paused,
    flash_active,
    last_saved_name,
):
    """Disegna HUD leggibile sull'anteprima live (senza modificare pil_img)."""
    hud = pil_img.copy()
    draw = ImageDraw.Draw(hud)
    w, h = hud.size

    # Barra superiore: classe attiva + contatori delle 3 cartelle
    draw.rectangle([0, 0, w, 28], fill=(0, 0, 0))
    header = (
        f"ATTIVA: {active_smiley} ({folder_name})   |   "
        f":) {counts_by_class[':)']}   :| {counts_by_class[':|']}   :( {counts_by_class[':(']}"
    )
    draw.text((8, 8), header, fill=(255, 255, 255))

    # Barra inferiore: progress bar + countdown / stato
    bot_h = 46
    bot_y = h - bot_h
    draw.rectangle([0, bot_y, w, h], fill=(0, 0, 0))

    bar_x, bar_y, bar_w, bar_h = 8, bot_y + 6, w - 16, 10
    ratio = max(0.0, min(1.0, (interval_sec - remaining_sec) / interval_sec))
    fill_w = int(bar_w * ratio)

    if paused:
        color = (180, 180, 180)
    elif flash_active:
        color = (0, 230, 80)
    elif remaining_sec <= 1.0:
        color = (255, 60, 60)
    elif remaining_sec <= 2.0:
        color = (255, 210, 0)
    else:
        color = (0, 200, 255)

    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=(110, 110, 110))
    if fill_w > 0:
        draw.rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], fill=color)

    if paused:
        status_txt = "IN PAUSA  [P=riprendi | SPAZIO=scatta | 1:) 2:| 3:( | Q=esci]"
    elif flash_active:
        status_txt = f"SCATTO SALVATO: {folder_name}\\{last_saved_name}"
        draw.rectangle([0, 0, w - 1, h - 1], outline=(0, 230, 80), width=4)
    else:
        status_txt = (
            f"PROSSIMO SCATTO: {remaining_sec:.1f}s   "
            f"[1:) 2:| 3:( | SPAZIO=scatta | P=pausa]"
        )

    draw.text((8, bot_y + 23), status_txt, fill=color)
    return hud


# ==============================================================================
# APPLICAZIONE PRINCIPALE
# ==============================================================================


class SmileyDatasetApp:
    def __init__(self, port):
        if ACTIVE_FOLDER not in CLASS_TO_FOLDER:
            raise ValueError(f"ACTIVE_FOLDER non valido: '{ACTIVE_FOLDER}'. Usa ':)', ':|' o ':('.")

        self.port = port
        self.active_smiley = ACTIVE_FOLDER
        self.paused = False
        self.manual_trigger = False
        self.last_capture_t = time.monotonic()
        self.flash_until_t = 0.0
        self.last_saved_name = ""
        self.last_printed_sec = -1
        self.tk_img = None
        self.running = True

        self.counts_by_class = count_all_classes()
        self.refresh_active_folder()

        # Avvio connessione e streaming OpenMV AE3
        self.cam = Camera(self.port)
        self.cam.__enter__()
        self.cam.stop()
        self.cam.exec(DEVICE_SCRIPT)
        self.cam.streaming(True)

        # Finestra anteprima live
        self.root = tk.Tk()
        self.root.title("Dataset Finale - Smiley Victims (OpenMV AE3)")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.label = tk.Label(self.root, bg="black")
        self.label.pack()

        # Barra pulsanti rapida sotto il video
        btn_frame = tk.Frame(self.root, bg="#1e1e1e", pady=6)
        btn_frame.pack(fill=tk.X)

        tk.Button(btn_frame, text="1: :) Happy", command=lambda: self.set_class(":)"), width=13).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="2: :| Neutral", command=lambda: self.set_class(":|"), width=13).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="3: :( Sad", command=lambda: self.set_class(":("), width=13).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="Scatta ora", command=self.trigger_manual_capture, width=11).pack(side=tk.LEFT, padx=4)
        self.pause_btn = tk.Button(btn_frame, text="Pausa", command=self.toggle_pause, width=10)
        self.pause_btn.pack(side=tk.LEFT, padx=4)

        # Scorciatoie tastiera
        self.root.bind("1", lambda _e: self.set_class(":)"))
        self.root.bind("2", lambda _e: self.set_class(":|"))
        self.root.bind("3", lambda _e: self.set_class(":("))
        self.root.bind("<space>", lambda _e: self.trigger_manual_capture())
        self.root.bind("p", lambda _e: self.toggle_pause())
        self.root.bind("P", lambda _e: self.toggle_pause())
        self.root.bind("q", lambda _e: self.close())
        self.root.bind("<Escape>", lambda _e: self.close())

        self.root.after(15, self.update_loop)

    def refresh_active_folder(self):
        self.folder_name = CLASS_TO_FOLDER[self.active_smiley]
        self.active_dir = os.path.join(OUTPUT_DIR, self.folder_name)
        count, self.next_index = scan_existing_pngs(self.active_dir)
        self.counts_by_class[self.active_smiley] = count
        print(
            f"[CLASSE] {self.active_smiley} ({CLASS_DESCRIPTIONS[self.active_smiley]}) "
            f"-> {self.active_dir} | Presenti: {count} | Prossimo: {self.next_index}.png"
        )

    def set_class(self, smiley):
        self.active_smiley = smiley
        self.refresh_active_folder()
        self.last_capture_t = time.monotonic()
        self.last_printed_sec = -1

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.configure(text="Riprendi" if self.paused else "Pausa")
        if not self.paused:
            self.last_capture_t = time.monotonic()
            self.last_printed_sec = -1
        print("[STATO]", "PAUSA" if self.paused else "ATTIVO")

    def trigger_manual_capture(self):
        self.manual_trigger = True

    def save_png(self, pil_img):
        filename = f"{self.next_index}.png"
        filepath = os.path.join(self.active_dir, filename)
        while os.path.exists(filepath):
            self.next_index += 1
            filename = f"{self.next_index}.png"
            filepath = os.path.join(self.active_dir, filename)

        pil_img.save(filepath, format="PNG")
        self.counts_by_class[self.active_smiley] += 1
        self.next_index += 1
        self.last_saved_name = filename
        size_kb = os.path.getsize(filepath) / 1024.0
        print(
            f"[SALVATO] {filename} -> {filepath} "
            f"({size_kb:.1f} KB | {self.folder_name}: {self.counts_by_class[self.active_smiley]})"
        )

    def update_loop(self):
        if not self.running:
            return

        try:
            if hasattr(self.cam, "read_stdout"):
                out = self.cam.read_stdout()
                if out:
                    print(out, end="")
            frame = self.cam.read_frame()
        except Exception as exc:
            print(f"[ERRORE STREAM] {exc}")
            self.close()
            return

        if frame is not None:
            w, h = frame["width"], frame["height"]
            data = frame["data"]
            raw = data.tobytes() if hasattr(data, "tobytes") else bytes(data)
            pil_clean = Image.frombytes("RGB", (w, h), raw)

            now = time.monotonic()
            elapsed = now - self.last_capture_t
            remaining = max(0.0, CAPTURE_INTERVAL_SEC - elapsed)

            if not self.paused:
                sec_ceil = int(remaining + 0.999)
                if sec_ceil != self.last_printed_sec and sec_ceil > 0:
                    self.last_printed_sec = sec_ceil
                    print(f"Prossimo scatto ({self.active_smiley}) tra {sec_ceil}s...")

            flash_active = now < self.flash_until_t
            should_capture = self.manual_trigger or (
                not self.paused and elapsed >= CAPTURE_INTERVAL_SEC
            )

            preview_img = pil_clean
            if PREVIEW_SCALE > 1:
                preview_img = pil_clean.resize(
                    (w * PREVIEW_SCALE, h * PREVIEW_SCALE), Image.NEAREST
                )

            hud_img = draw_hud(
                preview_img,
                self.active_smiley,
                self.folder_name,
                self.counts_by_class,
                remaining,
                CAPTURE_INTERVAL_SEC,
                self.paused,
                flash_active,
                self.last_saved_name,
            )

            if should_capture:
                self.manual_trigger = False
                try:
                    img_to_save = hud_img if DRAW_HUD_ON_SAVED_IMAGE else pil_clean
                    self.save_png(img_to_save)
                    self.last_capture_t = time.monotonic()
                    self.flash_until_t = self.last_capture_t + CAPTURE_FLASH_SEC
                    self.last_printed_sec = -1
                    hud_img = draw_hud(
                        preview_img,
                        self.active_smiley,
                        self.folder_name,
                        self.counts_by_class,
                        CAPTURE_INTERVAL_SEC,
                        CAPTURE_INTERVAL_SEC,
                        self.paused,
                        True,
                        self.last_saved_name,
                    )
                except Exception as exc:
                    print(f"[ERRORE SALVATAGGIO] {exc}")

            self.tk_img = ImageTk.PhotoImage(hud_img)
            self.label.configure(image=self.tk_img)

        self.root.after(15, self.update_loop)

    def close(self):
        if not self.running:
            return
        self.running = False
        try:
            self.cam.streaming(False)
            self.cam.stop()
        except Exception:
            pass
        try:
            self.cam.__exit__(None, None, None)
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    print("\n=== Dataset Finale - RoboCupJunior Rescue Smiley Victims ===")
    out_dir = ensure_dataset_dirs()
    print("[PC] Directory dataset:", out_dir)
    port = find_openmv_port()
    app = SmileyDatasetApp(port)
    app.run()


if __name__ == "__main__":
    main()
