# ==============================================================================
# RoboCupJunior Rescue - Smiley Victims Dataset Collector (OpenMV AE3)
# ==============================================================================
# Script MicroPython per acquisire automaticamente un dataset di immagini PNG
# delle "Smiley Victims" secondo il regolamento RoboCupJunior Rescue (sez. 4.4.6).
#
# PROMEMORIA REGOLAMENTO (Sez. 4.4.6 - Victims):
#   - 3 stati della faccina (Smiley Victims):
#       ":)" -> Happy face   (unharmed state)
#       ":|" -> Neutral face (stable state)
#       ":(" -> Sad face     (harmed state)
#   - Posizionamento: su un muro (NON su ostacoli, rampe, gradini, dossi o
#     piastrelle colorate vietate).
#   - Altezza: almeno 7 cm da terra.
#   - Dimensione e aspetto: diametro 4 cm, colore a contrasto con il muro,
#     sporgenza massima di 3 mm.
#   - Orientamento: le faccine possono essere ruotate -> durante la raccolta
#     del dataset varia rotazione, distanza, angolazione e illuminazione!
#
# NOTE HARDWARE / FILESYSTEM SU OPENMV AE3:
#   1) Caratteri speciali nei nomi cartella (":)", ":|", ":("):
#      La OpenMV AE3 espone la flash interna (/flash, ~8 MB) con filesystem
#      FAT (FatFs), lo stesso montato via USB su Windows. Nello standard FAT
#      (e su Windows) i caratteri ':' e '|' sono ILLEGALI nei nomi di file e
#      cartelle -> os.mkdir("dataset/:)") genera OSError (EINVAL).
#      Questo script prova comunque a creare esattamente "dataset/:)",
#      "dataset/:|" e "dataset/:(" e, se il filesystem li rifiuta, puo' fare
#      fallback automatico su nomi FAT-safe ("happy", "neutral", "sad") se
#      AUTO_FALLBACK_FAT_SAFE_NAMES = True.
#   2) Salvataggio PNG e RAM/Flash:
#      Su OpenMV AE3 (senza slot microSD, ~8 MB di flash interna FAT) il
#      salvataggio in .png consuma piu' RAM e spazio del .jpg. QVGA (320x240)
#      e' un buon compromesso tra qualita' del dataset e anteprima VS Code.
#      Se ottieni MemoryError, riduci FRAME_SIZE a sensor.QQVGA (160x120).
#   3) Modulo `sensor` vs `csi`:
#      Sui firmware AE3 recenti `sensor` e' un layer di compatibilita' sopra
#      il nuovo modulo `csi` e funziona normalmente (puo' stampare un avviso
#      di deprecazione su seriale, del tutto innocuo).
# ==============================================================================

import gc
import os
import time
import image
import sensor

# ==============================================================================
# CONFIGURAZIONE UTENTE
# ==============================================================================

# Scegli la classe / cartella attiva tra: ":)", ":|", ":("
ACTIVE_FOLDER = ":)"

# Intervallo di scatto automatico (in millisecondi)
CAPTURE_INTERVAL_MS = 5000  # 5.0 secondi

# Se False (CONSIGLIATO), salva il frame pulito SENZA timer/HUD e mostra
# l'overlay solo nell'anteprima live dell'estensione OpenMV di VS Code.
# Se True, disegna l'HUD anche sull'immagine salvata.
DRAW_HUD_ON_SAVED_IMAGE = False

# Configurazione sensore (QVGA 320x240 RGB565: nitido in anteprima e adatto al dataset)
PIXFORMAT = sensor.RGB565
FRAME_SIZE = sensor.QVGA  # In caso di MemoryError con PNG, usare sensor.QQVGA

# Cartella radice del dataset (verra' creata dentro lo storage scrivibile)
DATASET_DIR_NAME = "dataset"

# Se True e il filesystem FAT dell'AE3 rifiuta ":", "|", passa automaticamente
# a cartelle compatibili FAT/Windows ("happy", "neutral", "sad") mantenendo
# comunque ACTIVE_FOLDER impostabile come ":)", ":|", ":(".
AUTO_FALLBACK_FAT_SAFE_NAMES = True

# Spazio minimo libero richiesto sullo storage prima di salvare (byte)
MIN_FREE_BYTES = 256 * 1024  # 256 KB di margine di sicurezza per FAT

