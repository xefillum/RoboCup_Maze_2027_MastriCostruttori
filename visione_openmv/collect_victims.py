import os
import time
import csi
import image
import machine

# Seleziona la classe corrente durante la sessione di raccolta:
# "harmed", "stable", "unharmed" oppure "background"
TARGET_CLASS = "unharmed"
SAVE_ROOT = "/rcj_victims"
OUT_SIZE = 160            # 160x160 quadrato (o imposta 0 per salvare frame QVGA intero)
INTERVAL_MS = 300         # Intervallo tra acquisizioni automatiche (ms)
MAX_IMAGES = 150          # Limite immagini per sessione


def mkdir_p(path):
    cur = ""
    for part in path.split("/"):
        if not part:
            continue
        cur += "/" + part
        try:
            os.mkdir(cur)
        except OSError:
            pass


def next_path(folder, prefix):
    idx = 0
    for fname in os.listdir(folder):
        if fname.startswith(prefix + "_") and fname.endswith(".bmp"):
            num_part = fname[len(prefix) + 1 : -4]
            if num_part.isdigit():
                val = int(num_part)
                if val > idx:
                    idx = val
    return "%s/%s_%04d.bmp" % (folder, prefix, idx + 1)


def main():
    save_dir = "%s/%s" % (SAVE_ROOT, TARGET_CLASS)
    mkdir_p(save_dir)

    cam = csi.CSI()
    cam.reset()
    cam.set_pixformat(csi.RGB565)
    cam.set_framesize(csi.QVGA)  # 320x240 con global shutter PAG7936
    cam.skip_frames(time=1000)

    led_ok = machine.LED("LED_GREEN")
    led_busy = machine.LED("LED_BLUE")
    led_busy.on()

    count = 0
    t_last = time.ticks_ms()
    print("Raccolta classe '%s' in '%s'..." % (TARGET_CLASS, save_dir))

    while count < MAX_IMAGES:
        frame = cam.snapshot()
        now = time.ticks_ms()

        if time.ticks_diff(now, t_last) >= INTERVAL_MS:
            if OUT_SIZE > 0:
                # Crop centrale quadrato 240x240 da QVGA (320x240) e resize a OUT_SIZE
                crop_side = min(frame.width(), frame.height())
                cx = (frame.width() - crop_side) // 2
                cy = (frame.height() - crop_side) // 2
                roi_img = frame.copy(roi=(cx, cy, crop_side, crop_side))

                out_img = image.Image(OUT_SIZE, OUT_SIZE, csi.RGB565)
                scale = OUT_SIZE / float(crop_side)
                out_img.draw_image(roi_img, 0, 0, x_scale=scale, y_scale=scale)
            else:
                out_img = frame

            fpath = next_path(save_dir, TARGET_CLASS)
            out_img.save(fpath)
            count += 1
            t_last = now

            led_ok.on()
            time.sleep_ms(35)
            led_ok.off()
            print("Salvato [%d/%d]: %s" % (count, MAX_IMAGES, fpath))

    led_busy.off()
    print("Sessione completata: %d campioni salvati per '%s'." % (count, TARGET_CLASS))


if __name__ == "__main__":
    main()