"""
Mini "Teachable Machine" da riga di comando (Versione corretta per PyInstaller).
"""
import argparse
import os
import sys
import pickle

import cv2
import numpy as np

# Tentativo di importare tensorflow con gestione errori per l'eseguibile
try:
    import tensorflow as tf
    from tensorflow.keras.applications import MobileNetV2
    from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
except Exception as e:
    input(f"Errore nell'importazione di TensorFlow: {e}\nPremi INVIO per uscire...")
    sys.exit(1)

SAVE_FILE = "esempi.pkl"
K = 5  # numero di vicini per il voto

parser = argparse.ArgumentParser()
parser.add_argument("classi", nargs="*", help="nomi delle classi (max 9)")
parser.add_argument("--cam", type=int, default=0, help="indice della webcam")
args = parser.parse_args()

# Se avviato come .exe senza argomenti, mettiamo delle classi di default per evitare il crash
if not args.classi:
    classes = ["classe1", "classe2", "sfondo"]
    print("Nessuna classe passata da riga di comando. Uso quelle di default:classe1, classe2, sfondo")
else:
    classes = args.classi[:9]

print("Carico il modello MobileNetV2 (la prima volta scarica circa 14 MB)...")
try:
    net = MobileNetV2(input_shape=(224, 224, 3), include_top=False,
                      pooling="avg", weights="imagenet")
except Exception as e:
    input(f"Errore nel caricamento del modello: {e}\nPremi INVIO per uscire...")
    sys.exit(1)

def embed(frame):
    """Ritaglia il quadrato centrale e restituisce il vettore di caratteristiche."""
    h, w = frame.shape[:2]
    s = min(h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    crop = frame[y0:y0 + s, x0:x0 + s]
    rgb = cv2.cvtColor(cv2.resize(crop, (224, 224)), cv2.COLOR_BGR2RGB)
    x = preprocess_input(rgb.astype("float32")[None])
    v = net.predict(x, verbose=0)[0]
    return v / np.linalg.norm(v)

vectors, labels = [], []  # esempi raccolti

def predict(v):
    if not vectors:
        return None, 0.0
    sims = np.array(vectors) @ v
    idx = np.argsort(sims)[-K:]
    votes = {}
    for i in idx:
        votes[labels[i]] = votes.get(labels[i], 0.0) + max(sims[i], 0.0)
    total = sum(votes.values()) or 1.0
    best = max(votes, key=votes.get)
    return best, votes[best] / total

print(f"Apro la webcam (indice {args.cam})...")
cap = cv2.VideoCapture(args.cam)
if not cap.isOpened():
    input(f"ERRORE: Non riesco ad aprire la webcam con indice {args.cam}.\nPremi INVIO per uscire...")
    sys.exit(1)

print("Webcam aperta con successo! Premi 'q' per uscire.")

while True:
    ok, frame = cap.read()
    if not ok:
        print("Errore di lettura dal flusso video della webcam.")
        break

    v = embed(frame)
    best, conf = predict(v)

    counts = {c: labels.count(c) for c in range(len(classes))}
    view = frame.copy()
    if best is not None:
        text = f"{classes[best]}  {conf * 100:.0f}%"
        cv2.putText(view, text, (10, 35), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 255, 0), 2)
    for i, name in enumerate(classes):
        cv2.putText(view, f"[{i + 1}] {name}: {counts[i]} esempi",
                    (10, view.shape[0] - 15 - 25 * (len(classes) - 1 - i)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.imshow("Teach", view)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("c"):
        vectors.clear()
        labels.clear()
        print("Esempi cancellati.")
    elif key == ord("s"):
        with open(SAVE_FILE, "wb") as f:
            pickle.dump((classes, vectors, labels), f)
        print(f"Salvato in {SAVE_FILE}")
    elif key == ord("l") and os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "rb") as f:
            saved_classes, vectors, labels = pickle.load(f)
        classes = saved_classes
        print(f"Caricato da {SAVE_FILE}: classi {classes}")
    elif ord("1") <= key <= ord("9"):
        c = key - ord("1")
        if c < len(classes):
            vectors.append(v)
            labels.append(c)

cap.release()
cv2.destroyAllWindows()