# Durata del feedback visivo "SALVATO!" nell'anteprima live (ms)
CAPTURE_FLASH_MS = 700

# ==============================================================================
# COSTANTI CLASSI E MAPPATURE
# ==============================================================================

VALID_SMILEYS = (":)", ":|", ":(")

SMILEY_DESCRIPTIONS = {
    ":)": "happy (unharmed)",
    ":|": "neutral (stable)",
    ":(": "sad (harmed)",
}

FAT_SAFE_FOLDER_MAP = {
    ":)": "happy",
    ":|": "neutral",
    ":(": "sad",
}

# ==============================================================================
# UTILITY FILESYSTEM (compatibili MicroPython / FatFs)
# ==============================================================================


def join_path(base, name):
    """Unisce due segmenti di percorso senza slash finali (sicuro per FatFs)."""
    base = base.rstrip("/")
    name = name.strip("/")
    if not base:
        return "/" + name
    return base + "/" + name


def path_exists(path):
    """Verifica l'esistenza di file/cartelle in MicroPython senza os.path."""
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def ensure_dir(path):
    """Crea una cartella se non esiste; rilancia OSError se il nome non e' valido."""
    if not path_exists(path):
        os.mkdir(path)


def detect_storage_root():
    """
    Individua il mount scrivibile sulla OpenMV AE3.
    Su AE3 la flash FAT e' tipicamente montata su `/flash` (o direttamente su `/`).
    Preferisce `/sdcard` (se presente), poi `/flash`, infine `os.getcwd()` / `/`.
    """
    cwd = os.getcwd()
    candidates = ["/sdcard", "/flash", cwd, "/"]
    seen = set()
    for root in candidates:
        if not root or root in seen:
            continue
        seen.add(root)
        if path_exists(root):
            # Evita la root virtuale "/" se contiene il mount "/flash"
            if root == "/" and path_exists("/flash"):
                continue
            return root
    return "/"


def get_free_bytes(path):
    """Restituisce i byte liberi sullo storage, oppure None se non disponibile."""
    try:
        st = os.statvfs(path)
        block_size = st[1] if st[1] else st[0]
        return block_size * st[3]
    except Exception:
        return None


def setup_dataset_folders(storage_root):
    """
    Crea `dataset` e le 3 sottocartelle delle faccine.
    Prova prima esattamente `dataset/:)`, `dataset/:|`, `dataset/:(`.
    Se FatFs rifiuta ':' o '|', gestisce il fallback su nomi FAT-safe.

    Ritorna: (dataset_root, active_dir_path, active_folder_on_disk, used_fallback)
    """
    if ACTIVE_FOLDER not in VALID_SMILEYS:
        raise ValueError(
            "ACTIVE_FOLDER non valido: '{}'. Usa uno tra: {}".format(
                ACTIVE_FOLDER, VALID_SMILEYS
            )
        )

    dataset_root = join_path(storage_root, DATASET_DIR_NAME)
    ensure_dir(dataset_root)

    # 1) Tentativo con i nomi esatti richiesti: ":)", ":|", ":("
    literal_ok = True
    literal_err = None
    for smiley in VALID_SMILEYS:
        sub_path = join_path(dataset_root, smiley)
        try:
            ensure_dir(sub_path)
        except OSError as exc:
            literal_ok = False
            literal_err = exc
            break

    if literal_ok:
        active_dir = join_path(dataset_root, ACTIVE_FOLDER)
        print("[FS] OK: create/verificate le cartelle letterali :) , :| , :(")
        return dataset_root, active_dir, ACTIVE_FOLDER, False

    # 2) Il filesystem (tipicamente FAT su OpenMV AE3) ha rifiutato ':' o '|'
    print("=" * 64)
    print("[AVVISO FILESYSTEM] Impossibile creare cartelle con ':' o '|'!")
    print("  Errore ricevuto:", literal_err)
    print("  Causa: la flash interna della OpenMV AE3 usa FAT (FatFs), dove")
    print("         ':' e '|' sono caratteri illegali (anche su Windows).")
    print("=" * 64)

    if not AUTO_FALLBACK_FAT_SAFE_NAMES:
        raise OSError(
            "Cartelle ':)', ':|', ':(' non supportate dal filesystem FAT. "
            "Imposta AUTO_FALLBACK_FAT_SAFE_NAMES = True per usare happy/neutral/sad."
        )

    for smiley in VALID_SMILEYS:
        safe_name = FAT_SAFE_FOLDER_MAP[smiley]
        ensure_dir(join_path(dataset_root, safe_name))

    safe_active = FAT_SAFE_FOLDER_MAP[ACTIVE_FOLDER]
    active_dir = join_path(dataset_root, safe_active)
    print(
        "[FS] Fallback FAT-safe attivo: '{}' -> '{}' ({})".format(
            ACTIVE_FOLDER, active_dir, SMILEY_DESCRIPTIONS[ACTIVE_FOLDER]
        )
    )
    return dataset_root, active_dir, safe_active, True


