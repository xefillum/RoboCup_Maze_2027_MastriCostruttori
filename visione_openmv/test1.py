import sensor
import image
import time
import os
import pyb


# 1. Configurazione iniziale del sensore
sensor.reset()
sensor.set_pixformat(sensor.GRAYSCALE)  # Scala di grigi
sensor.set_framesize(sensor.QVGA)     # Risoluzione QVGA (320x240)
sensor.skip_frames(time=2000)


# 2. Creazione della cartella "triste" (se non esiste già)
cartella = "/triste"
try:
    os.mkdir(cartella)
except OSError:
    pass


# 3. Inizializzazione del contatore dei file basato sui file già presenti
file_counter = 1
try:
    esistenti = os.listdir(cartella)
    file_counter = len([f for f in esistenti if f.endswith(".pgm")]) + 1
except OSError:
    pass


# Inizializza la comunicazione USB Virtual COM per ricevere input dal PC
usb = pyb.USB_VCP()


print(f"=== SISTEMA PRONTO ===")
print(f"I file verranno salvati in: {cartella}/")
print("Per salvare un frame, clicca sulla finestra del Terminale nell'IDE OpenMV, premi un tasto qualsiasi (es. un tasto o Invio) e dai l'invio.")


while True:
    img = sensor.snapshot()


    # Controlla se il PC ha inviato un input tramite la seriale USB
    if usb.any():
        # Legge il dato inviato dal PC e pulisce il buffer
        comando_ricevuto = usb.read()
        
        if comando_ricevuto:
            # Genera il nome del file progressivo (es. /triste/1.pgm, /triste/2.pgm)
            nome_file = f"{cartella}/{file_counter}.pgm"
            
            # Salva l'immagine nella cartella
            img.save(nome_file)
            print(f"-> Immagine salvata con successo: {nome_file}")
            
            # Incrementa il contatore per il file successivo
            file_counter += 1
            
            # Breve pausa di sicurezza (debounce) per evitare salvataggi multipli
            time.sleep_ms(300)