# ==============================================================================
# RoboCupJunior Rescue - Smiley Victims Dataset Collector (PC -> OpenMV AE3)
# ==============================================================================
# Esegui QUESTO script con Python sul PC (es. tasto Play Python di VS Code,
# OPPURE `python collect_smiley_pc.py` dal terminale).
#
# IMPORTANTE PRIMA DI AVVIARLO:
#   1. Disconnetti la OpenMV AE3 dall'estensione OpenMV di VS Code (o chiudi
#      OpenMV IDE), perche' la porta seriale COM puo' essere usata da un solo
#      programma alla volta.
#   2. Installa le dipendenze sul PC (una sola volta):
#        pip install openmv pillow pyserial
#
# COSA FA:
#   - Si collega alla OpenMV AE3 via USB, avvia automaticamente lo streaming
#     dalla camera e mostra sul PC l'anteprima live con timer ogni 5 secondi.
#   - Salva le immagini PNG PULITE (senza HUD) direttamente sul PC in:
#       C:\Users\crist\Documents\RoboCup_Maze_2027_MastriCostruttori\RoboCup_Maze_2027_MastriCostruttori\visione_openmv\Dataset png
#   - Nota su Windows: i caratteri ':' e '|' sono vietati nei nomi di cartelle
#     Windows, quindi le 3 sottocartelle sono:
#       ":)" -> Dataset png\happy   (happy face / unharmed)
#       ":|" -> Dataset png\neutral (neutral face / stable)
#       ":(" -> Dataset png\sad     (sad face / harmed)
#   - Riprende sempre dalla numerazione PNG successiva (1.png, 2.png, ...)
#     senza sovrascrivere file esistenti.
#
# COMANDI RAPIDI NELLA FINESTRA ANTEPRIMA:
#   - Tasti 1 / 2 / 3 : cambia classe attiva al volo -> :) / :| / :(
#   - SPAZIO          : scatta subito una foto manuale
#   - P               : pausa / riprendi timer automatico
#   - Q o ESC         : esci
#
# PROMEMORIA REGOLAMENTO ROBOCUPJUNIOR RESCUE (Sez. 4.4.6 Victims):
#   - Posizionare le faccine su un muro (NO ostacoli, rampe, gradini, dossi
#     o piastrelle colorate vietate), ad almeno 7 cm da terra.
#   - Diametro 4 cm, colore a contrasto con il muro, sporgenza max 3 mm.
#   - Possono essere ruotate: varia rotazione, distanza, angolazione e luce.
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
        print("[ERRORE] Libreria 'openmv' non installata sul PC.")
        print("Installa con:  pip install openmv pillow pyserial")
        sys.exit(1)

try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None

# ==============================================================================
# CONFIGURAZIONE UTENTE
# ==============================================================================

# Classe iniziale attiva: ":)", ":|", ":("
ACTIVE_FOLDER = ":)"

# Percorso base sul PC richiesto dall'utente
OUTPUT_BASE_DIR = (
    r"C:\Users\crist\Documents\RoboCup_Maze_2027_MastriCostruttori"
    r"\RoboCup_Maze_2027_MastriCostruttori\visione_openmv"
)
DATASET_DIR_NAME = "Dataset png"

# Porta seriale della OpenMV AE3:
# Lascia None per rilevamento automatico, oppure specifica es. "COM3"
SERIAL_PORT = None

# Intervallo di scatto automatico (in secondi)
CAPTURE_INTERVAL_SEC = 5.0

# Se False (CONSIGLIATO), salva immagini pulite senza timer/HUD
DRAW_HUD_ON_SAVED_IMAGE = False

# Risoluzione camera (QVGA = 320x240, VGA = 640x480)
CAMERA_FRAMESIZE = "QVGA"

# Fattore di ingrandimento della finestra anteprima sul PC (es. 2 -> 640x480 per QVGA)
PREVIEW_SCALE = 2

# Durata flash verde di conferma scatto (in secondi)
CAPTURE_FLASH_SEC = 0.7

# ==============================================================================
# MAPPATURA CLASSI (Windows non accetta ':' e '|' nei nomi cartella)
# ==============================================================================

CLASS_TO_FOLDER = {
    ":)": "happy",
    ":|": "neutral",
    ":(": "sad",
}