def scan_existing_pngs(folder_path):
    """
    Scansiona i file `<numero>.png` gia' presenti nella cartella attiva.
    Ritorna: (conteggio_png, prossimo_indice) per riprendere senza sovrascrivere.
    """
    max_index = 0
    png_count = 0
    try:
        entries = os.listdir(folder_path)
    except OSError as exc:
        print("[ERRORE] Impossibile leggere la cartella {}: {}".format(folder_path, exc))
        return 0, 1

    for name in entries:
        lower = name.lower()
        if lower.endswith(".png"):
            png_count += 1
            stem = name[:-4]
            if stem.isdigit():
                idx = int(stem)
                if idx > max_index:
                    max_index = idx

    return png_count, max_index + 1


def save_image_as_png(img, filepath):
    """
    Salva il frame in formato PNG su OpenMV AE3.
    Prova prima `img.save(filepath)`; se il firmware non supporta il salvataggio
    diretto di `.png`, usa `img.to_png(copy=True)` scrivendo i byte su file.
    """
    try:
        img.save(filepath)
    except Exception as save_err:
        # Fallback tramite codifica PNG in memoria (se supportata dal firmware)
        if hasattr(img, "to_png"):
            png_img = None
            try:
                gc.collect()
                png_img = img.to_png(copy=True)
                with open(filepath, "wb") as f:
                    f.write(png_img.bytearray())
            finally:
                png_img = None
                gc.collect()
        else:
            raise save_err

    # Sincronizza i buffer FAT su flash se disponibile
    if hasattr(os, "sync"):
        try:
            os.sync()
        except Exception:
            pass


# ==============================================================================
# OVERLAY / HUD PER ANTEPRIMA LIVE (VS CODE OPENMV EXTENSION)
# ==============================================================================


def draw_hud(
    img,
    smiley_label,
    disk_folder,
    saved_count,
    remaining_ms,
    interval_ms,
    free_bytes,
    flash_active,
    last_saved_name,
    error_banner,
):
    """Disegna countdown, barra di avanzamento, contatore e stato sul frame."""
    w = img.width()
    h = img.height()

    # Colori RGB
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    GREEN = (0, 230, 80)
    YELLOW = (255, 210, 0)
    RED = (255, 50, 50)
    CYAN = (0, 200, 255)
    GRAY = (110, 110, 110)

    # --- Barra superiore: classe attiva, numero foto salvate, spazio libero ---
    top_h = 22
    img.draw_rectangle(0, 0, w, top_h, color=BLACK, fill=True)

    if disk_folder == smiley_label:
        cls_txt = "CLS:{}".format(smiley_label)
    else:
        cls_txt = "CLS:{}({})".format(smiley_label, disk_folder)

    free_txt = ""
    if free_bytes is not None:
        free_mb = free_bytes / (1024.0 * 1024.0)
        free_txt = " {:.1f}MB".format(free_mb)

    header = "{} | IMG:{}{}".format(cls_txt, saved_count, free_txt)
    img.draw_string(4, 6, header, color=WHITE, scale=1, mono_space=False)

    # --- Barra inferiore: progress bar + countdown leggibile ---
    bot_h = 36
    bot_y = h - bot_h
    img.draw_rectangle(0, bot_y, w, bot_h, color=BLACK, fill=True)

    # Barra di avanzamento (0% -> 100% nell'intervallo di 5s)
    bar_x = 6
    bar_y = bot_y + 4
    bar_w = w - 12
    bar_h = 7
    elapsed_ms = max(0, interval_ms - remaining_ms)
    ratio = min(1.0, float(elapsed_ms) / float(interval_ms))
    fill_w = int(bar_w * ratio)

    if error_banner:
        bar_color = RED
    elif flash_active:
        bar_color = GREEN
    elif remaining_ms <= 1000:
        bar_color = RED
    elif remaining_ms <= 2000:
        bar_color = YELLOW
    else:
        bar_color = CYAN

    img.draw_rectangle(bar_x, bar_y, bar_w, bar_h, color=GRAY, thickness=1, fill=False)
    if fill_w > 0:
        img.draw_rectangle(bar_x, bar_y, fill_w, bar_h, color=bar_color, fill=True)

    # Testo stato / countdown (scale=2 su QVGA per massima leggibilita')
    text_scale = 2 if w >= 240 else 1
    text_y = bot_y + (15 if text_scale == 2 else 18)

    if error_banner:
        img.draw_string(6, text_y, error_banner, color=RED, scale=1, mono_space=False)
        img.draw_rectangle(0, 0, w, h, color=RED, thickness=3, fill=False)
    elif flash_active:
        msg = "SCATTO! {}".format(last_saved_name)
        img.draw_string(6, text_y, msg, color=GREEN, scale=text_scale, mono_space=False)
        # Bordo verde luminoso per confermare visivamente lo scatto
        img.draw_rectangle(0, 0, w, h, color=GREEN, thickness=4, fill=False)
    else:
        secs = remaining_ms / 1000.0
        msg = "NEXT: {:.1f}s".format(secs)
        img.draw_string(6, text_y, msg, color=bar_color, scale=text_scale, mono_space=False)
        # Pallino lampeggiante nell'ultimo secondo prima dello scatto
        if remaining_ms <= 1000:
            img.draw_circle(w - 16, bot_y + 24, 6, color=RED, fill=True)


