# 🌌 Wallpics PRO MAX

> **Ultra-HD Image Scraper & Original CDN Upscaler**  
> Download images from any webpage at the **HIGHEST possible resolution** with a real-time progress bar, responsive desktop GUI, and local Web UI.

---

## 🌟 Key Features

- **Max Quality / Original CDN Rewriting**: Automatically recognizes thumbnail and resize parameters from major platforms (WordPress, Shopify, Wikipedia, Amazon, Cloudinary, Pinterest, Google, Twitter/X) and converts them into original uncompressed 4K/8K images.
- **Real-Time Progress Tracking**: Visual progress bar showing percentage, images discovered, candidates tested, and files saved.
- **Two User Interfaces**:
  - **🖥️ Native Desktop Software**: Built with `CustomTkinter` for a sleek dark-mode Windows application (`Wallpics.exe` / `gui.py`).
  - **🌐 Web Interface**: Local glassmorphism dashboard (`app.py`) with real-time SSE progress streaming and live gallery lightbox.
- **Headless Browser Rendering**: Optional Playwright Chromium integration to execute JavaScript and scroll for lazy-loaded image galleries.
- **Resolution Filtering**: Filter out low-res icons and banners (300px+, 720p+, 1080p+, 4K UHD+).

---

## 🚀 Getting Started

### 1. Installation

Clone the repository and install the dependencies:

```bash
git clone https://github.com/your-username/wallpics.git
cd wallpics
pip install -r requirements.txt
```

*(Optional for JavaScript-heavy dynamic websites)*:
```bash
playwright install chromium
```

---

## 💻 Usage

### A. Run Desktop Application (Native Software)
```bash
python gui.py
```
Or simply double-click `Launch_Wallpics.bat`.

### B. Run Web Dashboard
```bash
python app.py
```
Then open `http://127.0.0.1:5000` in your web browser.

### C. Command-Line CLI
```bash
# Basic download
python download_images.py https://example.com/gallery

# Render JavaScript and scroll dynamic pages
python download_images.py https://example.com/gallery --render

# Filter out images smaller than 1080px
python download_images.py https://example.com/gallery --min-dim 1080 -o ./my_wallpapers
```

---

## 🛠️ Build Standalone Executable (.exe)

To bundle the software into a standalone Windows executable:
```bash
python -m PyInstaller --noconsole --onedir --name "Wallpics" --collect-all customtkinter gui.py
```
The executable will be located in `dist/Wallpics/Wallpics.exe`.

---

## 📄 License

MIT License.