CLASS_DESCRIPTIONS = {
    ":)": "happy (unharmed)",
    ":|": "neutral (stable)",
    ":(": "sad (harmed)",
}

# Script MicroPython eseguito automaticamente sulla OpenMV AE3
DEVICE_SCRIPT = f"""
import time
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
# FUNZIONI DI SUPPORTO
# ==============================================================================


def find_openmv_port():
    """Trova automaticamente la porta COM della OpenMV AE3 su Windows."""
    if SERIAL_PORT:
        return SERIAL_PORT

    if list_ports is None:
        raise RuntimeError(
            "Impossibile rilevare la porta automaticamente (manca pyserial). "
            "Imposta SERIAL_PORT = 'COMx' in cima allo script."
        )

    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError(
            "Nessuna porta COM trovata. Collega la OpenMV AE3 via USB "
            "e verifica che sia disconnessa da VS Code OpenMV / OpenMV IDE."
        )

    # Priorita' a porte che riportano OpenMV o VID noti (OpenMV/ST/Alif)
    known_vids = {0x1209, 0x0483, 0x37C5}
    for p in ports:
        desc = (p.description or "").lower()
        manu = (p.manufacturer or "").lower()
        if "openmv" in desc or "openmv" in manu or (p.vid in known_vids):
            print(f"[USB] Rilevata scheda OpenMV su {p.device} ({p.description})")
            return p.device

    if len(ports) == 1:
        p = ports[0]
        print(f"[USB] Uso l'unica porta disponibile: {p.device} ({p.description})")
        return p.device

    print("[USB] Porte COM trovate:")
    for idx, p in enumerate(ports, start=1):
        print(f"  {idx}. {p.device} - {p.description}")
    raise RuntimeError(
        "Piu' porte COM trovate: imposta SERIAL_PORT = 'COMx' in cima allo script."
    )


def ensure_dataset_dirs():
    """Crea `Dataset png` e le 3 sottocartelle su PC."""
    dataset_root = os.path.join(OUTPUT_BASE_DIR, DATASET_DIR_NAME)
    os.makedirs(dataset_root, exist_ok=True)
    for folder_name in CLASS_TO_FOLDER.values():
        os.makedirs(os.path.join(dataset_root, folder_name), exist_ok=True)
    return dataset_root


def scan_existing_pngs(folder_path):
    """Restituisce (conteggio_png, prossimo_indice) per evitare sovrascritture."""
    max_idx = 0
    count = 0
    for name in os.listdir(folder_path):
        if name.lower().endswith(".png"):
            count += 1
            stem = name[:-4]
            if stem.isdigit():
                max_idx = max(max_idx, int(stem))
    return count, max_idx + 1


def draw_hud_on_pil(
    pil_img,
    active_smiley,
    folder_name,
    saved_count,
    remaining_sec,
    interval_sec,
    paused,
    flash_active,
    last_saved_name,
):
    """Disegna l'HUD con countdown, contatore e stato sulla copia per l'anteprima."""
    hud = pil_img.copy()
    draw = ImageDraw.Draw(hud)
    w, h = hud.size

    # Barra superiore
    draw.rectangle([0, 0, w, 26], fill=(0, 0, 0))
    header = f"CLS: {active_smiley} ({folder_name}) | IMG: {saved_count}"
    draw.text((8, 7), header, fill=(255, 255, 255))

    # Barra inferiore
    bot_h = 44
    bot_y = h - bot_h
    draw.rectangle([0, bot_y, w, h], fill=(0, 0, 0))

    bar_x, bar_y, bar_w, bar_h = 8, bot_y + 6, w - 16, 10
    progress = max(0.0, min(1.0, (interval_sec - remaining_sec) / interval_sec))
    fill_w = int(bar_w * progress)

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
        status_txt = "IN PAUSA (premi P per riprendere)"
    elif flash_active:
        status_txt = f"SCATTO! {last_saved_name}"
        draw.rectangle([0, 0, w - 1, h - 1], outline=(0, 230, 80), width=4)
    else:
        status_txt = f"PROSSIMO SCATTO: {remaining_sec:.1f}s  [1:) 2:| 3:( | SPAZIO=scatta]"

    draw.text((8, bot_y + 22), status_txt, fill=color)
    return hud


# ==============================================================================
# APPLICAZIONE PRINCIPALE
# ==============================================================================


class DatasetCollectorApp:
    def __init__(self, port, dataset_root):
        if ACTIVE_FOLDER not in CLASS_TO_FOLDER:
            raise ValueError(f"ACTIVE_FOLDER non valido: {ACTIVE_FOLDER}")

        self.port = port
        self.dataset_root = dataset_root
        self.active_smiley = ACTIVE_FOLDER
        self.paused = False
        self.last_capture_t = time.monotonic()
        self.flash_until_t = 0.0
        self.last_saved_name = ""
        self.last_printed_sec = -1
        self.tk_img = None

        self.refresh_folder_state()

        # Connessione alla OpenMV AE3
        self.cam = Camera(self.port)
        self.cam.__enter__()
        self.cam.stop()
        self.cam.exec(DEVICE_SCRIPT)
        self.cam.streaming(True)

        # Finestra anteprima live sul PC
        self.root = tk.Tk()
        self.root.title("RoboCupJunior Rescue - Smiley Dataset Collector (OpenMV AE3)")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.label = tk.Label(self.root, bg="black")
        self.label.pack()

        self.root.bind("1", lambda _e: self.set_class(":)"))
        self.root.bind("2", lambda _e: self.set_class(":|"))
        self.root.bind("3", lambda _e: self.set_class(":("))
        self.root.bind("<space>", lambda _e: self.trigger_manual_capture())
        self.root.bind("p", lambda _e: self.toggle_pause())
        self.root.bind("P", lambda _e: self.toggle_pause())
        self.root.bind("q", lambda _e: self.close())
        self.root.bind("<Escape>", lambda _e: self.close())

        self.manual_trigger = False
        self.running = True
        self.root.after(15, self.update_loop)

    def refresh_folder_state(self):
        self.folder_name = CLASS_TO_FOLDER[self.active_smiley]
        self.active_dir = os.path.join(self.dataset_root, self.folder_name)
        self.saved_count, self.next_index = scan_existing_pngs(self.active_dir)
        print(
            f"[CLASSE] {self.active_smiley} ({CLASS_DESCRIPTIONS[self.active_smiley]}) "
            f"-> {self.active_dir} | Gia' presenti: {self.saved_count} | "
            f"Prossimo: {self.next_index}.png"
        )

    def set_class(self, smiley):
        self.active_smiley = smiley
        self.refresh_folder_state()
        self.last_capture_t = time.monotonic()
        self.last_printed_sec = -1

    def toggle_pause(self):
        self.paused = not self.paused
        if not self.paused:
            self.last_capture_t = time.monotonic()
            self.last_printed_sec = -1
        print("[STATO]", "PAUSA" if self.paused else "RIPRESO")

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
        self.saved_count += 1
        self.next_index += 1
        self.last_saved_name = filename
        size_kb = os.path.getsize(filepath) / 1024.0
        print(f"[SALVATO] {filepath} ({size_kb:.1f} KB | totale: {self.saved_count})")

    def update_loop(self):
        if not self.running:
            return

        try:
            # Svuota eventuali log dalla scheda
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

            # Crea immagine per anteprima (scalata per essere ben visibile)
            preview_img = pil_clean
            if PREVIEW_SCALE > 1:
                preview_img = pil_clean.resize(
                    (w * PREVIEW_SCALE, h * PREVIEW_SCALE), Image.NEAREST
                )

            hud_img = draw_hud_on_pil(
                preview_img,
                self.active_smiley,
                self.folder_name,
                self.saved_count,
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
                    hud_img = draw_hud_on_pil(
                        preview_img,
                        self.active_smiley,
                        self.folder_name,
                        self.saved_count,
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
    print("\n=== RoboCupJunior Rescue - Smiley Dataset Collector (PC + OpenMV AE3) ===")
    dataset_root = ensure_dataset_dirs()
    print("[PC] Cartella salvataggio:", dataset_root)
    port = find_openmv_port()
    app = DatasetCollectorApp(port, dataset_root)
    app.run()


if __name__ == "__main__":
    main()
