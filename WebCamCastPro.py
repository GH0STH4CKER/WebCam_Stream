import tkinter as tk
from tkinter import ttk, messagebox
import threading, subprocess, socket, random, string, time, webbrowser
import cv2, qrcode, platform
from PIL import Image, ImageTk
from flask import Flask, Response

# ------------------- Flask Webcam Stream -------------------
app = Flask(__name__)

class WebcamStream:
    def __init__(self, camera_index=0, fps=15):
        self.cap = cv2.VideoCapture(camera_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open webcam (index {camera_index})")
        self.fps = fps
        self.frame = None
        self.running = True
        t = threading.Thread(target=self.update, daemon=True)
        t.start()

    def update(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                _, jpeg = cv2.imencode('.jpg', frame)
                self.frame = jpeg.tobytes()
            time.sleep(1.0 / self.fps)

    def get_frame(self):
        return self.frame

    def stop(self):
        self.running = False
        self.cap.release()


stream = None

@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            if stream:
                frame = stream.get_frame()
                if frame:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(0.05)
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ------------------- Helpers -------------------
def random_string(n=6):
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return "127.0.0.1"
    finally:
        s.close()

def hosted_network_supported():
    if platform.system() != "Windows":
        return False
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "drivers"],
            capture_output=True,
            text=True,
            check=True
        )
        for line in result.stdout.splitlines():
            if "Hosted network supported" in line:
                return "Yes" in line
    except Exception:
        return False
    return False

def create_hotspot_windows(ssid, password):
    subprocess.run(["netsh", "wlan", "set", "hostednetwork", "mode=allow",
                    f"ssid={ssid}", f"key={password}"], check=True)
    subprocess.run(["netsh", "wlan", "start", "hostednetwork"], check=True)

def stop_hotspot_windows():
    subprocess.run(["netsh", "wlan", "stop", "hostednetwork"])


def list_cameras_wmic():
    """Get camera names from WMIC, map to OpenCV index"""
    try:
        result = subprocess.run(
            ["wmic", "path", "win32_pnpentity", "where", "Service='usbvideo'", "get", "Name"],
            capture_output=True, text=True, check=True
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip() and "Name" not in l]
        if not lines:
            raise ValueError("No cameras detected via WMIC")
        return {i: name for i, name in enumerate(lines)}
    except Exception as e:
        print("WMIC failed, fallback to Camera 0..4:", e)
        return {i: f"Camera {i}" for i in range(5)}