# ==============================================================================
# INIZIALIZZAZIONE SENSORE E LOOP PRINCIPALE
# ==============================================================================


def init_camera():
    """Configura il sensore della OpenMV AE3 per la raccolta del dataset."""
    sensor.reset()
    sensor.set_pixformat(PIXFORMAT)
    sensor.set_framesize(FRAME_SIZE)
    sensor.skip_frames(time=2000)  # Attesa stabilizzazione AE/AWB


def main():
    print("\n=== RoboCupJunior Rescue - Smiley Victims Dataset Collector ===")
    print("Classe attiva: {} -> {}".format(ACTIVE_FOLDER, SMILEY_DESCRIPTIONS.get(ACTIVE_FOLDER, "?")))
    print("DRAW_HUD_ON_SAVED_IMAGE =", DRAW_HUD_ON_SAVED_IMAGE)

    storage_root = detect_storage_root()
    print("[FS] Storage rilevato:", storage_root)

    dataset_root, active_dir, disk_folder, used_fallback = setup_dataset_folders(storage_root)
    saved_count, next_index = scan_existing_pngs(active_dir)

    free_bytes = get_free_bytes(storage_root)
    if free_bytes is not None:
        print("[FS] Spazio libero: {:.2f} MB".format(free_bytes / (1024.0 * 1024.0)))
    print("[FS] Cartella attiva:", active_dir)
    print("[FS] Immagini PNG gia' presenti: {} | Prossimo file: {}.png".format(saved_count, next_index))

    init_camera()
    print("[CAM] Telecamera pronta. Scatto automatico ogni {:.1f}s...\n".format(CAPTURE_INTERVAL_MS / 1000.0))

    last_capture_ms = time.ticks_ms()
    flash_until_ms = 0
    last_printed_sec = -1
    last_saved_name = ""
    error_banner = ""
    storage_full = False

    while True:
        img = sensor.snapshot()
        now = time.ticks_ms()

        elapsed_ms = time.ticks_diff(now, last_capture_ms)
        remaining_ms = CAPTURE_INTERVAL_MS - elapsed_ms
        if remaining_ms < 0:
            remaining_ms = 0

        # Stampa countdown su seriale una volta al secondo (5, 4, 3, 2, 1)
        sec_ceil = (remaining_ms + 999) // 1000
        if not storage_full and sec_ceil != last_printed_sec and sec_ceil > 0:
            last_printed_sec = sec_ceil
            print("Prossimo scatto ({}) tra {}s...".format(ACTIVE_FOLDER, sec_ceil))

        should_capture = (not storage_full) and (elapsed_ms >= CAPTURE_INTERVAL_MS)
        flash_active = time.ticks_diff(flash_until_ms, now) > 0

        # Se l'HUD va disegnato ANCHE sull'immagine salvata, disegnalo prima del salvataggio
        if DRAW_HUD_ON_SAVED_IMAGE:
            draw_hud(
                img,
                ACTIVE_FOLDER,
                disk_folder,
                saved_count,
                remaining_ms,
                CAPTURE_INTERVAL_MS,
                free_bytes,
                flash_active,
                last_saved_name,
                error_banner,
            )

        if should_capture:
            # Controllo spazio libero prima di scrivere su flash FAT
            free_bytes = get_free_bytes(storage_root)
            if free_bytes is not None and free_bytes < MIN_FREE_BYTES:
                storage_full = True
                error_banner = "MEMORIA PIENA! Libera spazio su flash."
                print("[ERRORE] Spazio esaurito ({} byte liberi). Salvataggio sospeso.".format(free_bytes))
            else:
                # Garantisce di non sovrascrivere mai file esistenti
                filename = "{}.png".format(next_index)
                filepath = join_path(active_dir, filename)
                while path_exists(filepath):
                    next_index += 1
                    filename = "{}.png".format(next_index)
                    filepath = join_path(active_dir, filename)

                try:
                    save_image_as_png(img, filepath)
                    saved_count += 1
                    next_index += 1
                    last_saved_name = filename
                    error_banner = ""
                    free_bytes = get_free_bytes(storage_root)

                    # Dimensione del file appena salvato
                    file_kb = 0.0
                    try:
                        file_kb = os.stat(filepath)[6] / 1024.0
                    except OSError:
                        pass

                    free_str = (
                        "{:.2f} MB liberi".format(free_bytes / (1024.0 * 1024.0))
                        if free_bytes is not None
                        else "spazio n/d"
                    )
                    print(
                        "[SALVATO] {} -> {} ({:.1f} KB | totale: {} | {})".format(
                            filename, filepath, file_kb, saved_count, free_str
                        )
                    )

                    # Attiva il flash visivo e riavvia il timer pieno di 5.0s
                    now_after = time.ticks_ms()
                    last_capture_ms = now_after
                    flash_until_ms = time.ticks_add(now_after, CAPTURE_FLASH_MS)
                    flash_active = True
                    remaining_ms = CAPTURE_INTERVAL_MS
                    last_printed_sec = -1

                except MemoryError:
                    gc.collect()
                    error_banner = "RAM INSUFFICIENTE PER PNG (usa QQVGA)"
                    print("[ERRORE] MemoryError durante salvataggio PNG! Prova FRAME_SIZE = sensor.QQVGA.")
                    last_capture_ms = time.ticks_ms()
                    last_printed_sec = -1

                except OSError as exc:
                    errno = exc.args[0] if exc.args else None
                    if errno == 28:  # ENOSPC - No space left on device
                        storage_full = True
                        error_banner = "MEMORIA PIENA (ENOSPC)!"
                        print("[ERRORE] Memoria piena (ENOSPC). Salvataggio sospeso.")
                    else:
                        error_banner = "ERRORE SALVATAGGIO: {}".format(exc)
                        print("[ERRORE] Salvataggio fallito per {}: {}".format(filepath, exc))
                    last_capture_ms = time.ticks_ms()
                    last_printed_sec = -1

                except Exception as exc:
                    error_banner = "ERRORE PNG: {}".format(exc)
                    print("[ERRORE] Impossibile salvare {}: {}".format(filepath, exc))
                    last_capture_ms = time.ticks_ms()
                    last_printed_sec = -1

        # Se DRAW_HUD_ON_SAVED_IMAGE == False (default), disegna l'HUD DOPO lo scatto:
        # l'immagine salvata resta pulita, mentre l'anteprima live in VS Code mostra l'HUD!
        if not DRAW_HUD_ON_SAVED_IMAGE:
            draw_hud(
                img,
                ACTIVE_FOLDER,
                disk_folder,
                saved_count,
                remaining_ms,
                CAPTURE_INTERVAL_MS,
                free_bytes,
                flash_active,
                last_saved_name,
                error_banner,
            )


# Avvio dello script
main()