# ------------------- Tkinter GUI -------------------
class AppGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📡 WebCam Streamer")
        self.root.geometry("900x500")
        self.root.configure(bg="#1e1e2f")
        self.root.resizable(True, True)

        # Style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 11, "bold"), padding=8, background="#4CAF50", foreground="white")
        style.map("TButton", background=[("active", "#45a049")])
        style.configure("TRadiobutton", font=("Segoe UI", 11), foreground="white", background="#1e1e2f")
        style.configure("TLabel", background="#1e1e2f", foreground="white", font=("Segoe UI", 11))
        style.configure("TCombobox", font=("Segoe UI", 11))

        # Header
        header = tk.Frame(root, bg="#2c2c40", height=60)
        header.pack(fill="x")
        tk.Label(header, text="WebCam Streamer", font=("Segoe UI", 16, "bold"), fg="white", bg="#2c2c40").pack(pady=10)

        # Main horizontal frame (landscape)
        main_frame = tk.Frame(root, bg="#1e1e2f")
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # Left: QR code with fixed placeholder
        self.qr_frame = tk.Frame(main_frame, bg="#2c2c40", bd=2, relief="groove", width=280, height=280)
        self.qr_frame.pack_propagate(False)  # keep frame size fixed
        self.qr_frame.pack(side="left", padx=10, pady=10)
        
        # Placeholder image
        placeholder_img = Image.new("RGB", (260, 260), color="#2c2c40")
        self.qr_placeholder = ImageTk.PhotoImage(placeholder_img)
        
        # QR label centered inside the frame
        self.qr_label = ttk.Label(self.qr_frame, image=self.qr_placeholder)
        self.qr_label.pack(expand=True)  # centers it both horizontally and vertically

        # Right: Controls
        control_frame = tk.Frame(main_frame, bg="#1e1e2f")
        control_frame.pack(side="left", fill="both", expand=True, padx=20, pady=10)

        # Mode selection
        mode_frame = tk.LabelFrame(control_frame, text="Connection Mode", bg="#1e1e2f", fg="white", font=("Segoe UI", 11, "bold"))
        mode_frame.pack(fill="x", pady=(23, 13))
        self.mode = tk.StringVar(value="LAN")
        ttk.Radiobutton(mode_frame, text="LAN (same Wi-Fi)", variable=self.mode, value="LAN").pack(anchor="w", padx=10, pady=3)
        if hosted_network_supported():
            self.mode_hotspot_rb = ttk.Radiobutton(mode_frame, text="Hotspot (PC creates Wi-Fi)", variable=self.mode, value="Hotspot")
        else:
            self.mode_hotspot_rb = ttk.Radiobutton(mode_frame, text="Hotspot (not supported)", variable=self.mode, value="Hotspot", state="disabled")
        self.mode_hotspot_rb.pack(anchor="w", padx=10, pady=3)

        # Camera selection
        cam_frame = tk.LabelFrame(control_frame, text="Camera Selection", bg="#1e1e2f", fg="white", font=("Segoe UI", 11, "bold"))
        cam_frame.pack(fill="x", pady=10)
        self.cam_map = list_cameras_wmic()
        self.cam_var = tk.StringVar()
        self.cam_dropdown = ttk.Combobox(cam_frame, textvariable=self.cam_var, values=list(self.cam_map.values()), state="readonly")
        self.cam_dropdown.current(0)
        self.cam_dropdown.pack(padx=10, pady=5, fill="x")

        # Info label
        self.info_label = ttk.Label(control_frame, text="", font=("Segoe UI", 10))
        self.info_label.pack(pady=10)

        # Buttons
        btn_frame = tk.Frame(control_frame, bg="#1e1e2f")
        btn_frame.pack(pady=10)
        self.start_btn = ttk.Button(btn_frame, text="▶ Start Streaming", command=self.start)
        self.start_btn.grid(row=0, column=0, padx=10)
        self.stop_btn = ttk.Button(btn_frame, text="⏹ Stop", command=self.stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=10)


        # Developer footer with clickable hyperlink
        footer = tk.Label(root, text="Developed by Dimuth De Zoysa", fg="cyan", bg="#1e1e2f",
                          cursor="hand2", font=("Segoe UI", 10, "underline"))
        footer.pack(side="bottom", pady=5)
        footer.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/GH0STH4CKER"))

        # Status footer
        self.status_label = tk.Label(root, text="Idle", font=("Segoe UI", 10), fg="gray", bg="#1e1e2f")
        self.status_label.pack(side="bottom", pady=5)

        self.hotspot_ssid = None
        self.hotspot_pass = None
        self.server_thread = None

    def start(self):
        mode = self.mode.get()
        ip = get_local_ip()
        url = f"http://{ip}:5000/video_feed"

        selected_name = self.cam_var.get()
        cam_index = [idx for idx, name in self.cam_map.items() if name == selected_name][0]

        if mode == "Hotspot":
            self.hotspot_ssid = "WebCam_" + random_string(4)
            self.hotspot_pass = random_string(10)
            if platform.system() == "Windows":
                try:
                    create_hotspot_windows(self.hotspot_ssid, self.hotspot_pass)
                except Exception as e:
                    messagebox.showerror("Error", f"Could not start hotspot: {e}")
                    return
            wifi_qr = f"WIFI:T:WPA;S:{self.hotspot_ssid};P:{self.hotspot_pass};;"
            qr_img = qrcode.make(wifi_qr)
            self.show_qr(qr_img)
            self.info_label.config(text=f"SSID: {self.hotspot_ssid}\nPassword: {self.hotspot_pass}\nVisit:\n{url}")
        else:
            qr_img = qrcode.make(url)
            self.show_qr(qr_img)
            self.info_label.config(text=f"Connect to same Wi-Fi\nOpen in browser:\n{url}")

        global stream
        stream = WebcamStream(camera_index=cam_index)
        self.server_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000, threaded=True), daemon=True)
        self.server_thread.start()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_label.config(text=f"🟢 Streaming Active ({selected_name})", fg="#4CAF50")

    def show_qr(self, img):
        img = img.resize((260, 260))
        imgtk = ImageTk.PhotoImage(img)
        self.qr_label.imgtk = imgtk
        self.qr_label.config(image=imgtk)

    def stop(self):
        global stream
        if stream:
            stream.stop()
            stream = None
        if self.mode.get() == "Hotspot" and platform.system() == "Windows":
            stop_hotspot_windows()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.info_label.config(text="")
        self.qr_label.config(image=self.qr_placeholder)
        self.status_label.config(text="🔴 Stopped", fg="red")


# ------------------- Run -------------------
if __name__ == "__main__":
    root = tk.Tk()
    gui = AppGUI(root)
    root.mainloop()
